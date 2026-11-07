using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Instances;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Social;
using Lala.Core.State;
using Lala.Core.World;
using Lala.Core.World.Tent;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceSocialInstanceContractTests
{
    private static ServiceObservationContext Context(ServiceStateCoordinator state, ServiceObservationInputs? inputs = null) =>
        new(state.Snapshot(), inputs ?? new(100));
    private static ServiceObservationInputs Declared(params ushort[] ids) => new(100) { DeclaredMainCatalogMapIds = ids.ToImmutableHashSet() };
    private static ServerLayoutEvent World(uint role = 17, ushort scene = 101) => new(new WorldPlayerEvent(
        new(role, 0, scene, 1, 2, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0)));
    private static PositionSnapshotEvent Position(ushort scene, uint role = 17) => new(12, role, scene, 1, 2, 0, new(false));
    private static ServerInstanceEvent Instance(InstanceEvent value) => new(85, 5, value);
    private static StateValue Map(params (string Key, object? Value)[] entries) => StateValue.Map(entries.Select(entry =>
        KeyValuePair.Create(entry.Key, entry.Value is StateValue value ? value : StateValue.Scalar(entry.Value))));
    private static StateValue Seed(StateValue state, params (string Key, object? Value)[] entries) =>
        StateValue.Map(state.MapValue.SetItems(Map(entries).MapValue));
    private static string Text(StateValue state, string key) => Assert.IsType<string>(state[key].ScalarValue);
    private static InstanceReceiveSnapshot Started() => new()
    {
        Main = Seed(InstanceReceiveSnapshot.Empty.Main, ("room", Map(("room_id", 500), ("host_id", 17))),
            ("phase", "started"), ("enter_pending", Map(("room_id", 500), ("started", 0))))
    };
    private static ServiceStateCoordinator Boot(PartyEventSnapshot? party = null, InstanceReceiveSnapshot? instances = null,
        TentReceiveSnapshot? tent = null)
    {
        var local = new LocalStateCoordinator(); local.Apply(World());
        return new(new(local: local.Snapshot(), party: party, instances: instances, tent: tent));
    }
    private static TentReceiveSnapshot Entering(bool received = false) => new()
    {
        Scene = 101, Pending = new("enter") { Due = 0 }, Uncertain = true,
        EntryContext = new("enter") { SourceScene = 101, FurnitureReceived = received }
    };

    [Fact]
    public void NewDomainsAreReadonlyImmutableObservationsWithEmptyDeclaredCatalog()
    {
        var state = new ServiceStateSnapshot();
        Assert.Same(PartyEventSnapshot.Empty, state.Party);
        Assert.Same(InstanceReceiveSnapshot.Empty, state.Instances);
        Assert.Same(TentReceiveSnapshot.Empty, state.Tent);
        foreach (var name in new[] { "Party", "Instances", "Tent" })
            Assert.Null(typeof(ServiceStateSnapshot).GetProperty(name)!.SetMethod);
        Assert.Empty(new ServiceObservationInputs(1).DeclaredMainCatalogMapIds);
        Assert.False(state.IsCompleteState);
        Assert.False(Assert.IsType<bool>(state.Instances.Main["ready"].ScalarValue));
        Assert.False(state.Instances.Main.MapValue.ContainsKey("verified"));
        Assert.False(state.Local.World.Navigation.RuntimeGeometryVerified);
    }

    [Fact]
    public void FirstAndChangedWorldIdentityCannotRetroactivelyConfirmMainEntry()
    {
        var state = new ServiceStateCoordinator(new(instances: Started(), tent: Entering()));
        var first = state.Apply(World(17, 500), Context(state, Declared(500)));
        Assert.Null(first.Observation!.BeforeLocal.Player);
        Assert.Equal(17u, first.Player!.RoleId);
        Assert.Equal("started", Text(first.Instances.Main, "phase"));
        Assert.NotNull(first.Instances.Main["enter_pending"].MapValue);
        Assert.Equal((ushort)500, first.Tent.Scene);
        Assert.Null(first.Tent.Pending);
        var changed = state.Apply(World(18, 500), Context(state, Declared(500)));
        Assert.Equal("started", Text(changed.Instances.Main, "phase"));
        var same = state.Apply(World(18, 500), Context(state, Declared(500)));
        Assert.Equal("entered", Text(same.Instances.Main, "phase"));
        Assert.Null(same.Instances.Main["enter_pending"].ScalarValue);
        Assert.Equal("started", Text(first.Instances.Main, "phase"));
    }

    [Fact]
    public void InstanceCatalogDeclarationsAreIndependentPerObservationAndNeverInferred()
    {
        var state = Boot(instances: Started());
        var unrelated = new ServiceObservationInputs(100) { WorldCatalog = new([101, 500], [500]) };
        var withoutDeclaration = state.Apply(Position(500), Context(state, unrelated));
        Assert.Equal("started", Text(withoutDeclaration.Instances.Main, "phase"));
        state.Apply(new HeartbeatRequestEvent(), Context(state, Declared(500)));
        var omitted = state.Apply(Position(500), Context(state));
        Assert.Equal("started", Text(omitted.Instances.Main, "phase"));
        var other = state.Apply(Position(500, 18), Context(state, Declared(500)));
        Assert.Equal("started", Text(other.Instances.Main, "phase"));
        var matched = state.Apply(Position(500), Context(state, Declared(500)));
        Assert.Equal("entered", Text(matched.Instances.Main, "phase"));
        Assert.True(matched.Observation!.Inputs.ResourceHeld);
        Assert.False(matched.Local.World.Navigation.RuntimeGeometryVerified);
    }

    [Theory]
    [InlineData(true)] [InlineData(false)]
    public void TentUsesCurrentPostDispatchSceneAndDoesNotReuseCatalog(bool furnitureFirst)
    {
        var state = Boot(tent: Entering());
        var room = new ServerInventoryEvent(new FurnitureSnapshotEvent(17, []));
        var known = new ServiceObservationInputs(100) { WorldCatalog = new([101]) };
        state.Apply(new HeartbeatRequestEvent(), Context(state, known));
        if (furnitureFirst) state.Apply(room, Context(state));
        var moved = state.Apply(Position(63501), Context(state));
        Assert.Equal((ushort)63501, moved.Player!.Scene);
        Assert.Equal((ushort)63501, moved.Tent.Scene);
        Assert.False(moved.Tent.Inside);
        var confirmed = state.Apply(room, Context(state, known));
        Assert.True(confirmed.Tent.Inside);
        Assert.Equal((ushort)63501, confirmed.Tent.InteriorScene);
        Assert.Equal((ushort)101, confirmed.Tent.ReturnScene);
        Assert.Null(confirmed.Tent.EntryContext);
        var returned = state.Apply(Position(101), Context(state, known));
        Assert.False(returned.Tent.Inside);
        Assert.False(moved.Tent.Inside);
    }

    [Fact]
    public void RoleListRetainsPartyInstanceAndTentStateWhileWorldResetsOnlyTent()
    {
        var party = PartyEventSnapshot.Empty with { Teams = [new(17, [17, 18])] };
        var state = Boot(party, Started(), Entering());
        var prior = state.Snapshot();
        var selection = state.Apply(new ServerLayoutEvent(new RoleListAvailableEvent([])), Context(state));
        Assert.Same(prior.Party, selection.Party);
        Assert.Same(prior.Instances, selection.Instances);
        Assert.Same(prior.Tent, selection.Tent);
        Assert.Same(prior.Player, selection.Player);
        var world = state.Apply(World(18, 500), Context(state, Declared(500)));
        Assert.Same(prior.Party, world.Party);
        Assert.Equal("started", Text(world.Instances.Main, "phase"));
        Assert.Null(world.Tent.EntryContext);
        Assert.Equal((ushort)500, world.Tent.Scene);
        Assert.NotNull(prior.Tent.EntryContext);
    }

    [Theory]
    [InlineData(true)] [InlineData(false)]
    public void ElapsedDeadlinesAndResourceInputsNeverExpireRequestOrStartAnyAction(bool held)
    {
        var request = new PartyRequest("team_invite:18", "team_invite", 18, 1, "pending");
        var party = PartyEventSnapshot.Empty with
        {
            Requests = ImmutableDictionary<string, PartyRequest>.Empty.Add(request.Key, request),
            Outbound = ImmutableDictionary<string, PartyOutboundRequest>.Empty.Add("invite:18", new(18, 1)),
            EnabledRequested = true
        };
        var state = Boot(party, Started(), Entering());
        var before = state.Snapshot();
        var after = state.Apply(new HeartbeatRequestEvent(), Context(state, new(1e12)
            { ResourceHeld = held, DeclaredMainCatalogMapIds = [500], WorldCatalog = new([101]) }));
        Assert.Same(before.Party, after.Party);
        Assert.Same(before.Instances, after.Instances);
        Assert.Same(before.Tent, after.Tent);
        Assert.Single(after.Party.Requests);
        Assert.Single(after.Party.Outbound);
        Assert.True(after.Party.EnabledRequested);
        Assert.False(Assert.IsType<bool>(after.Instances.Coop["auto_claim_enabled"].ScalarValue));
        Assert.Equal(0, after.Tent.Pending!.Due);
    }

    [Fact]
    public void PartySelfPositionPrunesNearbyAndRoleSelectionDoesNotChangeCurrentIdentity()
    {
        var nearby = new NearbyPlayer(18, 0, 0, 0, 101, 1, 2, 0, 0, "Synthetic");
        var state = Boot(PartyEventSnapshot.Empty with { Nearby = ImmutableDictionary<uint, NearbyPlayer>.Empty.Add(18, nearby) });
        var initial = state.Snapshot();
        state.Apply(new ServerLayoutEvent(new RoleListAvailableEvent([])), Context(state));
        state.Apply(Position(500, 18), Context(state));
        Assert.Equal((ushort)500, state.Snapshot().Party.Nearby[18].Scene);
        state.Apply(Position(101), Context(state));
        Assert.Empty(state.Snapshot().Party.Nearby);
        Assert.Equal((ushort)101, initial.Party.Nearby[18].Scene);
    }

    [Fact]
    public void FailureAfterPartyAndInstanceStagingRollsBackAllDomainsAndCount()
    {
        var nearby = new NearbyPlayer(18, 0, 0, 0, 101, 1, 2, 0, 0, "Synthetic");
        var party = PartyEventSnapshot.Empty with { Nearby = ImmutableDictionary<uint, NearbyPlayer>.Empty.Add(18, nearby) };
        var instances = Started() with { Main = Seed(Started().Main, ("room", Map(("room_id", 63501), ("host_id", 17)))) };
        var state = Boot(party, instances, Entering(true));
        var before = state.Snapshot();
        // Both pre-local observers would change: nearby clears and main entry confirms.
        // Invalid house-floor evidence fails in local dispatch, after those private stages.
        var broken = new PositionSnapshotEvent(12, 17, 63501, 1, 2, 0, new(true));
        Assert.Empty(PartyEventReducer.Apply(before.Party, broken, 100, 17).Nearby);
        var privatelyReduced = InstanceReceiveReducer.Apply(before.Instances, broken,
            new() { OwnRoleId = 17, DeclaredMainCatalogMapIds = [63501] }, 100);
        Assert.Equal("entered", Text(privatelyReduced.Main, "phase"));
        Assert.Throws<ArgumentException>(() => state.Apply(broken, Context(state, Declared(63501))));
        Assert.Same(before, state.Snapshot());
        Assert.Single(before.Party.Nearby);
        Assert.Equal("started", Text(before.Instances.Main, "phase"));
        Assert.False(before.Tent.Inside);
        Assert.Equal(1, before.PacketCount);
    }

    [Fact]
    public void PostLocalTentFailureCannotPublishEvenThePrivateLocalCounter()
    {
        var state = Boot(instances: Started(), tent: Entering());
        var before = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(new TentSceneListEvent(default), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Same(before.Local, state.Snapshot().Local);
        state.Apply(new TentSceneListEvent([]), Context(state));
        Assert.Equal(before.PacketCount + 1, state.Snapshot().PacketCount);
    }

    [Fact]
    public void InstanceTypedFailureAndMalformedWireRemainAtomic()
    {
        var state = Boot(instances: Started());
        var before = state.Snapshot();
        Assert.ThrowsAny<Exception>(() => state.Apply(Instance(new MainRoomListEvent(default)), Context(state)));
        Assert.Same(before, state.Snapshot());
        foreach (var packet in new[] { new Packet(85, 5, [1]), new Packet(65, 3, [1]), new Packet(13, 6, [1]) })
        {
            Assert.Throws<ProtocolException>(() => state.Apply(packet, Context(state)));
            Assert.Same(before, state.Snapshot());
        }
    }

    [Fact]
    public void StaleAndNullDeclarationContextsFailBeforeDecodeOrDomainChanges()
    {
        var state = Boot(instances: Started(), tent: Entering());
        var stale = Context(state, Declared(500));
        state.Apply(new HeartbeatRequestEvent(), stale);
        var before = state.Snapshot();
        Assert.Throws<InvalidOperationException>(() => state.Apply(new Packet(85, 5, [1]), stale));
        Assert.Throws<ArgumentNullException>(() => state.Apply(new Packet(85, 5, [1]),
            Context(state, new(100) { DeclaredMainCatalogMapIds = null! })));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void DuplicatePartyRequestsAndInstanceListsObserveClockRegressionWithoutDeduplication()
    {
        var state = new ServiceStateCoordinator(new(local: new(session: new SessionEventSnapshot { PacketCount = BigInteger.One << 100 })));
        var invite = new ServerSocialEvent(new TeamInviteEvent(18));
        var first = state.Apply(invite, Context(state, new(200)));
        state.Apply(invite, Context(state, new(100)));
        state.Apply(Instance(new MainRoomListEvent([])), Context(state, new(-10)));
        var final = state.Apply(Instance(new MainRoomListEvent([])), Context(state, new(-20)));
        Assert.Equal(260, first.Party.Requests["team_invite:18"].Expires);
        Assert.Equal(160, final.Party.Requests["team_invite:18"].Expires);
        Assert.Equal(-20d, final.Instances.Main["list_updated_at"].ScalarValue);
        Assert.Equal((BigInteger.One << 100) + 4, final.PacketCount);
        Assert.Equal(final.PacketCount, final.Observation!.BeforeLocal.PacketCount);
        Assert.Equal(final.PacketCount, final.Observation.AfterLocal.PacketCount);
    }

    [Fact]
    public void InstanceImportsRetainDeepImmutableStateValueAndReadonlyForeignFields()
    {
        var source = new List<StateValue> { Map(("seen", 17)) };
        var custom = StateValue.Tuple(StateValue.Scalar(BigInteger.One << 100), StateValue.List(source));
        var initial = Started() with { Main = Seed(Started().Main, ("readonly_import", custom)) };
        var state = Boot(instances: initial);
        source.Clear();
        state.Apply(Instance(new MainRoomListEvent([])), Context(state));
        var result = state.Snapshot();
        Assert.Same(custom, result.Instances.Main["readonly_import"]);
        Assert.Single(custom[1].SequenceValue);
        Assert.Same(custom, initial.Main["readonly_import"]);
        Exception? error = null;
        var thread = new Thread(() =>
        {
            error = Record.Exception(() =>
            {
                Assert.Same(custom, result.Instances.Main["readonly_import"]);
                Assert.False(result.Tent.Inside);
                Assert.Empty(result.Party.Teams);
                Assert.Throws<InvalidOperationException>(() => state.Apply(new HeartbeatRequestEvent(), new(result, new(100))));
            });
        });
        thread.Start(); thread.Join(); Assert.Null(error);
    }
}
