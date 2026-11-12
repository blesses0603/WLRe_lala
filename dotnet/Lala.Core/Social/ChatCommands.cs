using System.Text;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Social;

/// <summary>Outgoing UIChat.SendChat framing and checks shared with the Python client.</summary>
public static class ChatCommands
{
    public static Packet Create(ServiceStateSnapshot state, string channel, string text, uint? target = null)
    {
        if (state.Player is not { RoleId: > 0 } player) throw new ProtocolException("請先登入角色。");
        int code = channel switch { "區域" => 2, "世界" => 1, "隊伍" => 5, "組織" => 6, "密語" => 3, _ => throw new ProtocolException("請選擇可發話的頻道。") };
        if (string.IsNullOrWhiteSpace(text)) throw new ProtocolException("請輸入聊天內容。");
        if (text.Any(c => c < 32 || c == 127)) throw new ProtocolException("聊天內容不可含換行或控制字元。");
        byte[] encoded;
        try { encoded = new UnicodeEncoding(false, false, true).GetBytes(text); }
        catch (EncoderFallbackException) { throw new ProtocolException("聊天文字無法編碼。"); }
        if (encoded.Length > 254) throw new ProtocolException("訊息過長，最多 127 個 UTF-16 字元。");
        if (code == 5 && state.Party.OwnTeam(player.RoleId) is null) throw new ProtocolException("請先加入隊伍再發話。");
        if (code == 6 && (!state.Guild.Ready || !state.Guild.Members.ContainsKey(player.RoleId))) throw new ProtocolException("目前角色尚未加入組織或組織資料未同步。");
        if (code == 1 && state.PlayerKnowledge.Stats.TryGetValue("level", out var level) && level < 10) throw new ProtocolException("須達 10 級才可世界發話。");
        var writer = new PacketWriter().U8(0);
        if (code == 3)
        {
            if (target is null or 0 || target == player.RoleId) throw new ProtocolException("密語請填入其他角色的 ID。");
            writer.U32(target.Value);
        }
        return new(2, code, writer.U8(encoded.Length).Raw(encoded).U32(0).Build());
    }
}
