using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Inventory;

/// <summary>Pure inventory.apply_inventory, inventory_updates.add_item and receive-only
/// reservations.refreshed/consumed/available parity. Decode before applying. No sending,
/// spending, acquiring holds, equipment commands or session/lifecycle integration.
/// Duplicate and late observations intentionally apply again, as in retained Python.</summary>
public static class BagReceiveReducer
{
    public static BagReceiveSnapshot Apply(BagReceiveSnapshot state, ServerEvent observation,
        ImmutableDictionary<ushort, bool>? stackRules = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation is ServerLiveDataEvent live ? Apply(state, live.Event, stackRules) : state;
    }

    /// <param name="stackRules">Explicit offline catalog projection. Missing means unknown,
    /// not a guessed default; source session stackability observations take precedence.</param>
    public static BagReceiveSnapshot Apply(BagReceiveSnapshot state, LiveDataEvent observation,
        ImmutableDictionary<ushort, bool>? stackRules = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation switch
        {
            BagSnapshotEvent snapshot => Refresh(state, snapshot),
            BagAddEvent add => Add(state, add.Item, stackRules) with { Revision = state.Revision + 1 },
            BagDeleteEvent delete => Delete(state, delete.Index, delete.Count),
            BagSellEvent sell => Delete(state, sell.Index, sell.Count),
            BagBrokenEvent broken => Delete(state, broken.Index, 1),
            BagDamageEvent damage when state.Items.TryGetValue(damage.Index, out var item) => state with
            {
                Items = state.Items.SetItem(damage.Index, item with { Damage = damage.Damage }), Revision = state.Revision + 1
            },
            ItemUseResultEvent result => state with
            {
                LastUseResult = result.Result, UseFailed = state.UseFailed || result.Result is 3 or 4
            },
            _ => state
        };
    }

    private static BagReceiveSnapshot Fail(BagReceiveSnapshot state, string error) => state with { Reliable = false, SyncError = error };
    private static BagItemSnapshot Item(ItemSave item, byte index, int count) => new(item, index, count, item.Damage);

    private static BagReceiveSnapshot Refresh(BagReceiveSnapshot old, BagSnapshotEvent snapshot)
    {
        var fresh = new BagReceiveSnapshot
        {
            Ready = true, Reliable = true, Capacity = snapshot.Capacity, Revision = old.Revision + 1,
            FieldSupply = old.FieldSupply ?? StateValue.Map(), ServerStackable = old.ServerStackable,
            AlchemySlots = old.AlchemySlots ?? [], ExpeditionSlots = old.ExpeditionSlots ?? [],
            MaintenanceSlots = old.MaintenanceSlots ?? [], Holds = old.Holds
        };
        if (snapshot.Capacity == 0) fresh = Fail(fresh, "伺服器背包容量無效");
        foreach (var item in snapshot.Items)
        {
            if (!fresh.Reliable) break;
            if (item.Index is not { } index || index < 1 || index > snapshot.Capacity || item.ItemId == 0 ||
                item.Count == 0 || fresh.Items.ContainsKey(index))
            {
                fresh = Fail(fresh, "伺服器背包格位或數量資料不一致"); break;
            }
            fresh = fresh with { Items = fresh.Items.Add(index, Item(item, index, item.Count)), ItemOrder = fresh.ItemOrder.Add(index) };
        }
        if (!fresh.Reliable) fresh = fresh with { Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty, ItemOrder = [] };
        var holds = ImmutableArray.CreateBuilder<StorageReservationGroup>();
        foreach (var group in fresh.Holds)
        {
            var rows = ImmutableArray.CreateBuilder<StorageReservationSnapshot>();
            foreach (var original in group.Rows)
            {
                var row = original;
                var item = row.Index <= byte.MaxValue ? fresh.Items.GetValueOrDefault((byte)row.Index) : null;
                var expected = row.Before - row.Count;
                if (item is null)
                {
                    if (expected > 0)
                    {
                        row = row with { Uncertain = true };
                        fresh = Fail(fresh, "保留物品格位遺失，請重新登入同步");
                    }
                    row = row with { Remaining = 0 };
                }
                else if (row.Identity != new StorageReservationIdentity(item.ItemId, item.OriginalRecord.Serial, item.OriginalRecord.SerialVersion))
                {
                    row = row with { Uncertain = true };
                    fresh = Fail(fresh, "保留物品序號已變更，請重新登入同步");
                }
                else row = row with { Remaining = BigInteger.Min(row.Remaining, BigInteger.Max(0, item.Count - expected)) };
                if (row.Uncertain) fresh = Fail(fresh, fresh.SyncError ?? "先前背包操作未確認，請重新登入同步");
                fresh = fresh with { Reserved = fresh.Reserved.SetItem(row.Index, fresh.Reserved.GetValueOrDefault(row.Index) + row.Remaining) };
                rows.Add(row);
            }
            var slots = rows.Select(row => row.Index).Distinct().ToImmutableArray();
            fresh = group.Owner switch
            {
                "alchemy" => fresh with { AlchemySlots = slots },
                "expedition" => fresh with { ExpeditionSlots = slots },
                "maintenance" => fresh with { MaintenanceSlots = slots },
                _ => fresh
            };
            holds.Add(group with { Rows = group.Owner == "battle" ? [.. rows.Where(row => row.Remaining != 0 || row.Uncertain)] : rows.ToImmutable() });
        }
        return fresh with { Holds = holds.ToImmutable() };
    }

