using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Automation;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceInventoryContractTests
{
    private static readonly ImmutableDictionary<ushort, bool> Rules = ImmutableDictionary<ushort, bool>.Empty.Add(42, true);
    private static ItemSave Item(byte index = 1, byte count = 1) =>
        new(index, 42, count, 0, 2, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, [new(1, 2)], false, 0, 0, 0);
    private static CompanionSnapshot Companion(byte? index = 1, uint npc = 42) =>
        new(index, npc, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, "synthetic", [new(1, 10)], [Item()], 0, 1, 2, 3, 4, 5, 6);
    private static ServiceObservationContext Context(ServiceStateCoordinator state, ServiceObservationInputs? input = null) =>
        new(state.Snapshot(), input ?? new(100));
    private static ServerLayoutEvent World(uint role) => new(new WorldPlayerEvent(
        new(role, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0)));
    private static AttributeSetEvent Attribute(byte kind = 25, long value = 999, byte human = 4) =>
        new(2, "follow:1", human, 1, kind, "synthetic", 1, value, 0);

    [Fact]
    public void LiveReceiveSlicesRemainExplicitlyPartialAndNonAuthorizing()
    {
        Assert.Equal(new[] { "bag", "companions" }, ServiceStateCoordinator.LiveReceiveSlices);
        Assert.False(ServiceStateCoordinator.ObserverOrder.Single(row => row.SourceFunction == "apply_live").Composed);
        Assert.True(ServiceStateCoordinator.ObserverOrder.Single(row => row.SourceFunction == "apply_crafting").Composed);
        var state = new ServiceStateCoordinator();
        var snapshot = state.Apply(new InitialDataCompleteEvent(), Context(state));
        Assert.True(snapshot.Crafting.Crafting.Ready);
        Assert.False(snapshot.Bag.Ready);
        Assert.False(snapshot.Companions.Ready);
        Assert.False(snapshot.IsCompleteState);
        Assert.True(snapshot.Observation!.Inputs.ResourceHeld);
        Assert.Null(snapshot.Observation.Inputs.CraftingSchedules);
        Assert.Null(snapshot.Observation.Inputs.ItemStackRules);
        Assert.Null(snapshot.Observation.Inputs.NpcSkills);
    }

    [Fact]
    public void ImportedStorageAndBagRulesAreOneMapAndContradictionsAreRejected()
    {
        var bag = new BagReceiveSnapshot { ServerStackable = Rules };
        var imported = new ServiceStateSnapshot(bag: bag);
        Assert.Same(bag, imported.Bag);
        Assert.Same(Rules, imported.Storage.ServerStackable);
        var storage = new StorageReceiveSnapshot { ServerStackable = Rules };
        imported = new(storage: storage);
        Assert.Same(storage, imported.Storage);
        Assert.Same(Rules, imported.Bag.ServerStackable);
        imported = new(storage: storage, bag: bag with { ServerStackable = Rules.ToImmutableDictionary() });
        Assert.Same(imported.Bag.ServerStackable, imported.Storage.ServerStackable);
        Assert.Throws<ArgumentException>(() => new ServiceStateSnapshot(storage: storage,
            bag: bag with { ServerStackable = Rules.SetItem(42, false) }));
        Assert.Throws<ArgumentException>(() => new ServiceStateSnapshot(storage: storage,
            bag: bag with { ServerStackable = ImmutableDictionary<ushort, bool>.Empty }));
    }

    [Fact]
    public void StorageObservationsOverrideCatalogEvenForInvalidMaterialSlots()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(new ServerLiveDataEvent(new BagSnapshotEvent(8, [])), Context(state));
        var before = state.Snapshot();
        var receipt = state.Apply(new ServerInventoryEvent(new StorageMaterialsAddEvent([new(0, 42, 3)])), Context(state));
        Assert.False(receipt.Storage.Storage.Materials.Reliable);
        Assert.True(receipt.Bag.ServerStackable![42]);
        Assert.Same(before.Bag, receipt.Observation!.BeforeObserversBag);
        Assert.Same(receipt.Bag, receipt.Observation.AfterLiveBag);
        var result = state.Apply(new ServerLiveDataEvent(new BagAddEvent(Item(count: 3), 0)),
            Context(state, new(100) { ItemStackRules = Rules.SetItem(42, false) }));
        Assert.Single(result.Bag.Items);
        Assert.Equal(3, result.Bag.Items[1].Count);
        Assert.Null(before.Bag.ServerStackable);
        Assert.Empty(before.Bag.Items);
    }

    [Fact]
    public void EmptyMaterialSnapshotImportsObservedEmptyMap()
    {
        var state = new ServiceStateCoordinator();
        var before = state.Snapshot();
        var result = state.Apply(new ServerInventoryEvent(new StorageMaterialsInitialEvent([])), Context(state));
        Assert.NotNull(result.Bag.ServerStackable);
        Assert.Empty(result.Bag.ServerStackable);
        Assert.Same(result.Storage.ServerStackable, result.Bag.ServerStackable);
        Assert.Null(before.Bag.ServerStackable);
    }

    [Fact]
    public void ExplicitScheduleContextIsPerObservationAndNeverInferredOrReused()
    {
        var state = new ServiceStateCoordinator();
        var packet = new Packet(64, 1, [1, 42, 0, 0, 0, 0, 0, 1, 10, 0, 0, 0, 1]);
        var absent = state.Apply(packet, Context(state));
        Assert.False(absent.Crafting.Crafting.Ready);
        Assert.Equal("unsupported_decoder", absent.Observation!.EventType);
        var legacy = state.Apply(packet, Context(state, new(100) { CraftingSchedules = CraftingScheduleContext.Legacy }));
        Assert.Equal((ushort)42, legacy.Crafting.Crafting.Queue[1].ItemId);
        var recipes = state.Apply(packet, Context(state, new(100)
            { CraftingSchedules = CraftingScheduleContext.FromRuntimeRows([new(42, 500)]) }));
        Assert.Equal((ushort)500, recipes.Crafting.Crafting.Queue[1].ItemId);
        Assert.Equal((ushort)42, recipes.Crafting.Crafting.Queue[1].RecipeId);
        var omittedAgain = state.Apply(packet, Context(state));
        Assert.Same(recipes.Crafting, omittedAgain.Crafting);
        Assert.Equal(4, omittedAgain.PacketCount);
        var before = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(packet, Context(state, new(100)
            { CraftingSchedules = CraftingScheduleContext.FromRuntimeRows([new(1, 500)]) })));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void StackAndNpcCatalogsDoNotLeakIntoLaterObservationInputs()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(new ServerLiveDataEvent(new BagSnapshotEvent(8, [])), Context(state));
        state.Apply(new ServerLiveDataEvent(new BagAddEvent(Item(count: 2), 0)), Context(state, new(100) { ItemStackRules = Rules }));
        var next = state.Apply(new ServerLiveDataEvent(new BagAddEvent(Item(count: 2), 0)), Context(state));
        Assert.False(next.Bag.Reliable);
        Assert.Equal(2, next.Bag.Items[1].Count);
        Assert.Null(next.Bag.ServerStackable);
        var snapshot = new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()]));
        var mapped = state.Apply(snapshot, Context(state, new(100)
            { NpcSkills = ImmutableDictionary<uint, ImmutableArray<uint>>.Empty.Add(42, [1001]) }));
        Assert.Contains(1001u, mapped.Companions.Companions[1].Skills.Keys);
        var unmapped = state.Apply(snapshot, Context(state));
        Assert.Empty(unmapped.Companions.Companions[1].Skills);
        Assert.Single(unmapped.Companions.Companions[1].Data.SkillSlots);
    }

    [Fact]
    public void ImportedSharedBuffersRequireExplicitOrderAndMatchingLocalValues()
    {
        var companions = CompanionReceiveSnapshot.Empty with
        { Attributes = ImmutableDictionary<ushort, ImmutableArray<CompanionAttribute>>.Empty.Add(1, [new(206, 0, 100), new(47, 0, 200)]) };
        var imported = new ServiceStateSnapshot(companions: companions);
        Assert.Equal(100, imported.Local.Session.Attributes["follow:1"]["206:0"]);
        Assert.Same(companions, imported.Companions);
        Assert.Throws<ArgumentException>(() => new ServiceStateSnapshot(local: imported.Local));
        Assert.Throws<ArgumentException>(() => new ServiceStateSnapshot(local: new(), companions: companions));
        var state = new ServiceStateCoordinator(new(local: imported.Local, companions: companions));
        var result = state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])), Context(state));
        Assert.Equal(200, result.Companions.Companions[1].StatOverrides["max_sp"]);
        Assert.Equal(new byte[] { 206, 47 }, result.Companions.Attributes[1].Select(row => row.Kind));
    }

    [Fact]
    public void LiveAttributeApplyAndLocalBufferWriteHaveSeparateSourceStages()
    {
        var initial = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty,
            new CompanionSnapshotEvent([Companion()]));
        var live = CompanionReceiveReducer.ApplyBeforeLocal(initial, Attribute());
        Assert.Equal(999, live.Companions[1].StatOverrides["hp"]);
        Assert.Empty(live.Attributes);
        var local = CompanionReceiveReducer.ObserveLocalAttribute(live, Attribute());
        Assert.Equal(999, local.Attributes[1][0].Value);
        Assert.Same(live.Companions, local.Companions);
        var foreignHuman = CompanionReceiveReducer.ApplyBeforeLocal(local, Attribute(value: 123, human: 9));
        Assert.Same(local, foreignHuman);
        var buffered = CompanionReceiveReducer.ObserveLocalAttribute(foreignHuman, Attribute(value: 123, human: 9));
        Assert.Equal(999, buffered.Companions[1].StatOverrides["hp"]);
        Assert.Equal(123, buffered.Attributes[1][0].Value);
    }

    [Fact]
    public void RoleSelectionRetainsIdentityAndBuffersUntilMatchingCompanionDeletion()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(World(17), Context(state));
        state.Apply(Attribute(), Context(state));
        state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent([Companion()])), Context(state));
        var previous = state.Snapshot();
        var roleList = state.Apply(new ServerLayoutEvent(new RoleListAvailableEvent([])), Context(state));
        Assert.Same(previous.Companions, roleList.Companions);
        Assert.Same(previous.Bag, roleList.Bag);
        Assert.Same(previous.Crafting, roleList.Crafting);
        state.Apply(World(18), Context(state));
        state.Apply(new ServerLiveDataEvent(new CompanionDeleteEvent(17, 1, 0)), Context(state));
        Assert.True(state.Snapshot().Local.Session.Attributes.ContainsKey("follow:1"));
        state.Apply(new ServerLiveDataEvent(new CompanionDeleteEvent(18, 1, 0)), Context(state));
        Assert.False(state.Snapshot().Local.Session.Attributes.ContainsKey("follow:1"));
        Assert.Empty(state.Snapshot().Companions.Attributes);
        Assert.NotEmpty(previous.Companions.Attributes);
        Assert.True(previous.Local.Session.Attributes.ContainsKey("follow:1"));
    }

    [Fact]
    public void TypedLateFailuresCannotPublishCraftingCompanionBuffersOrCounts()
    {
        var state = new ServiceStateCoordinator();
        state.Apply(Attribute(), Context(state));
        var before = state.Snapshot();
        Assert.Throws<InvalidOperationException>(() => state.Apply(new ServerInventoryEvent(new BrokenFurniture()), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Throws<ArgumentException>(() => state.Apply(new ServerLiveDataEvent(new CompanionSnapshotEvent(
            [Companion(1), Companion(null)])), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Empty(before.Companions.Companions);
        Assert.Equal(0, before.Crafting.Furniture.Revision);
        Assert.Equal(1, before.PacketCount);
    }

    [Fact]
    public void StaleContextsRejectNewDomainsBeforeDecodeAndNeverReuseInputCatalogs()
    {
        var state = new ServiceStateCoordinator();
        var stale = Context(state, new(100) { ItemStackRules = Rules, CraftingSchedules = CraftingScheduleContext.Legacy });
        state.Apply(new ServerLiveDataEvent(new BagSnapshotEvent(8, [])), stale);
        var before = state.Snapshot();
        Assert.Throws<InvalidOperationException>(() => state.Apply(new Packet(64, 1, [255]), stale));
        Assert.Throws<InvalidOperationException>(() => state.Apply(new ServerLiveDataEvent(new BagAddEvent(Item(), 0)), stale));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void BagUpdatesAndCraftCompletionsNeverSettlePendingDailyOrCubeRewards()
    {
        var candidate = new TaskCandidate(TaskClaimKind.Task, 1, 100, 1, [], []);
        var pending = new TaskPending(candidate, "synthetic", 17, 0, 20, false, 0, 1,
            ImmutableDictionary<int, long>.Empty.Add(42, 1), ImmutableDictionary<int, long>.Empty);
        var bag = BagReceiveSnapshot.Empty with { Revision = BigInteger.One << 90 };
        var craft = new CraftingReceiveSnapshot { Crafting = new() { Pending = "complete", AutoContinue = true } };
        var state = new ServiceStateCoordinator(new(bag: bag, crafting: craft,
            dailyTasks: new() { Pending = pending }, timeCube: new() { Pending = new(2, 1, false, 15) }));
        var receipt = state.Apply(new ServerLiveDataEvent(new BagSnapshotEvent(8, [Item()])), Context(state));
        Assert.Equal((BigInteger.One << 90) + 1, receipt.Bag.Revision);
        Assert.Same(bag, receipt.Observation!.BeforeObserversBag);
        Assert.Same(pending, receipt.DailyTasks.Pending);
        state.Apply(new ServerTimeCubeEvent(1, new CubeInfo(1, 1, 0, 0)), Context(state));
        state.Apply(new ServerDailyTaskEvent(4, new TaskRewardNotice(1, [])), Context(state));
        state.Apply(new HeartbeatRequestEvent(), Context(state, new(1e12) { ResourceHeld = false }));
        Assert.True(state.Snapshot().DailyTasks.Pending!.Notice);
        Assert.True(state.Snapshot().TimeCube.Pending!.CountUpdated);
        Assert.Equal(20, state.Snapshot().DailyTasks.Pending!.Due);
        Assert.Equal(15, state.Snapshot().TimeCube.Pending!.Due);
        Assert.Equal("complete", state.Snapshot().Crafting.Crafting.Pending);
        Assert.True(state.Snapshot().Crafting.Crafting.AutoContinue);
    }

    private sealed record BrokenFurniture() : CraftFurnitureEvent(1, "synthetic", "none")
    {
        public override bool AffectsGeometry => throw new InvalidOperationException("Synthetic failure after craft staging");
    }
}
