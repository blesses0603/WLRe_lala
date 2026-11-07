using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

public sealed record CompanionLearnedSkill(long Level, uint Exp, string Source);
public sealed record CompanionAttribute(byte Kind, uint Parameter, long Value);

/// <summary>Original S15 metadata and explicit S8 stat replacements. The raw skill slots
/// survive absent catalog mappings; these are observations, not permission to use skills.</summary>
public sealed record CompanionProfileSnapshot(CompanionSnapshot Data,
    ImmutableDictionary<uint, CompanionLearnedSkill> Skills,
    ImmutableDictionary<string, long> StatOverrides,
    ImmutableArray<uint>? RemovedSkillIds = null)
{
    public bool Ready => true;
    public override string ToString() => nameof(CompanionProfileSnapshot);
}

/// <summary>Bounded companion portion of apply_live/set_companion, including its S8 slot
/// buffer. This buffer is local to this domain, not wired to SessionEventSnapshot.Attributes.
/// A different NPC reusing a slot clears old attributes; the same NPC replays them.</summary>
public sealed record CompanionReceiveSnapshot
{
    public static CompanionReceiveSnapshot Empty { get; } = new();
    public bool Ready { get; init; }
    public uint? ActiveNpcId { get; init; }
    public ImmutableDictionary<ushort, CompanionProfileSnapshot> Companions { get; init; } = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty;
    public ImmutableArray<ushort> CompanionOrder { get; init; } = [];
    public ImmutableDictionary<ushort, ImmutableArray<CompanionAttribute>> Attributes { get; init; } = ImmutableDictionary<ushort, ImmutableArray<CompanionAttribute>>.Empty;
    public override string ToString() => nameof(CompanionReceiveSnapshot);
}
