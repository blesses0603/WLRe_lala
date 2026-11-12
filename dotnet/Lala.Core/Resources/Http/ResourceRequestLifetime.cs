namespace Lala.Core.Resources;

/// <summary>Owns timeout and cancellation forwarding. No exception from a hostile cancellation
/// callback escapes the timer thread. Cleanup waits for tracked callbacks before disposing CTS.</summary>
internal sealed class ResourceRequestLifetime : IDisposable
{
    private readonly CancellationTokenSource _cancellation = new();
    private readonly object _gate = new();
    private readonly Action _recordFailure;
    private readonly Dictionary<int, int> _callbackThreads = [];
    private CancellationTokenRegistration _caller, _shutdown;
    private ITimer? _timer;
    private TaskCompletionSource? _retirement;
    private int _active, _disposed, _failed;
    private bool _stopping, _deferred;
    internal CancellationToken Token { get; }
    internal bool CleanupIncomplete => Volatile.Read(ref _failed) != 0;
    internal bool DisposalAttemptsComplete => Volatile.Read(ref _disposed) == 2;

    internal ResourceRequestLifetime(CancellationToken caller, CancellationToken shutdown,
        TimeSpan timeout, TimeProvider clock, Action recordFailure)
    {
        _recordFailure = recordFailure;
        Token = _cancellation.Token;
        try
        {
            _caller = caller.Register(CancelTracked);
            _shutdown = shutdown.Register(CancelTracked);
            // Initialize the timer before enabling it, so callback self-disposal sees its owner.
            _timer = clock.CreateTimer(_ => CancelTracked(), null, Timeout.InfiniteTimeSpan, Timeout.InfiniteTimeSpan);
            if (!_timer.Change(timeout, Timeout.InfiniteTimeSpan)) throw new InvalidOperationException();
        }
        catch (Exception)
        {
            // Construction never exposes vendor/clock/callback exception details.
            var primary = new ResourceTransportException(ResourceTransportFailure.Transport);
            ResourceCleanup.DisposePreservingFailure(this, primary);
            throw primary;
        }
    }
    private void Fail()
    {
        Interlocked.Exchange(ref _failed, 1);
        _recordFailure();
    }
    private bool Attempt(Action action)
    {
        try { action(); return true; }
        catch (Exception) { Fail(); return false; }
    }
    private void CancelTracked()
    {
        int thread = Environment.CurrentManagedThreadId;
        lock (_gate)
        {
            if (_stopping) return;
            if (_active++ == 0) _retirement = new(TaskCreationOptions.RunContinuationsAsynchronously);
            _callbackThreads[thread] = _callbackThreads.GetValueOrDefault(thread) + 1;
        }
        try { Attempt(_cancellation.Cancel); }
        finally
        {
            TaskCompletionSource? retired = null;
            bool deferred = false;
            lock (_gate)
            {
                if (--_callbackThreads[thread] == 0) _callbackThreads.Remove(thread);
                if (--_active == 0) { retired = _retirement; deferred = _deferred; }
            }
            // No lock is held across cancellation, disposal or callback retirement.
            try
            {
                if (deferred) FinishOwnedCleanup();
            }
            finally
            {
                if (deferred) Volatile.Write(ref _disposed, 2);
                retired?.TrySetResult();
            }
        }
    }
    private void FinishOwnedCleanup()
    {
        Attempt(_caller.Dispose);
        Attempt(_shutdown.Dispose);
        Attempt(_cancellation.Dispose);
    }
    public void Dispose()
    {
        int prior = Interlocked.CompareExchange(ref _disposed, 1, 0);
        if (prior != 0)
        {
            ResourceCleanup.Report(prior != 2 || CleanupIncomplete);
            return;
        }
        Task retirement;
        bool self;
        lock (_gate)
        {
            _stopping = true;
            retirement = _retirement?.Task ?? Task.CompletedTask;
            self = _callbackThreads.ContainsKey(Environment.CurrentManagedThreadId);
            _deferred = self;
        }
        // Stop future callbacks, unregister non-blockingly, then wait for all admitted
        // cancellation callbacks. A callback already queued sees _stopping and does no work.
        if (_timer is not null) Attempt(_timer.Dispose);
        Attempt(() => _caller.Unregister());
        Attempt(() => _shutdown.Unregister());
        if (self)
        {
            // Cannot await our own callback. Its final exit performs CTS/registration cleanup.
            // Pending/incomplete is explicit, and later Dispose calls cannot report success.
            Fail();
            ResourceCleanup.Report(true);
            return;
        }
        try
        {
            retirement.GetAwaiter().GetResult();
            FinishOwnedCleanup();
        }
        finally { Volatile.Write(ref _disposed, 2); }
        ResourceCleanup.Report(CleanupIncomplete);
    }
}
