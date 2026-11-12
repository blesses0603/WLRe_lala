using System.Collections.Immutable;
using System.Text;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure receive-only port of social/chat.py decode_chat. No sends, state writes or
/// logs. S2-3 requires an explicit local identity for attribution; without one only the sender
/// prefix is read, then a notice is returned without guessing or parsing the body.</summary>
public static class ChatDecoder
{
    public static SocialPacketEvent? Decode(Packet packet, uint? localRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(packet);
        if (packet.Main != 2) return null;
        var r = new PacketReader(packet.Payload.Span);
        SocialPacketEvent result;
        switch (packet.Sub)
        {
            case 13:
                var code = r.U8();
                result = new ChatResultEvent(code, code switch
                {
                    0 => "伺服器已回覆發話結果", 1 => "發話太頻繁，請稍候再試",
                    2 => "目前被禁言，請稍後再發言", _ => $"發話結果代碼 {code}"
                });
                break;
            case 18: case 19:
                var role = r.U32();
                if (role == 0) result = new ChatNoticeEvent(packet.Sub, "查無此角色");
                else
                {
                    var online = r.U8() != 0;
                    result = new ChatProfileEvent(packet.Sub, role, ReadProfile(r), online);
                }
                break;
            case 21:
                var target = r.U32();
                result = new ChatNoticeEvent(packet.Sub, $"密語對象 {target} 目前離線", target);
                break;
            case 0:
                var index = r.U32(); var raw = r.Take(r.Remaining);
                // Lua uses System encoding here; non-ASCII remains intentionally unguessed.
                var text = raw.IndexOfAnyInRange((byte)128, byte.MaxValue) < 0
                    ? Encoding.ASCII.GetString(raw) : "收到系統公告（此公告文字編碼尚未確認）";
                result = new ChatAnnouncementEvent(text, index);
                break;
            default:
                var channel = packet.Sub switch
                {
                    1 or 10 => "世界", 2 => "區域", 3 or 17 => "密語", 5 => "隊伍",
                    6 => "組織", 27 or 28 => "跨服", _ => null
                };
                if (channel is null) return null;
                ushort? server = packet.Sub == 28 ? r.U16() : null;
                var sender = r.U32(); uint? recipient = null;
                if (packet.Sub == 3)
                {
                    if (localRoleId is null)
                        return new ChatNoticeEvent(packet.Sub, "收到密語，但尚無本機角色 ID，未猜測內容");
                    recipient = sender == localRoleId ? r.U32() : localRoleId;
                }
                else if (packet.Sub == 17) recipient = r.U32();
                string? name = null;
                if (packet.Sub is 10 or 17) name = ReadProfile(r);
                else if (packet.Sub == 28) { name = r.Unicode8(); r.Take(16); }
                result = ReadBody(r, packet.Sub, channel, sender, recipient, server, name);
                break;
        }
        r.End(); return result;
    }

    private static string ReadProfile(PacketReader r)
    {
        var name = r.Unicode8(); r.Take(16);
        if (r.U8() == 0)
        {
            r.Take(7); r.Unicode8(); r.Take(r.U8() * 2);
        }
        return name;
    }

    private static ChatMessageEvent ReadBody(PacketReader r, byte sub, string channel,
        uint sender, uint? recipient, ushort? server, string? name)
    {
        var count = r.U8(); var items = ImmutableArray.CreateBuilder<ItemSave>(count);
        for (var i = 0; i < count; i++) items.Add(LiveDataLayouts.ReadItem(r, r.U8()));
        var text = r.Unicode8(); var replyId = r.U32();
        ushort? replyServer = null; string? replyText = null; bool? replyAt = null;
        ImmutableArray<ushort>? replyItems = null;
        if (replyId != 0)
        {
            if (sub is 27 or 28) replyServer = r.U16();
            replyText = r.Unicode8(); replyAt = r.U8() != 0;
            var replyCount = r.U8(); var links = ImmutableArray.CreateBuilder<ushort>(replyCount);
            for (var i = 0; i < replyCount; i++) links.Add(r.U16());
            replyItems = links.MoveToImmutable();
        }
        return new(sub, channel, sender, items.MoveToImmutable(), text, replyId,
            recipient, server, name, replyServer, replyText, replyAt, replyItems);
    }
}
