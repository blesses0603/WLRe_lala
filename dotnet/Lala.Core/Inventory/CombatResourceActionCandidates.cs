using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

public sealed record CombatResourceBattleEntry(string Slot, CombatResourceActor Actor);

/// <summary>Explicit offline observations. Slot keys retain source dictionary order and may
/// differ from coordinates. Catalogs are unverified inputs, never runtime authority.</summary>
public sealed record CombatResourceActionContext
{
    public PlayerKnowledgeSnapshot Player { get; init; } = PlayerKnowledgeSnapshot.Empty;
    public CompanionReceiveSnapshot Companions { get; init; } = CompanionReceiveSnapshot.Empty;
    public uint? LocalRoleId { get; init; }
    public ImmutableArray<CombatResourceBattleEntry> Units { get; init; } = [];
    public BagReceiveSnapshot Inventory { get; init; } = BagReceiveSnapshot.Empty;
    public InventoryPlanningContext InventoryContext { get; init; } = InventoryPlanningContext.Empty;
    public CombatResourceCatalog Catalog { get; init; } = CombatResourceCatalog.Empty;
    public long? WarStyle { get; init; }
}

public enum CombatResourceActionKind { LearnedSkill, NormalAttack, BattleItem, FieldItem }

/// <summary>Detached candidate intent only. Allocations are proposed costs, not acquired
/// reservations. No method here installs holds, dispatches a command or grants send authority.</summary>
public sealed record CombatResourceActionIntent(CombatResourceActionKind Kind, int Col, int Row,
    uint? ActorPid, int TargetCol, int TargetRow, long? SkillId, ushort? ItemId, byte? BagIndex,
    string? Resource, ImmutableArray<InventoryAllocation> Allocations);
public sealed record CombatResourceActionCandidate(CombatResourceActionIntent? Intent, InventoryPlanningError? Error)
{
    public bool Success => Error is null;
}

/// <summary>Pure learned_command, best_skill_command and food_command candidates, including
/// only their normal action_command fallback. No round planner or lifecycle integration.</summary>
public static class CombatResourceActionCandidates
{
    private static readonly ImmutableHashSet<long> NoItems = ImmutableHashSet.Create<long>(9,12,13,14,15,16,17,18,21,22,23,24);

    public static CombatResourceActionCandidate Learned(CombatResourceActionContext context, CombatResourceActor actor,
        uint skillId, string? targetSlot = null, int targetKind = 1, bool nextSkill = false) =>
        Capture(() => LearnedCore(context,actor,skillId,targetSlot,targetKind,nextSkill));

    public static CombatResourceActionCandidate BestSkill(CombatResourceActionContext context, CombatResourceActor actor,
        NormalAttackCatalogSnapshot normalCatalog, string? targetSlot = null, int targetKind = 1) => Capture(() =>
    {
        Validate(context); ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(normalCatalog);
        var records = CombatResourceKnowledge.Learned(context.Player,context.Companions,context.LocalRoleId,actor,context.Catalog);
        var candidates = new List<(long Sp,long Sort,uint Id)>();
        foreach (var record in records)
        {
            var fields = context.Catalog.Skills.GetValueOrDefault(record.Id)?.Fields ?? ImmutableDictionary<string,long>.Empty;
            var atk = fields.GetValueOrDefault("AtkKind"); var way = fields.GetValueOrDefault("FightWay");
            var physical = atk == 1 || atk == 3 && way == 1;
            var magic = atk == 2 && way is 1 or 2 || atk == 3 && way == 2;
            if (fields.GetValueOrDefault("KindSort") is not (1 or 2) || !(physical || magic)) continue;
            if (actor.Pid == context.LocalRoleId && context.Player.Stats.TryGetValue("atk",out var attack) &&
                context.Player.Stats.TryGetValue("matk",out var magicAttack) && physical != (attack >= magicAttack)) continue;
            candidates.Add((fields.GetValueOrDefault("ReduceSP"),fields.GetValueOrDefault("Sort"),record.Id));
        }
        foreach (var candidate in candidates.OrderBy(value => value.Sp).ThenBy(value => value.Sort).ThenBy(value => value.Id))
        {
            try { return LearnedCore(context,actor,candidate.Id,targetSlot,targetKind,false); }
            catch (ProtocolException) { } // The source does not suppress malformed-catalog failures.
        }
        if (string.IsNullOrEmpty(targetSlot) && targetKind is 2 or 3)
        {
            var enemies = Enemies(context,actor);
            if (enemies.Count != 0)
            {
                var chosen = SelectTarget(enemies,context.Catalog,actor.Element ?? 0,targetKind);
                targetSlot = Slot(chosen);
            }
        }
        var targets = Enemies(context,actor).Where(value => string.IsNullOrEmpty(targetSlot) || Slot(value) == targetSlot).ToList();
        if (targets.Count == 0) throw new ProtocolException("沒有存活的敵方目標");
        var target = SelectTarget(targets,context.Catalog,0,1);
        // The shared normal-rule API intentionally requires known wire identities. Do not
        // manufacture a role/NPC ID when an imported observation lacks that information.
        if (actor.Pid is not { } pid || context.LocalRoleId is not { } role)
            throw new ArgumentException("Normal fallback requires explicit actor and local role identities.");
        var sid = CombatRules.NormalSkill(new(pid,actor.MasterId,actor.ChangeBodyId,actor.Equips.Select(value => (int)value.ItemId)),role,normalCatalog);
        return Intent(CombatResourceActionKind.NormalAttack,actor,target,sid,null,null,null,[]);
    });

