using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Catalogs;

namespace Lala.Core.Inventory;

public enum CraftingPreflightBlocker
{
    UnknownRecipe, AmbiguousProduct, ReadOnlyRecipe, ProductClosed, InvalidBatchCount,
    DesignUnlockUnknown, TimeOrLimitUnknown, OwnRoomUnknown, FurnitureOrderUnknown,
    MissingTool, ScheduleNotReady, QueueFull,
    DuplicateProduct, BagNotReadyOrReliable, StoragePendingOrUncertain,
    InvalidSnapshot, MaterialShortage, TooManyBagRows
}

public enum CraftingMaterialSource { Bag, Materials }

public sealed record CraftingMaterialNeed(ushort ItemId, BigInteger Count);

/// <summary>Before is the current balance, not OriginalRecord.Count. Cupboard rows have
/// no serial identity. These are observations, never acquired reservations.</summary>
public sealed record CraftingMaterialAllocation(CraftingMaterialSource Source, ushort Index,
    ushort ItemId, int Count, BigInteger Before, uint? Serial)
{
    public override string ToString() => nameof(CraftingMaterialAllocation);
}

/// <summary>Caller-supplied offline preflight only. Success means the bounded material
/// query succeeded, not that crafting may execute. No queue, pending state, hold or packet
/// is created. Failed results never expose a partial allocation as a usable plan.</summary>
public sealed class CraftingPreflightResult
{
    internal CraftingPreflightResult(CraftingPreflightContext recipes, ushort itemId, int count,
        uint? roleId, CraftingReceiveSnapshot crafting, BagReceiveSnapshot bag, RoomStorageSnapshot storage,
        RuntimeRecipe? recipe, ushort? tool, CraftingPreflightBlocker? blocker,
        ImmutableArray<CraftingMaterialNeed> needs = default,
        ImmutableArray<CraftingMaterialAllocation> allocations = default,
        ushort? missingItemId = null, BigInteger? missingCount = null)
    {
        Recipes = recipes; ItemId = itemId; BatchCount = count; RoleId = roleId;
        Crafting = crafting; Bag = bag; Storage = storage; Recipe = recipe;
        ToolIndex = tool; Blocker = blocker; Needs = needs.IsDefault ? [] : needs;
        Allocations = allocations.IsDefault ? [] : allocations;
        MissingItemId = missingItemId; MissingCount = missingCount;
    }
    public CraftingPreflightContext Recipes { get; }
    public ushort ItemId { get; }
    public int BatchCount { get; }
    public uint? RoleId { get; }
    public CraftingReceiveSnapshot Crafting { get; }
    public BagReceiveSnapshot Bag { get; }
    public RoomStorageSnapshot Storage { get; }
    public RuntimeRecipe? Recipe { get; }
    public ushort? ToolIndex { get; }
    public CraftingPreflightBlocker? Blocker { get; }
    public bool Success => Blocker is null;
    public bool CanSendPackets => false;
    public ImmutableArray<CraftingMaterialNeed> Needs { get; }
    public ImmutableArray<CraftingMaterialAllocation> Allocations { get; }
    public ushort? MissingItemId { get; }
    public BigInteger? MissingCount { get; }
    public override string ToString() => nameof(CraftingPreflightResult);
}

public static class CraftingMaterialPreflight
{
    // Synthetic/imported reservation observations are bounded before calling availability
    // helpers. These limits are an offline resource guard, not server capability claims.
    public const int MaxReservationGroups = 256;
    public const int MaxReservationRows = 65_536;