    private static BagReceiveSnapshot Add(BagReceiveSnapshot state, ItemSave value, ImmutableDictionary<ushort, bool>? rules)
    {
        if (value.ItemId == 0 || value.Index is not { } preferred || value.Count == 0)
            return Fail(state, "新增物品欄位不完整");
        var items = state.Items;
        var order = state.ItemOrder;
        int count = value.Count;
        var capacity = state.Capacity ?? 255;
        bool? stackable = state.ServerStackable?.TryGetValue(value.ItemId, out var observed) == true ? observed :
            rules?.TryGetValue(value.ItemId, out var reviewed) == true ? reviewed : null;
        if (stackable is null)
        {
            if (preferred >= 1 && preferred <= capacity && !items.ContainsKey(preferred) && count == 1)
                return state with { Items = items.Add(preferred, Item(value, preferred, 1)), ItemOrder = order.Add(preferred) };
            return Fail(state, "新版物品沒有經驗證的堆疊規則，等待背包重新同步");
        }
        byte? Empty()
        {
            // Known-rule path deliberately accepts a free preferred slot beyond capacity,
            // matching source behavior. The unknown-rule path above does not.
            if (preferred != 0 && !items.ContainsKey(preferred)) return preferred;
            for (var i = 1; i <= capacity; i++) if (!items.ContainsKey((byte)i)) return (byte)i;
            return null;
        }
        if (stackable.Value)
        {
            var target = preferred != 0 ? items.GetValueOrDefault(preferred) :
                order.Select(index => items[index]).FirstOrDefault(item => item.ItemId == value.ItemId && item.Count < 200);
            if (target is not null)
            {
                if (target.ItemId != value.ItemId) return Fail(state, "堆疊物品格位不符");
                var amount = Math.Min(count, 200 - target.Count);
                items = items.SetItem(target.Index, target with { Count = target.Count + amount }); count -= amount;
            }
            while (count != 0)
            {
                if (Empty() is not { } index) return Fail(state, "新增堆疊物品時包包格位不足");
                var amount = Math.Min(count, 200);
                items = items.Add(index, Item(value, index, amount)); order = order.Add(index); count -= amount;
            }
        }
        else
        {
            for (var i = 0; i < count; i++)
            {
                if (Empty() is not { } index) return Fail(state, "新增物品時包包格位不足");
                items = items.Add(index, Item(value, index, 1)); order = order.Add(index);
            }
        }
        return state with { Items = items, ItemOrder = order };
    }

    private static BagReceiveSnapshot Delete(BagReceiveSnapshot state, byte index, byte count)
    {
        var item = state.Items.GetValueOrDefault(index);
        if (item is null || count > item.Count) state = Fail(state, "物品扣除數量或格位不符");
        else state = state with
        {
            Items = item.Count == count ? state.Items.Remove(index) : state.Items.SetItem(index, item with { Count = item.Count - count }),
            ItemOrder = item.Count == count ? state.ItemOrder.Remove(index) : state.ItemOrder
        };
        // Even an invalid deduction consumes reservation counters in the retained source.
        BigInteger remaining = count;
        var holds = ImmutableArray.CreateBuilder<StorageReservationGroup>();
        foreach (var group in state.Holds)
        {
            var rows = ImmutableArray.CreateBuilder<StorageReservationSnapshot>();
            foreach (var original in group.Rows)
            {
                var row = original;
                if (row.Index == index)
                {
                    var used = BigInteger.Min(remaining, row.Remaining);
                    row = row with { Remaining = row.Remaining - used }; remaining -= used;
                }
                if (group.Owner != "battle" || row.Remaining != 0) rows.Add(row);
            }
            if (group.Owner != "battle" || rows.Count > 0) holds.Add(group with { Rows = rows.ToImmutable() });
        }
        return state with
        {
            Holds = holds.ToImmutable(), Revision = state.Revision + 1,
            Reserved = state.Reserved.SetItem(index, BigInteger.Max(0, state.Reserved.GetValueOrDefault(index) - count))
        };
    }

    public static BigInteger Available(BagReceiveSnapshot state, ushort index)
    {
        ArgumentNullException.ThrowIfNull(state);
        if (state.AlchemySlots?.Contains(index) == true || state.ExpeditionSlots?.Contains(index) == true ||
            state.MaintenanceSlots?.Contains(index) == true || state.Holds.Any(group => group.Rows.Any(row =>
                row.Index == index && (row.Exclusive || row.Uncertain)))) return 0;
        var count = index <= byte.MaxValue ? state.Items.GetValueOrDefault((byte)index)?.Count ?? 0 : 0;
        return BigInteger.Max(0, count - state.Reserved.GetValueOrDefault(index));
    }
}
