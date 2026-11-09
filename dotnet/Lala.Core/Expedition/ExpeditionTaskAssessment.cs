using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Sessions;

namespace Lala.Core.Expedition;

public enum ExpeditionAssessmentIssue
{
    InvalidSelection, NoPublication, CatalogsUnavailable, TaskUnavailable,
    ExpeditionLevelUnknown, LevelDefinitionMissing, OutpostUnknown, SelectedRoleMissing,
    UnsupportedRoleValues, BagUnknown, BagCapacityUnknown, InvalidBagData,
    RewardItemDetailsUnknown, UnsupportedRewardKind, RecoveryItemDetailsUnknown, InvalidCatalogData
}

/// <summary>Observed faith and deficit to this task's FaithCost, not a preference or restoration
/// plan. A null deficit is unknown/unsupported; signed observed faith is retained unchanged.
/// State is the observed role state, not a claim of availability for dispatch.</summary>
public sealed record ExpeditionRoleFaith(byte Index, ushort? NpcId, byte? State, int? Faith, long? Deficit);
public sealed record ExpeditionRecoveryItem(ushort ItemId, long FaithGain, BigInteger AvailableCount);

/// <summary>Historical calculation from one exact AccountRuntime publication token. Retention
/// does not preserve current resource binding. Nullable measurements are unknown, never zero.
/// RecoveryStockComplete distinguishes known empty stock from incomplete evidence; partial stock
/// does not prove restoration feasibility. Success.Complete describes only the success formula.
/// No readiness, reservation, dispatch, claim, restoration or command authority is established.</summary>
public sealed class ExpeditionTaskAssessment
{
    internal ExpeditionTaskAssessment(AccountRuntimePublicationSnapshot basis, ushort taskId,
        ImmutableArray<byte> selectedRoleIndices, int? durationSeconds, long? rewardEmptySlots,
        int? observedFreeSlots, bool? conditionMet, ExpeditionSuccess? success,
        ImmutableArray<ExpeditionRoleFaith> roleFaith, ImmutableArray<ExpeditionRecoveryItem> recoveryStock,
        bool recoveryStockComplete, ImmutableArray<ushort> unknownRecoveryItemIds,
        ImmutableArray<ExpeditionAssessmentIssue> issues)
        => (Basis, TaskId, SelectedRoleIndices, DurationSeconds, RewardEmptySlots, ObservedFreeSlots,
            ConditionMet, Success, RoleFaith, RecoveryStock, RecoveryStockComplete, UnknownRecoveryItemIds, Issues) =
            (basis, taskId, selectedRoleIndices, durationSeconds, rewardEmptySlots, observedFreeSlots,
                conditionMet, success, roleFaith, recoveryStock, recoveryStockComplete, unknownRecoveryItemIds, issues);
    public AccountRuntimePublicationSnapshot Basis { get; }
    public ushort TaskId { get; }
    public ImmutableArray<byte> SelectedRoleIndices { get; }
    public int? DurationSeconds { get; }
    /// <summary>Empty slots for every possible ordinary and special item reward. Existing
    /// stacks, duplicate rewards and special probability never reduce this requirement.</summary>
    public long? RewardEmptySlots { get; }
    public int? ObservedFreeSlots { get; }
    public bool? ConditionMet { get; }
    public ExpeditionSuccess? Success { get; }
    public ImmutableArray<ExpeditionRoleFaith> RoleFaith { get; }
    public ImmutableArray<ExpeditionRecoveryItem> RecoveryStock { get; }
    public bool RecoveryStockComplete { get; }
    public ImmutableArray<ushort> UnknownRecoveryItemIds { get; }
    public ImmutableArray<ExpeditionAssessmentIssue> Issues { get; }
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
    public override string ToString() => nameof(ExpeditionTaskAssessment);
}

