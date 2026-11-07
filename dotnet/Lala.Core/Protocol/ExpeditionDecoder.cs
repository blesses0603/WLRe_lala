using System.Collections.Frozen;
using System.Collections.Immutable;
namespace Lala.Core.Protocol;

public sealed record OutpostStats(ushort Str, ushort Con, ushort Int, ushort Wis, ushort Agi, byte Level, byte Degree, byte Potential);
public sealed record OutpostRole(byte Index, ushort NpcId, byte State, OutpostStats Stats, byte Faith, uint Exp, byte SportExp, ushort UseUpStats, ushort Modeling);
public sealed record ExpeditionReward(byte Kind, uint Id, uint Value);
public sealed class ExpeditionTeam
{
    public byte Index { get; }
    public ushort Minutes { get; }
    public IReadOnlyList<ushort> Members { get; }
    public IReadOnlyList<ushort> Items { get; }
    public ushort Quest { get; }
    internal ExpeditionTeam(byte index, ushort minutes, ushort[] members, ushort[] items, ushort quest)
    { Index = index; Minutes = minutes; Members = Array.AsReadOnly(members); Items = Array.AsReadOnly(items); Quest = quest; }
}
public abstract record ExpeditionEvent;
public sealed record OutpostSnapshotEvent(byte Capacity, ImmutableArray<OutpostRole> Roles) : ExpeditionEvent;
public sealed record OutpostRoleEvent(OutpostRole Role) : ExpeditionEvent;
public sealed record OutpostRemoveEvent(byte Index) : ExpeditionEvent;
public sealed record OutpostStatusEvent(byte Index, byte State) : ExpeditionEvent;
public sealed record OutpostFaithEvent(byte Index, byte Faith, byte Show) : ExpeditionEvent;
public sealed record OutpostAttributeEvent(byte Index, byte Kind, int Value) : ExpeditionEvent;
public sealed record ExpeditionSnapshotEvent(ImmutableArray<ExpeditionTeam> Teams, ImmutableArray<ushort> Quests, byte Level, uint Exp) : ExpeditionEvent;
public sealed record ExpeditionStartedEvent(int ExtensionBytes) : ExpeditionEvent;
public sealed record ExpeditionResultEvent(byte Result, byte Index, ushort Journal, ushort History, ImmutableArray<ExpeditionReward> Rewards) : ExpeditionEvent;
public sealed record ExpeditionTimeEvent(byte Index, ushort Minutes) : ExpeditionEvent;
public sealed record ExpeditionTeamEvent(ExpeditionTeam Team) : ExpeditionEvent;
public sealed record ExpeditionQuestsEvent(FrozenDictionary<byte, ushort> Quests, bool Show) : ExpeditionEvent;
public sealed record ExpeditionRejectedEvent(byte Code, byte Source) : ExpeditionEvent;
public sealed record ExpeditionLevelEvent(byte Level, uint Exp) : ExpeditionEvent;

/// <summary>Offline S31 packet decoder from wlre/network/expedition.py. No sending or state mutation.</summary>
public static class ExpeditionDecoder
{
    public static ExpeditionEvent? Decode(Packet packet)
    {
        if (packet.Main != 31) return null;
        var r = new PacketReader(packet.Payload.Span);
        ExpeditionEvent? result;
        switch (packet.Sub)
        {
            case 6:
                var capacity = r.U8(); var count = r.U8(); var roles = new OutpostRole[count];
                for (var i = 0; i < count; i++) roles[i] = ReadOutpost(r);
                result = new OutpostSnapshotEvent(capacity, roles.ToImmutableArray()); break;
            case 3: case 24: result = new OutpostRoleEvent(ReadOutpost(r)); break;
            case 5: case 26: result = new OutpostRemoveEvent(r.U8()); break;
            case 12: result = new OutpostStatusEvent(r.U8(), r.U8()); break;
            case 27: result = new OutpostFaithEvent(r.U8(), r.U8(), r.U8()); break;
            case 35: result = new OutpostAttributeEvent(r.U8(), r.U8(), r.I32()); break;
            case 13:
                var teams = new ExpeditionTeam[10]; for (var i = 0; i < 10; i++) teams[i] = ReadTeam(r);
                var quests = new ushort[50]; for (var i = 0; i < 50; i++) quests[i] = r.U16();
                r.Take(140); var level = r.U8(); var exp = r.U32(); r.Take(27);
                result = new ExpeditionSnapshotEvent(teams.ToImmutableArray(), quests.ToImmutableArray(), level, exp); break;
            case 15:
                result = new ExpeditionStartedEvent(r.Remaining); r.Take(r.Remaining); break;
            case 16:
                var code = r.U8(); var index = r.U8(); var journal = r.U16(); var history = r.U16();
                if (r.Remaining % 9 != 0) throw new ProtocolException("invalid expedition reward length");
                var rewards = new ExpeditionReward[r.Remaining / 9];
                for (var i = 0; i < rewards.Length; i++) rewards[i] = new(r.U8(), r.U32(), r.U32());
                result = new ExpeditionResultEvent(code, index, journal, history, rewards.ToImmutableArray()); break;
            case 17: result = new ExpeditionTimeEvent(r.U8(), r.U16()); break;
            case 18: result = new ExpeditionTeamEvent(ReadTeam(r)); break;
            case 19:
                var updates = new Dictionary<byte, ushort>(); for (var i = 0; i < 50; i++) updates[r.U8()] = r.U16();
                result = new ExpeditionQuestsEvent(updates.ToFrozenDictionary(), r.U8() != 0); break;
            case 20: case 25: result = new ExpeditionRejectedEvent(r.U8(), packet.Sub); break;
            case 21: result = new ExpeditionLevelEvent(r.U8(), r.U32()); break;
            default: return null;
        }
        r.End(); return result;
    }
    private static OutpostRole ReadOutpost(PacketReader r)
    {
        var index = r.U8(); var npc = r.U16(); var state = r.U8();
        var str = r.U16(); var con = r.U16(); var intelligence = r.U16(); var wis = r.U16(); var agi = r.U16(); var level = r.U8();
        r.Take(5); var faith = r.U8(); var exp = r.U32(); var sport = r.U8(); var useUp = r.U16(); var degree = r.U8(); var potential = r.U8(); var modeling = r.U16();
        return new(index, npc, state, new(str, con, intelligence, wis, agi, level, degree, potential), faith, exp, sport, useUp, modeling);
    }
    private static ExpeditionTeam ReadTeam(PacketReader r)
    {
        var index = r.U8(); var minutes = r.U16(); var members = new ushort[4]; var items = new ushort[4];
        for (var i = 0; i < 4; i++) members[i] = r.U16(); for (var i = 0; i < 4; i++) items[i] = r.U16();
        return new(index, minutes, members, items, r.U16());
    }
}
