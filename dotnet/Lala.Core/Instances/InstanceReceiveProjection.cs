using Lala.Core.State;

namespace Lala.Core.Instances;

public static partial class InstanceReceiveReducer
{
    // Explicit closed typed-event adapter. No JSON/reflection path and no arbitrary event dictionary entry point.
    private static StateValue? Project(InstanceEvent e)
    {
        StateValue? body = e switch
        {
            MainRoomListEvent v => Map(("rooms", StateValue.List(v.Rooms.Select(r => Map(("room_id", r.RoomId), ("manager", r.Manager),
                ("members", r.Members), ("organization", r.Organization), ("public", r.Public), ("sn", r.Sn)))))),
            CoopRoomListEvent v => Map(("rooms", StateValue.List(v.Rooms.Select(r => Map(("public", r.Public), ("kind", r.Kind),
                ("npc_id", r.NpcId), ("room_id", r.RoomId), ("capacity", r.Capacity), ("members", r.Members), ("host_id", r.HostId)))))),
            MainResultEvent v => Map(("action", v.Action), ("code", v.Code)),
            CoopResultEvent v => Map(("code", v.Code), ("role_id", v.RoleId)),
            MainMembersEvent v => Map(("room_id", v.RoomId), ("members", StateValue.List(v.Members.Select(m => Map(("role_id", m.RoleId)))))),
            CoopMembersEvent v => Map(("room_id", v.RoomId), ("host_id", v.HostId), ("created", v.Created), ("joined", v.Joined),
                ("standby", v.Standby), ("kind", v.Kind), ("npc_id", v.NpcId), ("capacity", v.Capacity),
                ("members", StateValue.List(v.Members.Select(m => Map(("role_id", m.RoleId), ("status", m.Status), ("hp", m.Hp),
                    ("max_hp", m.MaxHp), ("sp", m.Sp), ("max_sp", m.MaxSp)))))),
            MainRoomPhaseEvent v => Map(("kind", v.Kind), ("phase", v.Phase), ("room_id", v.RoomId), ("count", v.Count), ("host_id", v.HostId)),
            MainKickedEvent v => Map(("kind", v.Kind), ("kicked_role_id", v.KickedRoleId)),
            MainPhaseSignalEvent v => Map(("kind", v.Kind)),
            CoopPhaseEvent v => Map(("kind", v.Kind)),
            MainMemberJoinedEvent v => Map(("count", v.Count), ("role_id", v.RoleId), ("room_id", v.RoomId)),
            MainTimeEvent v => Map(("minutes", v.Minutes)),
            MainObjectiveKillsEvent v => Map(("kind", v.Kind), ("index", v.Index), ("kills", v.Kills), ("killer", v.Killer)),
            MainObjectiveDefeatedEvent v => Map(("kind", v.Kind), ("defeated", v.Defeated), ("killer", v.Killer)),
            MainObjectiveRequirementEvent v => Map(("kind", v.Kind), ("index", v.Index), ("required", v.Required), ("npc_id", v.NpcId)),
            MainObjectiveNpcEvent v => Map(("kind", v.Kind), ("npc_id", v.NpcId)),
            MainObjectiveRolesEvent v => Map(("kind", v.Kind), ("role_ids", StateValue.List(v.RoleIds.Select(r => Value(r))))),
            MainMemberLeftEvent v => Map(("count", v.Count), ("role_id", v.RoleId), ("host_id", v.HostId), ("kicked", v.Kicked)),
            MainCompletedEvent or MainMinPlayersEvent => Map(),
            MainNewInfoSnapshotEvent v => Map(("kind", v.Kind), ("dungeon_kind", v.DungeonKind), ("phase", v.Phase), ("scene", v.Scene),
                ("host_id", v.HostId), ("organization_only", v.OrganizationOnly), ("remaining", v.Remaining)),
            MainNewInfoPhaseEvent v => Map(("kind", v.Kind), ("phase", v.Phase), ("remaining", v.Remaining)),
            MainNewInfoCountEvent v => Map(("kind", v.Kind), ("count", v.Count)),
            MainNewInfoObjectiveEvent v => Map(("kind", v.Kind), ("index", v.Index), ("npc_id", v.NpcId), ("required", v.Required), ("kills", v.Kills)),
            MainNewInfoKillerEvent v => Map(("kind", v.Kind), ("index", v.Index), ("member_count", v.MemberCount), ("killer", v.Killer)),
            MainNewInfoNpcEvent v => Map(("kind", v.Kind), ("npc_id", v.NpcId)),
            MainNewInfoTextEvent v => Map(("kind", v.Kind), ("text_id", v.TextId), ("player_name", v.PlayerName), ("npc_id", v.NpcId)),
            MainNewInfoRecordsEvent v => Map(("kind", v.Kind), ("records", StateValue.List(v.Records.Select(r => Map(("role_id", r.RoleId), ("boss", r.Boss), ("normal", r.Normal)))))),
            MainNewInfoSignalEvent v => Map(("kind", v.Kind)),
            CoopMatchEvent v => Map(("kind", v.Kind), ("opponent_count", v.OpponentCount), ("roster_role_ids", StateValue.List(v.RosterRoleIds.Select(r => Value(r))))),
            CoopMemberRefreshRequestEvent v => Map(("room_id", v.RoomId)),
            CoopRewardReceiptEvent v => Map(("awards", StateValue.List(v.Awards.Select(a => Map(("kind", a.Kind), ("id", a.Id), ("value", a.Value)))))),
            CoopRewardStatusEvent v => Map(("reward_count", v.RewardCount), ("win_stage", v.WinStage), ("open_reward", v.OpenReward), ("reward_mark", v.RewardMark), ("npc_id", v.NpcId)),
            CoopFightCountEvent v => Map(("count", v.Count)),
            CoopStandbyEvent v => Map(("standby", v.Standby)),
            _ => null
        };
        return body?.SetKey("type", Value(e.Type)).SetKey("mode", Value(e.Mode));
    }
}