    /// <summary>Only the game resources hp and sp are valid typed input. Other keys are
    /// rejected before evaluating source gates; arbitrary Python resource strings are not
    /// an action surface and their repr/Unicode-uppercase error formatting is not ported.</summary>
    public static CombatResourceActionCandidate Food(CombatResourceActionContext context, CombatResourceActor actor,
        string resource = "hp", ushort? itemId = null, string? targetSlot = null, bool field = false, int? index = null) => Capture(() =>
    {
        Validate(context); ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(resource);
        if (resource is not ("hp" or "sp"))
            throw new ArgumentException("Food resource must be hp or sp.",nameof(resource));
        var inventory = context.Inventory;
        if (!inventory.Ready) throw new ProtocolException("包包尚未同步；請重新登入");
        if (!inventory.Reliable) throw new ProtocolException("包包同步異常：" + (inventory.SyncError ?? "先前操作未完整確認") + "；請重新登入同步");
        if (inventory.UseFailed) throw new ProtocolException("前次道具使用失敗或結果未確認；請重新登入同步");
        if (!field && context.WarStyle is { } style && NoItems.Contains(style)) throw new ProtocolException("此戰鬥類型禁止使用道具");
        var targets = context.Units.Where(entry => (entry.Actor.Hp ?? 0) > 0 && !entry.Actor.Exited &&
            (entry.Actor.Col > 2) == (actor.Col > 2) && (string.IsNullOrEmpty(targetSlot) || entry.Slot == targetSlot) &&
            entry.Actor.Stats.GetValueOrDefault("max_" + resource) > entry.Actor.Stats.GetValueOrDefault(resource)).Select(entry => entry.Actor).ToList();
        if (targets.Count == 0) throw new ProtocolException("沒有需要回復的存活同方目標");
        var target = targets.OrderBy(value => Ratio(value.Stats.GetValueOrDefault(resource),BigInteger.Max(1,value.Stats.GetValueOrDefault("max_" + resource))))
            .ThenBy(value => value.Col).ThenBy(value => value.Row).First();
        var missing = new BigInteger(Required(target,"max_" + resource)) - target.Stats.GetValueOrDefault(resource);
        var choices = new List<(bool Under,BigInteger Distance,byte Index,ushort Item)>();
        // Source iteration order matters for malformed rows. Ties ultimately use slot ID.
        foreach (var slot in OrderedItems(inventory))
        {
            if (inventory.AlchemySlots?.Contains(slot) == true || index is { } selected && slot != selected) continue;
            var item = inventory.Items[slot];
            if (itemId is > 0 && item.ItemId != itemId.Value) continue;
            var data = context.Catalog.Items.GetValueOrDefault(item.ItemId);
            var effects = CombatResourceKnowledge.HealEffects(item.ItemId,context.Catalog);
            if (!effects.TryGetValue(resource,out var amount) || amount == 0 || BagReceiveReducer.Available(inventory,slot) < 1 ||
                item.OriginalRecord.Locked || item.OriginalRecord.AvailableTime != 0 || item.OriginalRecord.LimitedTime != 0) continue;
            if (!field && (data!.Restrict & 256) != 0) continue;
            if (data!.Attributes.Any(attribute => attribute.Kind is 25 or 26 && attribute.Value is not (0 or 100) && attribute.Value < 100)) continue;
            choices.Add((amount < missing,BigInteger.Abs(amount - missing),slot,item.ItemId));
        }
        if (choices.Count == 0) throw new ProtocolException("包包沒有可用的" + resource.ToUpperInvariant() + "回復食物");
        var choice = choices.OrderBy(value => value.Under).ThenBy(value => value.Distance).ThenBy(value => value.Index).ThenBy(value => value.Item).First();
        return Intent(field ? CombatResourceActionKind.FieldItem : CombatResourceActionKind.BattleItem,actor,target,null,choice.Item,choice.Index,resource,
            [new(choice.Index,1,choice.Item)]);
    });

