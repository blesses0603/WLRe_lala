using System.Collections.Immutable;
using System.Net;
using System.Net.Sockets;
using Lala.Core.State;

namespace Lala.Core.Sessions;

/// <summary>Explicit caller-selected raw TCP targets and protocol profile. No production
/// endpoints are discovered or assumed. Game XOR is not credential encryption.</summary>
public sealed class AccountConnectionProfile
{
    private readonly IPEndPoint verification, formal;
    public IPEndPoint VerificationEndpoint => Copy(verification);
    public IPEndPoint FormalEndpoint => Copy(formal);
    public byte TransmitXor { get; }
    public byte ReceiveXor { get; }
    public int RoleIndex { get; }
    public byte Platform { get; }
    public byte Language { get; }
    public AccountConnectionProfile(IPEndPoint verificationEndpoint, IPEndPoint formalEndpoint,
        byte transmitXor, byte receiveXor, int roleIndex, byte platform, byte language)
    {
        verification = Copy(verificationEndpoint); formal = Copy(formalEndpoint);
        if (roleIndex is not (1 or 2)) throw new ArgumentOutOfRangeException(nameof(roleIndex));
        TransmitXor = transmitXor; ReceiveXor = receiveXor; RoleIndex = roleIndex;
        Platform = platform; Language = language;
    }
    private static IPEndPoint Copy(IPEndPoint endpoint)
    {
        ArgumentNullException.ThrowIfNull(endpoint);
        if (endpoint.Port == 0 || endpoint.AddressFamily is not (AddressFamily.InterNetwork or AddressFamily.InterNetworkV6))
            throw new ArgumentException("A concrete IP endpoint is required.", nameof(endpoint));
        var address = endpoint.Address;
        return new(address.AddressFamily == AddressFamily.InterNetworkV6
            ? new IPAddress(address.GetAddressBytes(), address.ScopeId) : new IPAddress(address.GetAddressBytes()), endpoint.Port);
    }
    public override string ToString() => nameof(AccountConnectionProfile);
}

/// <summary>One attempt by default, so hosts explicitly select a single retry owner.
/// Do not nest multi-attempt Core retries inside another host retry policy.</summary>
public sealed record AccountConnectionOptions
{
    public int MaximumAttempts { get; init; } = 1;
    public TimeSpan InitialRetryDelay { get; init; } = TimeSpan.FromSeconds(1);
    public TimeSpan MaximumRetryDelay { get; init; } = TimeSpan.FromSeconds(10);
    public TimeSpan MaximumRecoveryTime { get; init; } = TimeSpan.FromMinutes(5);
    public TimeSpan LoginTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan ConnectTimeout { get; init; } = TimeSpan.FromSeconds(5);
    public TimeSpan ReadTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan WriteTimeout { get; init; } = TimeSpan.FromSeconds(10);
}

/// <summary>Sanitized acquisition context. Account selection belongs to the host/source;
/// this generation is an ownership marker, not authenticated identity evidence.</summary>
public sealed record AccountCredentialRequest(long Generation, int AttemptNumber);
public interface IAccountCredentialSource
{
    /// <summary>Return a fresh, exclusively owned credential object per attempt, or null to
    /// decline. Ownership transfers to the runtime on return. The caller owns this source;
    /// it is never disposed by the runtime. Honor cancellation; marshal any UI prompt yourself.
    /// No source invocation occurs before RunAsync. No secret may be put in an exception.</summary>
    ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken cancellationToken);
}

public enum AccountConnectionPhase { Created, AcquiringCredentials, Connecting, ReceivingHeld, RetryWaiting, Stopping, Ended }
public enum AccountConnectionEndReason { ConnectionEnded, AttemptsExhausted, CredentialsUnavailable, ProviderFailed,
    AdmissionBlocked, Superseded, Cancelled, Stopped, Disposed, RecoveryDeadline, CleanupFailed, DelayFailed }
public enum AccountConnectionFailure { ConnectFailed, ConnectTimedOut, RemoteEof, ReadFailed,
    IncompleteLoginOrUnknown, LoginProtocolFailed, ProviderFailed, LoginDeadline, WriteFailed,
    WriteUncertain, CancelledOrHeld, CleanupFailed, InvalidProtocol, ObservationFailed, ReductionFailed, EventHandlerFailed }
public sealed record AccountConnectionAttempt(long Generation, Guid Attempt, AccountConnectionFailure Failure,
    bool LoginProtocolCompleted, bool RetryEligible);
public sealed record AccountConnectionStatus(Guid RuntimeId, long Generation, int AttemptNumber,
    AccountConnectionPhase Phase, AccountConnectionEndReason? EndReason, TimeSpan? RetryDelay,
    ImmutableArray<AccountConnectionAttempt> History)
{
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
}
public sealed record AccountConnectionResult(AccountConnectionStatus Status, bool ResourcesReleased);
public enum AccountReceivePhase { Created, Running, Ending, Ended }
/// <summary>Immutable read-only point-in-time observation. Retained snapshots can become
/// stale and never authorize effects. State is not sanitized for logging; ToString is redacted.</summary>
public sealed record AccountReceivePublication(Guid Attempt, long Revision, AccountReceivePhase Phase, ServiceStateSnapshot State)
{
    public bool ResourceHeld => true;
    public override string ToString() => nameof(AccountReceivePublication);
}
public sealed class AccountConnectionCleanupException() : IOException("Account connection cleanup did not complete successfully.");
