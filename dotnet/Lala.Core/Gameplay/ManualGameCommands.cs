using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Automation;
using Lala.Core.Battle;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World.Tent;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    internal static void Require([System.Diagnostics.CodeAnalysis.DoesNotReturnIf(false)] bool value, string message) { if (!value) throw new ProtocolException(message); }
    internal static GameActionPlan Plan(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate catalog, double now, string resourceKey, GameSocialCatalog? social = null)
    {
        Require(s.Phase == "world_ready" && s.Player?.RoleId > 0 && s.Local.Session.InitialDataComplete, "請等待角色與世界資料同步完成。");
        if (a.Scene != 0) Require(s.Player!.Scene == a.Scene, "場景已改變，請重新選取。");
        if (a.Kind == "battle") return Battle(a, s, catalog);
        if (a.Kind == "event") return ContinueEvent(s);
        if (a.Kind == "npc" && a.Operation != "start") return Npc(a, s, catalog, now);
        Require(s.Local.Battle.Active != true && !s.Local.Session.EventFlow.Blocked, "請等待戰鬥或遊戲事件結束。");
        Require(s.Activities.Count == 0, "請先結束目前活動。");
        return a.Kind switch
        {
            "party" => Party(a, s, now), "companion" => Companion(a, s),
            "attributes" => Attributes(a, s, now), "tent" => Tent(a, s, now),
            "alchemy" => Alchemy(a, s, catalog),
            "portal" => Portal(a, s, catalog),
            "cube" => Cube(s, now), "storage" => Storage(a, s), "field_item" => FieldItem(a, s, catalog),
            "instance" => Instance(a, s, catalog, now), "guild" => a.Operation == "donate" ? Donate(a, s, social, now) : Guild(a, s, catalog, now),
            "ark" => ArkAction(a, s, catalog, social, now, resourceKey),
            "expedition" => a.Operation == "restore" ? ExpeditionFaith(a, s, catalog) : Expedition(a, s, catalog, now), "craft" => CraftFull(a, s, catalog, now),
            "npc" => Npc(a, s, catalog, now), "daily" => Daily(a, s, catalog, now, resourceKey),
            _ => throw new ProtocolException("不支援的遊戲操作。")
        };
    }
    private static GameActionPlan Simple(Packet packet, string domain, string label, Func<ServiceStateSnapshot, bool> ack) =>
        new(packet, domain, label, s => s, ack);

    private static GameActionPlan Party(GameAction a, ServiceStateSnapshot s, double now)
    {
        var p = s.Party; uint own = s.Player!.RoleId; var team = p.OwnTeam(own);
        Packet packet;
        if (a.Operation == "flag") { Require(a.Count is 1 or 2, "組隊開關值無效。"); packet = new(33, 5, [(byte)a.Count]); }
        else if (a.Operation == "respond")
        {
            Require(a.Key is not null && p.Requests.ContainsKey(a.Key), "請選擇目前的組隊請求。");
            var request = p.Requests[a.Key!];
            Require(request.Status == "pending" && request.Expires > now && a.Count is 1 or 2, "組隊請求已回覆或逾時。");
            if (a.Count == 1)
            {
                Require(request.Type != "team_invite" || team is null, "已有隊伍，不能接受其他邀請。");
                Require(request.Type != "team_application" || team is null || team.LeaderId == own && team.Members.Length < 4, "僅未滿隊的隊長可接受申請。");
            }
            int sub = request.Type switch { "team_invite" => 8, "team_application" => 3, "team_leader_offer" => 10, _ => throw new ProtocolException("未知組隊請求。") };
            packet = new(13, sub, sub == 10 ? a.Count == 1 ? [3] : [2, 2] : new PacketWriter().U8(a.Count).U32(request.RoleId).Build());
        }
        else if (a.Operation == "leave") { Require(team is not null, "目前沒有隊伍。"); packet = new(13, 4); }
        else
        {
            Require(a.Target > 0 && a.Target != own, "請選擇其他玩家。");
            if (a.Operation is "invite" or "apply")
            {
                Require(p.Enabled != false, "請先開啟組隊。");
                Require(!p.Nearby.TryGetValue(a.Target, out var nearby) || nearby.Scene == s.Player.Scene, "目標已離開此地圖。");
                Require(a.Operation != "apply" || team is null, "已有隊伍，請先離隊。");
                Require(a.Operation != "invite" || team is null || team.LeaderId == own && team.Members.Length < 4, "僅未滿隊的隊長可邀請。");
            }
            else Require(team?.LeaderId == own && team.Members.Contains(a.Target), "僅隊長可操作目前隊員。");
            int sub = a.Operation switch { "invite" => 7, "apply" => 1, "kick" => 9, "leader" => 10, _ => throw new ProtocolException("未知組隊操作。") };
            var w = new PacketWriter(); if (sub == 10) w.U8(1);
            packet = new(13, sub, w.U32(a.Target).Build());
        }
        bool receipt = false;
        var plan = new GameActionPlan(packet, "party", "組隊操作", next => next, next => a.Operation switch
        {
            "flag" => receipt && next.Party.Enabled == (a.Count == 1),
            "invite" or "apply" => receipt,
            "leave" => next.Party.OwnTeam(own) is null,
            "kick" => next.Party.OwnTeam(own) is {} remaining && !remaining.Members.Contains(a.Target),
            "leader" => next.Party.OwnTeam(own)?.LeaderId == a.Target,
            "respond" => p.Requests[a.Key!].Type == "team_leader_offer" ? next.Party.OwnTeam(own)?.LeaderId == own :
                next.Party.OwnTeam(own)?.Members.Contains(p.Requests[a.Key!].RoleId) == true,
            _ => false
        })
        {
            ObserveReceipt = response =>
            {
                if (response.Type == "social_rejected" || response.Type == "team_answer" && response.Role == a.Target && response.Code != 1)
                    throw new ProtocolException("伺服器或對方未接受此組隊要求。");
                if (a.Operation == "flag" && response.Type == "team_flag" && response.Code == a.Count ||
                    response.Type == "team_notice" && (a.Operation == "invite" && response.Code == 1 || a.Operation == "apply" && response.Code == 2)) receipt = true;
            }
        };
        return a.Operation == "respond" && a.Count == 2 ? plan with { AwaitAcknowledgement = false,
            AfterWrite = next => CommandState.With(next, party: next.Party with { Requests = next.Party.Requests.Remove(a.Key!) }) } : plan;
    }
    private static GameActionPlan Companion(GameAction a, ServiceStateSnapshot s)
    {
        Require(s.Companions.Ready && a.Index is >= 1 and <= ushort.MaxValue &&
            s.Companions.Companions.TryGetValue((ushort)a.Index, out var selected) && selected.Data.NpcId == a.Target, "夥伴資料已變更，請重新選取。");
        Require(s.Companions.Companions.Values.Count(p => p.Data.NpcId == a.Target) == 1, "相同 NPC ID 有多隻夥伴，無法確認出戰格位。");
        bool deploy = a.Operation == "deploy";
        Require(deploy || a.Operation == "rest", "未知夥伴操作。");
        Require(deploy ? s.Companions.ActiveNpcId != a.Target : s.Companions.ActiveNpcId == a.Target, "夥伴出戰狀態已改變。");
        if (deploy) Require(!s.Companions.Companions[(ushort)a.Index].StatOverrides.TryGetValue("can_grow", out var can) || can != 0, "此夥伴無法出戰。");
        return Simple(deploy ? new(19, 1, new PacketWriter().U32(a.Target).Build()) : new(19, 2), "companion", deploy ? "夥伴出戰" : "夥伴休息",
            next => deploy ? next.Companions.ActiveNpcId == a.Target : next.Companions.ActiveNpcId != a.Target);
    }
    private static GameActionPlan Attributes(GameAction a, ServiceStateSnapshot s, double now)
    {
        Require(s.PlayerKnowledge.Ready && !s.AttributeAllocation.Pending && !s.AttributeAllocation.Uncertain, "能力未同步，或上一筆配點尚未確認。");
        var fields = new[] { ("int", 27), ("str", 28), ("con", 29), ("agi", 30), ("wis", 33) };
        var stats = s.PlayerKnowledge.Stats; var values = a.Values ?? ImmutableDictionary<string, int>.Empty;
        Require(values.Keys.All(k => fields.Any(f => f.Item1 == k)) && values.Values.All(v => v >= 0), "配點欄位或數值無效。");
        long count = values.Values.Sum(v => (long)v);
        Require(count > 0 && stats.TryGetValue("attribute_potential", out var potential) && count <= potential, "可分配點數不足。");
        var expected = ImmutableDictionary.CreateBuilder<string, BigInteger>();
        var entries = fields.Where(f => values.GetValueOrDefault(f.Item1) > 0).ToArray();
        var w = new PacketWriter().U8(0).U8(entries.Length);
        foreach (var (key, kind) in fields)
        {
            Require(stats.TryGetValue(key, out var before) && before >= 0 && before + values.GetValueOrDefault(key) <= 602, "能力尚未同步或超過基礎上限 602。");
            expected[key] = before + values.GetValueOrDefault(key);
            if (values.GetValueOrDefault(key) > 0) w.U8(kind).U32(values[key]);
        }
        expected["attribute_potential"] = stats["attribute_potential"] - count;
        return new(new(8, 1, w.Build()), "attributes", "角色配點",
            next => CommandState.With(next, points: new() { Pending = true, Expected = expected.ToImmutable(), SentAt = now, Status = "配點已送出，等待能力同步" }),
            next => !next.AttributeAllocation.Pending && next.AttributeAllocation.Status == "配點成功，能力值已同步");
    }
    private static GameActionPlan Tent(GameAction a, ServiceStateSnapshot s, double now)
    {
        var t = s.Tent;
        Require(t.Pending is null && !t.Uncertain, "帳篷操作尚未確認。");
        Packet packet;
        if (a.Operation == "open") { Require(t.DeployedScene is null && !t.Inside, "已有帳篷，或目前位於小屋內。"); packet = new(65, 6); }
        else if (a.Operation == "close") { Require(t.DeployedScene is not null && !t.Inside, "尚未確認可收起的帳篷。"); packet = new(65, 2); }
        else if (a.Operation == "enter") { Require(t.Visible && t.Scene == s.Player!.Scene, "本場景未確認自家帳篷。"); packet = new(65, 1, new PacketWriter().U32(s.Player!.RoleId).Build()); }
        else throw new ProtocolException("未知帳篷操作。");
        var pending = new TentActionObservation(a.Operation) { Due = now + 15, SourceScene = s.Player!.Scene };
        return new(packet, "tent", "帳篷操作", next => CommandState.With(next, tent: next.Tent with
        { Pending = pending, EntryContext = a.Operation == "enter" ? pending : null }),
            next => next.Tent.Pending is null);
    }
    private static AutomationContext Context(ServiceStateSnapshot s) => new()
    {
        WorldReady = s.Phase == "world_ready", InitialDataComplete = s.Local.Session.InitialDataComplete,
        WorldAcknowledged = true, RoleId = s.Player?.RoleId, ResourceHeld = false,
        BattleActive = s.Local.Battle.Active == true, EventBlocked = s.Local.Session.EventFlow.Blocked,
        HasActivities = s.Activities.Count > 0,
        Bag = new() { Ready = s.Bag.Ready, Reliable = s.Bag.Reliable, Capacity = s.Bag.Capacity ?? 0,
            Revision = (long)s.Bag.Revision, Items = [..s.Bag.Items.Values.Select(i => new BagSlot(i.Index, i.ItemId, i.Count))],
            HasHolds = !s.Bag.Holds.IsEmpty, HasReservedItems = s.Bag.Reserved.Count > 0 }
    };
    private static GameActionPlan Cube(ServiceStateSnapshot s, double now)
    {
        var plan = TimeCubeService.RequestOpen(s.TimeCube, Context(s), now);
        return new(plan.Candidate!, "rewards", "開啟時間魔方", next => CommandState.With(next, cube: plan.State),
            next => next.TimeCube.Count < s.TimeCube.Count && next.Bag.Revision > s.Bag.Revision,
            next => CommandState.With(next, cube: next.TimeCube with { Pending = null }));
    }
}
