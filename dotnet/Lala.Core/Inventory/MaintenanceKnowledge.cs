using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Catalogs;
using Lala.Core.Sessions;

namespace Lala.Core.Inventory;

public enum MaintenanceAssessmentOutcome { Evaluated, NoPublication, CatalogsUnavailable, InvalidOptions }
public enum MaintenanceCleanupClassification { Sell, Delete }

/// <summary>Source equipment identity and current damage, not an acquired repair target.</summary>
public sealed record MaintenanceRepairTarget(ushort NpcIndex, int EquipIndex, KnowledgeEquipment Equipment)
{
    public override string ToString() => nameof(MaintenanceRepairTarget);
}
public sealed record MaintenanceStock(ushort ItemId, BigInteger Count);

/// <summary>Historical query joined to exactly one publication. Evaluated only means the
/// bounded source helpers ran. It is not command readiness, a repair plan, or permission.
/// Unknown reviewed item metadata is never inferred from IDs or another publication.</summary>
public sealed class MaintenanceAssessment
{
    internal MaintenanceAssessment(AccountRuntimePublicationSnapshot basis, int threshold,
        ImmutableArray<ushort> repairItems, MaintenanceAssessmentOutcome outcome,
        ImmutableArray<MaintenanceRepairTarget> targets = default,
        ImmutableArray<MaintenanceStock> stock = default, BagItemSnapshot? supply = null)
    {
        Basis = basis; RepairBelow = threshold; RepairItems = repairItems; Outcome = outcome;
        Targets = targets.IsDefault ? [] : targets; RepairStock = stock.IsDefault ? [] : stock;
        RepairSupply = supply;
    }
    public AccountRuntimePublicationSnapshot Basis { get; }
    public int RepairBelow { get; }
    public ImmutableArray<ushort> RepairItems { get; }
    public MaintenanceAssessmentOutcome Outcome { get; }
    public ImmutableArray<MaintenanceRepairTarget> Targets { get; }
    /// <summary>Ready/reliable backpack repair-tool counts, not source selection. Damage
    /// 250 still contributes stock but cannot be selected as RepairSupply.</summary>
    public ImmutableArray<MaintenanceStock> RepairStock { get; }
    /// <summary>First configured repair item and lowest eligible slot, only when a target
    /// exists. No reservation is installed and no wrapper coordination gates are checked.</summary>
    public BagItemSnapshot? RepairSupply { get; }
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
    public override string ToString() => nameof(MaintenanceAssessment);
}

internal static class MaintenanceKnowledge
{
    private static readonly ImmutableHashSet<ushort> Broken =
        [10062, 11098, 12069, 13064, 15051, 14063, 17066, 18062, 19055, 20039, 21120, 22125, 23105, 24090, 25044];

    internal static bool IsRepair(IReadOnlyDictionary<ushort, ItemDataRow> items, ushort id) =>
        items.TryGetValue(id, out var row) && row.ReviewedDetails is { Kind: 25, Special: 130 };

    internal static MaintenanceCleanupClassification? CleanupAction(IReadOnlyDictionary<ushort, ItemDataRow> items, ushort id)
    {
        if (!items.TryGetValue(id, out var row)) return null;
        return (row.Restrict & 16) == 0 ? MaintenanceCleanupClassification.Sell :
            (row.Restrict & 128) == 0 ? MaintenanceCleanupClassification.Delete : null;
    }

    internal static KnowledgeEquipment? Equipment(PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions,
        ushort npc, int index)
    {
        ImmutableArray<KnowledgeEquipment>? equips = npc == 0 ? player.Equipment.Equips :
            companions.Companions.TryGetValue(npc, out var profile) ? Equips(profile) : null;
        return equips is { } rows && index >= 1 && index <= rows.Length ? rows[index - 1] : null;
    }

    private static ImmutableArray<KnowledgeEquipment> Equips(CompanionProfileSnapshot profile) =>
        profile.EquipmentOverrides ?? [.. profile.Data.Equips.Select(KnowledgeEquipment.FromItem)];

