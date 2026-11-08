using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class CompanionSkillMetadataStateTests
{
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> Mapping =
        ImmutableDictionary<uint, ImmutableArray<uint>>.Empty.Add(42, [1001, 1002, 1003, 0, 0]);
    private static CompanionSnapshot Companion() =>
        new(1, 42, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, "synthetic",
            [new(1, 10), new(2, 20), new(3, 30), new(0, 0), new(0, 0)], [], 0, 1, 2, 3, 4, 5, 6);
    private static ServiceObservationContext Context(ServiceStateCoordinator state,
        ImmutableDictionary<uint, ImmutableArray<uint>>? mapping = null) =>
        new(state.Snapshot(), new(100) { NpcSkills = mapping, ReconcileNpcSkills = true });
    private static AttributeSetEvent Skill(uint id, long level, byte human = 4) =>
        new(2, "follow:1", human, 1, 110, "skill", 1, level, id);

    [Fact]
    public void ReconciliationIsExplicitPerObservationAndDoesNotChangeDefaultPythonReceiveSemantics()
    {
        var state = new ServiceStateCoordinator();
        var unresolved = state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])),
            new(state.Snapshot(), new(100)));
        var unchanged = state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), new(100) { NpcSkills = Mapping }));
        Assert.False(unchanged.Observation!.Inputs.ReconcileNpcSkills);
        Assert.Same(unresolved.Companions, unchanged.Companions);
        var resolved = state.Apply(new HeartbeatRequestEvent(), Context(state, Mapping));
        Assert.True(resolved.Observation!.Inputs.ReconcileNpcSkills);
        Assert.Equal(3, resolved.Companions.Companions[1].Skills.Count);
        var retained = state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), new(100)));
        Assert.Same(resolved.Companions, retained.Companions);
        Assert.Null(retained.Observation!.Inputs.NpcSkills);
        Assert.False(retained.Observation.Inputs.ReconcileNpcSkills);
        var withdrawn = state.Apply(new HeartbeatRequestEvent(), Context(state));
        Assert.Empty(withdrawn.Companions.Companions[1].Skills);
        Assert.Equal(3, retained.Companions.Companions[1].Skills.Count);
    }

    [Fact]
    public void HeldServiceResolvesAndRevokesLateMetadataOnUnrelatedObservationsWithoutAuthority()
    {
        var state = new ServiceStateCoordinator();
        var unresolved = state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])), Context(state));
        var resolved = state.Apply(new HeartbeatRequestEvent(), Context(state, Mapping));
        Assert.Empty(unresolved.Companions.Companions[1].Skills);
        Assert.Equal(new uint[] { 1001, 1002, 1003 }, resolved.Companions.Companions[1].SkillOrder);
        Assert.Same(unresolved.Companions.Companions[1].Data, resolved.Companions.Companions[1].Data);
        Assert.Same(unresolved.Companions.Attributes, resolved.Companions.Attributes);
        Assert.Equal(unresolved.PacketCount + 1, resolved.PacketCount);
        Assert.True(resolved.Observation!.Inputs.ResourceHeld);
        Assert.False(resolved.IsCompleteState);
        Assert.False(resolved.PlayerKnowledge.Ready);
        var withdrawn = state.Apply(new HeartbeatRequestEvent(), Context(state));
        Assert.Empty(withdrawn.Companions.Companions[1].Skills);
        Assert.Equal(5, withdrawn.Companions.Companions[1].Data.SkillSlots.Length);
        Assert.Null(withdrawn.Observation!.Inputs.NpcSkills);
        Assert.Same(Mapping, resolved.Observation.Inputs.NpcSkills);
        var unchanged = state.Apply(new HeartbeatRequestEvent(), Context(state));
        Assert.Same(withdrawn.Companions, unchanged.Companions);
        Assert.Equal(3, resolved.Companions.Companions[1].Skills.Count);
    }

    [Fact]
    public void MetadataAndS8InOneObservationPreserveLiveAndLocalDispatchBoundaries()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])), Context(state));
        state.Apply(Skill(1001, 8), Context(state));
        state.Apply(Skill(1002, 0), Context(state));
        var mapped = state.Apply(Skill(1003, 9, human: 9), Context(state, Mapping));
        var profile = mapped.Companions.Companions[1];
        Assert.Equal(new CompanionLearnedSkill(8, 0, "S8-2"), profile.Skills[1001]);
        Assert.DoesNotContain(1002u, profile.Skills.Keys);
        Assert.Equal(new CompanionLearnedSkill(3, 30, "S15技能槽＋NpcData"), profile.Skills[1003]);
        Assert.Equal(9, mapped.Local.Session.Attributes["follow:1"]["110:1003"]);
        Assert.Equal(9, mapped.Companions.Attributes[1].Single(row => row.Parameter == 1003).Value);
        var stable = state.Apply(new HeartbeatRequestEvent(), Context(state, Mapping));
        Assert.Same(mapped.Companions, stable.Companions);
        var withdrawn = state.Apply(new HeartbeatRequestEvent(), Context(state));
        Assert.Equal(1001u, Assert.Single(withdrawn.Companions.Companions[1].Skills).Key);
        Assert.Equal(new uint[] { 1002 }, withdrawn.Companions.Companions[1].RemovedSkillIds!.Value);
        Assert.Same(mapped.Companions.Attributes, withdrawn.Companions.Attributes);
        Assert.Same(mapped.Local.Session.Attributes, withdrawn.Local.Session.Attributes);
    }

    [Fact]
    public void LateLocalFailureCannotPublishResolvedOrRevokedMetadata()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(new ServerLayoutEvent(new WorldPlayerEvent(
            new(17, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0))), Context(state));
        state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])), Context(state));
        var before = state.Snapshot();
        var invalid = new PositionSnapshotEvent(12, 17, 63501, 1, 2, 0, new(true));
        Assert.Throws<ArgumentException>(() => state.Apply(invalid, Context(state, Mapping)));
        Assert.Same(before, state.Snapshot());
        var resolved = state.Apply(new HeartbeatRequestEvent(), Context(state, Mapping));
        Assert.Throws<ArgumentException>(() => state.Apply(invalid, Context(state)));
        Assert.Same(resolved, state.Snapshot());
        Assert.Equal(3, resolved.Companions.Companions[1].Skills.Count);
        Assert.Empty(before.Companions.Companions[1].Skills);
    }
}
