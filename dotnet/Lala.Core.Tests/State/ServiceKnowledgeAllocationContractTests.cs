using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceKnowledgeAllocationContractTests
{
    private static readonly CombatKnowledgeCatalog Catalog = new()
        { ItemFitTypes = ImmutableDictionary<ushort, int>.Empty.Add(42, 3) };
    private static ServiceObservationContext Context(ServiceStateCoordinator state, CombatKnowledgeCatalog? catalog = null) =>
        new(state.Snapshot(), new(100) { KnowledgeCatalog = catalog });
    private static ServerLayoutEvent World(uint role = 17) => new(new WorldPlayerEvent(
        new(role, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0)));
    private static AttributeSetEvent Attribute(long value, string entity = "self", byte kind = 28) =>
        new(1, entity, 1, null, kind, "synthetic", 1, value, 0);
    private static AttributeAllocationSnapshot Pending(string stat = "str", BigInteger? expected = null) => new()
    {
        Pending = true, Acknowledged = true, SentAt = 1, Status = "imported",
        Expected = ImmutableDictionary<string, BigInteger>.Empty.Add(stat, expected ?? 22)
    };
    private static PlayerKnowledgeSnapshot Knowledge(long value = 20) => new()
        { Stats = ImmutableDictionary<string, long>.Empty.Add("str", value) };
    private static ItemSave Item() => new(null, 42, 1, 4, 2, 999, null, null,
        3, -100, 10, 1, 2, 3, null, 4, 5, 6, [new(7, 8)], true, 9, 10, null);
    private static BattleUnit Unit(uint pid = 17, ushort npc = 0, uint master = 0, byte col = 1) =>
        new(9, 4, pid, npc, master, col, 1, 100, 20, 90, 15, 3, 1, 0, 0, 0, 0, 1, 2, 3, 4, "synthetic",
            [.. Enumerable.Range(0, 9).Select(_ => new EquipmentAppearance(42, 6))]);
    private static ServiceStateCoordinator Boot()
    {
        var state = new ServiceStateCoordinator(); state.Apply(World(), Context(state)); return state;
    }

    [Fact]
    public void SamePacketKnowledgeCompletesAllocationBeforeLocalAttributeDispatch()
    {
        var raw = ImmutableDictionary<string, ImmutableDictionary<string, long>>.Empty.Add("self",
            ImmutableDictionary<string, long>.Empty.Add("28:0", 20));
        var prior = new ServiceStateSnapshot(local: new(session: new() { Attributes = raw }),
            playerKnowledge: Knowledge(), attributeAllocation: Pending());
        var state = new ServiceStateCoordinator(prior);
        var current = state.Apply(Attribute(22), Context(state));
        Assert.False(current.AttributeAllocation.Pending);
        Assert.Equal(22, current.PlayerKnowledge.Stats["str"]);
        Assert.Equal(22, current.Observation!.AllocationContext.PlayerStats["str"]);
        Assert.Same(current.PlayerKnowledge, current.Observation.AfterLivePlayerKnowledge);
        Assert.Equal(22, current.Local.Session.Attributes["self"]["28:0"]);
        Assert.Equal(20, prior.Local.Session.Attributes["self"]["28:0"]);
        Assert.True(prior.AttributeAllocation.Pending);
        Assert.Equal(prior.PacketCount + 1, current.PacketCount);
    }

    [Fact]
    public void RawAttributeMatchAndOtherEntitiesNeverStandInForPlayerKnowledge()
    {
        var raw = ImmutableDictionary<string, ImmutableDictionary<string, long>>.Empty.Add("self",
            ImmutableDictionary<string, long>.Empty.Add("28:0", 22));
        var state = new ServiceStateCoordinator(new(local: new(session: new() { Attributes = raw }),
            playerKnowledge: Knowledge(), attributeAllocation: Pending()));
        Assert.True(state.Apply(new AttributeAllocationSuccessEvent(), Context(state)).AttributeAllocation.Pending);
        Assert.True(state.Apply(Attribute(22, "other:17"), Context(state)).AttributeAllocation.Pending);
        Assert.False(state.Apply(Attribute(22), Context(state)).AttributeAllocation.Pending);
    }

    [Theory]
    [InlineData(long.MinValue)] [InlineData(long.MaxValue)] [InlineData(-4294967295L)]
    public void CurrentKnowledgeWidensExactlyWithoutClamping(long value)
    {
        var state = new ServiceStateCoordinator(new(playerKnowledge: Knowledge(value), attributeAllocation: Pending(expected: value)));
        var result = state.Apply(new AttributeAllocationSuccessEvent(), Context(state));
        Assert.False(result.AttributeAllocation.Pending);
        Assert.Equal(new BigInteger(value), result.Observation!.AllocationContext.PlayerStats["str"]);
    }

    [Fact]
    public void BattleProjectionFromLiveStageSurvivesEveryLocalDispatchPartition()
    {
        var state = Boot();
        state.Apply(new ServerLayoutEvent(new BattleStartEvent(1, 2, [Unit()])), Context(state));
        var previous = state.Snapshot();
        var equipment = state.Apply(new ServerLiveDataEvent(new BattleEquipEvent(17, 0, 3, 99, 123)), Context(state));
        Assert.Equal(new EquipmentAppearance(99, 123), equipment.Local.Battle.Units[0].Equips[2]);
        foreach (var observation in new ServerEvent[] { new HeartbeatRequestEvent(), Attribute(22),
            new BattleAttributeSetEvent([new(1, 1, 25, 321)]), World() })
            Assert.Equal(new EquipmentAppearance(99, 123), state.Apply(observation, Context(state)).Local.Battle.Units[0].Equips[2]);
        Assert.Equal(new EquipmentAppearance(42, 6), previous.Local.Battle.Units[0].Equips[2]);
        Assert.Equal(90u, equipment.Local.Battle.Units[0].Hp);
        Assert.Equal(321u, state.Snapshot().Local.Battle.Units[0].Hp);
        Assert.Equal(new EquipmentAppearance(42, 6), state.Snapshot().Local.Battle.Units[0].Layout.Equips[2]);
    }

    [Fact]
    public void BattleKnowledgeUsesPreLocalOccupantsAndOnlyReceiptKindsCompleteAllocation()
    {
        var local = new LocalStateCoordinator(); local.Apply(World());
        var state = new ServiceStateCoordinator(new(local: local.Snapshot(), attributeAllocation: Pending("hp", 321)));
        state.Apply(new ServerLayoutEvent(new BattleStartEvent(1, 2, [Unit()])), Context(state));
        var result = state.Apply(new BattleAttributeSetEvent([new(1, 1, 25, 321)]), Context(state));
        Assert.Equal(321, result.PlayerKnowledge.Stats["hp"]);
        Assert.True(result.AttributeAllocation.Pending);
        result = state.Apply(Attribute(123, "other:17", 255), Context(state));
        Assert.False(result.AttributeAllocation.Pending);
        Assert.Equal(321, result.PlayerKnowledge.Stats["hp"]);
    }

    [Fact]
    public void ResolverRunsBeforeBagWritesAndOmittedCatalogNeverReusesMappings()
    {
        var state = Boot();
        state.Apply(new ServerLiveDataEvent(new PlayerEquipDataEvent([Item()])), Context(state));
        var unresolved = state.Snapshot();
        var resolved = state.Apply(new ServerLiveDataEvent(new BagSnapshotEvent(8, [])), Context(state, Catalog));
        Assert.Empty(resolved.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Single(unresolved.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Equal(unresolved.Bag.Revision + 1, resolved.Bag.Revision);
        var omitted = state.Apply(new ServerLiveDataEvent(new PlayerEquipDataEvent([Item()])), Context(state));
        Assert.Single(omitted.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Null(omitted.Observation!.Inputs.KnowledgeCatalog);
    }

    [Fact]
    public void CompanionAddRunsOnceAndReturnedEquipmentRemainsAuthoritative()
    {
        var state = Boot();
        var data = new CompanionSnapshot(1, 42, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2,
            3, "synthetic", [new(1, 10)], [.. Enumerable.Range(0, 9).Select(_ => Item())], 0, 1, 2, 3, 4, 5, 6);
        state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([])), Context(state));
        state.Apply(new ServerLiveDataEvent(new CompanionAddEvent(17, data with { Index = null }, 0)), Context(state));
        Assert.Single(state.Snapshot().Companions.Companions);
        var current = state.Apply(new ServerLiveDataEvent(new BattleEquipEvent(17, 1, 3, 99, 123)), Context(state));
        Assert.Equal((ushort)99, current.Companions.Companions[1].EquipmentOverrides!.Value[2].ItemId);
        var later = state.Apply(Attribute(22), Context(state));
        Assert.Same(current.Companions, later.Companions);
        Assert.Equal((ushort)42, data.Equips[2].ItemId);
    }

    [Fact]
    public void DecodeAndLaterLocalFailureDoNotPublishResolvedEquipmentOrCount()
    {
        var state = Boot();
        state.Apply(new ServerLiveDataEvent(new PlayerEquipDataEvent([Item()])), Context(state));
        var before = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(new Packet(8, 1, [28]), Context(state, Catalog)));
        Assert.Same(before, state.Snapshot());
        Assert.Throws<ArgumentException>(() => state.Apply(new PositionSnapshotEvent(12, 17, 63501, 1, 2, 0, new(true)), Context(state, Catalog)));
        Assert.Same(before, state.Snapshot());
        Assert.Single(before.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Empty(state.Apply(new HeartbeatRequestEvent(), Context(state, Catalog)).PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
    }

    [Fact]
    public void TypedBattleFailureDoesNotPublishAnyOfTheThreeKnowledgeProjections()
    {
        var state = Boot();
        state.Apply(new ServerLiveDataEvent(new PlayerEquipDataEvent([Item()])), Context(state));
        state.Apply(new ServerLayoutEvent(new BattleStartEvent(1, 2, [Unit() with { Equips = [] }])), Context(state));
        var before = state.Snapshot();
        Assert.Throws<ArgumentException>(() => state.Apply(new ServerLiveDataEvent(new BattleEquipEvent(17, 0, 3, 99, 1)), Context(state, Catalog)));
        Assert.Same(before, state.Snapshot());
        Assert.Single(before.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Null(before.Local.Battle.Units[0].EquipmentOverrides);
    }

    [Fact]
    public void ImportedDomainsAreImmutableAndRoleChangesDoNotResetOrAuthorizeThem()
    {
        var allocation = Pending() with { Uncertain = true, Expected = ImmutableDictionary<string, BigInteger>.Empty.Add("str", BigInteger.One << 90) };
        var knowledge = Knowledge();
        var state = new ServiceStateCoordinator(new(playerKnowledge: knowledge, attributeAllocation: allocation));
        foreach (var role in new uint[] { 17, 18, 0 })
        {
            var next = state.Apply(World(role), Context(state));
            Assert.Same(allocation, next.AttributeAllocation);
            Assert.Same(knowledge.Stats, next.PlayerKnowledge.Stats);
            Assert.False(next.IsCompleteState);
            Assert.False(next.PlayerKnowledge.Ready);
        }
        var current = state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), new(1e12) { ResourceHeld = false }));
        Assert.Same(allocation, current.AttributeAllocation);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, BigInteger>)current.Observation!.AllocationContext.PlayerStats).Clear());
        foreach (var name in new[] { "PlayerKnowledge", "AttributeAllocation" })
            Assert.Null(typeof(ServiceStateSnapshot).GetProperty(name)!.SetMethod);
        Assert.Same(PlayerKnowledgeSnapshot.Empty, new ServiceStateSnapshot().PlayerKnowledge);
        Assert.Same(AttributeAllocationSnapshot.Empty, new ServiceStateSnapshot().AttributeAllocation);
    }
}
