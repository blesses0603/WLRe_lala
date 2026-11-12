using Lala.Core.State;

namespace Lala.Core.Instances;

public static partial class InstanceReceiveReducer
{
    private static readonly IReadOnlyDictionary<int, string> MainCreateErrors = new Dictionary<int, string>
    {
        [1] = "房間額滿", [2] = "等級不足", [3] = "已完成挑戰", [4] = "冷卻中", [7] = "副本時間已到",
        [8] = "目前場景不可傳送", [9] = "目前狀態不可傳送", [11] = "副本尚未開放", [13] = "訊息不合規",
        [14] = "已參加協力戰", [15] = "乘坐大型交通工具", [16] = "目前為組織活動場景", [17] = "活動場景禁止操作"
    };
    private static readonly IReadOnlyDictionary<int, string> CoopCreateErrors = new Dictionary<int, string>
    {
        [1] = "房間額滿", [2] = "人數額滿", [3] = "房間不存在", [4] = "已有房間", [5] = "今日活動已完成",
        [6] = "門票不足", [7] = "建立房間扣點失敗", [8] = "扣點失敗", [11] = "目前正在副本",
        [12] = "指定出戰夥伴不符合", [13] = "指定夥伴狀態不符", [14] = "私人房間密碼錯誤"
    };
    private static readonly IReadOnlyDictionary<int, string> MainJoinErrors = new Dictionary<int, string>
    {
        [1] = "房間已滿", [2] = "等級不足", [3] = "副本已開始", [4] = "房間不存在", [5] = "副本已完成", [6] = "無法進入",
        [7] = "所屬組織不符", [8] = "私人房間密碼錯誤", [14] = "已參加協力戰", [15] = "乘坐大型交通工具",
        [16] = "所在場景不可進入", [17] = "活動場景不可進入", [255] = "伺服器拒絕加入"
    };
    private static readonly IReadOnlyDictionary<int, string> CoopJoinErrors = new Dictionary<int, string>
    {
        [2] = "房間人數已滿", [3] = "房間不存在", [4] = "已有其他房間", [5] = "活動已完成", [6] = "門票不足",
        [8] = "加入時扣點失敗", [11] = "目前位於其他副本", [12] = "指定夥伴不符合要求", [13] = "指定夥伴狀態不可變更", [14] = "私人房間密碼錯誤"
    };

    private static void ResolveCreate(Edit data, StateValue e, InstanceReceiveContext context, bool isMain)
    {
        var pending = data["create_pending"]; var attempt = Truth(pending) ? pending : data["create_attempt"];
        if (!Truth(attempt)) return;
        var kind = Text(e, "type"); var code = (int)Number(e, "code");
        if (isMain)
        {
            if (!Truth(pending)) return;
            if (kind == "instance_result" && Text(e, "action") == "create")
            {
                data.Set("create_result", code);
                if (code != 0) data.Set("create_pending", null, "status", "伺服器拒絕創房：" + MainCreateErrors.GetValueOrDefault(code, $"代碼 {code}"));
                else data.Set("create_pending", pending.SetKey("ack", Value(true)), "status", "伺服器已接受建立要求，等待房間資訊");
            }
            else if (kind == "instance_phase" && Number(e, "kind") == 1 && Equal(Get(e, "room_id"), pending["map_id"]) &&
                Equal(Get(e, "host_id"), Value(context.OwnRoleId)))
                data.Set("create_pending", null, "create_result", 0, "status", "建立副本房間成功（已確認房主與房間 ID）");
        }
        else if (kind == "instance_result" && Truth(pending))
        {
            if (CoopCreateErrors.TryGetValue(code, out var error)) data.Set("create_result", code, "create_pending", null,
                "create_attempt", null, "status", "伺服器拒絕協力創房：" + error);
            else if (code == 9) data.Set("create_pending", pending.SetKey("ack", Value(true)), "create_result", 9, "status", "協力創房／扣點回覆成功，等待房間同步");
        }
        else if (kind == "instance_members")
        {
            var members = Rows(e["members"]); var hostId = Get(e, "host_id");
            if (Null(hostId) && members.Length > 0) hostId = Get(members[0], "role_id");
            if (IsInteger(Get(e, "room_id")) && Number(e, "room_id") > 0 && Equal(Get(e, "kind"), attempt["kind"]) &&
                Equal(Get(e, "npc_id"), attempt["npc_id"]) && Equal(hostId, Value(context.OwnRoleId)) &&
                members.Length > 0 && Equal(Get(members[0], "role_id"), hostId))
                data.Set("create_pending", null, "create_uncertain", false, "create_attempt", null, "create_result", 9,
                    "status", "協力創房成功，已由伺服器房主與活動資訊確認");
        }
    }

