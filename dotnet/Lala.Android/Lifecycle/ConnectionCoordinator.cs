namespace Lala.Android.Lifecycle;

/// <summary>
/// Single selected-account owner. Android services own this instance; activities
/// only observe it. Network starts unavailable until a platform observation arrives.
/// All transitions are serialized, while adapter work and observers run off-thread.
/// This is not a transport, authentication implementation or multi-account registry.
/// </summary>
public sealed class ConnectionCoordinator : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly IConnectionAdapterFactory factory;
    private readonly bool adapterAvailable;
    private readonly ConnectionPolicy policy;
    private readonly IConnectionDelay delay;
    private readonly List<Subscription> subscriptions = [];
    private readonly Queue<Subscription> notifications = new();
    private bool dispatching, networkAvailable, disposed;
    private long generation, nextAttemptId;
    private int attemptsStarted;
    private ConnectionEndReason retryReason = ConnectionEndReason.TransientNetworkFailure;
    private ConnectionTarget? desiredTarget;
    private Attempt? attempt;
    private RetryWait? retry;
    private ConnectionSnapshot snapshot = new(0, 0, ConnectionPhase.Stopped, 0, ConnectionEndReason.None);

    public ConnectionCoordinator(IConnectionAdapterFactory factory,
        ConnectionPolicy? policy = null, IConnectionDelay? delay = null)
    {
        ArgumentNullException.ThrowIfNull(factory);
        this.factory = factory;
        adapterAvailable = factory.IsAvailable;
        this.policy = policy ?? new ConnectionPolicy();
        this.policy.Validate();
        this.delay = delay ?? new SystemConnectionDelay();
    }

    public ConnectionSnapshot Snapshot { get { lock (gate) return snapshot; } }

    /// <summary>
    /// Delivers the latest snapshot and subsequent changes on a background thread.
    /// Pending snapshots coalesce per observer, so slow views cannot grow an event
    /// backlog. Observer exceptions are isolated. Unsubscribe drops queued callbacks; an
    /// already-running callback may finish. Marshal UI/Android updates as required.
    /// </summary>
    public IDisposable Subscribe(Action<ConnectionSnapshot> observer)
    {
        ArgumentNullException.ThrowIfNull(observer);
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            var subscription = new Subscription(this, observer);
            subscriptions.Add(subscription);
            QueueNotificationLocked(snapshot, [subscription]);
            return subscription;
        }
    }

    /// <summary>
    /// Explicit user intent. Repeated starts of the same active selection are
    /// idempotent. Changing selection waits for old cleanup (bounded by policy).
    /// A new attempt never begins before the old adapter has actually been released.
    /// </summary>
    public Task StartAsync(ConnectionTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        target.Validate();
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (desiredTarget == target)
                return attempt is { CleanupStarted: true } current ? current.CleanupWait.Task : Task.CompletedTask;

            generation = checked(generation + 1);
            desiredTarget = target;
            attemptsStarted = 0;
            retryReason = ConnectionEndReason.TransientNetworkFailure;
            CancelRetryLocked();
            if (attempt is { } previous)
            {
                RequestCancellationLocked(previous, ConnectionEndReason.UserStopped);
                return previous.CleanupWait.Task;
            }
            ProgressLocked();
            return Task.CompletedTask;
        }
    }

    /// <summary>
    /// Cancels retries and current work. Completes when cleanup finishes, or when
    /// the watchdog exposes CleanupBlocked. Inspect Snapshot; a timeout is not
    /// proof of release, and does not permit a second session.
    /// </summary>
    public Task StopAsync(ConnectionEndReason reason = ConnectionEndReason.UserStopped)
    {
        if (!Enum.IsDefined(reason) || reason == ConnectionEndReason.None)
            throw new ArgumentOutOfRangeException(nameof(reason));
        lock (gate)
        {
            if (desiredTarget is not null || retry is not null || attempt is not null)
                generation = checked(generation + 1);
            desiredTarget = null;
            CancelRetryLocked();
            if (attempt is { } previous)
            {
                RequestCancellationLocked(previous, disposed ? ConnectionEndReason.Disposed : reason);
                return previous.CleanupWait.Task;
            }
            PublishLocked(ConnectionPhase.Stopped, disposed ? ConnectionEndReason.Disposed : reason);
            return Task.CompletedTask;
        }
    }

    /// <summary>
    /// OS readiness only. A lost network cancels the owned attempt, without claiming
    /// the server logged out. Restored readiness can schedule a bounded retry, never
    /// mark the session Active or bypass pending cleanup.
    /// </summary>
    public Task SetNetworkAvailableAsync(bool available)
    {
        lock (gate)
        {
            if (disposed || networkAvailable == available) return Task.CompletedTask;
            networkAvailable = available;
            if (desiredTarget is null) return Task.CompletedTask;
            if (!available)
            {
                CancelRetryLocked();
                if (attempt is { } current)
                {
                    RequestCancellationLocked(current, ConnectionEndReason.NetworkUnavailable);
                    return current.CleanupWait.Task;
                }
                PublishLocked(ConnectionPhase.WaitingForNetwork, ConnectionEndReason.NetworkUnavailable);
            }
            else if (attempt is null)
                ProgressLocked();
            return Task.CompletedTask;
        }
    }

    public ValueTask DisposeAsync()
    {
        lock (gate)
        {
            if (!disposed)
            {
                disposed = true;
                generation = checked(generation + 1);
                desiredTarget = null;
                CancelRetryLocked();
                foreach (var subscription in subscriptions) subscription.Deactivate();
                subscriptions.Clear();
                notifications.Clear();
            }
            if (attempt is { } current)
            {
                RequestCancellationLocked(current, ConnectionEndReason.Disposed);
                return new ValueTask(current.CleanupWait.Task);
            }
            PublishLocked(ConnectionPhase.Stopped, ConnectionEndReason.Disposed);
            return ValueTask.CompletedTask;
        }
    }

    private void ProgressLocked()
    {
        if (disposed || desiredTarget is null || attempt is not null || retry is not null) return;
        if (!adapterAvailable)
        {
            desiredTarget = null;
            PublishLocked(ConnectionPhase.Unavailable, ConnectionEndReason.CoreUnavailable);
        }
        else if (!networkAvailable)
            PublishLocked(ConnectionPhase.WaitingForNetwork, ConnectionEndReason.NetworkUnavailable);
        else if (attemptsStarted == 0)
            BeginAttemptLocked();
        else
            ScheduleRetryLocked();
    }

    private void BeginAttemptLocked()
    {
        if (disposed || desiredTarget is null || attempt is not null || !networkAvailable) return;
        if (attemptsStarted > policy.MaximumRetries)
        {
            desiredTarget = null;
            PublishLocked(ConnectionPhase.Failed, ConnectionEndReason.RetryLimitReached);
            return;
        }
        attemptsStarted = checked(attemptsStarted + 1);
        var current = new Attempt(generation, checked(++nextAttemptId), desiredTarget);
        attempt = current;
        PublishLocked(ConnectionPhase.Connecting, ConnectionEndReason.None);
        _ = Task.Run(() => WatchConnectAsync(current));
        _ = Task.Run(() => RunAttemptAsync(current));
    }

    private async Task RunAttemptAsync(Attempt current)
    {
        IConnectionAdapter? adapter = null;
        var result = ConnectionEndReason.AdapterFailure;
        try
        {
            current.Cancellation.Token.ThrowIfCancellationRequested();
            adapter = factory.Create(current.Target)
                ?? throw new InvalidOperationException("Adapter factory returned no owner.");
            current.Cancellation.Token.ThrowIfCancellationRequested();
            result = await adapter.RunAsync(() => MarkActive(current), current.Cancellation.Token).ConfigureAwait(false);
            if (!Enum.IsDefined(result) || result == ConnectionEndReason.None)
                result = ConnectionEndReason.AdapterFailure;
        }
        catch (OperationCanceledException) when (current.Cancellation.IsCancellationRequested)
        {
            result = ConnectionEndReason.UserStopped;
        }
        catch (Exception)
        {
            // Adapter errors may contain credentials. Never publish their text.
            result = ConnectionEndReason.AdapterFailure;
        }

        lock (gate)
        {
            if (ReferenceEquals(attempt, current))
            {
                current.Result = result;
                BeginCleanupLocked(current);
            }
        }

        bool released = true;
        try
        {
            if (adapter is not null) await adapter.DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception)
        {
            // A failed release is not proof that its resources are gone.
            released = false;
        }
        finally
        {
            CompleteAttempt(current, released);
            current.Cancellation.Dispose();
        }
    }

    private void MarkActive(Attempt current)
    {
        lock (gate)
        {
            if (!disposed && ReferenceEquals(attempt, current) && current.Generation == generation &&
                !current.CleanupStarted && !current.StopRequested && desiredTarget == current.Target)
            {
                current.Activated = true;
                CancelWithoutBlocking(current.ConnectTimer);
                PublishLocked(ConnectionPhase.Active, ConnectionEndReason.None);
            }
        }
    }

    private async Task WatchConnectAsync(Attempt current)
    {
        try
        {
            await delay.DelayAsync(policy.ConnectTimeout, current.ConnectTimer.Token).ConfigureAwait(false);
            lock (gate)
            {
                if (ReferenceEquals(attempt, current) && !current.Activated &&
                    !current.CleanupStarted && !disposed && current.Generation == generation)
                    RequestCancellationLocked(current, ConnectionEndReason.ConnectTimedOut);
            }
        }
        catch (OperationCanceledException) when (current.ConnectTimer.IsCancellationRequested) { }
        catch (Exception)
        {
            lock (gate)
            {
                if (!ReferenceEquals(attempt, current) || current.CleanupStarted || current.Activated) return;
                desiredTarget = null;
                RequestCancellationLocked(current, ConnectionEndReason.AdapterFailure);
            }
        }
        finally { current.ConnectTimer.Dispose(); }
    }

    private void RequestCancellationLocked(Attempt current, ConnectionEndReason reason)
    {
        current.StopRequested = true;
        current.StopReason = reason;
        BeginCleanupLocked(current);
        CancelWithoutBlocking(current.Cancellation);
    }

    private void BeginCleanupLocked(Attempt current)
    {
        if (!current.CleanupStarted)
        {
            current.CleanupStarted = true;
            CancelWithoutBlocking(current.ConnectTimer);
            _ = Task.Run(() => WatchCleanupAsync(current));
        }
        if (current.CleanupBlocked)
            PublishLocked(ConnectionPhase.CleanupBlocked, current.BlockReason);
        else
            PublishLocked(ConnectionPhase.Stopping,
                current.StopRequested ? current.StopReason : current.Result);
    }

    private async Task WatchCleanupAsync(Attempt current)
    {
        try
        {
            await delay.DelayAsync(policy.CleanupTimeout, current.CleanupTimer.Token).ConfigureAwait(false);
            BlockCleanup(current, ConnectionEndReason.CleanupTimedOut);
        }
        catch (OperationCanceledException) when (current.CleanupTimer.IsCancellationRequested) { }
        catch (Exception)
        {
            BlockCleanup(current, ConnectionEndReason.AdapterFailure);
        }
        finally { current.CleanupTimer.Dispose(); }
    }

    private void BlockCleanup(Attempt current, ConnectionEndReason reason)
    {
        lock (gate)
        {
            if (!ReferenceEquals(attempt, current) || current.CleanupBlocked) return;
            current.CleanupBlocked = true;
            current.BlockReason = reason;
            desiredTarget = null;
            CancelRetryLocked();
            PublishLocked(ConnectionPhase.CleanupBlocked, reason);
            current.CleanupWait.TrySetResult();
        }
    }

    private void CompleteAttempt(Attempt current, bool released)
    {
        lock (gate)
        {
            if (!ReferenceEquals(attempt, current)) return;
            CancelWithoutBlocking(current.CleanupTimer);
            if (!released)
            {
                current.CleanupBlocked = true;
                current.BlockReason = ConnectionEndReason.AdapterFailure;
                desiredTarget = null;
                PublishLocked(ConnectionPhase.CleanupBlocked, ConnectionEndReason.AdapterFailure);
                current.CleanupWait.TrySetResult();
                return;
            }

            attempt = null;
            if (disposed || desiredTarget is null)
                PublishLocked(ConnectionPhase.Stopped, disposed ? ConnectionEndReason.Disposed :
                    current.StopRequested ? current.StopReason : current.Result);
            else if (current.Generation != generation)
                ProgressLocked(); // Explicit replacement starts only after this release.
            else if (current.Result is not (ConnectionEndReason.UserStopped or ConnectionEndReason.TransientNetworkFailure))
                FinishTerminalLocked(current.Result); // A known rejection must win over a coincident network callback.
            else if (current.StopRequested && current.StopReason is ConnectionEndReason.NetworkUnavailable or ConnectionEndReason.ConnectTimedOut)
            {
                retryReason = current.StopReason;
                ProgressLocked();
            }
            else if (current.Result == ConnectionEndReason.TransientNetworkFailure)
            {
                retryReason = current.Result;
                ProgressLocked();
            }
            else
                FinishTerminalLocked(current.Result);
            current.CleanupWait.TrySetResult();
        }
    }

    private void FinishTerminalLocked(ConnectionEndReason reason)
    {
        desiredTarget = null;
        PublishLocked(reason == ConnectionEndReason.CoreUnavailable ? ConnectionPhase.Unavailable :
            reason == ConnectionEndReason.UserStopped ? ConnectionPhase.Stopped : ConnectionPhase.Failed, reason);
    }

    private void ScheduleRetryLocked()
    {
        if (attemptsStarted > policy.MaximumRetries)
        {
            desiredTarget = null;
            PublishLocked(ConnectionPhase.Failed, ConnectionEndReason.RetryLimitReached);
            return;
        }
        var wait = new RetryWait(generation);
        retry = wait;
        PublishLocked(ConnectionPhase.RetryWaiting, retryReason);
        TimeSpan duration = policy.RetryDelay(attemptsStarted);
        _ = Task.Run(() => WaitForRetryAsync(wait, duration));
    }

    private async Task WaitForRetryAsync(RetryWait wait, TimeSpan duration)
    {
        try
        {
            await delay.DelayAsync(duration, wait.Cancellation.Token).ConfigureAwait(false);
            lock (gate)
            {
                if (!ReferenceEquals(retry, wait) || wait.Generation != generation || disposed) return;
                retry = null;
                BeginAttemptLocked();
            }
        }
        catch (OperationCanceledException) when (wait.Cancellation.IsCancellationRequested) { }
        catch (Exception)
        {
            lock (gate)
            {
                if (!ReferenceEquals(retry, wait)) return;
                retry = null;
                desiredTarget = null;
                PublishLocked(ConnectionPhase.Failed, ConnectionEndReason.AdapterFailure);
            }
        }
        finally { wait.Cancellation.Dispose(); }
    }

    private void CancelRetryLocked()
    {
        var old = retry;
        retry = null;
        if (old is not null) CancelWithoutBlocking(old.Cancellation);
    }

    private static void CancelWithoutBlocking(CancellationTokenSource cancellation)
    {
        // CancelAsync sets IsCancellationRequested synchronously and invokes
        // callbacks asynchronously. Do not defer this call to Task.Run: that
        // would let a queued factory/RunAsync begin after Stop already returned.
        try { _ = ObserveCancellationAsync(cancellation.CancelAsync()); }
        catch (ObjectDisposedException) { }
    }

    private static async Task ObserveCancellationAsync(Task cancellation)
    {
        try { await cancellation.ConfigureAwait(false); }
        catch (Exception) { /* Cancellation callback failures never escape the owner. */ }
    }

    private void PublishLocked(ConnectionPhase phase, ConnectionEndReason reason)
    {
        var next = new ConnectionSnapshot(generation, attempt?.Id ?? nextAttemptId,
            phase, Math.Max(0, attemptsStarted - 1), reason);
        if (snapshot == next) return;
        snapshot = next;
        QueueNotificationLocked(next, subscriptions.ToArray());
    }

    private void QueueNotificationLocked(ConnectionSnapshot state, Subscription[] recipients)
    {
        if (recipients.Length == 0) return;
        foreach (var recipient in recipients)
        {
            recipient.Pending = state;
            if (recipient.Queued) continue;
            recipient.Queued = true;
            notifications.Enqueue(recipient);
        }
        if (dispatching) return;
        dispatching = true;
        _ = Task.Run(DispatchNotifications);
    }

    private void DispatchNotifications()
    {
        while (true)
        {
            Subscription subscription;
            ConnectionSnapshot state;
            lock (gate)
            {
                if (!notifications.TryDequeue(out subscription!))
                {
                    dispatching = false;
                    return;
                }
                subscription.Queued = false;
                state = subscription.Pending!;
            }
            subscription.Deliver(state);
        }
    }

    private void Unsubscribe(Subscription subscription)
    {
        subscription.Deactivate();
        lock (gate) subscriptions.Remove(subscription);
    }

    private sealed class Subscription(ConnectionCoordinator owner, Action<ConnectionSnapshot> observer) : IDisposable
    {
        private int inactive;
        // Both fields are accessed only while holding the coordinator gate.
        public ConnectionSnapshot? Pending;
        public bool Queued;
        public void Deactivate() => Interlocked.Exchange(ref inactive, 1);
        public void Deliver(ConnectionSnapshot state)
        {
            if (Volatile.Read(ref inactive) != 0) return;
            try { observer(state); } catch (Exception) { /* Isolate presentation failures. */ }
        }
        public void Dispose() => owner.Unsubscribe(this);
    }

    private sealed class Attempt(long generation, long id, ConnectionTarget target)
    {
        public long Generation { get; } = generation;
        public long Id { get; } = id;
        public ConnectionTarget Target { get; } = target;
        public CancellationTokenSource Cancellation { get; } = new();
        public CancellationTokenSource ConnectTimer { get; } = new();
        public CancellationTokenSource CleanupTimer { get; } = new();
        public TaskCompletionSource CleanupWait { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public bool StopRequested, CleanupStarted, CleanupBlocked, Activated;
        public ConnectionEndReason StopReason, Result, BlockReason;
    }
    private sealed class RetryWait(long generation)
    {
        public long Generation { get; } = generation;
        public CancellationTokenSource Cancellation { get; } = new();
    }
    private sealed class SystemConnectionDelay : IConnectionDelay
    {
        public Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken)
            => Task.Delay(duration, cancellationToken);
    }
}