    private static CombatResourceActionIntent LearnedCore(CombatResourceActionContext context, CombatResourceActor actor,
        uint skillId, string? targetSlot, int targetKind, bool nextSkill)
    {
        Validate(context); ArgumentNullException.ThrowIfNull(actor);
        var records = CombatResourceKnowledge.Learned(context.Player,context.Companions,context.LocalRoleId,actor,context.Catalog);
        if (nextSkill)
            for (var hop = 0; hop < 2; hop++)
            {
                var fields = context.Catalog.Skills.GetValueOrDefault(skillId)?.Fields;
                var next = fields?.GetValueOrDefault("NextSkillId") ?? 0;
                if (next == 0 || (records.FirstOrDefault(value => value.Id == skillId)?.Level ?? 0) < (fields?.GetValueOrDefault("LvLimit",1) ?? 1) ||
                    !records.Any(value => value.Id == next)) break;
                skillId = checked((uint)next);
            }
        var reasons = CombatResourceKnowledge.SkillReasons(context.Player,context.Companions,context.LocalRoleId,actor,skillId,context.Catalog,context.Inventory,context.InventoryContext);
        if (!reasons.IsEmpty) throw new ProtocolException(string.Join("；",reasons));
        var data = context.Catalog.Skills[skillId];
        var targets = new List<CombatResourceActor>();
        foreach (var entry in context.Units)
            if ((string.IsNullOrEmpty(targetSlot) || entry.Slot == targetSlot) && CombatResourceKnowledge.TargetValid(actor,entry.Actor,data) &&
                (data.Required("TargetNPCID") is var npc && (npc == 0 || entry.Actor.Pid == npc))) targets.Add(entry.Actor);
        if (targets.Count == 0) throw new ProtocolException("此技能沒有符合條件的目標");
        var element = targetKind == 2 ? skillId is 10001 or 10002 or 10003 or 10004 ? actor.Element ?? 0 : data.Required("Element") : 0;
        var target = SelectTarget(targets,context.Catalog,element,targetKind);
        ImmutableArray<InventoryAllocation> costs = [];
        if (actor.Pid == context.LocalRoleId && data.Required("CostItemID") is var item && item != 0 && data.Required("CostItemCount") is var count && count != 0)
        {
            var allocation = InventoryPlanning.Allocate(context.Inventory,item,count,context.InventoryContext);
            if (allocation.Error is { } error) throw new ProtocolException(error.Message);
            costs = allocation.Rows;
        }
        return Intent(CombatResourceActionKind.LearnedSkill,actor,target,skillId,null,null,null,costs);
    }

