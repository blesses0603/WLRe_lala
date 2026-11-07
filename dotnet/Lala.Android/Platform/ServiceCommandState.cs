namespace Lala.Android.Platform;

/// <summary>
/// Main-thread service intent state. An initial/stopped Core snapshot cannot end
/// the foreground handshake while an explicit start is still being delivered.
/// Completion from an older command never releases a newer command's guard.
/// </summary>
internal sealed class ServiceCommandState
{
    private long _epoch;
    private long? _pendingStart;

    public long Epoch => _epoch;
    public bool StartPending => _pendingStart is not null;
    public bool IsCurrent(long epoch) => epoch == _epoch;
    public bool CanFinish(bool connectionRunning) => !connectionRunning && !StartPending;

    public long BeginStart()
    {
        _epoch = checked(_epoch + 1);
        _pendingStart = _epoch;
        return _epoch;
    }

    public long BeginStop()
    {
        _epoch = checked(_epoch + 1);
        _pendingStart = null;
        return _epoch;
    }

    public bool CompleteStart(long epoch)
    {
        if (!IsCurrent(epoch) || _pendingStart != epoch)
            return false;
        _pendingStart = null;
        return true;
    }
}

/// <summary>
/// Atomically checks service ownership and begins a Core operation. The supplied
/// delegate must perform its state mutation synchronously before returning its
/// Task (as ConnectionCoordinator does); only cleanup may complete later.
/// Ownership is never held while awaiting cleanup, and old owners cannot issue
/// a deferred stop after a replacement service acquires the lease.
/// </summary>
internal sealed class ServiceOwnerLease
{
    private readonly object _gate = new();
    private long _owner;

    public long Acquire()
    {
        lock (_gate)
            return _owner = checked(_owner + 1);
    }

    public bool IsCurrent(long owner)
    {
        lock (_gate)
            return owner == _owner;
    }

    public Task? Invoke(long owner, Func<Task> beginOperation)
    {
        ArgumentNullException.ThrowIfNull(beginOperation);
        lock (_gate)
            return owner == _owner ? beginOperation() : null;
    }
}
