using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Pure port of room_storage.apply_storage, _add, _delete and
/// confirmed_material_count, with only the consumed/available reservation receive effects.
/// Decode first: decoder errors never enter this reducer. Duplicate/late packets are not
/// deduplicated, initial batches append, and unreliable state stays unreliable until the
/// caller supplies a new domain snapshot. None of these observations authorizes an action.</summary>
public static class RoomStorageReducer
{
    public static StorageReceiveSnapshot Apply(StorageReceiveSnapshot state, ServerEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation is ServerInventoryEvent inventory ? Apply(state, inventory.Event) : state;
    }

    public static StorageReceiveSnapshot Apply(StorageReceiveSnapshot state, InventoryEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (!observation.Type.StartsWith("storage_", StringComparison.Ordinal)) return state;
        var storage = state.Storage;
        var stackable = state.ServerStackable;
        switch (observation)
        {
            case StorageGarageInitialEvent initial:
                var garage = storage.Garage;
                foreach (var item in initial.Items) garage = AddGarage(garage, item);
                storage = storage with { Garage = garage with { Ready = true } };
                break;
            case StorageGarageAddEvent add:
                storage = storage with { Garage = AddGarage(storage.Garage, add.Item) };
                break;
            case StorageGarageDeleteEvent delete:
                storage = storage with { Garage = Delete(storage.Garage, delete.Index, delete.Count) };
                break;
            case StorageMaterialsEvent materials:
                var bucket = storage.Materials;
                stackable ??= ImmutableDictionary<ushort, bool>.Empty;
                foreach (var item in materials.Items)
                {
                    // Python records this before _add, even when the slot is invalid or
                    // conflicts with a different item. It is not catalog/action authority.
                    if (item.ItemId > 0 && item.Count > 0) stackable = stackable.SetItem(item.ItemId, true);
                    bucket = Add(bucket, new(item.Index, item.ItemId, item.Count));
                }
                storage = storage with
                {
                    Materials = materials is StorageMaterialsInitialEvent ? bucket with { Ready = true } : bucket
                };
                break;
            case StorageMaterialsDeleteEvent delete:
                storage = storage with { Materials = Delete(storage.Materials, delete.Index, delete.Count) };
                break;
            case StorageParametersEvent parameters:
                storage = storage with
                {
                    Garage = storage.Garage with { Capacity = parameters.GarageSpace },
                    Materials = storage.Materials with { Capacity = parameters.MaterialSpace },
                    MaterialStackLimit = parameters.MaterialStackLimit,
                    ParametersReady = true
                };
                break;
            case StorageExpandedEvent expanded:
                storage = expanded.Target switch
                {
                    "garage" => storage with { Garage = storage.Garage with { Capacity = expanded.Value } },
                    "materials" => storage with { Materials = storage.Materials with { Capacity = expanded.Value } },
                    "stack" => storage with { MaterialStackLimit = expanded.Value },
                    _ => throw new KeyNotFoundException(expanded.Target)
                };
                break;
            case StorageMoveResultEvent result:
                storage = storage with { LastResult = result.Result };
                break;
            case StorageErrorEvent error:
                storage = storage with { LastError = error.ErrorCode };
                break;
        }
        return state with { Storage = storage with { Revision = storage.Revision + 1 }, ServerStackable = stackable };
    }

    private static StorageBucketSnapshot AddGarage(StorageBucketSnapshot bucket, ItemSave item) =>
        item.Index is not { } index ? bucket with { Reliable = false } :
            Add(bucket, new(index, item.ItemId, item.Count, item));

    private static StorageBucketSnapshot Add(StorageBucketSnapshot bucket, StorageItemSnapshot item)
    {
        if (item.Index == 0 || item.ItemId == 0 || item.Count < 1 || item.Count > 65535)
            return bucket with { Reliable = false };
        var exists = bucket.Items.TryGetValue(item.Index, out var previous);
        if (exists)
        {
            if (previous!.ItemId != item.ItemId) return bucket with { Reliable = false };
            // Serial and other metadata are deliberately not replaced or used as an add
            // rejection criterion: this mirrors the source, not a stronger identity policy.
            item = previous with { Count = previous.Count + item.Count };
        }
        return bucket with
        {
            Items = bucket.Items.SetItem(item.Index, item),
            ItemOrder = exists ? bucket.ItemOrder : bucket.ItemOrder.Add(item.Index)
        };
    }

    private static StorageBucketSnapshot Delete(StorageBucketSnapshot bucket, ushort index, ushort count)
    {
        if (!bucket.Items.TryGetValue(index, out var item) || count < 1 || count > item.Count)
            return bucket with { Reliable = false };
        BigInteger remaining = count;
        var holds = ImmutableArray.CreateBuilder<StorageReservationGroup>(bucket.Holds.Length);
        foreach (var group in bucket.Holds)
        {
            var rows = ImmutableArray.CreateBuilder<StorageReservationSnapshot>(group.Rows.Length);
            foreach (var original in group.Rows)
            {
                var row = original;
                if (row.Index == index)
                {
                    var used = BigInteger.Min(remaining, row.Remaining);
                    row = row with { Remaining = row.Remaining - used };
                    remaining -= used;
                }
                if (group.Owner != "battle" || row.Remaining != 0) rows.Add(row);
            }
            if (group.Owner != "battle" || rows.Count != 0) holds.Add(group with { Rows = rows.ToImmutable() });
        }
        var rest = item.Count - count;
        return bucket with
        {
            Items = rest == 0 ? bucket.Items.Remove(index) : bucket.Items.SetItem(index, item with { Count = rest }),
            ItemOrder = rest == 0 ? bucket.ItemOrder.Remove(index) : bucket.ItemOrder,
            Reserved = bucket.Reserved.SetItem(index, BigInteger.Max(0, bucket.Reserved.GetValueOrDefault(index) - count)),
            Holds = holds.ToImmutable()
        };
    }

    /// <summary>A source-compatible count query, not a transfer plan. Null means the source
    /// cannot confirm a count. Overgrown stacks are retained but not counted as confirmed.</summary>
    public static BigInteger? ConfirmedMaterialCount(RoomStorageSnapshot storage, ushort itemId)
    {
        ArgumentNullException.ThrowIfNull(storage);
        var bucket = storage.Materials;
        if (!string.IsNullOrEmpty(storage.Pending) || storage.Uncertain || !bucket.Ready || !bucket.Reliable) return null;
        BigInteger count = 0;
        foreach (var (index, item) in bucket.Items)
        {
            if (item.ItemId != itemId) continue;
            if (item.Count < 1 || item.Count > 65535) return null;
            count += Available(bucket, index);
        }
        return count;
    }

    public static BigInteger Available(StorageBucketSnapshot bucket, ushort index)
    {
        ArgumentNullException.ThrowIfNull(bucket);
        if (bucket.AlchemySlots?.Contains(index) == true || bucket.ExpeditionSlots?.Contains(index) == true ||
            bucket.MaintenanceSlots?.Contains(index) == true || bucket.Holds.Any(group =>
                group.Rows.Any(row => row.Index == index && (row.Exclusive || row.Uncertain)))) return 0;
        return BigInteger.Max(0, (bucket.Items.GetValueOrDefault(index)?.Count ?? 0) - bucket.Reserved.GetValueOrDefault(index));
    }
}
