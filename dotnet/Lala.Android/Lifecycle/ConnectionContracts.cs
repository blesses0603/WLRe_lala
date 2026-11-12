namespace Lala.Android.Lifecycle;

/// <summary>Opaque selection only. Never put passwords, tokens or packet data here.</summary>
public sealed record ConnectionTarget(string AccountKey, string Endpoint)
{
    internal void Validate()
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(AccountKey);
        ArgumentException.ThrowIfNullOrWhiteSpace(Endpoint);
    }

    // Accidental interpolation must not disclose the selected account or endpoint.
    public override string ToString() => nameof(ConnectionTarget);
}

public enum ConnectionPhase
{
    Stopped, Unavailable, WaitingForNetwork, Connecting, Active,
    RetryWaiting, Stopping, CleanupBlocked, Failed, ReceivingHeld
}

internal static class ConnectionPhaseState
{
    internal static bool IsRunning(ConnectionPhase phase) => phase is ConnectionPhase.WaitingForNetwork
        or ConnectionPhase.Connecting or ConnectionPhase.Active or ConnectionPhase.ReceivingHeld
        or ConnectionPhase.RetryWaiting or ConnectionPhase.Stopping or ConnectionPhase.CleanupBlocked;
}

public enum ConnectionEndReason
{
    None, UserStopped, NetworkUnavailable, TransientNetworkFailure, RemoteClosed,
    AuthenticationRejected, ResourceHeld, CoreUnavailable, AdapterFailure,
    ConnectTimedOut, CleanupTimedOut, RetryLimitReached, Disposed
}

/// <summary>Safe immutable host state; intentionally contains no account, endpoint or exception text.</summary>
public sealed record ConnectionSnapshot(long Generation, long AttemptId,
    ConnectionPhase Phase, int RetryCount, ConnectionEndReason Reason);

public sealed record ConnectionPolicy
{
    public int MaximumRetries { get; init; } = 5;
    public TimeSpan InitialRetryDelay { get; init; } = TimeSpan.FromSeconds(1);
    public TimeSpan MaximumRetryDelay { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan ConnectTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan CleanupTimeout { get; init; } = TimeSpan.FromSeconds(5);

    internal void Validate()
    {
        if (MaximumRetries < 0) throw new ArgumentOutOfRangeException(nameof(MaximumRetries));
        if (InitialRetryDelay <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(InitialRetryDelay));
        if (MaximumRetryDelay < InitialRetryDelay) throw new ArgumentOutOfRangeException(nameof(MaximumRetryDelay));
        if (ConnectTimeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(ConnectTimeout));
        if (CleanupTimeout <= TimeSpan.Zero) throw new ArgumentOutOfRangeException(nameof(CleanupTimeout));
    }

    internal TimeSpan RetryDelay(int retryNumber)
        => TimeSpan.FromTicks((long)Math.Min(MaximumRetryDelay.Ticks,
            InitialRetryDelay.Ticks * Math.Pow(2, Math.Min(retryNumber - 1, 62))));
}

public interface IConnectionDelay
{
    Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken);
}

public interface IConnectionAdapterFactory
{
    /// <summary>Read once by the coordinator. False means no configured usable Core adapter is available.</summary>
    bool IsAvailable { get; }

    /// <summary>Create one owner without opening a socket. No Android objects or credentials cross this boundary.</summary>
    IConnectionAdapter Create(ConnectionTarget target);
}

public interface IConnectionAdapter : IAsyncDisposable
{
    /// <summary>
    /// Own the complete attempt until it ends. Call onActive only after Core has
    /// confirmed its real session is active; OS network availability is insufficient.
    /// Honor cancellation and close resources in DisposeAsync. Callbacks may arrive
    /// late: the host rejects stale generations and attempts. Never replay commands.
    /// </summary>
    Task<ConnectionEndReason> RunAsync(Action onActive, CancellationToken cancellationToken);
}

/// <summary>Protocol login with receive running, but resource authority remains held.
/// The callback cancels the login watchdog, never authorizes gameplay or commands.</summary>
public interface IHeldConnectionAdapter : IConnectionAdapter
{
    /// <summary>onRetiring starts the cleanup watchdog without changing the final
    /// outcome or cancelling the attempt. It is not proof that resources are released.</summary>
    Task<ConnectionEndReason> RunHeldAsync(Action onReceivingHeld, Action onRetiring, CancellationToken cancellationToken);
}

/// <summary>Production default until secure account/profile/credential selection is configured. It never simulates a connection.</summary>
public sealed class UnavailableConnectionAdapterFactory : IConnectionAdapterFactory
{
    public bool IsAvailable => false;
    public IConnectionAdapter Create(ConnectionTarget target)
        => throw new InvalidOperationException("Shared Core transport is unavailable.");
}
