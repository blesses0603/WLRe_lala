using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Pure receive-only port of crafting.apply_crafting, compact and elapsed.
/// Decode completely first with an explicitly selected CraftingScheduleContext. No
/// layout/runtime is selected here, and no resource token is verified or created.
/// Caller supplies the pre-application player identity and a finite monotonic timestamp.
/// Duplicate/late observations retain source behavior; they do not authorize commands.</summary>
public static class CraftingReducer
{
    public static CraftingReceiveSnapshot Apply(CraftingReceiveSnapshot state, ServerEvent observation,
        uint? playerRoleId, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (observation is ServerInventoryEvent inventory) return Apply(state, inventory.Event, playerRoleId, observedAt);
        if (observation is not InitialDataCompleteEvent) return state;
        var room = state.Furniture;
        var craft = state.Crafting;
        if (room.PersonalBatch == true && room.Owner == playerRoleId)
            room = room with { Ready = true, Revision = room.Revision + 1 };
        if (!craft.Ready && string.IsNullOrEmpty(craft.Pending) && !craft.Uncertain)
        {
            craft = craft.Active != 0 && !craft.Queue.ContainsKey(craft.Active)
                ? craft with { Uncertain = true, Status = "製作索引缺資料，請重新同步" }
                : craft with { Ready = true, SyncSource = "S1-11", Status = "登入資料接收完成，製作排程已就緒" };
            craft = craft with { Revision = craft.Revision + 1 };
        }
        return ReferenceEquals(craft, state.Crafting) && ReferenceEquals(room, state.Furniture)
            ? state : state with { Crafting = craft, Furniture = room };
    }

    public static CraftingReceiveSnapshot Apply(CraftingReceiveSnapshot state, InventoryEvent observation,
        uint? playerRoleId, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (observation is CraftFurnitureEvent furniture)
            return state with { Furniture = ApplyFurniture(state.Furniture, furniture, playerRoleId) };
        if (!observation.Type.StartsWith("craft_", StringComparison.Ordinal)) return state;
        var craft = state.Crafting;
        switch (observation)
        {
            case CraftSnapshotEvent snapshot:
                RequireFinite(observedAt);
                var queue = ImmutableDictionary<byte, CraftScheduleRow>.Empty;
                var queueOrder = ImmutableArray.CreateBuilder<byte>();
                foreach (var row in snapshot.Rows)
                {
                    if (!queue.ContainsKey(row.Index)) queueOrder.Add(row.Index);
                    queue = queue.SetItem(row.Index, row);
                }
                var missing = snapshot.Active != 0 && !queue.ContainsKey(snapshot.Active);
                craft = craft with
                {
                    Ready = true, SyncSource = "S64-1", Queue = queue, QueueOrder = queueOrder.ToImmutable(), Active = snapshot.Active,
                    Running = snapshot.Active != 0 && !missing, StartedAt = observedAt,
                    CompletionRequested = false, Uncertain = missing,
                    Status = missing ? "製作索引缺資料，請重新同步" : "伺服器製作排程已同步"
                };
                break;
            case CraftAddedEvent added:
                craft = craft with
                {
                    Queue = craft.Queue.SetItem(added.Row.Index, added.Row),
                    QueueOrder = craft.Queue.ContainsKey(added.Row.Index) ? craft.QueueOrder : craft.QueueOrder.Add(added.Row.Index),
                    Status = "已加入伺服器製作排程"
                };
                break;
            case CraftStartedEvent started:
                if (!craft.Queue.ContainsKey(started.Index))
                    craft = craft with { Uncertain = true, Status = "製作索引缺資料，停止自動接續" };
                else
                {
                    RequireFinite(observedAt);
                    craft = craft with { Active = started.Index, Running = true, StartedAt = observedAt,
                        CompletionRequested = false, Status = "製作中（伺服器確認）" };
                }
                break;
            case CraftPausedEvent paused:
                if (craft.Queue.TryGetValue(paused.Index, out var pausedRow))
                    craft = craft with { Queue = craft.Queue.SetItem(paused.Index, pausedRow with { Elapsed = Elapsed(craft, pausedRow, observedAt) }) };
                craft = craft with { Active = 0, Running = false, StartedAt = null, AutoContinue = false, Status = "已暫停製作（伺服器確認）" };
                break;
            case CraftCompletedEvent completed:
                if (craft.Running && completed.Index == craft.Active && craft.Queue.ContainsKey(completed.Index))
                    craft = Compact(craft with { Queue = craft.Queue.Remove(completed.Index) }) with
                    {
                        Completed = craft.Completed + 1,
                        Active = 0, Running = false, StartedAt = null, CompletionRequested = false,
                        Status = "製作完成，等待確認產物／包包更新"
                    };
                break;
            case CraftFailedEvent failed:
                craft = craft with { Running = false, Active = 0, AutoContinue = false, CompletionRequested = false, Status = failed.Reason };
                break;
            case CraftDeletedEvent deleted:
                craft = Compact(craft with { Queue = craft.Queue.Remove(deleted.Index) }) with { Status = "已移除製作排程（伺服器確認）" };
                break;
            case CraftHumanEvent human:
                craft = craft with { HumanIndex = human.Index, HumanId = human.NpcId };
                break;
            case CraftSwappedEvent swapped:
                if (swapped.Success && swapped.First is { } first && swapped.Second is { } second &&
                    craft.Queue.TryGetValue(first, out var a) && craft.Queue.TryGetValue(second, out var b))
                    craft = craft with { Queue = craft.Queue.SetItem(first, b with { Index = first }).SetItem(second, a with { Index = second }) };
                craft = craft with { Status = swapped.Success ? "製作順序已更新" : "伺服器拒絕交換製作順序" };
                break;
        }
        // Unknown craft_* observations and ignored duplicate completions still revise the source domain.
        return state with { Crafting = craft with { Revision = state.Crafting.Revision + 1 } };
    }

