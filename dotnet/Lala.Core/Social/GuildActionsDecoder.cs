using System.Collections.Frozen;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure receive-only social/guild_actions.py decode_actions. Metadata main/sub is
/// added to the typed contract; no sign-in, donation, reservations or automatic commands.</summary>
public static class GuildActionsDecoder
{
    public static SocialPacketEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if ((packet.Main, packet.Sub) is not ((39, 15 or 85 or 86 or 87) or (10, 5))) return null;
        var r = new PacketReader(packet.Payload.Span);
        SocialPacketEvent result = (packet.Main, packet.Sub) switch
        {
            (39, 85) => ReadSignState(r),
            (39, 86) => new GuildSignResultEvent(r.U8()),
            (39, 87) => ReadDonationState(r),
            (39, 15) => new GuildActionErrorEvent(r.U8()),
            _ => r.U8() switch
            {
                0 => new UiSellNoticeEvent(),
                1 => new UiSellUpdateEvent(r.U8(), r.U8()),
                2 => ReadSellSnapshot(r),
                3 => new UiSellDayResetEvent(),
                _ => throw new ProtocolException("未知的介面消費同步種類")
            }
        };
        r.End(); return result;
    }

    private static GuildSignStateEvent ReadSignState(PacketReader r)
    {
        var state = r.U8();
        if (state > 3) throw new ProtocolException("組織簽到狀態無效");
        return new(state);
    }

    private static GuildDonateStateEvent ReadDonationState(PacketReader r)
    {
        var count = r.U8(); var allow = r.U8();
        if (allow > 1) throw new ProtocolException("組織捐獻資格旗標無效");
        return new(count, allow != 0);
    }

    private static UiSellSnapshotEvent ReadSellSnapshot(PacketReader r)
    {
        var count = r.U8(); var counts = new Dictionary<byte, byte>(count);
        for (var i = 1; i <= count; i++) counts.Add((byte)i, r.U8());
        return new(counts.ToFrozenDictionary());
    }
}
