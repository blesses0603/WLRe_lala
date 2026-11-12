using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Instances;

/// <summary>Pure receive-only port of services/instances.apply_instances and the six
/// receive observers it calls, in source order. Decode first: malformed packet payloads
/// cannot partly change a snapshot. Duplicate/late observations are intentionally not
/// deduplicated. Receipt success is not inventory settlement. Pending inputs are imported
/// evidence only; command construction, timers, disconnects, planners and sends are absent.
/// observedAt is a caller-supplied finite monotonic timestamp, consumed only by room lists.</summary>
public static partial class InstanceReceiveReducer
{
    public static InstanceReceiveSnapshot Apply(InstanceReceiveSnapshot state, ServerEvent observation,
        InstanceReceiveContext context, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state); ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        if (observation is ServerInstanceEvent instance) return Apply(state, instance.Event, context, observedAt);
        StateValue? entry = observation switch
        {
            PositionSnapshotEvent position => Map(("type", "position_snapshot"), ("role_id", position.RoleId), ("scene", position.Scene)),
            ServerLayoutEvent { Event: WorldPlayerEvent world } => Map(("type", "world_player"),
                ("player", Map(("role_id", world.Player.RoleId), ("scene", world.Player.Scene)))),
            ServerLayoutEvent { Event: BattleStartEvent } => Map(("type", "battle_start")),
            FightExitEvent exit => Map(("type", "fight_exit"), ("role_id", exit.RoleId)),
            WinnerEvent => Map(("type", "winner")),
            _ => null
        };
        if (entry is null) return state;
        var main = new Edit(state.Main); var coop = new Edit(state.Coop);
        ObserveEntry(main, coop, entry, context);
        return state with { Main = main.Value, Coop = coop.Value };
    }

    public static InstanceReceiveSnapshot Apply(InstanceReceiveSnapshot state, InstanceEvent observation,
        InstanceReceiveContext context, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state); ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        var e = Project(observation);
        if (e is null) return state;
        var main = new Edit(state.Main); var coop = new Edit(state.Coop);
        var isMain = observation.Mode == "main"; var data = isMain ? main : coop;
        var kind = Text(e, "type"); var room = Get(data.Value, "room");
        switch (kind)
        {
            case "instance_room_list":
                if (!double.IsFinite(observedAt)) throw new ArgumentOutOfRangeException(nameof(observedAt));
                data.Set("rooms", e["rooms"], "ready", true, "list_updated_at", observedAt,
                    "status", $"已同步房間清單（{Rows(e["rooms"]).Length} 間）");
                break;
            case "instance_result":
                var code = Number(e, "code"); var action = Text(e, "action");
                if (isMain)
                {
                    data.Set("status", $"{action}回覆：{(code == 0 ? "成功，等待房間同步" : $"拒絕代碼 {code}")}");
                    if (code == 0 && !Null(room))
                    {
                        if (action == "join") data.Set("status", "已加入一般副本房間（伺服器確認）");
                        if (action == "create") data.Set("status", "房間建立完成（伺服器已同步）");
                    }
                }
                else data.Set("status", code == 9 && !Null(room) ? "協力創房／扣點已確認" :
                    code == 10 && !Null(room) ? "已加入協力房間（伺服器確認）" : $"協力事件通知：代碼 {code}（待房間資料確認）");
                break;
            case "instance_phase":
                var phase = Number(e, "kind");
                if (phase == 2 || phase == 4)
                {
                    data.Set("room", null, "members", StateValue.List(), "phase", "idle", "battle_active", false,
                        "status", phase == 2 ? "已離開副本房間" : "已被移出副本房間");
                    if (isMain) data.Set("objectives", StateValue.Map(), "entered_scene", null);
                    else data.Set("fight_count", null, "fight_consumed_battle", null, "match_kind", null);
                }
                else if (phase == 1)
                {
                    if (isMain) ClearMainRound(data);
                    data.Set("room", Select(e, "room_id", "host_id").SetKey("members", e["count"]),
                        "members", StateValue.List(), "phase", "waiting", "status", "已收到入房狀態，等待成員同步");
                }
                else if (phase == 3) data.Set("phase", "started", "status", "伺服器通知副本開始");
                else if (phase == 5) data.Set("status", "伺服器確認移出成員");
                break;
            case "instance_members":
                if (!isMain)
                {
                    var oldId = Get(room, "room_id");
                    if (!Equal(oldId, e["room_id"]))
                    {
                        if (!Null(oldId) || Null(data["reward"])) ClearCoopRound(data);
                        if (!Null(oldId) && !RewardUnresolved(data)) data.Set("reward", null,
                            "reward_handled_fingerprint", null, "claim_result", null, "cancel_result", null);
                    }
                    data.Set("room", Select(e, "room_id", "kind", "npc_id", "capacity", "host_id", "standby"));
                    if (!In(Text(data.Value, "phase"), "matched", "combat") || !Equal(oldId, e["room_id"])) data.Set("phase", "waiting");
                    data.Set("standby", e["standby"]);
                    if (Text(data.Value, "phase") == "waiting") data.Set("status", "協力房間與成員已同步");
                }
                else if (Null(room) || !Equal(Get(room, "room_id"), e["room_id"])) return state;
                data.Set("members", e["members"]);
                break;
            case "instance_member_joined":
                if (Null(room) || !Equal(room["room_id"], e["room_id"])) return state;
                data.Set("members", StateValue.List(Rows(data["members"]).Where(m => !Equal(m["role_id"], e["role_id"]))
                        .Append(Select(e, "role_id"))), "room", room.SetKey("members", e["count"]), "status", "已有新成員加入");
                break;
            case "instance_member_left":
                if (Null(room)) return state;
                data.Set("room", room.SetKey("members", e["count"]).SetKey("host_id", e["host_id"]),
                    "members", StateValue.List(Rows(data["members"]).Where(m => !Equal(m["role_id"], e["role_id"]))));
                if (Equal(e["role_id"], Value(context.OwnRoleId))) data.Set("room", null, "members", StateValue.List(), "phase", "idle");
                data.Set("status", "伺服器確認成員離開");
                break;
            case "instance_time": data.Set("remaining_minutes", e["minutes"]); break;
            case "instance_objective": ApplyObjective(data, e); break;
            case "instance_completed": data.Set("completed", true, "completion_source", "S85-15", "phase", "completed",
                "status", "伺服器已確認一般副本完成；不需額外送出通關指令"); break;
            case "instance_min_players": data.Set("status", "伺服器通知已達最低進入人數"); break;
            case "instance_new_info": ApplyNewInfo(data, e); break;
            case "instance_reward_status": data.Set("reward", Select(e, "reward_count", "win_stage", "open_reward", "reward_mark", "npc_id"),
                "status", "協力獎勵狀態已同步（尚未領取）"); break;
            case "instance_fight_count": data.Set("fight_count", e["count"], "fight_consumed_battle", null, "last_fight_victory", null); break;
            case "instance_standby": data.Set("standby", e["standby"]); break;
        }
        ResolveCreate(data, e, context, isMain);
        ResolveRoom(data, e, context, isMain);
        if (!isMain) ResolveStandby(data, e);
        if (isMain) ResolveStart(data, e);
        ObserveEntry(main, coop, e, context);
        ResolveRewards(coop, e);
        return state with { Main = main.Value, Coop = coop.Value };
    }

    private static void ClearMainRound(Edit data) => data.Set("objectives", Map(("targets", StateValue.Map()),
        ("boss", null), ("scores", StateValue.Map())), "completed", false, "completion_source", null, "entered_scene", null, "battle_active", false);
    private static bool RewardUnresolved(Edit data) => Truth(data["claim_pending"]) || Truth(data["cancel_pending"]) || Truth(data["reward_uncertain"]);
    private static void ClearCoopRound(Edit data)
    {
        data.Set("fight_count", null, "fight_consumed_battle", null, "last_fight_victory", null,
            "match_kind", null, "battle_active", false, "completed", false, "completion_source", null);
        if (!RewardUnresolved(data)) data.Set("received_awards", StateValue.List(), "mail_notice", false);
    }

    private static void ApplyObjective(Edit data, StateValue e)
    {
        var objectives = new Edit(OrMap(data["objectives"]));
        var targets = new Edit(OrMap(objectives["targets"]));
        var category = Number(e, "kind"); var index = Key(Get(e, "index"));
        var row = new Edit(OrMap(targets[index])); var boss = new Edit(OrMap(objectives["boss"]));
        if (category == 1)
        {
            row.Set("kills", BigInteger.Min(Number(e, "kills"), Number(row.Value, "required", Number(e, "kills"))), "last_killer", e["killer"]);
            targets.Set(index, row.Value);
        }
        else if (category == 2 && Truth(e["defeated"]))
        {
            boss.Set("defeated", true, "last_killer", e["killer"]); objectives.Set("boss", boss.Value);
        }
        else if (category == 3)
        {
            row.Set("npc_id", e["npc_id"], "required", e["required"], "kills", BigInteger.Min(Number(row.Value, "kills"), Number(e, "required")));
            targets.Set(index, row.Value);
        }
        else if (category == 4)
        {
            boss.Set("npc_id", e["npc_id"]); if (!boss.Value.MapValue.ContainsKey("defeated")) boss.Set("defeated", false);
            objectives.Set("boss", boss.Value);
        }
        else if (category == 5 || category == 6)
        {
            var scores = new Edit(OrMap(objectives["scores"])); var key = category == 5 ? "normal" : "boss";
            foreach (var role in Rows(e["role_ids"]))
            {
                var entry = new Edit(Null(scores[Key(role)]) ? Map(("normal", 0), ("boss", 0)) : scores[Key(role)]);
                entry.Set(key, Number(entry.Value, key) + 1); scores.Set(Key(role), entry.Value);
            }
            objectives.Set("scores", scores.Value);
        }
        objectives.Set("targets", targets.Value);
        data.Set("objectives", objectives.Value, "status", "副本目標與成員積分已依 S85-10 同步");
    }

    private static void ApplyNewInfo(Edit data, StateValue e)
    {
        var kind = Number(e, "kind");
        if (kind == 0)
        {
            if (!Equal(Get(data["room"], "scene"), e["scene"])) ClearMainRound(data);
            data.Set("room", Select(e, "scene", "host_id", "dungeon_kind", "organization_only"),
                "phase", "new_instance", "remaining_minutes", e["remaining"], "status", "新式副本基本資料已同步");
        }
        else if (kind == 1) data.Set("remaining_minutes", e["remaining"]);
        else if (kind == 2) data.Set("member_count", e["count"]);
        else if (kind == 3 || kind == 4)
        {
            var objectives = new Edit(OrMap(data["objectives"])); var targets = new Edit(OrMap(objectives["targets"]));
            var index = Key(e["index"]); var previous = targets[index];
            if (kind == 3 || !Null(previous))
            {
                var row = new Edit(OrMap(previous));
                if (kind == 3) row.Set("npc_id", e["npc_id"], "required", e["required"], "kills", BigInteger.Min(Number(e, "kills"), Number(e, "required")));
                else row.Set("kills", BigInteger.Min(Number(row.Value, "required"), Number(row.Value, "kills") + 1), "last_killer", e["killer"]);
                targets.Set(index, row.Value);
            }
            objectives.Set("targets", targets.Value); data.Set("objectives", objectives.Value);
        }
        else if (kind == 5) data.Set("last_target_npc_id", e["npc_id"]);
        else if (kind == 98) data.Set("challenge_notice", Select(e, "text_id", "player_name", "npc_id"));
        else if (kind == 6) data.Set("room", null, "members", StateValue.List(), "objectives", StateValue.Map(), "phase", "idle");
        else if (kind == 100) data.Set("objectives", OrMap(data["objectives"]).SetKey("records", e["records"]),
            "completed", true, "completion_source", "S85-21-100", "phase", "completed", "status", "伺服器通知新式副本已完成；不自動推測獎勵");
        else if (kind == 99 || kind == 101 || kind == 102) data.Set("status", $"新式副本狀態通知：{kind}");
    }

    private sealed class Edit(StateValue value)
    {
        public StateValue Value { get; private set; } = value.Kind == StateValueKind.Map ? value : throw new ArgumentException("Expected source-shaped map.");
        public StateValue this[string key] => Get(Value, key);
        public void Set(params object?[] entries)
        {
            for (var i = 0; i < entries.Length; i += 2) Value = Value.SetKey((string)entries[i]!, InstanceReceiveReducer.Value(entries[i + 1]));
        }
    }
    private static StateValue Value(object? value) => value is StateValue state ? state : StateValue.Scalar(value);
    private static StateValue Map(params (string Key, object? Value)[] entries) => StateValue.Map(entries.Select(e => KeyValuePair.Create(e.Key, Value(e.Value))));
    private static StateValue Select(StateValue map, params string[] keys) => StateValue.Map(keys.Select(k => KeyValuePair.Create(k, Get(map, k))));
    private static StateValue Get(StateValue value, string key) => value.Kind == StateValueKind.Map ? value.MapValue.GetValueOrDefault(key, StateValue.Null) : StateValue.Null;
    private static StateValue OrMap(StateValue value) => Null(value) ? StateValue.Map() : value;
    private static bool Null(StateValue value) => value.Kind == StateValueKind.Scalar && value.ScalarValue is null;
    private static ImmutableArray<StateValue> Rows(StateValue value) => value.Kind is StateValueKind.List or StateValueKind.Tuple ? value.SequenceValue : [];
    private static bool Truth(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => value.MapValue.Count > 0,
        StateValueKind.List or StateValueKind.Tuple => value.SequenceValue.Length > 0,
        _ => value.ScalarValue switch { null => false, bool b => b, string s => s.Length != 0, _ => Integer(value) != 0 }
    };
    private static bool IsInteger(StateValue value) => value.Kind == StateValueKind.Scalar && value.ScalarValue is sbyte or byte or short or ushort or int or uint or long or ulong or BigInteger;
    private static BigInteger Integer(StateValue value) => value.ScalarValue is BigInteger big ? big : BigInteger.Parse(Convert.ToString(value.ScalarValue, CultureInfo.InvariantCulture)!, CultureInfo.InvariantCulture);
    private static BigInteger Number(StateValue map, string key, BigInteger fallback = default) => IsInteger(Get(map, key)) ? Integer(Get(map, key)) : fallback;
    private static string Text(StateValue map, string key) => Get(map, key).Kind == StateValueKind.Scalar ? Get(map, key).ScalarValue as string ?? "" : "";
    private static string Key(StateValue value) => Null(value) ? "" : Convert.ToString(value.ScalarValue, CultureInfo.InvariantCulture)!;
    private static bool Equal(StateValue left, StateValue right) => IsInteger(left) && IsInteger(right) ? Integer(left) == Integer(right) :
        left.Kind == StateValueKind.Scalar && right.Kind == StateValueKind.Scalar && Equals(left.ScalarValue, right.ScalarValue);
    private static bool In(string value, params string[] choices) => choices.Contains(value, StringComparer.Ordinal);
}
