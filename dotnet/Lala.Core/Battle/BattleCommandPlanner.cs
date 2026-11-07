using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Inventory;

namespace Lala.Core.Battle;

/// <summary>Explicit offline capture observations, never catalog or send authority.</summary>
public sealed record BattleCaptureCatalog
{
    public ImmutableDictionary<uint, bool> CatchableNpcs { get; init; } = ImmutableDictionary<uint, bool>.Empty;
    public ImmutableDictionary<ushort, long> NetBonuses { get; init; } = ImmutableDictionary<ushort, long>.Empty;
}

public sealed record BattleCommandContext
{
    public CombatResourceActionContext Resources { get; init; } = new();
    public NormalAttackCatalogSnapshot NormalCatalog { get; init; } = new([],[]);
    public BattleCaptureCatalog CaptureCatalog { get; init; } = new();
    public bool Active { get; init; }
    public long Round { get; init; }
    /// <summary>Source battle.commands keys, not coordinates inferred from its values.</summary>
    public ImmutableArray<string> CommandedSlots { get; init; } = [];
}

public readonly record struct BattleUnitIdentity(uint Pid, uint MasterId);
public enum BattleCommandKind { Normal, Defend, Escape, Catch, LearnedSkill, BattleItem }
/// <summary>Offline intent. Allocations are hypothetical costs, never installed holds.</summary>
public sealed record BattleCommandIntent(BattleCommandKind Kind, int Col, int Row, uint ActorPid,
    int TargetCol, int TargetRow, long? SkillId, ushort? ItemId, byte? BagIndex, string? Resource,
    ImmutableArray<InventoryAllocation> Allocations);
public sealed record BattleCommandCandidate(BattleCommandIntent? Intent, InventoryPlanningError? Error)
{
    public bool Success => Error is null;
}
public sealed record BattleRoundPlan(ImmutableArray<BattleCommandIntent> Intents, InventoryPlanningError? Error)
{
    public bool Success => Error is null;
}

/// <summary>Pure battle_commands.py selection. No session, scheduler, transport, packet,
/// catalog activation, state reducer or reservation acquisition is involved.</summary>
public static class BattleCommandPlanner
{
    public static string Slot(CombatResourceActor unit)
    {
        ArgumentNullException.ThrowIfNull(unit);
        return unit.Col.ToString(CultureInfo.InvariantCulture) + ":" + unit.Row.ToString(CultureInfo.InvariantCulture);
    }

    /// <summary>Missing master evidence uses the source default zero. Actor identity must
    /// be known; explicit Python null versus an absent master key is not a typed distinction.</summary>
    public static BattleUnitIdentity Identity(CombatResourceActor unit)
    {
        ArgumentNullException.ThrowIfNull(unit);
        return new(RequirePid(unit),unit.MasterId ?? 0);
    }

    public static ImmutableArray<CombatResourceActor> OwnedUnits(CombatResourceActionContext context, bool living = true)
    {
        ValidateUnits(context);
        if (context.LocalRoleId is not { } pid) return [];
        var owned = context.Units.Select(entry => entry.Actor)
            .Where(unit => (unit.Pid == pid || unit.MasterId == pid) && (!living || (unit.Hp ?? 0) > 0 && !unit.Exited)).ToArray();
        // Python evaluates every sort key even for a one-element sequence. LINQ may
        // skip sorting such a sequence, so identity validation cannot live in its key.
        foreach (var unit in owned) RequirePid(unit);
        return [.. owned.OrderBy(unit => unit.Pid != pid).ThenBy(unit => unit.Col).ThenBy(unit => unit.Row)];
    }

    public static bool CatchAllowed(BattleCommandContext context, CombatResourceActor actor, CombatResourceActor target)
    {
        ArgumentNullException.ThrowIfNull(context); ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(target);
        ArgumentNullException.ThrowIfNull(context.CaptureCatalog); ArgumentNullException.ThrowIfNull(context.CaptureCatalog.CatchableNpcs);
        ArgumentNullException.ThrowIfNull(context.CaptureCatalog.NetBonuses);
        var targetPid = RequirePid(target);
        if (!context.CaptureCatalog.CatchableNpcs.GetValueOrDefault(targetPid)) return false;
        var owned = OwnedUnits(context.Resources,false);
        if (owned.Any(unit => unit.Pid == targetPid)) return false;
        var pid = context.Resources.LocalRoleId ?? throw new ArgumentException("Capture requires an explicit local role identity.",nameof(context));
        var master = owned.FirstOrDefault(unit => unit.Pid == pid);
        var levelUnit = actor.MasterId == pid ? master : actor;
        if (levelUnit is null || !levelUnit.Stats.TryGetValue("level",out var level) || !target.Stats.TryGetValue("level",out var targetLevel)) return false;
        if (actor.Equips.IsDefault) throw new ArgumentException("An initialized equipment array is required.",nameof(actor));
        if (actor.Equips.Length < 6) return false;
        var special = actor.Equips[5] ?? throw new ArgumentException("Null equipment record.",nameof(actor));
        var bonus = context.CaptureCatalog.NetBonuses.GetValueOrDefault(special.ItemId);
        return targetLevel <= new BigInteger(levelUnit.Stats.GetValueOrDefault("degree")) * 100 + level + bonus + 5;
    }

