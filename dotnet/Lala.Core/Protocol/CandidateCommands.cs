using System.Text;

namespace Lala.Core.Protocol;

/// <summary>Pure byte construction ported from Python. No transport or live-server approval implied.</summary>
public static class CandidateCommands
{
    // Release-owned values from wlre/configuration.py ESkill, not downloaded catalog policy.
    private static readonly HashSet<int> BuiltInActions = [10001, 10002, 10003, 10004, 10005, 10006, 10007, 10008, 10009, 10010, 10018, 10019, 10020, 10023, 10024, 10025, 10026, 10027, 10029, 10030, 15003, 15090, 15996, 25147, 60021, 60027, 60041, 60046];
    public static Packet Attack(int col, int row, int targetCol, int targetRow, int skillId)
    {
        if (!BuiltInActions.Contains(skillId)) throw new ProtocolException("unknown built-in action ID");
        return CastSkill(col, row, targetCol, targetRow, skillId);
    }
    public static Packet Login(string account, string password, int loginKind, int platform, int language)
    {
        if (account.Any(c => c > 127) || password.Any(c => c > 127))
            throw new ProtocolException("non-ASCII account/password encoding is unverified");
        if (account.Length == 0 || password.Length == 0) throw new ProtocolException("empty credentials");
        // Never log or persist credential payloads.
        return new Packet(63, 7, new PacketWriter().U8(loginKind).U8(0).U8(platform).U8(language)
            .U8(account.Length).Raw(Encoding.ASCII.GetBytes(account))
            .U8(password.Length).Raw(Encoding.ASCII.GetBytes(password)).Build());
    }
    public static Packet SelectRole(int index)
    {
        if (index is not (1 or 2)) throw new ProtocolException("role index must be 1 or 2");
        return new Packet(63, 2, new PacketWriter().U8(index).Build());
    }
    public static Packet Walk(int x, int y) => new(6, 1, new PacketWriter().U16(x).U16(y).Build());
    public static Packet CastSkill(int col, int row, int targetCol, int targetRow, int skillId) =>
        new(50, 1, new PacketWriter().U8(col).U8(row).U8(targetCol).U8(targetRow).U16(skillId).U8(0).U8(0).U8(0).Build());
    public static Packet UseBattleItem(int col, int row, int targetCol, int targetRow, int itemId, int index) =>
        new(50, 2, new PacketWriter().U8(col).U8(row).U8(targetCol).U8(targetRow).U16(itemId).U8(0).U8(0).U8(index).U8(0).Build());
    public static Packet UseFieldItem(int itemId, int index, int npcIndex) =>
        new(23, 15, new PacketWriter().U8(index).U16(itemId).U32(1).U8(npcIndex).Build());
}
