using Lala.Core.Sessions.Handshake;
namespace Lala.Core.Sessions;

public enum AccountLoginStage
{
    ConnectingVerification, SendingVerification, AwaitingVerification, ConnectingFormal,
    SendingFormal, AwaitingFormal, AwaitingRoles, SelectingRole, SendingRole,
    AwaitingWorld, AcknowledgingWorld, ProtocolComplete, Failed, Cancelled, Held
}
/// <summary>Observed handshake stage only. No credentials, packet contents or game-command authority.</summary>
public sealed record AccountLoginProgress(Guid Attempt, AccountLoginStage Stage)
{
    internal static AccountLoginProgress From(HandshakeView value) => new(value.Attempt, value.Phase switch
    {
        HandshakePhase.Created => AccountLoginStage.ConnectingVerification,
        HandshakePhase.VerificationWrite => AccountLoginStage.SendingVerification,
        HandshakePhase.VerificationReply => AccountLoginStage.AwaitingVerification,
        HandshakePhase.Verified => AccountLoginStage.ConnectingFormal,
        HandshakePhase.FormalWrite => AccountLoginStage.SendingFormal,
        HandshakePhase.FormalReply => AccountLoginStage.AwaitingFormal,
        HandshakePhase.Roles => AccountLoginStage.AwaitingRoles,
        HandshakePhase.Selection => AccountLoginStage.SelectingRole,
        HandshakePhase.SelectionWrite => AccountLoginStage.SendingRole,
        HandshakePhase.World => AccountLoginStage.AwaitingWorld,
        HandshakePhase.MapAckWrite or HandshakePhase.AppearAckWrite => AccountLoginStage.AcknowledgingWorld,
        HandshakePhase.ScriptedComplete => AccountLoginStage.ProtocolComplete,
        HandshakePhase.Cancelled => AccountLoginStage.Cancelled,
        HandshakePhase.Held => AccountLoginStage.Held,
        _ => AccountLoginStage.Failed
    });
}