    public static BattleCommandCandidate Action(BattleCommandContext context, CombatResourceActor actor,
        string mode, string? targetSlot = null)
    {
        // Unknown modes precede all source resource/target gates.
        if (mode is not ("auto_skill" or "heal_hp" or "heal_sp" or "normal" or "defend" or "escape" or "catch"))
            return Failure("未知戰鬥行動");
        ArgumentNullException.ThrowIfNull(context); ArgumentNullException.ThrowIfNull(actor);
        if (mode == "auto_skill") return Adapt(CombatResourceActionCandidates.BestSkill(context.Resources,actor,context.NormalCatalog,targetSlot));
        // Source healing action modes ignore the caller's target_slot.
        if (mode is "heal_hp" or "heal_sp") return Adapt(CombatResourceActionCandidates.Food(context.Resources,actor,mode == "heal_hp" ? "hp" : "sp"));
        if (mode == "normal") return Adapt(CombatResourceActionCandidates.Normal(context.Resources,actor,context.NormalCatalog,targetSlot));
        var pid = RequirePid(actor);
        if (mode is "defend" or "escape") return new(new(mode == "defend" ? BattleCommandKind.Defend : BattleCommandKind.Escape,
            actor.Col,actor.Row,pid,0,0,mode == "defend" ? 60021 : 60041,null,null,null,[]),null);
        ValidateUnits(context.Resources);
        // Source evaluates capture permission before filtering the requested slot.
        var targets = context.Resources.Units.Select(entry => entry.Actor)
            .Where(unit => (unit.Col > 2) != (actor.Col > 2) && (unit.Hp ?? 0) > 0 && !unit.Exited)
            .Where(unit => CatchAllowed(context,actor,unit))
            .Where(unit => string.IsNullOrEmpty(targetSlot) || Slot(unit) == targetSlot)
            .OrderBy(unit => unit.Hp!.Value).ThenBy(unit => unit.Col).ThenBy(unit => unit.Row).ToList();
        if (targets.Count == 0) return Failure("沒有符合條件的捕捉目標");
        var target = targets[0];
        return new(new(BattleCommandKind.Catch,actor.Col,actor.Row,pid,target.Col,target.Row,10008,null,null,null,[]),null);
    }

    public static BattleRoundPlan PlanRound(BattleCommandContext context,
        IReadOnlyDictionary<string,string>? modes = null, string? targetSlot = null, IEnumerable<string>? excluded = null)
    {
        ArgumentNullException.ThrowIfNull(context);
        if (!context.Active || context.Round <= 0) return new([],new("ProtocolError","等待伺服器開啟戰鬥回合"));
        if (context.CommandedSlots.IsDefault || context.CommandedSlots.Any(slot => slot is null))
            throw new ArgumentException("Initialized command slot keys are required.",nameof(context));
        var skip = context.CommandedSlots.ToHashSet(StringComparer.Ordinal);
        if (excluded is not null) skip.UnionWith(excluded);
        var resources = context.Resources;
        var proposals = ImmutableArray.CreateBuilder<BattleCommandIntent>();
        foreach (var actor in OwnedUnits(resources))
        {
            var slot = Slot(actor);
            if (skip.Contains(slot)) continue;
            var mode = modes is not null && modes.TryGetValue(slot,out var choice) ? choice : "normal";
            var result = Action(context with { Resources = resources },actor,mode,targetSlot);
            if (result.Error is { } error)
                return new([],error.Type == "ProtocolError" ? error with { Message = (actor.Name ?? slot) + "：" + error.Message } : error);
            var intent = result.Intent!;
            // This copied snapshot exists only during the proposal. No holds are installed,
            // and a failed round returns no partial intents or hypothetical inventory.
            var reserved = resources.Inventory.Reserved;
            foreach (var cost in intent.Allocations)
                reserved = reserved.SetItem(cost.Index,reserved.GetValueOrDefault(cost.Index) + cost.Count);
            resources = resources with { Inventory = resources.Inventory with { Reserved = reserved } };
            proposals.Add(intent);
        }
        return proposals.Count == 0 ? new([],new("ProtocolError","本回合可操作單位皆已送出，或沒有存活的本機角色／夥伴")) : new(proposals.ToImmutable(),null);
    }

    private static BattleCommandCandidate Adapt(CombatResourceActionCandidate candidate)
    {
        if (candidate.Error is { } error) return new(null,error);
        var value = candidate.Intent!;
        // General resource helpers retain nullable imported identities. A battle intent
        // must name its actor, but preceding source candidate errors still win.
        var pid = value.ActorPid ?? throw new ArgumentException("A battle intent requires an explicit actor identity.",nameof(candidate));
        var kind = value.Kind switch { CombatResourceActionKind.NormalAttack => BattleCommandKind.Normal,
            CombatResourceActionKind.LearnedSkill => BattleCommandKind.LearnedSkill,
            CombatResourceActionKind.BattleItem => BattleCommandKind.BattleItem,
            _ => throw new ArgumentException("Field items are not battle actions.",nameof(candidate)) };
        return new(new(kind,value.Col,value.Row,pid,value.TargetCol,value.TargetRow,value.SkillId,value.ItemId,value.BagIndex,value.Resource,value.Allocations),null);
    }
    private static BattleCommandCandidate Failure(string message) => new(null,new("ProtocolError",message));
    private static uint RequirePid(CombatResourceActor unit) => unit.Pid ?? throw new ArgumentException("An explicit actor identity is required.",nameof(unit));
    private static void ValidateUnits(CombatResourceActionContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        if (context.Units.IsDefault || context.Units.Any(entry => entry is null || entry.Actor is null || entry.Slot is null || entry.Actor.Stats is null) ||
            context.Units.Select(entry => entry.Slot).Distinct(StringComparer.Ordinal).Count() != context.Units.Length)
            throw new ArgumentException("Initialized ordered battle entries with distinct source keys and actor stats are required.",nameof(context));
    }
}
