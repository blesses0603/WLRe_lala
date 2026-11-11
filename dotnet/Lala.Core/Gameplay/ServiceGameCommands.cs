using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Automation;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Social;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    internal static long Number(StateValue map, string key) => map.Kind == StateValueKind.Map && map.MapValue.TryGetValue(key, out var v)
        && v.Kind == StateValueKind.Scalar && v.ScalarValue is {} value && long.TryParse(value.ToString(), out var n) ? n : 0;
    internal static string Text(StateValue map, string key) => map.Kind == StateValueKind.Map && map.MapValue.TryGetValue(key, out var v) && v.Kind == StateValueKind.Scalar ? v.ScalarValue as string ?? "" : "";
    private static GameActionPlan Instance(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now)
    {
        bool coop = a.Key == "coop"; var data = coop ? s.Instances.Coop : s.Instances.Main;
        int main = coop ? 186 : 85; Packet packet;
        if (a.Operation == "refresh") return Simple(new(main, coop ? 17 : 1), "instance-list", "查詢副本房間",
            next => !ReferenceEquals(coop ? next.Instances.Coop : next.Instances.Main, data));
        if (a.Operation is "claim" or "cancel")
        {
            Require(coop && data["reward"].Kind == StateValueKind.Map && s.Instances.Main["room"] == StateValue.Null, "尚未取得可操作的協力獎勵狀態。");
            var reward = data["reward"]; long open = Number(reward, "open_reward");
            if (a.Operation == "claim") Require(open == 1 && (Number(reward, "reward_mark") & 1) != 0 && Context(s).Bag.Problem(4).Length == 0, "沒有可領取的免費寶箱，或背包不足四格。");
            else Require(open is 1 or 2, "目前沒有可放棄的寶箱。");
            packet = new(186, a.Operation == "claim" ? 10 : 21);
            return Simple(packet, "instance-reward", a.Operation == "claim" ? "領取免費協力寶箱" : "放棄協力寶箱",
                next => next.Instances.Coop["reward"].Kind == StateValueKind.Map && Number(next.Instances.Coop["reward"], "open_reward") == 0 ||
                    a.Operation == "claim" && next.Instances.Coop["received_awards"].SequenceValue.Length > 0 && !ReferenceEquals(next.Instances.Coop["received_awards"], data["received_awards"]));
        }
        if (a.Operation == "standby")
        {
            Require(coop && data["room"].Kind == StateValueKind.Map && Text(data, "phase") == "waiting", "請先加入協力房間並等待房間名單。");
            var room = data["room"]; var members = data["members"].SequenceValue;
            Require(members.Length > 0 && Number(members[0], "role_id") == s.Player!.RoleId && members.Length == Number(room, "capacity"), "只有全員到齊且名單完整的房主能準備配對。");
            Require(room.MapValue.TryGetValue("standby", out var standby) && standby.ScalarValue is bool, "準備狀態尚未同步。");
            bool desired = !(bool)standby!.ScalarValue!;
            packet = new(186, 7, new PacketWriter().U16(Number(room, "room_id")).U8(desired ? 1 : 0).Build());
            return Simple(packet, "instance", "協力準備配對", next => next.Instances.Coop["room"].Kind == StateValueKind.Map &&
                next.Instances.Coop["room"].MapValue.GetValueOrDefault("standby")?.ScalarValue is bool value && value == desired);
        }
        if (a.Operation == "leave")
        {
            Require(data["room"] != StateValue.Null, "目前沒有已確認的房間。");
            packet = new(main, coop ? 5 : 6);
        }
        else if (a.Operation == "join")
        {
            var rooms = data["rooms"].SequenceValue.Where(r => Number(r, "room_id") == a.Target).ToArray();
            Require(rooms.Length == 1 && data["room"] == StateValue.Null, "房間清單已改變，請重新查詢或先離開目前房間。");
            var room = rooms[0]; bool isPublic = room.MapValue.TryGetValue("public", out var privacy) && privacy.ScalarValue is true;
            int password = a.Values?.GetValueOrDefault("password") ?? 0;
            Require(password >= 0 && (coop || password <= 65535) && (!isPublic || password == 0), "房間密碼無效。");
            var w = new PacketWriter().U16(a.Target);
            if (coop) w.U32(password);
            else { w.U16(Number(room, "sn")); if (!isPublic) w.U16(password); }
            packet = new(main, coop ? 4 : 5, w.Build());
        }
        else if (a.Operation == "create")
        {
            Require(c.OptionalInstances is not null && data["room"] == StateValue.Null, "請先等待同版副本資料，並離開目前房間。");
            var entries = c.OptionalInstances!.Entries.Where(e => e.Data.Id == a.Target && e.CreationSupported && (e.Data.Kind != 1) == coop).ToArray();
            Require(entries.Length == 1, "所選副本不在目前已核對的可建立清單。");
            var entry = entries[0];
            Require(s.PlayerKnowledge.Stats.TryGetValue("level", out var level) && level >= entry.MinLevel, "角色等級不足或尚未同步。");
            int password = a.Values?.GetValueOrDefault("password") ?? 0; bool isPublic = password == 0;
            Require(password >= 0 && (coop || password <= 65535), "房間密碼無效。");
            var w = new PacketWriter();
            if (coop)
            {
                Require(a.Count >= entry.MinMembers && a.Count <= entry.MaxMembers, "協力人數超出官方限制。");
                Require(entry.CooperativeEvent is not null && entry.CooperativeEvent.SellDataId == 0, "此協力副本有入場費，尚未取得可確認的費用明細。");
                w.U8(a.Count).U8(entry.Variant).U8(entry.CooperativeEvent!.Id).U8(isPublic ? 1 : 0).U32(password).U8(0);
            }
            else { w.U16(entry.Data.MapId).U8(isPublic ? 1 : 0).U16(password); if (isPublic) w.U8(0); }
            packet = new(main, coop ? 1 : 3, w.Build());
        }
        else if (a.Operation is "start" or "enter")
        {
            Require(!coop && data["room"].Kind == StateValueKind.Map, "請選擇已確認的一般副本房間。");
            var room = data["room"]; long id = Number(room, "room_id");
            Require(c.OptionalInstances?.Entries.Any(e => e.Data.Kind == 1 && e.Data.MapId == id) == true, "房間不在同版一般副本清單。");
            var members = data["members"].SequenceValue;
            Require(members.Any(m => Number(m, "role_id") == s.Player!.RoleId), "房間名單尚未確認本角色。");
            if (a.Operation == "start")
            {
                var entry = c.OptionalInstances!.Entries.First(e => e.Data.Kind == 1 && e.Data.MapId == id);
                Require(Text(data, "phase") == "waiting" && Number(room, "host_id") == s.Player!.RoleId && Number(room, "members") == members.Length
                    && members.Length >= entry.MinMembers && members.Length <= entry.MaxMembers, "只有人數與名單完整的房主能開始副本。");
                packet = new(85, 7);
            }
            else { Require(Text(data, "phase") == "started" && s.Player!.Scene != id, "尚未確認副本已開始，或已在副本地圖。"); packet = new(85, 9); }
        }
        else throw new ProtocolException("未知副本操作。");
        return Simple(packet, "instance", "副本操作", next => a.Operation == "enter" ? next.Player?.Scene != s.Player!.Scene :
            !ReferenceEquals(coop ? next.Instances.Coop : next.Instances.Main, data));
    }
    private static GameActionPlan Guild(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now)
    {
        Require(s.Guild.Ready && s.Guild.Serial > 0 && s.Guild.Members.ContainsKey(s.Player!.RoleId), "尚未確認本角色的組織成員身分。");
        var g = s.GuildActions;
        Require(!g.Uncertain && g.Pending is null, "前次組織操作尚未確認。");
        if (a.Operation == "sign")
        {
            Require(g.SignState == 1 && !g.SignAttempted, "簽到狀態未同步或已簽到。");
            var pending = new GuildSignPending(s.Player!.RoleId, s.Guild.Serial!.Value, g.CatalogToken, g.Epoch, now + 20);
            return new(new(39, 69), "guild", "組織簽到", next => CommandState.With(next, guildActions: next.GuildActions with { Pending = pending, SignAttempted = true }),
                next => next.GuildActions.SignState == 2 && next.GuildActions.Pending is GuildSignPending { SignAck: true },
                next => CommandState.With(next, guildActions: next.GuildActions with { Pending = null }));
        }
        throw new ProtocolException("組織捐獻費用資料尚未核對，不能送出扣款操作。");
    }
    private static GameActionPlan Expedition(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now)
    {
        var e = s.Expedition; Require(e.Ready && e.OutpostReady && !e.Uncertain && e.Pending is null, "遠征與駐紮所尚未同步，或前次操作未確認。");
        if (a.Operation == "claim")
        {
            Require(a.Index is >= 1 and <= 255 && e.Teams.TryGetValue((byte)a.Index, out var selectedTeam) && selectedTeam.Quest > 0 && selectedTeam.Due is {} due && now >= due, "此遠征尚未完成或資料已變更。");
            var team = e.Teams[(byte)a.Index];
            Require(c.Expedition.Tasks.ContainsKey(team.Quest), "缺少遠征獎勵資料，不能核對容量。");
            var issues = new List<Lala.Core.Expedition.ExpeditionAssessmentIssue>();
            var needed = Lala.Core.Expedition.ExpeditionTaskInspection.RewardSlots(c.Expedition.Tasks[team.Quest], c.Items, issues);
            Require(needed is not null && Context(s).Bag.Problem(needed.Value).Length == 0, "遠征獎勵種類未知，或背包空位不足。");
            var claim=new ExpeditionClaimReceipt(a.Index,s.Bag);
            return new(new(31,16,[(byte)a.Index]),"expedition","領取遠征結果",next=>next,
                next=>claim.Acknowledged(next.Expedition.Teams.GetValueOrDefault((byte)a.Index)?.Quest==0,next.Bag))
                {ObserveReceipt=claim.Observe};
        }
        Require(a.Operation == "dispatch" && a.Target <= 65535 && c.Expedition.Tasks.ContainsKey((ushort)a.Target) && e.Quests.ContainsValue((ushort)a.Target), "請選擇目前已同步的遠征任務。");
        var slots = (a.Values ?? ImmutableDictionary<string, int>.Empty).OrderBy(p => p.Key).Select(p => p.Value).ToArray();
        Require(slots.Length is >= 1 and <= 4 && slots.Distinct().Count() == slots.Length && slots.All(i => i is >= 1 and <= 255 && e.Roles.ContainsKey((byte)i)), "請選擇一至四名駐紮所夥伴。");
        var task = c.Expedition.Tasks[(ushort)a.Target];
        var members = slots.Select(i => e.Roles[(byte)i]).ToArray();
        Require(e.Level is {} level && c.Expedition.Levels.ContainsKey(level), "遠征等級尚未確認。");
        var lv = c.Expedition.Levels[e.Level!.Value];
        Require(task.Difficulty <= lv.Difficulty && e.Teams.Values.Any(t => t.Index <= lv.Teams && t.Quest == 0), "遠征難度超出目前等級，或沒有空隊伍。");
        Require(!e.Teams.Values.Any(t => t.Quest != 0 && c.Expedition.Tasks.GetValueOrDefault(t.Quest)?.Area == task.Area), "此區域已有派遣中的遠征。");
        var occupied = e.Teams.Values.Where(t => t.Quest != 0).SelectMany(t => t.Members).ToHashSet();
        Require(members.All(m => !occupied.Contains(m.NpcId)), "所選夥伴已在其他遠征隊伍中。");
        Require(members.All(r => r.State == 0 && r.Faith >= task.FaithCost) && members.Select(r => r.NpcId).Distinct().Count() == members.Length, "所選夥伴忙碌、重複或信仰不足。");
        var w = new PacketWriter().U16(a.Target);
        foreach (var member in members) w.U16(member.NpcId);
        for (int i = members.Length; i < 4; i++) w.U16(0);
        w.U8(0);
        return Simple(new(31, 15, w.Build()), "expedition", "派遣遠征", next => next.Expedition.Teams.Values.Any(t => t.Quest == a.Target && members.All(m => t.Members.Contains(m.NpcId))));
    }
    private static GameActionPlan Craft(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        var craft = s.Crafting.Crafting;
        Require(craft.Ready && !craft.Uncertain && craft.Pending is null, "製作排程未同步，或前次操作尚未確認。");
        Packet packet;
        if (a.Operation == "pause") { Require(craft.Active != 0 && craft.Running, "目前沒有執行中的製作。"); packet = new(64, 3, [craft.Active]); }
        else if (a.Operation is "delete" or "up" or "down")
        {
            Require(a.Index is >= 1 and <= 255 && craft.Queue.ContainsKey((byte)a.Index) && a.Index != craft.Active, "請選擇未執行的排程。");
            if (a.Operation == "delete") packet = new(64, 4, [(byte)a.Index]);
            else
            {
                int other = a.Index + (a.Operation == "up" ? -1 : 1);
                Require(other is >= 1 and <= 255 && craft.Queue.ContainsKey((byte)other) && other != craft.Active, "無可交換的相鄰排程。");
                packet = new(64, 6, [(byte)a.Index, (byte)other]);
            }
        }
        else throw new ProtocolException("請先選擇已核對配方及小屋設備後再開始製作。");
        return Simple(packet, "craft", "製作排程操作", next => next.Crafting.Crafting.Revision > craft.Revision);
    }
    private static GameActionPlan Npc(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now)
    {
        var session = s.Local.Session; var dialogue = session.NpcDialogue; Packet packet;
        if (a.Operation == "start")
        {
            var rows = c.EveIndexes.Scenes.FirstOrDefault(scene => scene.SceneId == s.Player!.Scene)?.Npcs ?? [];
            var matches = rows.Where(row => row.Index == a.Index && row.NpcId == a.Target && row.X == a.X && row.Y == a.Y && row.EventIds.Length > 0).ToArray();
            Require(matches.Length == 1 && !dialogue.Active && s.Local.World.Location.ConfirmedIsCurrent, "NPC、起點或事件資料已改變。");
            Require(s.Party.OwnTeam(s.Player!.RoleId) is not {} team || team.LeaderId == s.Player.RoleId, "隊員不能自行觸發 NPC。");
            packet = new(20, 1, new PacketWriter().U16(a.Index).Build());
            dialogue = dialogue with { Active = true, Phase = "requesting", Scene = s.Player!.Scene, NpcIndex = (ushort)a.Index, NpcId = a.Target };
        }
        else if (a.Operation == "next")
        {
            Require(dialogue.Active && dialogue.Scene == s.Player!.Scene && dialogue.Phase is "talk" or "continue" && !session.EventFlow.AwaitingResponse && s.Local.Battle.Active != true, "目前沒有可接續的 NPC 對話。");
            packet = new(20, 6, [0]); dialogue = dialogue with { Phase = "awaiting_reply" };
        }
        else if (a.Operation is "choose" or "close_choice" or "close_shop")
        {
            Require(dialogue.Active && dialogue.Scene == s.Player!.Scene && dialogue.Phase == "choice_unavailable" && dialogue.EffectType == 6 &&
                dialogue.OptionIndex is not null && !session.EventFlow.AwaitingResponse && s.Local.Battle.Active != true, "目前沒有可操作的 NPC 選項。");
            Require(a.Scene == dialogue.Scene && a.Count == dialogue.OptionIndex, "對話場景或選單已變更。");
            Require(dialogue.EffectPacket is not null && a.Key == dialogue.EffectPacket.Value.ToString(System.Globalization.CultureInfo.InvariantCulture), "NPC 對話已更新，請重新選擇。");
            var rows = c.EveIndexes.Scenes.Where(scene => scene.SceneId == a.Scene).SelectMany(scene => scene.Interactions).Where(row => row.Index == dialogue.OptionIndex).ToArray();
            Require(rows.Length == 1, "NPC 選單來源尚未唯一核對。");
            if (a.Operation == "choose")
            {
                var menu = GameNpcChoices.Read(c.EveIndexes, c.Talks, a.Scene, dialogue.OptionIndex!.Value);
                Require(menu is not null && a.Index >= 0 && a.Index < menu.Options.Length && menu.Options[a.Index].TextId == a.Target, "NPC 選項身分或官方文字已變更。");
                packet = new(20, 9, [checked((byte)(30 + a.Index))]);
                dialogue = dialogue with { Phase = "awaiting_choice", SelectedChoice = (byte)a.Index, ChoiceContinuationPending = true };
            }
            else if (a.Operation == "close_shop")
            {
                Require(rows[0].FormKind is 2 or 3 && SceneShopPreviewRequest.Build(rows[0], c.Items) is not null, "目前事件不是已核對的道具／武器商店。");
                packet = new(20, 9); dialogue = dialogue with { Phase = "closing_shop", ChoiceContinuationPending = false };
            }
            else
            {
                Require(rows[0].FormKind == 1, "商店或未知類型不可使用一般選項關閉封包。");
                packet = new(20, 9, [40]); dialogue = dialogue with { Phase = "closing", ChoiceContinuationPending = false };
            }
        }
        else throw new ProtocolException("未知 NPC 操作或選項尚未核對。");
        var nextSession = session with { NpcDialogue = dialogue, EventFlow = session.EventFlow with { Blocked = true, AwaitingResponse = true, LastSource = "NPC 手動操作" } };
        return new(packet, "npc", "NPC 互動", next => CommandState.With(next, local: new(nextSession, next.Local.World, next.Local.Battle)),
            next => !next.Local.Session.EventFlow.AwaitingResponse || !next.Local.Session.NpcDialogue.Active)
        { ContinueNpcChoice = a.Operation == "choose" };
    }
    private static GameActionPlan Daily(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now, string resourceKey)
    {
        Require(c.OptionalDailyCatalog is not null, "同版每日任務目錄尚未就緒。");
        var input = new DailyCatalogInput(c.OptionalDailyCatalog!.ToPlanningDefinitions(), resourceKey);
        var bound = DailyTaskService.Tick(s.DailyTasks, Context(s), input, now).State;
        var plan = DailyTaskService.Request(bound, Context(s), input,
            a.Operation == "task" ? DailyClaimAction.Task : a.Operation == "chest" ? DailyClaimAction.Chest : DailyClaimAction.ClaimReady, now, a.Index, a.Count);
        return new(plan.Candidate!, "rewards", "領取任務獎勵", next => CommandState.With(next, daily: plan.State),
            next => DailyTaskService.Tick(next.DailyTasks, Context(next), input, System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency).State is { Pending: null, Uncertain: false },
            next => CommandState.With(next, daily: DailyTaskService.Tick(next.DailyTasks, Context(next), input, System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency).State));
    }
}
