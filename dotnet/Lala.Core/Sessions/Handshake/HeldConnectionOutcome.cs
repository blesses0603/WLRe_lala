using Lala.Core.Sessions.Receive;

namespace Lala.Core.Sessions.Handshake;

internal enum HeldConnectionFailure
{
    ConnectFailed, ConnectTimedOut, RemoteEof, ReadFailed,
    IncompleteLoginOrUnknown, LoginProtocolFailed, ProviderFailed, LoginDeadline,
    WriteFailed, WriteUncertain, CancelledOrHeld, CleanupFailed, InvalidProtocol,
    ObservationFailed, ReductionFailed, EventHandlerFailed, ReadTimedOut
}

/// <summary>Historical retry evidence only. Never grants login or resource authority.</summary>
internal sealed record HeldConnectionOutcome(HeldConnectionFailure Failure, bool LoginCompleted, bool CanReconnect)
{
    internal static HeldConnectionOutcome Classify(ReceiveResult result, bool loginCompleted,
        IEnumerable<HeldConnectionFailure> recorded)
    {
        var facts = recorded.ToHashSet();
        HeldConnectionOutcome Stop(HeldConnectionFailure failure) => new(failure, loginCompleted, false);
        if (!result.ResourcesReleased || result.End == ReceiveEnd.CleanupFailed)
            return Stop(HeldConnectionFailure.CleanupFailed);
        // A racing read must never hide a failed/uncertain write or pre-commit failure.
        foreach (var failure in new[] { HeldConnectionFailure.WriteUncertain, HeldConnectionFailure.WriteFailed,
            HeldConnectionFailure.ProviderFailed, HeldConnectionFailure.LoginDeadline,
            HeldConnectionFailure.LoginProtocolFailed, HeldConnectionFailure.InvalidProtocol,
            HeldConnectionFailure.EventHandlerFailed, HeldConnectionFailure.IncompleteLoginOrUnknown })
            if (facts.Contains(failure)) return Stop(failure);
        foreach (var failure in facts)
            if (failure is not (HeldConnectionFailure.ConnectFailed or HeldConnectionFailure.ConnectTimedOut or
                HeldConnectionFailure.RemoteEof or HeldConnectionFailure.ReadFailed or HeldConnectionFailure.ReadTimedOut or HeldConnectionFailure.CancelledOrHeld)) return Stop(failure);
        switch (result.End)
        {
            case ReceiveEnd.Cancelled: case ReceiveEnd.Disposed: return Stop(HeldConnectionFailure.CancelledOrHeld);
            case ReceiveEnd.InvalidFrame: case ReceiveEnd.TruncatedFrame: case ReceiveEnd.InvalidPayload:
                return Stop(HeldConnectionFailure.InvalidProtocol);
            case ReceiveEnd.ObservationInputFailed: case ReceiveEnd.MissingArkRuntime:
                return Stop(HeldConnectionFailure.ObservationFailed);
            case ReceiveEnd.ReductionFailed: return Stop(HeldConnectionFailure.ReductionFailed);
            case ReceiveEnd.EventHandlerFailed: return Stop(HeldConnectionFailure.EventHandlerFailed);
        }
        // Cancellation caused by receive retirement is secondary evidence: a decoder or
        // observer failure that triggered it must remain visible, not resemble a clean stop.
        if (facts.Contains(HeldConnectionFailure.CancelledOrHeld)) return Stop(HeldConnectionFailure.CancelledOrHeld);
        if (result.End == ReceiveEnd.ReadFailed)
        {
            if (facts.Contains(HeldConnectionFailure.ConnectFailed)) return new(HeldConnectionFailure.ConnectFailed, loginCompleted, true);
            if (facts.Contains(HeldConnectionFailure.ConnectTimedOut)) return new(HeldConnectionFailure.ConnectTimedOut, loginCompleted, true);
            if (facts.Contains(HeldConnectionFailure.ReadTimedOut)) return new(HeldConnectionFailure.ReadTimedOut, loginCompleted, loginCompleted);
            if (loginCompleted && facts.Contains(HeldConnectionFailure.ReadFailed)) return new(HeldConnectionFailure.ReadFailed, true, true);
        }
        if (result.End == ReceiveEnd.Completed && loginCompleted && facts.Contains(HeldConnectionFailure.RemoteEof))
            return new(HeldConnectionFailure.RemoteEof, true, true);
        return Stop(HeldConnectionFailure.IncompleteLoginOrUnknown);
    }
}
