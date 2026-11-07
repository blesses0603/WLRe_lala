using System.Collections.Frozen;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure read-only roster port of social/guild.py decode_guild. Skipped profile
/// fields, signatures and rules are never retained. No guild state mutation or requests.</summary>
public static class GuildDecoder
{
    public static SocialPacketEvent? Decode(Packet packet)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (packet.Main != 39 || packet.Sub is not (2 or 6 or 7 or 8 or 10 or 60)) return null;
        var r = new PacketReader(packet.Payload.Span);
        SocialPacketEvent result = packet.Sub switch
        {
            2 => ReadRoster(r),
            60 => new GuildMemberProfileEvent(r.U32(), ReadProfile(r)),
            6 => new GuildMemberRemovedEvent(r.U32()),
            8 => new GuildMemberAddedEvent(r.U32()),
            7 => new GuildLeaveResultEvent(r.U8(), r.U32()),
            _ => new GuildDisbandResultEvent(r.U8())
        };
        r.End(); return result;
    }

    private static string ReadProfile(PacketReader r)
    {
        var name = r.Unicode8();
        r.Take(6 + 8 + 1); r.Take(r.U8() * 6); r.Take(4 + 3 + 1);
        r.Unicode8(); r.Take(8);
        return name;
    }

    private static GuildRosterEvent ReadRoster(PacketReader r)
    {
        var name = r.Unicode8(); var chief = r.Unicode8();
        var count = r.U8(); var members = new Dictionary<uint, GuildMember>(count);
        for (var i = 0; i < count; i++)
        {
            var roleId = r.U32(); var memberName = ReadProfile(r); r.Take(1 + 4 + 4 + 1 + 2 + 1);
            if (roleId == 0 || !members.TryAdd(roleId, new(roleId, memberName)))
                throw new ProtocolException("invalid or duplicate guild member ID");
        }
        r.Unicode8(); r.Take(2); var level = r.U8();
        r.Take(16); r.Take(3 + 1 + 6); r.Take(1 + 1 + 2 + 4 + 1 + 1 + 1);
        var serial = r.U32();
        return new(name, chief, serial, members.ToFrozenDictionary(), level);
    }
}