    private static CraftingRoomSnapshot ApplyFurniture(CraftingRoomSnapshot room, CraftFurnitureEvent observation, uint? playerRoleId)
    {
        var revision = room.Revision + 1;
        if (observation is FurnitureSnapshotEvent snapshot)
        {
            room = room with { CurrentOwner = snapshot.Owner };
            if (snapshot.Owner == playerRoleId)
            {
                var items = ImmutableDictionary<ushort, CraftFurnitureSnapshot>.Empty;
                var itemOrder = ImmutableArray.CreateBuilder<ushort>();
                foreach (var row in snapshot.Furniture)
                {
                    if (!items.ContainsKey(row.Index)) itemOrder.Add(row.Index);
                    items = items.SetItem(row.Index, CraftFurnitureSnapshot.From(row));
                }
                room = room with { Owner = snapshot.Owner, Ready = true, Items = items, ItemOrder = itemOrder.ToImmutable() };
            }
        }
        else if (observation is FurnitureAddedEvent { Kind: 2 } or FurnitureToolEvent { Kind: 2 } || room.CurrentOwner == playerRoleId)
        {
            switch (observation)
            {
                case FurnitureAddedEvent add:
                    if (add.Kind == 2) room = room with { Owner = playerRoleId, PersonalBatch = true };
                    room = SetFurniture(room, CraftFurnitureSnapshot.From(add.Furniture));
                    break;
                case FurnitureRemovedEvent remove:
                    room = RemoveFurniture(room, remove.Index);
                    break;
                case FurnitureRetainedEvent retain when room.Items.TryGetValue(retain.Index, out var item):
                    room = room with { Items = room.Items.SetItem(retain.Index, item with { Status = 1 }) };
                    break;
                case FurnitureToolEvent tool:
                    room = tool.Kind == 1
                        ? SetFurniture(room, new(tool.Index, tool.ItemId, tool.Workbench, 0, 0))
                        : RemoveFurniture(room, tool.Index);
                    break;
            }
        }
        return room with { Revision = revision };
    }

    private static CraftingRoomSnapshot SetFurniture(CraftingRoomSnapshot room, CraftFurnitureSnapshot row) => room with
    {
        Items = room.Items.SetItem(row.Index, row),
        ItemOrder = room.Items.ContainsKey(row.Index) ? room.ItemOrder : room.ItemOrder.Add(row.Index)
    };

    private static CraftingRoomSnapshot RemoveFurniture(CraftingRoomSnapshot room, ushort index) => room with
    {
        Items = room.Items.Remove(index), ItemOrder = room.ItemOrder.Remove(index)
    };

    private static CraftingSnapshot Compact(CraftingSnapshot craft)
    {
        var result = ImmutableDictionary<byte, CraftScheduleRow>.Empty;
        var order = ImmutableArray.CreateBuilder<byte>(craft.Queue.Count);
        var index = 0;
        foreach (var row in craft.Queue.Values.OrderBy(row => row.Index))
        {
            var next = checked((byte)++index);
            result = result.SetItem(next, row with { Index = next });
            order.Add(next);
        }
        return craft with { Queue = result, QueueOrder = order.MoveToImmutable() };
    }

    /// <summary>Display/receive timing only. Passing the base time never completes a row,
    /// spends materials, proves output receipt or emits a completion request.</summary>
    public static double Elapsed(CraftingSnapshot state, CraftScheduleRow row, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(row);
        if (!state.Running || row.Index != state.Active || state.StartedAt is not { } startedAt) return row.Elapsed;
        RequireFinite(observedAt);
        return row.Elapsed + Math.Max(0, observedAt - startedAt);
    }

    private static void RequireFinite(double observedAt)
    {
        if (!double.IsFinite(observedAt)) throw new ArgumentOutOfRangeException(nameof(observedAt), "A finite monotonic timestamp is required.");
    }
}
