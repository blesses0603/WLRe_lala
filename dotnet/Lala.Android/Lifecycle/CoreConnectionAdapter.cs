using Lala.Core.Sessions;

namespace Lala.Android.Lifecycle;

/// <summary>
/// Resolves an opaque selection only after an explicit lifecycle start. The host owns
/// this resolver and credential sources, including their final disposal. Never derive
/// secrets from Target, Intent extras, environment variables or log messages.
/// </summary>
public interface ICoreConnectionSelectionResolver
{
    ValueTask<CoreConnectionSelection?> ResolveAsync(ConnectionTarget target, CancellationToken cancellationToken);
}

/// <summary>Explicit profile and caller-owned credential source. No resource authority.</summary>
public sealed record CoreConnectionSelection(AccountConnectionProfile Profile, IAccountCredentialSource Credentials)
{
    public override string ToString() => nameof(CoreConnectionSelection);
}

/// <summary>
/// Opt-in integration only; production keeps UnavailableConnectionAdapterFactory until
/// secure selection and credential providers exist. Construction/Create are inert.
/// Lifecycle owns all retries; each adapter runs exactly one Core attempt.
/// </summary>
public sealed class CoreConnectionAdapterFactory : IConnectionAdapterFactory
{
    private readonly ICoreConnectionSelectionResolver resolver;
    private readonly AccountConnectionOptions options;
    public CoreConnectionAdapterFactory(ICoreConnectionSelectionResolver resolver, AccountConnectionOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(resolver);
        this.resolver = resolver;
        this.options = (options ?? new()) with { MaximumAttempts = 1 };
    }
    public bool IsAvailable => true;
    public IConnectionAdapter Create(ConnectionTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        target.Validate();
        return new Adapter(resolver, target, options);
    }

    private sealed class Adapter(ICoreConnectionSelectionResolver resolver, ConnectionTarget target,
        AccountConnectionOptions options) : IHeldConnectionAdapter
    {
        private readonly object gate = new();
        private readonly CancellationTokenSource stop = new();
        private Task<ConnectionEndReason>? running;
        private Task? disposal;
        private AccountConnectionRuntime? admittedRuntime;
        private bool disposed, cleanupFailed;

        // Legacy consumers get no Active notification: held login never grants authority.
        public Task<ConnectionEndReason> RunAsync(Action onActive, CancellationToken token)
            => RunHeldAsync(() => { }, () => { }, token);

        public Task<ConnectionEndReason> RunHeldAsync(Action onReceivingHeld, Action onRetiring, CancellationToken token)
        {
            ArgumentNullException.ThrowIfNull(onReceivingHeld);
            ArgumentNullException.ThrowIfNull(onRetiring);
            lock (gate)
            {
                if (disposed) return Task.FromResult(ConnectionEndReason.UserStopped);
                return running ??= Task.Run(() => RunCoreAsync(onReceivingHeld, onRetiring, token));
            }
        }

        private async Task<ConnectionEndReason> RunCoreAsync(Action onReceivingHeld, Action onRetiring, CancellationToken token)
        {
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(token, stop.Token);
            AccountConnectionRuntime? runtime = null;
            try
            {
                linked.Token.ThrowIfCancellationRequested();
                var selection = await resolver.ResolveAsync(target, linked.Token).ConfigureAwait(false);
                linked.Token.ThrowIfCancellationRequested();
                if (selection is null) return ConnectionEndReason.CoreUnavailable;
                lock (gate)
                {
                    // Cancellation callbacks can lag behind disposal. This is the actual
                    // admission barrier, not a check of the linked token alone.
                    if (disposed || token.IsCancellationRequested || stop.IsCancellationRequested)
                        return ConnectionEndReason.UserStopped;
                    var session = new AccountSession();
                    var generation = session.Begin(target.AccountKey, target.Endpoint).Generation;
                    runtime = new(session, generation, selection.Profile, selection.Credentials, options);
                    admittedRuntime = runtime;
                }
                var run = runtime.RunAsync(linked.Token);
                bool reported = false, retiring = false;
                while (!run.IsCompleted)
                {
                    var status = runtime.Snapshot;
                    if (!reported && status.Phase == AccountConnectionPhase.ReceivingHeld && !linked.IsCancellationRequested)
                    {
                        reported = true;
                        onReceivingHeld();
                    }
                    if (!retiring && status.Phase is AccountConnectionPhase.Draining or AccountConnectionPhase.Stopping or AccountConnectionPhase.Ended)
                    {
                        retiring = true;
                        onRetiring();
                    }
                    if (status.Phase == AccountConnectionPhase.Ended) break;
                    try { await runtime.WaitForChangeAsync(status, linked.Token).ConfigureAwait(false); }
                    catch (OperationCanceledException) when (linked.IsCancellationRequested) { break; }
                }
                var result = await run.ConfigureAwait(false);
                if (!result.ResourcesReleased) { cleanupFailed = true; return ConnectionEndReason.AdapterFailure; }
                return MapResult(result);
            }
            catch (OperationCanceledException) when (linked.IsCancellationRequested)
            {
                return ConnectionEndReason.UserStopped;
            }
            catch (Exception)
            {
                return ConnectionEndReason.AdapterFailure;
            }
            finally
            {
                if (runtime is not null)
                {
                    try { await runtime.DisposeAsync().ConfigureAwait(false); }
                    catch (Exception) { cleanupFailed = true; }
                    finally { lock (gate) admittedRuntime = null; }
                }
            }
        }

        public ValueTask DisposeAsync()
        {
            lock (gate)
            {
                disposed = true;
                // Core Stop revokes admission synchronously; it schedules cancellation
                // callbacks outside its lock. A not-yet-started runtime stays inert.
                admittedRuntime?.Stop();
                return new(disposal ??= DisposeCoreAsync());
            }
        }
        private async Task DisposeCoreAsync()
        {
            try { await stop.CancelAsync().ConfigureAwait(false); }
            catch (Exception) { cleanupFailed = true; }
            try { if (running is not null) await running.ConfigureAwait(false); }
            catch (Exception) { cleanupFailed = true; }
            finally { stop.Dispose(); }
            if (cleanupFailed) throw new InvalidOperationException("Core connection cleanup was not confirmed.");
        }
    }

    internal static ConnectionEndReason MapResult(AccountConnectionResult result)
    {
        if (!result.ResourcesReleased) return ConnectionEndReason.AdapterFailure;
        var status = result.Status;
        if (status.History.Length == 1)
        {
            var attempt = status.History[0];
            if (attempt.Failure == AccountConnectionFailure.WriteUncertain) return ConnectionEndReason.AdapterFailure;
            if (attempt.RetryEligible) return ConnectionEndReason.TransientNetworkFailure;
            if (attempt.Failure != AccountConnectionFailure.CancelledOrHeld)
                return ConnectionEndReason.AdapterFailure;
        }
        if (status.EndReason is AccountConnectionEndReason.Cancelled or AccountConnectionEndReason.Stopped or AccountConnectionEndReason.Disposed)
            return ConnectionEndReason.UserStopped;
        // A declined credential source or login-protocol failure does not prove
        // authentication rejection. Keep those terminal without inventing evidence.
        return ConnectionEndReason.AdapterFailure;
    }
}