    private static void ResolveRoom(Edit data, StateValue e, InstanceReceiveContext context, bool isMain)
    {
        var kind = Text(e, "type"); var pending = data["join_pending"]; var code = (int)Number(e, "code");
        if (Truth(pending))
        {
            if (isMain)
            {
                if (kind == "instance_result" && Text(e, "action") == "join")
                {
                    if (code == 0) data.Set("join_pending", pending.SetKey("accepted", Value(true)), "status", "伺服器接受加入要求，等待房間狀態");
                    else data.Set("join_pending", null, "join_result", code, "status", "伺服器拒絕加入：" + MainJoinErrors.GetValueOrDefault(code, $"拒絕代碼 {code}"));
                }
                else if (kind == "instance_phase" && Number(e, "kind") == 1 && Equal(Get(e, "room_id"), pending["room_id"]))
                    data.Set("join_pending", null, "join_result", 0, "status", "已加入一般副本房間（伺服器確認）");
            }
            else if (kind == "instance_result")
            {
                if (code == 10) data.Set("join_pending", pending.SetKey("accepted", Value(true)), "status", "伺服器確認協力加入／扣點，等待成員名單");
                else if (CoopJoinErrors.TryGetValue(code, out var error)) data.Set("join_pending", null, "join_result", code, "status", "伺服器拒絕協力加入：" + error);
            }
            else if (kind == "instance_members" && Equal(Get(e, "room_id"), pending["room_id"]) && Equal(Get(e, "joined"), Value(true)) &&
                Rows(e["members"]).Any(m => Equal(Get(m, "role_id"), Value(context.OwnRoleId))))
                data.Set("join_pending", null, "join_result", 10, "status", "已加入協力房間（伺服器成員名單確認）");
        }
        if (Null(data["leave_pending"])) return;
        var confirmed = isMain ? (kind == "instance_phase" && (Number(e, "kind") == 2 || Number(e, "kind") == 4)) ||
            (kind == "instance_member_left" && Equal(Get(e, "role_id"), Value(context.OwnRoleId))) : kind == "instance_phase" && Number(e, "kind") == 2;
        if (confirmed) data.Set("leave_pending", null, "leave_result", "success", "status", "已離開副本房間（伺服器確認）");
    }

    private static void ResolveStandby(Edit data, StateValue e)
    {
        var pending = data["standby_pending"];
        var expected = Truth(pending) ? pending : Truth(data["standby_uncertain"]) ? data["standby_attempt"] : StateValue.Null;
        if (Null(expected)) return;
        if (Text(e, "type") == "instance_members")
        {
            if (Equal(Get(e, "room_id"), expected["room_id"]) && Equal(Get(e, "standby"), expected["target"]) &&
                Equal(Get(data["room"], "room_id"), expected["room_id"]))
                data.Set("standby_pending", null, "standby_uncertain", false, "standby_attempt", null,
                    "standby_result", expected["target"], "status", Truth(expected["target"]) ? "協力準備已由伺服器確認" : "協力取消準備已由伺服器確認");
        }
        else if (Text(e, "type") == "instance_phase" && Number(e, "kind") == 2)
            data.Set("standby_pending", null, "standby_attempt", null, "standby_uncertain", true, "status", "房間已退出，準備要求結果不明；本連線禁止重試");
    }

    private static void ResolveStart(Edit data, StateValue e)
    {
        var pending = data["start_pending"];
        if (Null(pending) || Text(e, "type") != "instance_phase") return;
        var kind = Number(e, "kind");
        if (kind == 3)
        {
            if (Truth(data["room"]) && Equal(Get(data["room"], "room_id"), pending["room_id"]))
                data.Set("start_pending", null, "start_result", "confirmed", "status", "伺服器已確認開始副本，等待後續入場狀態");
        }
        else if (kind == 2 || kind == 4) data.Set("start_pending", null, "start_uncertain", true, "status", "副本房間已結束／被移出，開始結果不明；禁止重送");
    }