    private static CombatResourceActionIntent Intent(CombatResourceActionKind kind,CombatResourceActor actor,CombatResourceActor target,
        long? skill,ushort? item,byte? index,string? resource,ImmutableArray<InventoryAllocation> allocations) =>
        new(kind,actor.Col,actor.Row,actor.Pid,target.Col,target.Row,skill,item,index,resource,allocations);
    private static List<CombatResourceActor> Enemies(CombatResourceActionContext context,CombatResourceActor actor) =>
        [.. context.Units.Select(entry => entry.Actor).Where(value => (value.Col > 2) != (actor.Col > 2) && (value.Hp ?? 0) > 0 && !value.Exited)];
    private static CombatResourceActor SelectTarget(List<CombatResourceActor> candidates,CombatResourceCatalog catalog,long element,int kind)
    {
        // Avoid negating Int64.MinValue; descending integer comparisons equal Python's
        // unbounded negative-key ordering. LINQ preserves source order for exact ties.
        if (kind == 3) return candidates.OrderByDescending(value => Required(value,"hp")).ThenBy(value => value.Col).ThenBy(value => value.Row).First();
        if (kind == 2) return candidates.OrderByDescending(value => catalog.ElementWeights.GetValueOrDefault(element)?.GetValueOrDefault(value.Element ?? 0,1) ?? 1)
            .ThenBy(value => value.Col).ThenBy(value => value.Row).First();
        return candidates.OrderBy(value => Required(value,"hp")).ThenBy(value => value.Col).ThenBy(value => value.Row).First();
    }
    private static string Slot(CombatResourceActor actor) => actor.Col.ToString(CultureInfo.InvariantCulture) + ":" + actor.Row.ToString(CultureInfo.InvariantCulture);
    private static long Required(CombatResourceActor actor,string key) => actor.Stats.TryGetValue(key,out var value) ? value : throw new SourceKeyException(key);
    private sealed class SourceKeyException(string key) : Exception { internal string Key { get; } = key; }
    private static CombatResourceActionCandidate Capture(Func<CombatResourceActionIntent> create)
    {
        try { return new(create(),null); }
        catch (ProtocolException error) { return new(null,new("ProtocolError",error.Message)); }
        catch (SourceKeyException error) { return new(null,new("KeyError","'" + error.Key + "'")); }
        // Required intentionally retains ArgumentException for the older diagnostic APIs.
        // At this candidate boundary expose the source KeyError without swallowing other
        // invalid typed inputs or letting BestSkill skip malformed catalog data.
        catch (ArgumentException error) when (error.GetType() == typeof(ArgumentException) && error.ParamName is null &&
            error.Message.StartsWith("Missing skill catalog field: ",StringComparison.Ordinal) && error.Message.EndsWith(".",StringComparison.Ordinal))
        { return new(null,new("KeyError","'" + error.Message[29..^1] + "'")); }
    }
    private static void Validate(CombatResourceActionContext context)
    {
        ArgumentNullException.ThrowIfNull(context); ArgumentNullException.ThrowIfNull(context.Inventory);
        ArgumentNullException.ThrowIfNull(context.Catalog); ArgumentNullException.ThrowIfNull(context.Catalog.ElementWeights);
        if (context.Catalog.ElementWeights.Values.Any(row => row is null || row.Values.Any(value => !double.IsFinite(value))))
            throw new ArgumentException("Explicit finite element weight rows are required.",nameof(context));
        if (context.Units.IsDefault || context.Units.Any(entry => entry is null || entry.Actor is null || entry.Slot is null) ||
            context.Units.Select(entry => entry.Slot).Distinct(StringComparer.Ordinal).Count() != context.Units.Length)
            throw new ArgumentException("Initialized ordered battle entries with distinct source keys are required.",nameof(context));
    }
    private static ImmutableArray<byte> OrderedItems(BagReceiveSnapshot bag)
    {
        if (bag.ItemOrder.IsDefault || bag.ItemOrder.Length != bag.Items.Count || bag.ItemOrder.Distinct().Count() != bag.Items.Count || bag.ItemOrder.Any(index => !bag.Items.ContainsKey(index)))
            throw new ArgumentException("Source item order must name every current slot exactly once.",nameof(bag));
        return bag.ItemOrder;
    }
    private static double Ratio(BigInteger numerator,BigInteger denominator)
    {
        // Python true division rounds the exact integer ratio directly to binary64.
        // Casting each Int64 first changes which unit wins near 2^53 and 2^63.
        if (numerator.IsZero) return 0;
        var positive = BigInteger.Abs(numerator);
        var exponent = (int)(positive.GetBitLength() - denominator.GetBitLength());
        if (exponent >= 0 ? positive < denominator << exponent : positive << -exponent < denominator) exponent--;
        var shift = 52 - exponent;
        var n = shift >= 0 ? positive << shift : positive;
        var d = shift >= 0 ? denominator : denominator << -shift;
        var mantissa = BigInteger.DivRem(n,d,out var remainder);
        if (remainder * 2 > d || remainder * 2 == d && !mantissa.IsEven) mantissa++;
        return Math.ScaleB((double)mantissa,exponent - 52) * numerator.Sign;
    }
}
