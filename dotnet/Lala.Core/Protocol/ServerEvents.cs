using System.Collections.Immutable;
using Lala.Core.Activities;
using Lala.Core.Instances;

namespace Lala.Core.Protocol;

/// <summary>Offline decoded server data, never an instruction or authorization to send.</summary>
public abstract record ServerEvent(byte Main, byte Sub)
{
    public abstract string Type { get; }
}

public sealed record ServerInstanceEvent(byte Main, byte Sub, InstanceEvent Event) : ServerEvent(Main, Sub)
{
    public override string Type => Event.Type;
}

// Reuse the already migrated immutable event models instead of converting them to dictionaries.
public sealed record ServerLayoutEvent(LayoutEvent Event) : ServerEvent(Event.Main, Event.Sub)
{
    public override string Type => Event.Type;
}
public sealed record ServerLiveDataEvent(LiveDataEvent Event) : ServerEvent(Event.Main, Event.Sub)
{
    public override string Type => Event.Type;
}
public sealed record ServerSocialEvent(SocialEvent Event) : ServerEvent(Event.Main, Event.Sub)
{
    public override string Type => Event.Type;
}
public sealed record ServerActivityEvent(byte Main, byte Sub, ActivityEvent Event)
    : ServerEvent(Main, Sub)
{
    public override string Type => Event.Roles is null ? "activity_self" : "activity_roles";
}
public sealed record ServerExpeditionEvent(byte Sub, ExpeditionEvent Event) : ServerEvent(31, Sub)
{
    public override string Type => Event switch
    {
        OutpostSnapshotEvent => "outpost_snapshot", OutpostRoleEvent => "outpost_role",
        OutpostRemoveEvent => "outpost_remove", OutpostStatusEvent => "outpost_status",
        OutpostFaithEvent => "outpost_faith", OutpostAttributeEvent => "outpost_attribute",
        ExpeditionSnapshotEvent => "expedition_snapshot", ExpeditionStartedEvent => "expedition_started",
        ExpeditionResultEvent => "expedition_result", ExpeditionTimeEvent => "expedition_time",
        ExpeditionTeamEvent => "expedition_team", ExpeditionQuestsEvent => "expedition_quests",
        ExpeditionRejectedEvent => "expedition_rejected", ExpeditionLevelEvent => "expedition_level",
        _ => throw new InvalidOperationException("Unknown expedition event")
    };
}
public sealed record UnimplementedServerEvent(byte Main, byte Sub, int PayloadBytes)
    : ServerEvent(Main, Sub)
{
    public override string Type => "unimplemented";
}
/// <summary>The named Python decoder has not been ported. No body validation or partial
/// interpretation was attempted, including for keys which shadow a simpler direct branch.</summary>
public sealed record UnsupportedServerDecoderEvent(byte Main, byte Sub, string Decoder, int PayloadBytes)
    : ServerEvent(Main, Sub)
{
    public override string Type => "unsupported_decoder";
}
public sealed record NavigationGeometryChangeEvent(byte Main, byte Sub, string Reason,
    bool AffectsGeometry, int PayloadBytes, uint? ClearActivityRole = null) : ServerEvent(Main, Sub)
{
    public override string Type => "navigation_geometry_change";
    public string GeometryScope => "house";
    public bool GeometryRebuilt => false;
    public bool DetailsParsed => false;
}
public sealed record GoldDeltaEvent(byte Sub, long Delta, bool Notify) : ServerEvent(26, Sub)
{
    public override string Type => "gold_delta";
}
public sealed record GoldSnapshotEvent(uint Amount) : ServerEvent(26, 4)
{
    public override string Type => "gold_snapshot";
}
public sealed record GoldLimitEvent() : ServerEvent(26, 3)
{
    public override string Type => "gold_limit";
}
public sealed record EventEndEvent() : ServerEvent(20, 8)
{
    public override string Type => "event_end";
}
public sealed record EventContinuePermissionEvent(byte Sub, int ExtensionBytes) : ServerEvent(20, Sub)
{
    public override string Type => "event_continue_permission";
}
public sealed record NpcEffect(byte Diagnosis, ushort Group, byte Number, byte EffectType, byte RoleClass,
    ushort Parameter, byte Style, uint Value, ushort MeanNumber, byte Condition, ushort EventNo, int ExtensionBytes);