internal static class ExpeditionTaskInspection
{
    internal static ExpeditionTaskAssessment Inspect(AccountRuntimePublicationSnapshot basis,
        ushort taskId, ImmutableArray<byte> selection)
    {
        var issues = new List<ExpeditionAssessmentIssue>();
        int? duration = null, free = null; long? need = null; bool? condition = null;
        ExpeditionSuccess? success = null;
        ImmutableArray<ExpeditionRoleFaith> faith = [];
        ImmutableArray<ExpeditionRecoveryItem> stock = [];
        ImmutableArray<ushort> unknownStock = [];
        bool stockComplete = false;
        ExpeditionTaskAssessment Result() => new(basis, taskId, selection.IsDefault ? [] : selection,
            duration, need, free, condition, success, faith, stock, stockComplete, unknownStock,
            [.. issues.Distinct()]);
        // No arbitrary enumerable, callback or search. Reject large requests before visiting slots.
        if (taskId == 0 || selection.IsDefaultOrEmpty || selection.Length > 4 ||
            selection.Contains((byte)0) || selection.Distinct().Count() != selection.Length)
        { issues.Add(ExpeditionAssessmentIssue.InvalidSelection); return Result(); }
        if (basis.Publication is not { Receive.Phase: AccountReceivePhase.Running } publication)
        { issues.Add(ExpeditionAssessmentIssue.NoPublication); return Result(); }
        var state = publication.Receive.State;
        free = FreeSlots(state.Bag, issues);
        if (publication.Catalogs is not { } catalogs)
        { issues.Add(ExpeditionAssessmentIssue.CatalogsUnavailable); return Result(); }
        (stock, stockComplete, unknownStock) = RecoveryStock(state.Bag, catalogs.Items, issues);
        if (!catalogs.Expedition.Tasks.TryGetValue(taskId, out var task))
        { issues.Add(ExpeditionAssessmentIssue.TaskUnavailable); return Result(); }
        if (task is null || task.Id != taskId || !ValidTask(task))
        { issues.Add(ExpeditionAssessmentIssue.InvalidCatalogData); return Result(); }
        need = RewardSlots(task, catalogs.Items, issues);
        if (state.Expedition.Level is not byte level)
            issues.Add(ExpeditionAssessmentIssue.ExpeditionLevelUnknown);
        else if (!catalogs.Expedition.Levels.TryGetValue(level, out var definition))
            issues.Add(ExpeditionAssessmentIssue.LevelDefinitionMissing);
        else if (definition.Reduction > 1000)
            issues.Add(ExpeditionAssessmentIssue.InvalidCatalogData);
        else duration = DurationSeconds(task.Minutes, definition.Reduction);
        if (!state.Expedition.OutpostReady)
        { issues.Add(ExpeditionAssessmentIssue.OutpostUnknown); return Result(); }
        var roleFaith = ImmutableArray.CreateBuilder<ExpeditionRoleFaith>(selection.Length);
        var roles = new List<ExpeditionRole>(selection.Length);
        var npcs = new Dictionary<int, ExpeditionNpc>();
        foreach (byte index in selection)
        {
            if (!state.Expedition.Roles.TryGetValue(index, out var role))
            {
                issues.Add(ExpeditionAssessmentIssue.SelectedRoleMissing);
                roleFaith.Add(new(index, null, null, null, null)); continue;
            }
            var stats = role.Stats;
            roleFaith.Add(new(index, role.NpcId, role.State, role.Faith,
                role.Faith < 0 ? null : Math.Max(0L, (long)task.FaithCost - role.Faith)));
            if (role.Faith < 0 || stats.Level < 0 || stats.Str < 0 || stats.Con < 0 ||
                stats.Int < 0 || stats.Wis < 0 || stats.Agi < 0)
            { issues.Add(ExpeditionAssessmentIssue.UnsupportedRoleValues); continue; }
            roles.Add(new(index, role.NpcId, role.Faith, stats.Level, stats.Degree, stats.Potential,
                stats.Str, stats.Con, stats.Int, stats.Wis, stats.Agi));
            if (catalogs.Npcs.TryGetValue(role.NpcId, out var npc))
                npcs[role.NpcId] = new(npc.Element, npc.Kind, npc.Original);
        }
        faith = roleFaith.MoveToImmutable();
        if (roles.Count == selection.Length)
        {
            condition = ExpeditionTeams.ConditionMet(Condition(task.Condition), roles, npcs);
            success = ExpeditionTeams.SuccessDetails(task.SuccessRate, task.Recommendations.Select(
                r => new ExpeditionRecommendation(Condition(r.Condition), r.Bonus)), roles, npcs);
        }
        return Result();
    }

    private static ExpeditionCondition Condition(ImmutableArray<ushort> values) => new(values[0], values[1], values[2]);
    private static bool ValidTask(ExpeditionTaskData task) => task.Id != 0 && task.Minutes > 0 && task.FaithCost <= 100 &&
        !task.Condition.IsDefault && task.Condition.Length == 3 && !task.Recommendations.IsDefault &&
        task.Recommendations.Length <= 4 && task.Recommendations.All(r => r is not null &&
            !r.Condition.IsDefault && r.Condition.Length == 3) && !task.Rewards.IsDefault &&
        task.Rewards.Length <= 3 && task.Rewards.All(r => r is not null) && task.SpecialReward is not null;

