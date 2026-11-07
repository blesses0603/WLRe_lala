using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Receive-only room_storage.decode_storage. Non-storage S62-25 kinds return null
/// after reading the two-byte header, ignoring any tail exactly as the source does.</summary>
public static class StorageDecoder
{
    public static InventoryEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (packet.Main != 62 || packet.Sub is not (7 or 11 or 13 or 25 or 57 or 71 or 72 or 73 or 74 or 75)) return null;
        var r = new PacketReader(packet.Payload.Span);
        InventoryEvent result;
        switch (packet.Sub)
        {
            case 7:
                var count = r.U8(); var items = ImmutableArray.CreateBuilder<ItemSave>(count);
                for (var i = 0; i < count; i++) items.Add(LiveDataLayouts.ReadItem(r, r.U8()));
                if (items.Select(item => item.Index).Distinct().Count() != items.Count)
                    throw new ProtocolException("儲藏室初始化格位重複");
                result = new StorageGarageInitialEvent(items.MoveToImmutable());
                break;
            case 11: result = new StorageGarageAddEvent(LiveDataLayouts.ReadItem(r, r.U8())); break;
            case 13: result = new StorageGarageDeleteEvent(r.U8(), r.U8()); break;
            case 57: result = ReadMaterials(r); break;
            case 71: result = new StorageMoveResultEvent(r.U8()); break;
            case 72: result = new StorageParametersEvent(r.U8(), r.U16(), r.U16()); break;
            case 73: result = new StorageExpandedEvent(73, "garage", r.U8()); break;
            case 74: result = new StorageExpandedEvent(74, "materials", r.U16()); break;
            case 75: result = new StorageExpandedEvent(75, "stack", r.U16()); break;
            default:
                var kind = r.U8(); var error = r.U8();
                if (kind != 1) return null;
                result = new StorageErrorEvent(kind, error);
                break;
        }
        r.End(); return result;
    }

    private static InventoryEvent ReadMaterials(PacketReader r)
    {
        var kind = r.U8();
        if (kind == 2) return new StorageMaterialsDeleteEvent(r.U16(), r.U16());
        if (kind != 1) throw new ProtocolException("雜物櫃封包種類不明");
        var sendKind = r.U8();
        if (sendKind is not (1 or 2)) throw new ProtocolException("雜物櫃同步種類不明");
        var count = sendKind == 1 ? r.U16() : 1;
        if (count > r.Remaining / 6) throw new ProtocolException("雜物櫃物品數量不符");
        var items = ImmutableArray.CreateBuilder<StorageMaterial>(count);
        for (var i = 0; i < count; i++) items.Add(new(r.U16(), r.U16(), r.U16()));
        if (sendKind == 1 && items.Select(item => item.Index).Distinct().Count() != items.Count)
            throw new ProtocolException("雜物櫃初始化格位重複");
        return sendKind == 1 ? new StorageMaterialsInitialEvent(items.MoveToImmutable())
            : new StorageMaterialsAddEvent(items.MoveToImmutable());
    }
}