    private static void ObserveEntry(Edit main, Edit coop, StateValue e, InstanceReceiveContext context)
    {
        var kind = Text(e, "type"); var mode = Text(e, "mode"); var subkind = Number(e, "kind");
        if (kind == "instance_phase" && mode == "main" && (subkind == 2 || subkind == 4))
        {
            if (!Null(main["enter_pending"])) main.Set("enter_pending", null, "enter_uncertain", true, "status", "入場期間房間結束，結果不明，禁止重送");
            main.Set("entered_scene", null, "battle_active", false); return;
        }
        if (kind == "instance_phase" && mode == "coop" && subkind == 2)
        {
            coop.Set("battle_active", false, "match_kind", null); return;
        }
        var scene = StateValue.Null;
        if (kind == "position_snapshot" && Equal(Get(e, "role_id"), Value(context.OwnRoleId))) scene = Get(e, "scene");
        else if (kind == "world_player" && Equal(Get(Get(e, "player"), "role_id"), Value(context.OwnRoleId))) scene = Get(e["player"], "scene");
        var roomId = Get(main["room"], "room_id");
        if (!Null(scene) && In(Text(main.Value, "phase"), "started", "entered", "combat") && IsInteger(roomId) && Equal(scene, roomId) &&
            Integer(roomId) >= ushort.MinValue && Integer(roomId) <= ushort.MaxValue && context.DeclaredMainCatalogMapIds.Contains((ushort)Integer(roomId)))
        {
            main.Set("enter_pending", null, "enter_uncertain", false, "enter_result", "confirmed", "entered_scene", scene);
            if (Text(main.Value, "phase") != "combat") main.Set("phase", "entered", "status", "伺服器已確認本角色進入副本場景，等待戰鬥");
            return;
        }
        if (kind == "instance_coop_match")
        {
            if (!Null(coop["room"]) && Null(main["room"]) &&
                (Equal(coop["standby"], Value(true)) || Equal(Get(coop["standby_pending"], "target"), Value(true))))
                coop.Set("phase", "matched", "match_kind", e["kind"], "status", "協力配對成功通知已收到，等待正式戰鬥開始");
        }
        else if (kind == "battle_start")
        {
            if (In(Text(main.Value, "phase"), "entered", "combat") && Equal(main["entered_scene"], roomId))
                main.Set("phase", "combat", "battle_active", true, "status", "收到正式戰鬥開始封包，沿用既有戰鬥系統");
            if (In(Text(coop.Value, "phase"), "matched", "combat") && !Null(coop["room"]))
                coop.Set("phase", "combat", "battle_active", true, "status", "協力配對後收到正式戰鬥開始封包");
        }
        else if (kind == "fight_exit" || kind == "winner")
        {
            if (kind == "fight_exit" && !Equal(Get(e, "role_id"), Value(context.OwnRoleId))) return;
            if (Truth(main["battle_active"]))
            {
                main.Set("battle_active", false);
                if (Text(main.Value, "phase") == "combat") main.Set("phase", "entered", "status", "戰鬥已結束；正式通關仍待 S85-15");
            }
            if (Truth(coop["battle_active"]))
            {
                coop.Set("battle_active", false);
                if (Text(coop.Value, "phase") == "combat") coop.Set("phase", "matched", "status", "協力戰鬥已結束；後續場次與獎勵待伺服器確認");
            }
        }
    }

    private static void ResolveRewards(Edit data, StateValue e)
    {
        var kind = Text(e, "type");
        if (Text(e, "mode") != "coop") return;
        if (kind == "instance_reward_receipt")
        {
            if (!Null(data["claim_pending"]) && Truth(e["awards"])) data.Set("claim_pending", null, "claim_result", "confirmed", "received_awards", e["awards"],
                "status", "S186-10 獎勵內容已由伺服器確認（不代表所有包包格位已更新）");
            else if (!Null(data["claim_pending"])) data.Set("status", "S186-10 未帶獎品，等待 S186-11 狀態回覆確認");
        }
        else if (kind == "instance_reward_status")
        {
            var reward = data["reward"]; var open = Number(reward, "open_reward");
            if (Number(reward, "reward_count") > 0 && Number(reward, "win_stage") >= Number(reward, "reward_count"))
                data.Set("completed", true, "completion_source", "S186-11");
            if (open == 0)
            {
                if (!Null(data["claim_pending"])) data.Set("claim_pending", null, "claim_result", Truth(data["received_awards"]) ? "confirmed" : "server_closed_unverified_awards",
                    "status", "S186-11 寶箱已結束；尚無獎品明細請檢查包包／信箱");
                else if (!Null(data["cancel_pending"])) data.Set("cancel_pending", null, "cancel_result", "confirmed", "status", "伺服器已確認取消協力寶箱");
                data.Set("reward_handled_fingerprint", null);
            }
            else if (!Null(data["claim_pending"]) || !Null(data["cancel_pending"])) data.Set("status", "等待協力獎勵回覆；不可重送");
            else if (open == 2) data.Set("status", "伺服器有付費協力寶箱，禁止自動領取或扣點");
            else if (open == 1) data.Set("status", "伺服器有免費協力寶箱；可手動或明確啟用自動領取");
        }
        else if (kind == "instance_result" && Number(e, "code") == 15)
        {
            data.Set("mail_notice", true);
            if (Truth(data["claim_pending"])) data.Set("status", "伺服器通知獎勵已寄送信箱；仍待領獎結果同步");
        }
        else if (kind == "instance_phase" && Number(e, "kind") == 2 && (Truth(data["claim_pending"]) || Truth(data["cancel_pending"])))
            data.Set("reward_uncertain", true, "claim_pending", null, "cancel_pending", null, "status", "退出房間時獎勵操作結果不明；禁止重發");
    }
}
