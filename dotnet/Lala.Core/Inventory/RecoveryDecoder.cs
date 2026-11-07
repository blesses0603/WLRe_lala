using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Receive-only recovery.decode_recovery. Negative deltas and item durability are
/// retained; only an absolute potion balance rejects a negative value.</summary>
public static class RecoveryDecoder
{
    public static InventoryEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if ((packet.Main, packet.Sub) != (23, 208)) return null;
        var r = new PacketReader(packet.Payload.Span); var kind = r.U8();
        InventoryEvent result;
        switch (kind)
        {
            case 3: case 4:
                var bottle = r.U8();
                if (bottle is < 1 or > 4) throw new ProtocolException("未知藥水儲存槽類型");
                var value = r.I32();
                if (kind == 3 && value < 0) throw new ProtocolException("藥水儲存槽數量無效");
                result = kind == 3 ? new PotionBalanceEvent(Resource(bottle), value)
                    : new PotionBalanceAddEvent(Resource(bottle), value);
                break;
            case 5:
                var usedBottle = r.U8();
                if (usedBottle is not (3 or 4)) throw new ProtocolException("未知藥水儲存槽回覆類型");
                var count = r.U8(); var targets = ImmutableArray.CreateBuilder<byte>(count);
                for (var i = 0; i < count; i++) targets.Add(r.U8());
                result = new PotionUsedEvent(Resource(usedBottle), targets.MoveToImmutable());
                break;
            case 1: case 2:
                byte? bottleKind = kind == 1 ? r.U8() : null;
                var index = r.U8(); var durable = r.I32();
                result = new PotionItemUpdateEvent(index, durable, bottleKind, kind == 1 ? r.U8() : null);
                break;
            default: throw new ProtocolException("未知藥水儲存槽回覆");
        }
        r.End(); return result;
    }

    private static string Resource(byte bottle) => bottle is 1 or 3 ? "hp" : "sp";
}