    internal static int DurationSeconds(ushort minutes, ushort reduction) =>
        checked((int)(((long)minutes * (1000 - reduction) + 500) / 1000) * 60);

    internal static long? RewardSlots(ExpeditionTaskData task, IReadOnlyDictionary<ushort, ItemDataRow> items,
        List<ExpeditionAssessmentIssue> issues)
    {
        long need = 0;
        foreach (var reward in task.Rewards.Append(task.SpecialReward))
        {
            if (reward.Kind is 10 or 11)
            {
                if (reward.Id > ushort.MaxValue || !items.TryGetValue((ushort)reward.Id, out var item) || item.ReviewedDetails is null)
                { issues.Add(ExpeditionAssessmentIssue.RewardItemDetailsUnknown); return null; }
                need += reward.Kind == 10 && item.ReviewedDetails.Stackable ? ((long)reward.Value + 199) / 200 : reward.Value;
            }
            else if (reward.Kind is not (0 or 1 or 2 or 6 or 12 or 21 or 22 or 23 or 24 or 25 or 26 or 27 or 28 or 29 or 30 or 31))
            { issues.Add(ExpeditionAssessmentIssue.UnsupportedRewardKind); return null; }
        }
        return need;
    }

    internal static long? FaithGain(ItemDataRow? item)
    {
        if (item?.ReviewedDetails is not { } details) return null;
        if (details.Special != 0) return 0;
        long gain = 0;
        foreach (var attribute in details.Attributes)
            if (attribute.Kind == 64) gain = (long)attribute.Value - 100;
        return Math.Max(0, gain);
    }

    internal static int? FreeSlots(BagReceiveSnapshot bag, List<ExpeditionAssessmentIssue> issues)
    {
        if (!bag.Ready || !bag.Reliable) { issues.Add(ExpeditionAssessmentIssue.BagUnknown); return null; }
        if (bag.Capacity is not > 0) { issues.Add(ExpeditionAssessmentIssue.BagCapacityUnknown); return null; }
        int free = 0;
        for (int i = 1; i <= bag.Capacity; i++) if (!bag.Items.ContainsKey((byte)i)) free++;
        return free;
    }

    private static bool ValidSlots(ImmutableArray<ushort>? slots) =>
        slots is null || !slots.Value.IsDefault && slots.Value.Length <= 256;

    internal static (ImmutableArray<ExpeditionRecoveryItem> Stock, bool Complete, ImmutableArray<ushort> Unknown)
        RecoveryStock(BagReceiveSnapshot bag, IReadOnlyDictionary<ushort, ItemDataRow> items,
            List<ExpeditionAssessmentIssue> issues)
    {
        if (!bag.Ready || !bag.Reliable)
        { issues.Add(ExpeditionAssessmentIssue.BagUnknown); return ([], false, []); }
        // Defensive imported-input limits, not additional Python parity. Bound collections
        // before Available scans their lock metadata. The item map has byte keys already.
        if (bag.Holds.IsDefault || bag.Holds.Length > 256 || bag.Holds.Any(group => group is null ||
                group.Rows.IsDefault || group.Rows.Length > 256 || group.Rows.Any(row => row is null)) ||
            !ValidSlots(bag.AlchemySlots) || !ValidSlots(bag.ExpeditionSlots) || !ValidSlots(bag.MaintenanceSlots))
        { issues.Add(ExpeditionAssessmentIssue.InvalidBagData); return ([], false, []); }
        var stock = new Dictionary<ushort, ExpeditionRecoveryItem>();
        var unknown = new HashSet<ushort>(); bool complete = true;
        foreach (var (index, item) in bag.Items)
        {
            var record = item.OriginalRecord;
            if (record.Locked || record.LimitedTime != 0 || record.AvailableTime != 0) continue;
            if (item.Count < 0 || bag.Reserved.GetValueOrDefault(index) < 0)
            { issues.Add(ExpeditionAssessmentIssue.InvalidBagData); complete = false; continue; }
            var amount = BagReceiveReducer.Available(bag, index);
            if (amount == 0) continue;
            long? gain = FaithGain(items.GetValueOrDefault(item.ItemId));
            if (gain is null) { unknown.Add(item.ItemId); complete = false; continue; }
            if (gain == 0) continue;
            stock.TryGetValue(item.ItemId, out var prior);
            stock[item.ItemId] = new(item.ItemId, gain.Value, (prior?.AvailableCount ?? 0) + amount);
        }
        if (unknown.Count != 0) issues.Add(ExpeditionAssessmentIssue.RecoveryItemDetailsUnknown);
        return ([.. stock.Values.OrderBy(row => row.ItemId)], complete, [.. unknown.Order()]);
    }
}