    public static CraftingPreflightResult Evaluate(CraftingPreflightContext recipes, ushort itemId,
        int batchCount, uint? roleId, CraftingReceiveSnapshot crafting, BagReceiveSnapshot bag,
        RoomStorageSnapshot storage)
    {
        ArgumentNullException.ThrowIfNull(recipes);
        ArgumentNullException.ThrowIfNull(crafting);
        ArgumentNullException.ThrowIfNull(bag);
        ArgumentNullException.ThrowIfNull(storage);
        var selected = recipes.Find(itemId);
        ushort? tool = null;
        CraftingPreflightResult Fail(CraftingPreflightBlocker blocker) =>
            new(recipes, itemId, batchCount, roleId, crafting, bag, storage, selected, tool, blocker);
        if (selected is null) return Fail(recipes.IsAmbiguous(itemId) ? CraftingPreflightBlocker.AmbiguousProduct : CraftingPreflightBlocker.UnknownRecipe);
        var recipe = selected.Recipe;
        if (recipe.ReadOnly == true) return Fail(CraftingPreflightBlocker.ReadOnlyRecipe);
        if (selected.OpenUsed != 0) return Fail(CraftingPreflightBlocker.ProductClosed);
        if (batchCount is < 1 or > 255) return Fail(CraftingPreflightBlocker.InvalidBatchCount);
        if (recipe.DesignId != 0) return Fail(CraftingPreflightBlocker.DesignUnlockUnknown);
        if (recipe.TimeId != 0 || recipe.LimitKind != 0) return Fail(CraftingPreflightBlocker.TimeOrLimitUnknown);

        var room = crafting.Furniture;
        var schedule = crafting.Crafting;
        if (room is null || schedule is null) return Fail(CraftingPreflightBlocker.InvalidSnapshot);
        // Equality follows the helper, including absent owner/role. This observation does
        // not prove account ownership; callers must enforce command-wrapper identity gates.
        if (!room.Ready || room.Owner != roleId) return Fail(CraftingPreflightBlocker.OwnRoomUnknown);
        if (room.Items is null || room.ItemOrder.IsDefault || room.ItemOrder.Length != room.Items.Count ||
            room.ItemOrder.Distinct().Count() != room.ItemOrder.Length ||
            room.ItemOrder.Any(index => !room.Items.TryGetValue(index, out var row) || row is null || row.Index != index))
            return Fail(CraftingPreflightBlocker.FurnitureOrderUnknown);
        var tools = new Dictionary<ushort, ushort>();
        foreach (var index in room.ItemOrder)
        {
            var row = room.Items[index];
            if (row.Status == 0) tools[row.ItemId] = row.Index;
        }
        if (!tools.TryGetValue(recipe.ToolId, out var found)) return Fail(CraftingPreflightBlocker.MissingTool);
        tool = found;
        if (!schedule.Ready) return Fail(CraftingPreflightBlocker.ScheduleNotReady);
        if (schedule.Queue is null || schedule.Queue.Any(pair => pair.Value is null || pair.Key != pair.Value.Index))
            return Fail(CraftingPreflightBlocker.InvalidSnapshot);
        if (schedule.Queue.Count >= (tools.ContainsKey(39050) ? 5 : 3)) return Fail(CraftingPreflightBlocker.QueueFull);
        if (schedule.Queue.Values.Any(row => row.ItemId == itemId) && !tools.ContainsKey(39814))
            return Fail(CraftingPreflightBlocker.DuplicateProduct);
        if (!bag.Ready || !bag.Reliable) return Fail(CraftingPreflightBlocker.BagNotReadyOrReliable);
        if (!string.IsNullOrEmpty(storage.Pending) || storage.Uncertain) return Fail(CraftingPreflightBlocker.StoragePendingOrUncertain);
        var cupboard = storage.Materials;
        if (bag.Items is null || cupboard is null || cupboard.Items is null ||
            bag.Items.Any(pair => pair.Value is null || pair.Value.OriginalRecord is null || pair.Key != pair.Value.Index || pair.Value.Count < 0) ||
            cupboard.Items.Any(pair => pair.Value is null || pair.Key != pair.Value.Index || pair.Value.Count < 0) ||
            !ValidReservations(bag.Reserved, bag.Holds, bag.AlchemySlots, bag.ExpeditionSlots, bag.MaintenanceSlots) ||
            !ValidReservations(cupboard.Reserved, cupboard.Holds, cupboard.AlchemySlots, cupboard.ExpeditionSlots, cupboard.MaintenanceSlots))
            return Fail(CraftingPreflightBlocker.InvalidSnapshot);

        var required = new Dictionary<ushort, BigInteger>();
        var order = new List<ushort>();
        foreach (var material in recipe.Materials)
        {
            if (!required.ContainsKey(material.ItemId)) order.Add(material.ItemId);
            required[material.ItemId] = required.GetValueOrDefault(material.ItemId) + (BigInteger)material.Count * batchCount;
        }
        var needs = order.Select(id => new CraftingMaterialNeed(id, required[id])).ToImmutableArray();
        var allocations = ImmutableArray.CreateBuilder<CraftingMaterialAllocation>();
        var bagRows = bag.Items.OrderBy(pair => pair.Key).ToArray();
        var cupboardRows = cupboard.Items.OrderBy(pair => pair.Key).ToArray();
        // Index lock observations once, rather than rescanning every hold for every slot.
        // The existing reducers still own reserved-counter subtraction/zero clamping.
        var bagLocked = LockedSlots(bag.Holds, bag.AlchemySlots, bag.ExpeditionSlots, bag.MaintenanceSlots);
        var storageLocked = LockedSlots(cupboard.Holds, cupboard.AlchemySlots, cupboard.ExpeditionSlots, cupboard.MaintenanceSlots);
        var bagBalances = bag with { Holds = [], AlchemySlots = null, ExpeditionSlots = null, MaintenanceSlots = null };
        var storageBalances = cupboard with { Holds = [], AlchemySlots = null, ExpeditionSlots = null, MaintenanceSlots = null };
        foreach (var id in order)
        {
            var number = required[id];
            foreach (var (index, item) in bagRows)
            {
                var original = item.OriginalRecord;
                if (item.ItemId != id || original.Locked || original.EnhanceLevel != 0 || original.MagicSpar != 0 || original.BeatLevel != 0) continue;
                var available = bagLocked.Contains(index) ? BigInteger.Zero : BagReceiveReducer.Available(bagBalances, index);
                var use = (int)BigInteger.Min(number, BigInteger.Min(available, 255));
                if (use > 0) { allocations.Add(new(CraftingMaterialSource.Bag, index, id, use, item.Count, original.Serial)); number -= use; }
                if (number.IsZero) break;
            }
            if (number > 0 && cupboard.Ready && cupboard.Reliable)
                foreach (var (index, item) in cupboardRows)
                {
                    if (item.ItemId != id) continue;
                    var available = storageLocked.Contains(index) ? BigInteger.Zero : RoomStorageReducer.Available(storageBalances, index);
                    var use = (int)BigInteger.Min(number, BigInteger.Min(available, 65_535));
                    if (use > 0) { allocations.Add(new(CraftingMaterialSource.Materials, index, id, use, item.Count, null)); number -= use; }
                    if (number.IsZero) break;
                }
            if (number > 0) return new(recipes, itemId, batchCount, roleId, crafting, bag, storage, selected, tool,
                CraftingPreflightBlocker.MaterialShortage, needs, missingItemId: id, missingCount: number);
        }
        if (allocations.Count(row => row.Source == CraftingMaterialSource.Bag) > 255) return Fail(CraftingPreflightBlocker.TooManyBagRows);
        return new(recipes, itemId, batchCount, roleId, crafting, bag, storage, selected, tool, null, needs, allocations.ToImmutable());
    }

    private static bool ValidReservations(ImmutableDictionary<ushort, BigInteger> reserved,
        ImmutableArray<StorageReservationGroup> holds, params ImmutableArray<ushort>?[] projections)
    {
        if (reserved is null || holds.IsDefault || holds.Length > MaxReservationGroups ||
            projections.Any(slots => slots is { } values && (values.IsDefault || values.Length > 65_536))) return false;
        var count = 0;
        foreach (var group in holds)
        {
            if (group is null || group.Rows.IsDefault || group.Rows.Length > MaxReservationRows - count) return false;
            count += group.Rows.Length;
            if (group.Rows.Any(row => row is null)) return false;
        }
        return true;
    }

    private static HashSet<ushort> LockedSlots(ImmutableArray<StorageReservationGroup> holds,
        params ImmutableArray<ushort>?[] projections)
    {
        var slots = new HashSet<ushort>();
        foreach (var projection in projections) if (projection is { } values) slots.UnionWith(values);
        foreach (var group in holds)
            foreach (var row in group.Rows)
                if (row.Exclusive || row.Uncertain) slots.Add(row.Index);
        return slots;
    }
}