public sealed record NpcEffectEvent(byte Sub, NpcEffect? NpcEffect, int PayloadBytes) : ServerEvent(20, Sub)
{
    public override string Type => "event_active";
}
public sealed record EventActiveEvent(byte Sub) : ServerEvent(20, Sub)
{
    public override string Type => "event_active";
}
public sealed record EventRejectedEvent(byte ReasonCode, string Reason) : ServerEvent(20, 74)
{
    public override string Type => "event_rejected";
}
public sealed record HeartbeatRequestEvent() : ServerEvent(1, 23)
{
    public override string Type => "heartbeat_request";
}
public sealed record InitialDataCompleteEvent() : ServerEvent(1, 11)
{
    public override string Type => "initial_data_complete";
}
public sealed record AccountIdentityEvent(uint AccountId) : ServerEvent(1, 4)
{
    public override string Type => "account_identity";
}
public sealed record LoginResultEvent(byte Result, byte LoginKind) : ServerEvent(63, 7)
{
    public override string Type => "login_result";
}
public sealed record MovementStopEvent(byte Kind) : ServerEvent(6, 2)
{
    public override string Type => "movement_stop";
}
public sealed record HouseFloorExtension(bool Verified, byte? Floor = null, byte? Size = null, byte? SizeFloor = null);
public sealed record PositionSnapshotEvent(byte Main, uint RoleId, ushort Scene, ushort X, ushort Y,
    int ExtensionBytes, HouseFloorExtension HouseFloor) : ServerEvent(Main, 1)
{
    public override string Type => "position_snapshot";
    public string Source => $"S{Main}-{Sub}";
    public bool SameStageHandler => Main == 7;
}
public sealed record BattleAttributeValue(byte Col, byte Row, byte Kind, uint Value);
public sealed record BattleAttributeInvalidEvent(int PayloadBytes, int CompleteRecords, int TrailingBytes) : ServerEvent(51, 1)
{
    public override string Type => "battle_attribute_invalid";
}
public sealed record BattleAttributeSetEvent(ImmutableArray<BattleAttributeValue> Values) : ServerEvent(51, 1)
{
    public override string Type => "battle_attribute_set";
}
public sealed record RoundStartEvent(ushort Round) : ServerEvent(52, 1)
{
    public override string Type => "round_start";
}
public sealed record BattleUnitExitEvent(byte Col, byte Row, byte? ExtensionByte) : ServerEvent(11, 1)
{
    public override string Type => "battle_unit_exit";
}
public sealed record AttributeAllocationSuccessEvent() : ServerEvent(8, 4)
{
    public override string Type => "attribute_allocation_success";
}
public sealed record AttributeSetEvent(byte Sub, string Entity, byte? HumanKind, ushort? Index,
    byte Kind, string Attribute, byte Sign, long Value, uint Parameter) : ServerEvent(8, Sub)
{
    public override string Type => "attribute_set";
}
public sealed record WalkEvent(int RoleId, ushort X, ushort Y) : ServerEvent(6, 1)
{
    public override string Type => "walk";
    public string Coordinates => "raw";
}
public sealed record WarStyleEvent(byte Value) : ServerEvent(11, 10)
{
    public override string Type => "war_style";
}
public sealed record WinnerEvent(byte Side) : ServerEvent(11, 12)
{
    public override string Type => "winner";
}
public sealed record FightExitEvent(uint RoleId, ushort Index) : ServerEvent(11, 0)
{
    public override string Type => "fight_exit";
}
public sealed record AttackAttribute(byte Kind, string Attribute, uint Value, byte Sign);
public sealed record AttackTarget(byte Col, byte Row, byte AttackResult, byte HitAction, ImmutableArray<AttackAttribute> Attributes);
public sealed record AttackAction(byte Col, byte Row, ushort SkillId, byte SkillLevel, byte FightArea,
    string SkillName, ImmutableArray<AttackTarget> Targets);
public sealed record AttackResultEvent(ImmutableArray<AttackAction> Actions) : ServerEvent(50, 1)
{
    public override string Type => "attack_result";
}
public sealed record MovementRequestEvent(ushort X, ushort Y) : ServerEvent(6, 1)
{
    public override string Type => "movement_request";
}
