using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CompanionSkillMetadataTests
{
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> Mapping = Map(1001, 1002, 0, 1003, 1004);
    private static ImmutableDictionary<uint, ImmutableArray<uint>> Map(params uint[] skills) =>
        ImmutableDictionary<uint, ImmutableArray<uint>>.Empty.Add(42, [.. skills]);
    private static CompanionSnapshot Companion(byte index = 1, uint npc = 42) =>
        new(index, npc, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, "synthetic",
            [new(1, 10), new(2, 20), new(3, 30), new(4, 40), new(0, 50)], [], 0, 1, 2, 3, 4, 5, 6);
    private static AttributeSetEvent Skill(uint id, long level, byte human = 4, byte sub = 2) =>
        new(sub, "follow:1", human, 1, 110, "skill", 1, level, id);
    private static CompanionReceiveSnapshot Seed(ImmutableDictionary<uint, ImmutableArray<uint>>? mapping = null) =>
        CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([Companion()]), 7, mapping);
    private static CompanionReceiveSnapshot Observe(CompanionReceiveSnapshot state,
        ImmutableDictionary<uint, ImmutableArray<uint>>? mapping = null) =>
        CompanionReceiveReducer.Apply(state, new HeartbeatRequestEvent(), 7, mapping, reconcileNpcSkills: true);

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    public void DefaultEntryPointsPreservePythonStoredEvidenceUntilFreshS15(int entryPoint)
    {
        CompanionReceiveSnapshot DefaultObserve(CompanionReceiveSnapshot state,
            ImmutableDictionary<uint, ImmutableArray<uint>>? mapping) => entryPoint switch
        {
            0 => CompanionReceiveReducer.Apply(state, new HeartbeatRequestEvent(), 7, mapping),
            1 => CompanionReceiveReducer.Apply(state, new StarInfoEvent(1, 2, 3), 7, mapping),
            _ => CompanionReceiveReducer.ApplyBeforeLocal(state, new ServerLiveDataEvent(new StarInfoEvent(1, 2, 3)), 7, mapping)
        };
        var unresolved = Seed();
        Assert.Same(unresolved, DefaultObserve(unresolved, Mapping));
        var mapped = Seed(Mapping);
        Assert.Same(mapped, DefaultObserve(mapped, null));
        Assert.Same(mapped, DefaultObserve(mapped, Map(2001, 2002, 0, 0, 0)));
        var replaced = CompanionReceiveReducer.Apply(mapped, new CompanionSnapshotEvent([Companion()]));
        Assert.Empty(replaced.Companions[1].Skills);
        Assert.Equal(3, mapped.Companions[1].Skills.Count);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    public void LateMappingResolvesRetainedSlotsThroughEveryEntryPointWithoutReplacingOccupantEvidence(int entryPoint)
    {
        var state = Seed();
        var original = state.Companions[1];
        var profile = original with
        {
            StatOverrides = ImmutableDictionary<string, long>.Empty.Add("hp", 321),
            EquipmentOverrides = [new(99)]
        };
        state = state with { Companions = state.Companions.SetItem(1, profile), ActiveNpcId = 42 };
        var next = entryPoint switch
        {
            0 => Observe(state, Mapping),
            1 => CompanionReceiveReducer.Apply(state, new StarInfoEvent(1, 2, 3), 7, Mapping, reconcileNpcSkills: true),
            _ => CompanionReceiveReducer.ApplyBeforeLocal(state, new ServerLiveDataEvent(new StarInfoEvent(1, 2, 3)), 7, Mapping, reconcileNpcSkills: true)
        };
        var resolved = next.Companions[1];
        Assert.Equal(new uint[] { 1001, 1002, 1003 }, resolved.SkillOrder);
        Assert.Equal(new CompanionLearnedSkill(2, 20, "S15技能槽＋NpcData"), resolved.Skills[1002]);
        Assert.Same(profile.Data, resolved.Data);
        Assert.Same(profile.StatOverrides, resolved.StatOverrides);
        Assert.Equal(profile.EquipmentOverrides, resolved.EquipmentOverrides);
        Assert.Same(state.Attributes, next.Attributes);
        Assert.Equal(state.CompanionOrder, next.CompanionOrder);
        Assert.Equal(state.ActiveNpcId, next.ActiveNpcId);
        Assert.Equal(state.Ready, next.Ready);
        Assert.Empty(original.Skills);
        Assert.Same(next, Observe(next, Mapping));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    public void WithdrawalRemovesOnlyMetadataEvidenceAndNeverReusesAnOldMap(int missingKind)
    {
        var mapped = Seed(Mapping);
        var overridden = CompanionReceiveReducer.Apply(mapped, Skill(1002, 8), 7, Mapping);
        overridden = CompanionReceiveReducer.Apply(overridden, Skill(9000, 6), 7, Mapping);
        overridden = CompanionReceiveReducer.Apply(overridden, Skill(1003, 0), 7, Mapping);
        ImmutableDictionary<uint, ImmutableArray<uint>>? missing = missingKind switch
        {
            0 => null,
            1 => ImmutableDictionary<uint, ImmutableArray<uint>>.Empty,
            2 => ImmutableDictionary<uint, ImmutableArray<uint>>.Empty.Add(43, [1001, 1002, 0, 1003, 1004]),
            3 => ImmutableDictionary<uint, ImmutableArray<uint>>.Empty.Add(42, default),
            4 => Map(),
            _ => Map(0, 0, 0, 0, 0)
        };
        var withdrawn = Observe(overridden, missing);
        var profile = withdrawn.Companions[1];
        Assert.Equal(new uint[] { 1002, 9000 }, profile.SkillOrder);
        Assert.Equal(new CompanionLearnedSkill(8, 0, "S8-2"), profile.Skills[1002]);
        Assert.Equal(new CompanionLearnedSkill(6, 0, "S8-2"), profile.Skills[9000]);
        Assert.Equal(new uint[] { 1003 }, profile.RemovedSkillIds!.Value);
        Assert.Same(overridden.Attributes, withdrawn.Attributes);
        Assert.Same(withdrawn, Observe(withdrawn));
        Assert.Same(withdrawn, Observe(withdrawn, missing));
        Assert.Contains(1001u, overridden.Companions[1].Skills.Keys);
        var restored = Observe(withdrawn, Mapping);
        Assert.Equal(new uint[] { 1002, 9000, 1001 }, restored.Companions[1].SkillOrder);
        Assert.Equal(profile.Skills[1002], restored.Companions[1].Skills[1002]);
        Assert.False(restored.Companions[1].Skills.ContainsKey(1003));
    }

    [Fact]
    public void MappingReplacementChangesOnlyDerivedSkillsAndKeepsS8InsertionOrder()
    {
        var state = Seed(Mapping);
        state = CompanionReceiveReducer.Apply(state, Skill(1002, 9), 7, Mapping);
        state = CompanionReceiveReducer.Apply(state, Skill(1003, -1), 7, Mapping);
        var replacement = Map(1005, 1001, 1003, 1002, 1006);
        var next = Observe(state, replacement);
        var profile = next.Companions[1];
        Assert.Equal(new uint[] { 1001, 1002, 1005 }, profile.SkillOrder);
        Assert.Equal(new CompanionLearnedSkill(2, 20, "S15技能槽＋NpcData"), profile.Skills[1001]);
        Assert.Equal(new CompanionLearnedSkill(1, 10, "S15技能槽＋NpcData"), profile.Skills[1005]);
        Assert.Equal(new CompanionLearnedSkill(9, 0, "S8-2"), profile.Skills[1002]);
        Assert.DoesNotContain(1003u, profile.Skills.Keys);
        Assert.DoesNotContain(1006u, profile.Skills.Keys);
        Assert.Same(next, Observe(next, replacement));
        Assert.Equal(1, state.Companions[1].Skills[1001].Level);
    }

    [Fact]
    public void StoredDuplicateSlotsKeepLastPositiveValueWhileLearnedUsesFirstPositiveValue()
    {
        var mapping = Map(1001, 0, 1001, 1002, 1002);
        var late = Observe(Seed(), mapping);
        var immediate = Seed(mapping);
        Assert.Equal(new uint[] { 1001, 1002 }, late.Companions[1].SkillOrder);
        Assert.Equal(new CompanionLearnedSkill(3, 30, "S15技能槽＋NpcData"), late.Companions[1].Skills[1001]);
        Assert.Equal(new CompanionLearnedSkill(4, 40, "S15技能槽＋NpcData"), late.Companions[1].Skills[1002]);
        Assert.Equal(immediate.Companions[1].Skills.OrderBy(pair => pair.Key), late.Companions[1].Skills.OrderBy(pair => pair.Key));
        var catalog = new CombatResourceCatalog
            { Npcs = ImmutableDictionary<uint, CombatResourceNpc>.Empty.Add(42, new() { Skills = mapping[42] }) };
        var actor = new CombatResourceActor { Pid = 42, MasterId = 7, NpcIndex = 1 };
        var learned = CombatResourceKnowledge.Learned(PlayerKnowledgeSnapshot.Empty, late, 7, actor, catalog);
        Assert.Equal(new uint[] { 1001, 1002 }, learned.Select(row => row.Id));
        Assert.Equal(1, learned[0].Level);
        Assert.Equal(10u, learned[0].Exp);
        Assert.Equal(4, learned[1].Level);
        Assert.Empty(CombatResourceKnowledge.Learned(PlayerKnowledgeSnapshot.Empty, late, 7, actor with { Pid = 43 }, catalog));
        Assert.Empty(CombatResourceKnowledge.Learned(PlayerKnowledgeSnapshot.Empty, late, 7, actor with { MasterId = 8 }, catalog));
    }

    [Fact]
    public void S8BeforeMappingAndOnArrivalWinsAndRemovalStaysUntilExplicitReaddition()
    {
        var state = CompanionReceiveReducer.Apply(Seed(), Skill(1001, 7));
        state = CompanionReceiveReducer.Apply(state, Skill(1002, 0));
        var next = CompanionReceiveReducer.Apply(state, Skill(1003, 9, sub: 3), 7, Mapping, reconcileNpcSkills: true);
        Assert.Equal(new uint[] { 1001, 1003 }, next.Companions[1].SkillOrder);
        Assert.Equal(new CompanionLearnedSkill(7, 0, "S8-2"), next.Companions[1].Skills[1001]);
        Assert.Equal(new CompanionLearnedSkill(9, 0, "S8-3"), next.Companions[1].Skills[1003]);
        Assert.Equal(new uint[] { 1002 }, next.Companions[1].RemovedSkillIds!.Value);
        var readded = CompanionReceiveReducer.Apply(next, Skill(1002, 6), 7, Mapping);
        Assert.Equal(new uint[] { 1001, 1003, 1002 }, readded.Companions[1].SkillOrder);
        Assert.Empty(readded.Companions[1].RemovedSkillIds!.Value);
        Assert.Same(readded, Observe(readded, Mapping));
    }

    [Fact]
    public void MetadataRefreshDoesNotReplayForeignHumanAttributes()
    {
        var state = CompanionReceiveReducer.Apply(Seed(), Skill(1001, 7));
        state = CompanionReceiveReducer.Apply(state, Skill(1001, 0, human: 9));
        state = CompanionReceiveReducer.Apply(state, Skill(1002, 0, human: 9));
        var next = Observe(state, Mapping);
        Assert.Equal(new CompanionLearnedSkill(7, 0, "S8-2"), next.Companions[1].Skills[1001]);
        Assert.Equal(new CompanionLearnedSkill(2, 20, "S15技能槽＋NpcData"), next.Companions[1].Skills[1002]);
        Assert.Empty(next.Companions[1].RemovedSkillIds!.Value);
        Assert.Equal(0, next.Attributes[1][0].Value);
        // A new S15 still intentionally replays every buffered local attribute.
        var refreshed = CompanionReceiveReducer.Apply(next, new CompanionSnapshotEvent([Companion()]), 7, Mapping);
        Assert.Equal(new uint[] { 1003 }, refreshed.Companions[1].SkillOrder);
        Assert.Equal(new uint[] { 1001, 1002 }, refreshed.Companions[1].RemovedSkillIds!.Value);
    }

    [Fact]
    public void MetadataResolutionUsesCurrentOccupantAndDoesNotRestoreDeletedCompanions()
    {
        var state = CompanionReceiveReducer.Apply(Seed(), Skill(1001, 7));
        state = CompanionReceiveReducer.Apply(state, Skill(1002, 0));
        var replacement = CompanionReceiveReducer.Apply(state, new CompanionSnapshotEvent([Companion(npc: 43)]));
        var wrongNpcMap = Observe(replacement, Mapping);
        Assert.Same(replacement, wrongNpcMap);
        Assert.Empty(wrongNpcMap.Attributes);
        var mapped = Observe(wrongNpcMap, Mapping.Add(43, [2001, 2002, 0, 0, 0]));
        Assert.Equal(43u, mapped.Companions[1].Data.NpcId);
        Assert.Equal(new uint[] { 2001, 2002 }, mapped.Companions[1].SkillOrder);
        Assert.Null(mapped.Companions[1].RemovedSkillIds);
        var deleted = CompanionReceiveReducer.Apply(mapped, new CompanionDeleteEvent(7, 1, 0), 7);
        Assert.Same(deleted, Observe(deleted, Mapping));
        Assert.Empty(deleted.Companions);
        Assert.Equal(new CompanionLearnedSkill(7, 0, "S8-2"), state.Companions[1].Skills[1001]);
    }

    [Fact]
    public void MissingMapIsANoopWithoutMetadataAndMetadataNeverCreatesReadinessOrOccupants()
    {
        Assert.Same(CompanionReceiveSnapshot.Empty, Observe(CompanionReceiveSnapshot.Empty, Mapping));
        var state = Seed();
        Assert.Same(state, Observe(state));
        state = CompanionReceiveReducer.Apply(state, Skill(1001, 7));
        Assert.Same(state, Observe(state));
        var resolved = Observe(state, Mapping);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<uint, CompanionLearnedSkill>)resolved.Companions[1].Skills).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<uint>)resolved.Companions[1].SkillOrder).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<CompanionSkillSlot>)resolved.Companions[1].Data.SkillSlots).Clear());
        Assert.Single(state.Companions[1].Skills);
    }
}
