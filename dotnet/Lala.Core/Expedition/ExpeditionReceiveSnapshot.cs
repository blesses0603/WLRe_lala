using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Expedition;

/// <summary>S31-35 replaces these values with signed Int32s, even when the original
/// S31 role layout used an unsigned byte or UInt16. Do not clamp or wrap updates.</summary>
public sealed record ExpeditionOutpostStats(int Str, int Con, int Int, int Wis, int Agi,
    int Level, byte Degree, byte Potential);
public sealed record ExpeditionOutpostState(byte Index, ushort NpcId, byte State,
    ExpeditionOutpostStats Stats, int Faith, uint Exp, byte SportExp, ushort UseUpStats, ushort Modeling)
{
    internal static ExpeditionOutpostState From(OutpostRole role) => new(role.Index, role.NpcId, role.State,
        new(role.Stats.Str, role.Stats.Con, role.Stats.Int, role.Stats.Wis, role.Stats.Agi,
            role.Stats.Level, role.Stats.Degree, role.Stats.Potential),
        role.Faith, role.Exp, role.SportExp, role.UseUpStats, role.Modeling);
}

/// <summary>A result clears the team without an items field or deadline. Null differs
/// from an observed empty/zero value; a later time observation can establish a new deadline.</summary>
public sealed record ExpeditionTeamState(byte Index, ushort Minutes, ImmutableArray<ushort> Members,
    ImmutableArray<ushort>? Items, ushort Quest, double? Due);

/// <summary>Immutable receive-side projection of expedition.manager.defaults(). Byte-keyed
/// maps are bounded to 256 slots. Automation fields are carried as caller-supplied evidence
/// only: this state cannot enable a service, reserve items, authorize sending or confirm a claim.
/// New/Empty state is a fresh defaults projection, not an implicit response to a role-list packet.</summary>
public sealed record ExpeditionReceiveSnapshot
{
    public static ExpeditionReceiveSnapshot Empty { get; } = new();
    public bool Ready { get; init; }
    public bool OutpostReady { get; init; }
    public ImmutableDictionary<byte, ExpeditionOutpostState> Roles { get; init; } = ImmutableDictionary<byte, ExpeditionOutpostState>.Empty;
    public ImmutableDictionary<byte, ExpeditionTeamState> Teams { get; init; } = ImmutableDictionary<byte, ExpeditionTeamState>.Empty;
    public ImmutableDictionary<byte, ushort> Quests { get; init; } = ImmutableDictionary<byte, ushort>.Empty;
    public byte? Level { get; init; }
    public BigInteger Revision { get; init; }
    public bool Enabled { get; init; }
    public string? Pending { get; init; }
    public bool Uncertain { get; init; }
    public string Status { get; init; } = "尚未啟動";
    public StateValue Settings { get; init; } = StateValue.Map();
    public BigInteger Claimed { get; init; }
}
