using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Explicit, unverified offline mappings. Presence of an item row is distinct from
/// a missing row, even when its fit type is zero. These mappings grant no runtime authority.</summary>
public sealed record CombatKnowledgeCatalog
{
    public static CombatKnowledgeCatalog Empty { get; } = new();
    public ImmutableDictionary<ushort, uint> SkillKeys { get; init; } = ImmutableDictionary<ushort, uint>.Empty;
    public ImmutableDictionary<ushort, int> ItemFitTypes { get; init; } = ImmutableDictionary<ushort, int>.Empty;
}

public sealed record PlayerSkillEvidence(long Level, uint Exp, string Source, ushort? Key = null);

/// <summary>A full S23/S15 record, an empty slot, or a sparse S11 appearance replacement.
/// OriginalRecord retains untouched metadata; ItemId/DesignId/Damage are authoritative when
/// present. A sparse appearance replacement deliberately discards full-record metadata.</summary>
public sealed record KnowledgeEquipment(ushort ItemId, uint? DesignId = null, uint? Damage = null,
    ItemSave? OriginalRecord = null)
{
    public static KnowledgeEquipment FromItem(ItemSave item) => new(item.ItemId, item.DesignId, item.Damage, item);
    public override string ToString() => nameof(KnowledgeEquipment);
}

/// <summary>Null collections mean never observed (or removed by the Python pop), not empty.
/// Deferred events are immutable receive observations, not commands to be sent.</summary>
public sealed record PlayerEquipmentKnowledge
{
    public ImmutableArray<KnowledgeEquipment>? Equips { get; init; }
    public ImmutableArray<ItemSave>? UnresolvedEquips { get; init; }
    public ImmutableArray<LiveDataEvent>? DeferredEquipUpdates { get; init; }
    public bool? EquipmentNeedsSnapshot { get; init; }
    public override string ToString() => nameof(PlayerEquipmentKnowledge);
}

/// <summary>Only knowledge.player, not the local role identity, attributes or battle units.
/// S5 merges stats but replaces skill evidence; S8 and battle values never imply readiness.</summary>
public sealed record PlayerKnowledgeSnapshot
{
    public static PlayerKnowledgeSnapshot Empty { get; } = new();
    public bool Ready { get; init; }
    public ImmutableDictionary<uint, PlayerSkillEvidence> Skills { get; init; } = ImmutableDictionary<uint, PlayerSkillEvidence>.Empty;
    public ImmutableArray<uint> SkillOrder { get; init; } = [];
    public ImmutableArray<LearnedSkill>? ServerSkillRecords { get; init; }
    public ImmutableArray<uint>? RemovedSkillIds { get; init; }
    public ImmutableDictionary<string, long> Stats { get; init; } = ImmutableDictionary<string, long>.Empty;
    public PlayerEquipmentKnowledge Equipment { get; init; } = new();
    public override string ToString() => nameof(PlayerKnowledgeSnapshot);
}

/// <summary>Explicit replacement projections. The caller must retain all three; do not keep a
/// second battle/companion store. No local attribute buffer is read or copied by this slice.</summary>
public sealed record CombatKnowledgeReceiveResult(PlayerKnowledgeSnapshot Player,
    CompanionReceiveSnapshot Companions, BattleEventSnapshot Battle)
{
    public override string ToString() => nameof(CombatKnowledgeReceiveResult);
}
