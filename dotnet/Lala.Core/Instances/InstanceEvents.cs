using System.Collections.Immutable;

namespace Lala.Core.Instances;

public sealed record MainInstanceRoom(ushort RoomId, string Manager, byte Members,
    string Organization, bool Public, ushort Sn);
public sealed record CoopInstanceRoom(bool Public, byte Kind, byte NpcId, ushort RoomId,
    byte Capacity, byte Members, uint HostId);
public sealed record MainInstanceMember(uint RoleId);
public sealed record CoopInstanceMember(uint RoleId, byte Status, uint Hp, uint MaxHp,
    uint Sp, uint MaxSp);
public sealed record InstanceSettlementRecord(uint RoleId, byte Boss, byte Normal);
public sealed record InstanceAward(byte Kind, uint Id, uint Value);

/// <summary>Immutable offline observations, not instructions or authorization for game actions.</summary>
public abstract record InstanceEvent
{
    public abstract string Type { get; }
    public abstract string Mode { get; }
}
public abstract record MainInstanceEvent : InstanceEvent
{
    public sealed override string Mode => "main";
}
public abstract record CoopInstanceEvent : InstanceEvent
{
    public sealed override string Mode => "coop";
}
public sealed record MainRoomListEvent(ImmutableArray<MainInstanceRoom> Rooms) : MainInstanceEvent
{
    public override string Type => "instance_room_list";
}
public sealed record CoopRoomListEvent(ImmutableArray<CoopInstanceRoom> Rooms) : CoopInstanceEvent
{
    public override string Type => "instance_room_list";
}
public sealed record MainResultEvent(string Action, byte Code) : MainInstanceEvent
{
    public override string Type => "instance_result";
}
public sealed record CoopResultEvent(byte Code, uint? RoleId) : CoopInstanceEvent
{
    public override string Type => "instance_result";
}
public sealed record MainMembersEvent(ushort RoomId, ImmutableArray<MainInstanceMember> Members) : MainInstanceEvent
{
    public override string Type => "instance_members";
}
public sealed record CoopMembersEvent(ushort RoomId, uint? HostId, bool Created, bool Joined,
    bool Standby, byte Kind, byte NpcId, byte Capacity, ImmutableArray<CoopInstanceMember> Members) : CoopInstanceEvent
{
    public override string Type => "instance_members";
}
public abstract record MainPhaseEvent(byte Kind) : MainInstanceEvent
{
    public sealed override string Type => "instance_phase";
}
public sealed record MainRoomPhaseEvent(byte Phase, ushort RoomId, byte Count, uint HostId) : MainPhaseEvent(1);
public sealed record MainPhaseSignalEvent(byte Kind) : MainPhaseEvent(Kind);
public sealed record MainKickedEvent(uint KickedRoleId) : MainPhaseEvent(5);
public sealed record CoopPhaseEvent() : CoopInstanceEvent
{
    public override string Type => "instance_phase";
    public byte Kind => 2;
}
public sealed record MainMemberJoinedEvent(byte Count, uint RoleId, ushort RoomId) : MainInstanceEvent
{
    public override string Type => "instance_member_joined";
}
public sealed record MainTimeEvent(uint Minutes) : MainInstanceEvent
{
    public override string Type => "instance_time";
}
public abstract record MainObjectiveEvent(byte Kind) : MainInstanceEvent
{
    public sealed override string Type => "instance_objective";
}
public sealed record MainObjectiveKillsEvent(byte Index, byte Kills, string Killer) : MainObjectiveEvent(1);
public sealed record MainObjectiveDefeatedEvent(bool Defeated, string Killer) : MainObjectiveEvent(2);
public sealed record MainObjectiveRequirementEvent(byte Index, byte Required, ushort NpcId) : MainObjectiveEvent(3);
public sealed record MainObjectiveNpcEvent(ushort NpcId) : MainObjectiveEvent(4);
public sealed record MainObjectiveRolesEvent(byte Kind, ImmutableArray<uint> RoleIds) : MainObjectiveEvent(Kind);
public sealed record MainMemberLeftEvent(byte Count, uint RoleId, uint HostId, bool Kicked) : MainInstanceEvent
{
    public override string Type => "instance_member_left";
}
public sealed record MainCompletedEvent() : MainInstanceEvent
{
    public override string Type => "instance_completed";
}
public sealed record MainMinPlayersEvent() : MainInstanceEvent
{
    public override string Type => "instance_min_players";
}
public abstract record MainNewInfoEvent(byte Kind) : MainInstanceEvent
{
    public sealed override string Type => "instance_new_info";
}
public sealed record MainNewInfoSnapshotEvent(byte DungeonKind, byte Phase, ushort Scene,
    uint HostId, bool OrganizationOnly, uint Remaining) : MainNewInfoEvent(0);
public sealed record MainNewInfoPhaseEvent(byte Phase, uint Remaining) : MainNewInfoEvent(1);
public sealed record MainNewInfoCountEvent(uint Count) : MainNewInfoEvent(2);
public sealed record MainNewInfoObjectiveEvent(byte Index, ushort NpcId, byte Required, byte Kills) : MainNewInfoEvent(3);
public sealed record MainNewInfoKillerEvent(byte Index, byte MemberCount, string Killer) : MainNewInfoEvent(4);
public sealed record MainNewInfoNpcEvent(ushort NpcId) : MainNewInfoEvent(5);
public sealed record MainNewInfoTextEvent(ushort TextId, string PlayerName, ushort NpcId) : MainNewInfoEvent(98);
public sealed record MainNewInfoRecordsEvent(ImmutableArray<InstanceSettlementRecord> Records) : MainNewInfoEvent(100);
public sealed record MainNewInfoSignalEvent(byte Kind) : MainNewInfoEvent(Kind);
public sealed record CoopMatchEvent(byte Kind, byte OpponentCount, ImmutableArray<uint> RosterRoleIds) : CoopInstanceEvent
{
    public override string Type => "instance_coop_match";
}
public sealed record CoopMemberRefreshRequestEvent(ushort RoomId) : CoopInstanceEvent
{
    public override string Type => "instance_member_refresh_request";
}
public sealed record CoopRewardReceiptEvent(ImmutableArray<InstanceAward> Awards) : CoopInstanceEvent
{
    public override string Type => "instance_reward_receipt";
}
public sealed record CoopRewardStatusEvent(byte RewardCount, byte WinStage, byte OpenReward,
    byte RewardMark, byte NpcId) : CoopInstanceEvent
{
    public override string Type => "instance_reward_status";
}
public sealed record CoopFightCountEvent(byte Count) : CoopInstanceEvent
{
    public override string Type => "instance_fight_count";
}
public sealed record CoopStandbyEvent(bool Standby) : CoopInstanceEvent
{
    public override string Type => "instance_standby";
}
