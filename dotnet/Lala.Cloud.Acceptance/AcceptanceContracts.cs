using Lala.Core.Sessions;

namespace Lala.Cloud.Acceptance;

public enum AcceptancePhase { Created, WaitingForLogin, ObservingHeldReceive, Stopping, Completed }
public enum AcceptanceStopReason { None, ObservationWindowElapsed, OverallDeadline, CallerCancellation, ConnectionEnded, RunnerFailure }
public enum LoginProtocolEvidence { NotObserved, Completed }
public enum ReceiveEvidence { NoBaseline, BaselineObserved, RevisionAdvanced }
public enum CleanupDisposition { Released, Failed }
public enum AcceptanceOutcome
{
    ProtocolCompleteWithReceiveProgress, ProtocolCompleteWithoutReceiveProgress,
    IncompleteLogin, LoginProtocolFailed, ConnectionFailed, CredentialsUnavailable,
    CredentialProviderFailed, ObservationInterrupted, Cancelled, DeadlineExpired, CleanupFailed, RunnerFailed
}

/// <summary>Only enums and counts. No endpoint, account, credential, exception, GUID,
/// receive state, packet contents or catalog contents are retained in this observation.</summary>
public sealed record AcceptanceProgress(
    AcceptancePhase Phase,
    AcceptanceStopReason StopReason,
    LoginProtocolEvidence Login,
    ReceiveEvidence Receive,
    int PollCount,
    long? BaselineRevision,
    long? LatestRevision)
{
    public long RevisionAdvanceCount => BaselineRevision is { } first && LatestRevision is { } last
        ? Math.Max(0, last - first) : 0;
}

/// <summary>Sanitized evidence, not authentication, resource admission, gameplay
/// authorization, proof of heartbeat handling, or official/live-server validation.</summary>
public sealed record AcceptanceResult(
    AcceptanceOutcome Outcome,
    AcceptanceStopReason StopReason,
    LoginProtocolEvidence Login,
    ReceiveEvidence Receive,
    CleanupDisposition Cleanup,
    int AttemptCount,
    int PollCount,
    long? BaselineRevision,
    long? LatestRevision,
    AccountConnectionEndReason? ConnectionEnd,
    AccountConnectionFailure? ConnectionFailure)
{
    public long RevisionAdvanceCount => BaselineRevision is { } first && LatestRevision is { } last
        ? Math.Max(0, last - first) : 0;
}

/// <summary>Timing bounds request stop; they are not hard cleanup deadlines.
/// An admitted noncooperative credential callback must return before completion.</summary>
public sealed record AcceptanceOptions
{
    public TimeSpan OverallTimeout { get; init; } = TimeSpan.FromSeconds(45);
    public TimeSpan ObservationWindow { get; init; } = TimeSpan.FromSeconds(5);
    public TimeSpan PollInterval { get; init; } = TimeSpan.FromMilliseconds(20);
    public TimeSpan LoginTimeout { get; init; } = TimeSpan.FromSeconds(30);
    public TimeSpan ConnectTimeout { get; init; } = TimeSpan.FromSeconds(5);
    public TimeSpan ReadTimeout { get; init; } = TimeSpan.FromSeconds(45);
    public TimeSpan WriteTimeout { get; init; } = TimeSpan.FromSeconds(10);

    internal void Validate()
    {
        PositiveBound(OverallTimeout, TimeSpan.FromMinutes(5), nameof(OverallTimeout));
        PositiveBound(ObservationWindow, OverallTimeout, nameof(ObservationWindow));
        PositiveBound(PollInterval, TimeSpan.FromSeconds(1), nameof(PollInterval));
        if (PollInterval < TimeSpan.FromMilliseconds(1) || PollInterval > ObservationWindow)
            throw new ArgumentOutOfRangeException(nameof(PollInterval));
        PositiveBound(LoginTimeout, TimeSpan.FromMinutes(2), nameof(LoginTimeout));
        PositiveBound(ConnectTimeout, TimeSpan.FromMinutes(5), nameof(ConnectTimeout));
        PositiveBound(ReadTimeout, TimeSpan.FromMinutes(5), nameof(ReadTimeout));
        PositiveBound(WriteTimeout, TimeSpan.FromMinutes(5), nameof(WriteTimeout));
    }

    private static void PositiveBound(TimeSpan value, TimeSpan maximum, string parameter)
    {
        if (value <= TimeSpan.Zero || value > maximum)
            throw new ArgumentOutOfRangeException(parameter);
    }
}
