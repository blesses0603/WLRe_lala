using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static GameActionPlan Storage(GameAction a, ServiceStateSnapshot s)
    {
        bool deposit = a.Operation == "deposit"; bool materials = a.Key == "materials";
        Require(deposit || a.Operation == "withdraw", "未知儲藏操作。");
        Require(a.Key is "materials" or "garage" && a.Index is >= 1 and <= 65535 && a.Count is >= 1 and <= 65535, "儲藏格位或數量無效。");
        var bucket = materials ? s.Storage.Storage.Materials : s.Storage.Storage.Garage;
        Require(s.Bag.Ready && s.Bag.Reliable && bucket.Ready && bucket.Reliable && !s.Storage.Storage.Uncertain, "背包或儲藏空間尚未完整同步。");
        ushort item; BigInteger sourceCount; ItemSave? record;
        if (deposit)
        {
            Require(a.Index <= 255 && s.Bag.Items.ContainsKey((byte)a.Index), "背包格位已改變。");
            var row = s.Bag.Items[(byte)a.Index]; item = row.ItemId; sourceCount = row.Count; record = row.OriginalRecord;
            Require(s.Bag.Holds.IsEmpty && s.Bag.Reserved.Count == 0, "物品仍被其他功能保留。");
        }
        else
        {
            Require(bucket.Items.ContainsKey((ushort)a.Index), "儲藏物品已改變。");
            var row = bucket.Items[(ushort)a.Index]; item = row.ItemId; sourceCount = row.Count; record = row.OriginalGarageRecord;
            Require(bucket.Holds.IsEmpty && bucket.Reserved.Count == 0, "儲藏物品仍被其他功能保留。");
        }
        Require(item == a.Target && sourceCount >= a.Count && item != 34977, "物品身分或可用數量已改變。");
        // Metadata restrictions are checked against the original complete wire record.
        Require(record is null || !record.Locked && record.LimitedTime == 0 && record.AvailableTime == 0, "鎖定或期限物品不能存取。");
        bool stackable = s.Bag.ServerStackable?.GetValueOrDefault(item) == true || sourceCount > 1;
        if (deposit && materials) Require(stackable && record is not null && record.EnhanceLevel == 0 && record.MagicSpar == 0 && record.BeatLevel == 0 && record.DesignId == 0, "雜物櫃只接受無附加屬性的可堆疊物品。");
        int limit = deposit && materials ? s.Storage.Storage.MaterialStackLimit ?? 0 : 200;
        Require(limit > 0, "目的容器堆疊上限尚未同步。");
        int capacity = deposit ? bucket.Capacity ?? 0 : s.Bag.Capacity ?? 0;
        int occupied = deposit ? bucket.Items.Count : s.Bag.Items.Count;
        BigInteger space = stackable ? deposit
            ? bucket.Items.Values.Where(r => r.ItemId == item).Aggregate(BigInteger.Zero, (sum, r) => sum + BigInteger.Max(0, limit - r.Count))
            : s.Bag.Items.Values.Where(r => r.ItemId == item).Sum(r => Math.Max(0, limit - r.Count)) : 0;
        var needed = stackable ? (BigInteger.Max(0, a.Count - space) + limit - 1) / limit : a.Count;
        Require(capacity > 0 && occupied + needed <= capacity, "目的容器空間不足。");
        var w = new PacketWriter(); Packet packet;
        if (!materials)
        {
            Require(a.Count <= 255 && a.Index <= 255, "儲藏室單次最多一個格位的數量。");
            packet = new(62, deposit ? 18 : 19, w.U8(1).U8(a.Index).U8(a.Count).Build());
        }
        else if (deposit)
        {
            Require(a.Count <= 255, "存入數量超過背包格位上限。");
            packet = new(62, 52, w.U8(1).U8(1).U8(a.Index).U8(a.Count).Build());
        }
        else
        {
            int parts = (a.Count + 199) / 200; Require(parts <= 255, "取出數量過多，請分次操作。");
            w.U8(2).U8(parts);
            for (int left = a.Count; left > 0; left -= 200) w.U16(a.Index).U8(Math.Min(left, 200));
            packet = new(62, 52, w.Build());
        }
        BigInteger beforeBag = s.Bag.Items.Values.Where(i => i.ItemId == item).Sum(i => (long)i.Count);
        BigInteger beforeStore = bucket.Items.Values.Where(i => i.ItemId == item).Aggregate(BigInteger.Zero, (sum, i) => sum + i.Count);
        return Simple(packet, "inventory", deposit ? "存入物品" : "取出物品", next =>
        {
            var destination = materials ? next.Storage.Storage.Materials : next.Storage.Storage.Garage;
            BigInteger bag = next.Bag.Items.Values.Where(i => i.ItemId == item).Sum(i => (long)i.Count);
            BigInteger store = destination.Items.Values.Where(i => i.ItemId == item).Aggregate(BigInteger.Zero, (sum, i) => sum + i.Count);
            int amount = deposit ? a.Count : -a.Count;
            return bag == beforeBag - amount && store == beforeStore + amount;
        });
    }
    private static CombatResourceCatalog ResourceCatalog(OfflineRuntimeCandidate c) => new()
    {
        Npcs = c.ReviewedNpcs ?? ImmutableDictionary<uint, CombatResourceNpc>.Empty,
        SkillKeys = Lala.Core.Sessions.AccountRuntime.ProjectSkillKeys(c.OptionalSkills)?.SkillKeys ?? ImmutableDictionary<ushort, uint>.Empty,
        Skills = (c.OptionalSkills ?? new Dictionary<ushort, SkillDataRow>()).ToImmutableDictionary(p => (uint)p.Key,
            p => new CombatResourceSkill { Fields = p.Value.Fields.ToImmutableDictionary(f => f.Key, f => (long)f.Value) }),
        Items = c.Items.Where(p => p.Value.ReviewedDetails is not null).ToImmutableDictionary(p => p.Key,
            p => new CombatResourceItem { Kind = p.Value.ReviewedDetails!.Kind, FitType = p.Value.ReviewedDetails.FitType,
                Restrict = p.Value.Restrict, SkillLink = p.Value.ReviewedDetails.SkillLink ?? 0,
                Attributes = [..p.Value.ReviewedDetails.Attributes.Select(v => new CombatResourceAttribute(v.Kind, v.Value))] })
    };
    private static GameActionPlan FieldItem(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        Require(a.Index is >= 1 and <= 255 && s.Bag.Ready && s.Bag.Reliable && s.Bag.Items.TryGetValue((byte)a.Index, out var item) && item.ItemId == a.Target && item.Count > 0,
            "請選擇目前背包中的補給物品。");
        var catalog = ResourceCatalog(c);
        var field = CombatResourceKnowledge.FieldContext(s.PlayerKnowledge, s.Companions, s.Player, catalog);
        var context = new CombatResourceActionContext { Player = s.PlayerKnowledge, Companions = s.Companions, LocalRoleId = s.Player!.RoleId,
            Units = [..field.Units.Select(actor => new CombatResourceBattleEntry(BattleCommandPlanner.Slot(actor), actor))], Inventory = s.Bag, Catalog = catalog };
        var actor = field.Actor;
        string? target = context.Units.FirstOrDefault(entry => entry.Actor.NpcIndex == a.Count)?.Slot;
        Require(target is not null, "補給目標不是目前角色或出戰夥伴。");
        var candidate = CombatResourceActionCandidates.Food(context, actor, a.Operation == "sp" ? "sp" : "hp", (ushort)a.Target, target, true, (byte)a.Index);
        Require(candidate.Success, candidate.Error?.Message ?? "無法核對物品效果。");
        var intent = candidate.Intent!; int before = s.Bag.Items[(byte)a.Index].Count;
        var recipient = field.Units.First(entry => entry.NpcIndex == a.Count); string resource = a.Operation == "sp" ? "sp" : "hp";
        long original = recipient.Stats.GetValueOrDefault(resource);
        return Simple(CandidateCommands.UseFieldItem(intent.ItemId!.Value, intent.BagIndex!.Value, a.Count), "inventory", "使用補給物品",
            next => (next.Bag.Items.GetValueOrDefault((byte)a.Index)?.Count == before - 1 || before == 1 && !next.Bag.Items.ContainsKey((byte)a.Index)) &&
                CombatResourceKnowledge.FieldContext(next.PlayerKnowledge, next.Companions, next.Player, catalog).Units.Any(unit => unit.NpcIndex == a.Count && unit.Pid == recipient.Pid && unit.Stats.GetValueOrDefault(resource) > original));
    }
    private static GameActionPlan Battle(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        var b = s.Local.Battle;
        Require(b.Active == true && b.Round > 0 && a.Index == b.Round, "戰場或回合已改變。");
        var unit = b.Units.FirstOrDefault(u => u.Layout.Col == a.X && u.Layout.Row == a.Y);
        Require(unit is not null && (unit.Layout.Pid == s.Player!.RoleId || unit.Layout.MasterId == s.Player!.RoleId) && unit.Layout.Pid == a.Target && unit.Hp > 0 && !unit.Exited, "戰鬥單位已改變或不屬於本機。");
        Require(b.CommandAt(unit!.Slot) is null, "本單位本回合已下令。");
        var resources = new CombatResourceActionContext { LocalRoleId = s.Player!.RoleId, Player = s.PlayerKnowledge, Companions = s.Companions,
            Inventory = s.Bag, Units = b.Actors, Catalog = ResourceCatalog(c), WarStyle = b.WarStyle };
        var context = new BattleCommandContext { Active = true, Round = b.Round!.Value, Resources = resources,
            NormalCatalog = c.OptionalNormalAttackCatalog?.NormalAttacks ?? new([], []) };
        BattleCommandIntent intent;
        if (a.Operation == "auto" && a.BattleProfile is {} profile)
        {
            var choice = AutoBattleRuleChooser.Choose(context, unit.Actor, profile);
            Require(choice.Success, choice.Error?.Message ?? "沒有符合條件的自動戰鬥行動。"); intent = choice.Intent!;
        }
        else if (a.Operation == "skill")
        {
            Require(a.Count is >= 1 and <= 65535, "特技 ID 無效。");
            var choice = CombatResourceActionCandidates.Learned(resources, unit.Actor, (uint)a.Count, a.Key);
            Require(choice.Success, choice.Error?.Message ?? "無法使用此特技。");
            var v = choice.Intent!; intent = new(BattleCommandKind.LearnedSkill, v.Col, v.Row, v.ActorPid!.Value, v.TargetCol, v.TargetRow, v.SkillId, v.ItemId, v.BagIndex, v.Resource, v.Allocations);
        }
        else
        {
            var choice = BattleCommandPlanner.Action(context, unit.Actor, a.Operation, a.Key);
            Require(choice.Success, choice.Error?.Message ?? "無法選擇戰鬥行動。"); intent = choice.Intent!;
        }
        if (intent.BagIndex is {} used) Require(!b.Commands.Any(cmd => cmd.Event.BagIndex == used), "此格位本回合已有待確認的物品消耗。");
        var packet = intent.ItemId is {} item ? CandidateCommands.UseBattleItem(intent.Col, intent.Row, intent.TargetCol, intent.TargetRow, item, intent.BagIndex!.Value)
            : CandidateCommands.CastSkill(intent.Col, intent.Row, intent.TargetCol, intent.TargetRow, (int)intent.SkillId!.Value);
        var sent = new BattleCommandSentEvent((byte)a.X, (byte)a.Y, (byte)intent.TargetCol, (byte)intent.TargetRow, (ushort?)intent.SkillId, intent.ItemId, intent.BagIndex);
        return new(packet, "battle", "戰鬥下令", next => next, next => false)
        {
            AwaitAcknowledgement = false,
            AfterWrite = next => next.Local.Battle.BattleCount == b.BattleCount && next.Local.Battle.Round == b.Round
                ? CommandState.With(next, local: new(next.Local.Session, next.Local.World, BattleEventReducer.Apply(next.Local.Battle, sent))) : next
        };
    }
}
