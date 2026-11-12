using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.World.Tent;

/// <summary>Pure port of world/tent.py decode_tent and _camp. Unknown keys and nonempty
/// extensions of S65-2/5/8 remain opaque, never misreported as confirmed outcomes.</summary>
public static class TentDecoder
{
    public static TentEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (packet.Main != 65) return null;
        var r = new PacketReader(packet.Payload.Span);
        TentEvent result;
        switch (packet.Sub)
        {
            case 1:
                RequireLength(r, 16, "S65-1 帳篷資料長度不符");
                result = new TentAddedEvent(ReadCamp(r)); break;
            case 3:
                if (r.Remaining % 16 != 0) throw new ProtocolException("S65-3 帳篷清單長度不符");
                var count = r.Remaining / 16;
                var tents = ImmutableArray.CreateBuilder<TentCamp>(count);
                for (var i = 0; i < count; i++) tents.Add(ReadCamp(r));
                result = new TentSceneListEvent(tents.MoveToImmutable()); break;
            case 4:
                RequireLength(r, 4, "S65-4 帳篷移除資料長度不符");
                result = new TentRemovedEvent(r.U32()); break;
            case 7:
                RequireLength(r, 2, "S65-7 帳篷開放狀態長度不符");
                result = new TentAccessEvent(r.U8() == 0, r.U8() != 0); break;
            case 16:
                RequireLength(r, 1, "S65-16 帳篷錯誤碼長度不符");
                result = new TentErrorEvent(r.U8()); break;
            case 18:
                RequireLength(r, 2, "S65-18 帳篷外觀長度不符");
                result = new TentAppearanceEvent(r.U8(), r.U8()); break;
            case 2: case 5: case 8:
                if (r.Remaining != 0) return null;
                result = packet.Sub switch
                {
                    2 => new TentLimitEvent(), 5 => new TentOwnerLeftEvent(), _ => new TentEntryDeniedEvent()
                };
                break;
            default: return null;
        }
        r.End(); return result;
    }

    private static TentCamp ReadCamp(PacketReader r) => new(r.U32(), r.U16(), r.U32(), r.U32(), r.U8(), r.U8());
    private static void RequireLength(PacketReader r, int length, string message)
    {
        if (r.Remaining != length) throw new ProtocolException(message);
    }
}