    internal static ImmutableArray<MaintenanceRepairTarget> RepairTargets(IReadOnlyDictionary<ushort, ItemDataRow> items,
        PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions, int threshold)
    {
        var result = ImmutableArray.CreateBuilder<MaintenanceRepairTarget>();
        void Add(ushort npc, ImmutableArray<KnowledgeEquipment>? equips)
        {
            if (equips is not { } rows) return;
            for (var i = 0; i < rows.Length; i++)
            {
                var e = rows[i];
                if (e.ItemId == 0 || Broken.Contains(e.ItemId) || e.ItemId == 25746 ||
                    !items.TryGetValue(e.ItemId, out var data) || data.ReviewedDetails is not { Special: 0, FitType: >= 1 and <= 6 }) continue;
                // Python .get flags default false for sparse S11 replacements. Null damage
                // remains unknown and is never replaced with a catalog or old record value.
                if (e.OriginalRecord is { } r && (r.Locked || r.AvailableTime != 0 || r.LimitedTime != 0)) continue;
                if (e.Damage is not (> 0 and < 250) || 250 - e.Damage.Value > threshold) continue;
                result.Add(new(npc, i + 1, e));
            }
        }
        Add(0, player.Equipment.Equips);
        foreach (var index in companions.CompanionOrder)
        {
            var profile = companions.Companions[index];
            if (profile.Data.NpcId == companions.ActiveNpcId && profile.Data.Index is { } npc) Add(npc, Equips(profile));
        }
        return result.ToImmutable();
    }

    internal static ImmutableArray<MaintenanceStock> BackpackStock(IReadOnlyDictionary<ushort, ItemDataRow> items,
        BagReceiveSnapshot bag, bool repair)
    {
        if (!bag.Ready || !bag.Reliable) return [];
        var counts = new Dictionary<ushort, BigInteger>();
        foreach (var index in bag.ItemOrder)
        {
            var item = bag.Items[index];
            if (bag.AlchemySlots?.Contains(index) == true || bag.Reserved.GetValueOrDefault(index) != 0) continue;
            if (item.ItemId == 0 || !items.ContainsKey(item.ItemId) || !FlagsClear(item) || repair && !IsRepair(items, item.ItemId)) continue;
            var count = BagReceiveReducer.Available(bag, index);
            if (count > 0) counts[item.ItemId] = counts.GetValueOrDefault(item.ItemId) + count;
        }
        return [.. counts.Select(pair => new MaintenanceStock(pair.Key, pair.Value))];
    }

    private static bool FlagsClear(BagItemSnapshot item) => !item.OriginalRecord.Locked &&
        item.OriginalRecord.AvailableTime == 0 && item.OriginalRecord.LimitedTime == 0;

    internal static bool SlotAvailable(BagReceiveSnapshot bag, byte index) =>
        bag.Items.TryGetValue(index, out var item) && item.Count > 0 && FlagsClear(item) &&
        BagReceiveReducer.Available(bag, index) == item.Count;

    internal static BagItemSnapshot? SelectRepairSupply(IReadOnlyDictionary<ushort, ItemDataRow> items,
        BagReceiveSnapshot bag, ImmutableArray<ushort> repairItems)
    {
        var stock = BackpackStock(items, bag, repair: true).Select(row => row.ItemId).ToHashSet();
        foreach (var id in repairItems)
        {
            if (!stock.Contains(id)) continue;
            foreach (var pair in bag.Items.OrderBy(pair => pair.Key))
                if (pair.Value.ItemId == id && SlotAvailable(bag, pair.Key) && pair.Value.Damage < 250) return pair.Value;
        }
        return null;
    }

    internal static MaintenanceAssessment Inspect(AccountRuntimePublicationSnapshot basis, int threshold,
        ImmutableArray<ushort> repairItems)
    {
        MaintenanceAssessment Missing(MaintenanceAssessmentOutcome outcome) => new(basis, threshold, repairItems, outcome);
        if (basis.Publication is not { Receive.Phase: AccountReceivePhase.Running } publication)
            return Missing(MaintenanceAssessmentOutcome.NoPublication);
        if (publication.Catalogs is not { } catalogs) return Missing(MaintenanceAssessmentOutcome.CatalogsUnavailable);
        // Source threshold/list-size domain; unlike validate with an empty catalog,
        // runtime inspection requires reviewed metadata for every nonzero repair ID.
        // No configuration is installed.
        if (threshold is < 0 or > 249 || repairItems.IsDefault || repairItems.Length != 2 ||
            repairItems.Any(id => id != 0 && !IsRepair(catalogs.Items, id)))
            return Missing(MaintenanceAssessmentOutcome.InvalidOptions);
        var state = publication.Receive.State;
        var targets = RepairTargets(catalogs.Items, state.PlayerKnowledge, state.Companions, threshold);
        var stock = BackpackStock(catalogs.Items, state.Bag, repair: true);
        var supply = targets.IsEmpty ? null : SelectRepairSupply(catalogs.Items, state.Bag, repairItems);
        return new(basis, threshold, repairItems, MaintenanceAssessmentOutcome.Evaluated, targets, stock, supply);
    }
}
