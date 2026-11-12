using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Receive-only crafting.decode_crafting, including its recipe-keyed schedule
/// variant and detailed furniture geometry observations. No runtime lookup or state changes.
/// S64-1/16 require an explicit schedule context; absence never establishes the legacy layout.</summary>
public static class CraftingDecoder
{
    public static InventoryEvent? Decode(Packet packet, CraftingScheduleContext? schedules = null)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (packet.Main == 64 && packet.Sub is 1 or 16 && schedules is null)
            throw new InvalidOperationException("S64-1/16 requires an explicitly selected crafting schedule context.");
        var r = new PacketReader(packet.Payload.Span);
        InventoryEvent? result;
        if (packet.Main == 64)
        {
            result = packet.Sub switch
            {
                1 => ReadSnapshot(r, schedules!),
                16 => new CraftAddedEvent(ReadScheduleRecord(r, schedules!)),
                2 => new CraftStartedEvent(r.U8()),
                3 => new CraftPausedEvent(r.U8()),
                5 => new CraftDeletedEvent(r.U8()),
                4 => new CraftCompletedEvent(r.U8(), r.U16()),
                6 or 7 or 8 => new CraftFailedEvent(packet.Sub, r.U8(), r.U16(), packet.Sub switch
                {
                    6 => "包包空間不足", 7 => "住宅空間不足", _ => "器具數量已達上限"
                }),
                10 => new CraftHumanEvent(r.U8(), r.U32()),
                25 => r.U8() == 1 ? new CraftSwappedEvent(true, r.U8(), r.U8()) : new CraftSwappedEvent(false),
                _ => null
            };
        }
        else if (packet.Main == 62)
        {
            result = packet.Sub switch
            {
                4 => ReadFurnitureSnapshot(r),
                1 => new FurnitureAddedEvent(r.U8(), ReadFurniture(r, r.U16())),
                2 => new FurnitureRemovedEvent(r.U16()),
                76 => new FurnitureRetainedEvent(r.U16()),
                5 => new FurnitureToolEvent(r.U8(), r.U16(), r.U16(), r.U16()),
                _ => null
            };
        }
        else return null;
        if (result is not null) r.End();
        return result;
    }

    private static CraftScheduleRow ReadScheduleRecord(PacketReader r, CraftingScheduleContext schedules)
    {
        var index = r.U8(); var identity = r.U16(); var elapsed = r.U32() / 1000d;
        var count = r.U8(); var baseTime = r.U32();
        if (index == 0 || identity == 0 || count == 0) throw new ProtocolException("製作排程欄位無效");
        return new(index, schedules.UsesRecipeIds ? schedules.ItemFor(identity) : identity, elapsed, count, baseTime,
            schedules.UsesRecipeIds ? identity : null);
    }

    private static CraftSnapshotEvent ReadSnapshot(PacketReader r, CraftingScheduleContext schedules)
    {
        if (r.Remaining < 1 || (r.Remaining - 1) % 12 != 0) throw new ProtocolException("製作排程長度不符");
        var count = (r.Remaining - 1) / 12; var rows = ImmutableArray.CreateBuilder<CraftScheduleRow>(count);
        for (var i = 0; i < count; i++) rows.Add(ReadScheduleRecord(r, schedules!));
        // The legacy decoder checks duplicates before active; the recipe decoder after End.
        if (!schedules.UsesRecipeIds) CheckDuplicateIndices(rows);
        var active = r.U8();
        if (schedules.UsesRecipeIds) { r.End(); CheckDuplicateIndices(rows); }
        return new(rows.MoveToImmutable(), active);
    }

    private static void CheckDuplicateIndices(ImmutableArray<CraftScheduleRow>.Builder rows)
    {
        if (rows.Select(row => row.Index).Distinct().Count() != rows.Count)
            throw new ProtocolException("製作排程索引重複");
    }

    private static FurnitureSnapshotEvent ReadFurnitureSnapshot(PacketReader r)
    {
        var owner = r.U32();
        if (r.Remaining % 44 != 0) throw new ProtocolException("小屋家具資料長度不符");
        var count = r.Remaining / 44; var furniture = ImmutableArray.CreateBuilder<FurnitureRecord>(count);
        for (var i = 0; i < count; i++) furniture.Add(ReadFurniture(r, r.U16()));
        return new(owner, furniture.MoveToImmutable());
    }

    private static FurnitureRecord ReadFurniture(PacketReader r, ushort index)
    {
        var item = r.U16(); var x = r.U16(); var y = r.U16(); var z = r.U16();
        var direction = r.U8(); var workbench = r.U16(); var contents = ImmutableArray.CreateBuilder<ushort>(11);
        for (var i = 0; i < 11; i++) contents.Add(r.U16());
        var floor = r.U8(); var status = r.U8(); r.Take(7);
        return new(index, item, x, y, z, direction, workbench, contents.MoveToImmutable(), floor, status);
    }
}
