using System.Collections.Immutable;
using Lala.Core.Activities;
using Lala.Core.Automation;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.State;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceStateContractTests
{
    [Fact]
    public void DefaultsRemainUnknownHeldAndIncomplete()
    {
        var state = new ServiceStateCoordinator();
        var inputs = new ServiceObservationInputs(10);
        Assert.True(inputs.ResourceHeld);
        Assert.Null(inputs.WorldCatalog);
        Assert.Null(inputs.DailyCatalog.Catalog);
        Assert.Null(inputs.DailyCatalog.Token);
        Assert.False(inputs.Bag.Ready);
        var result = state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), inputs));
        Assert.False(result.IsCompleteState);
        Assert.False(result.DailyTasks.CatalogReady);
        Assert.False(result.TimeCube.Ready);
        Assert.Empty(result.Recovery.Resources);
        Assert.Empty(result.Activities);
        Assert.Same(inputs, result.Observation!.Inputs);
    }

    [Fact]
    public void RoleSelectionResetsOnlyDomainsTheSourceResets()
    {
        var initial = Seed();
        var state = new ServiceStateCoordinator(initial);
        var result = state.Apply(new ServerLayoutEvent(new RoleListAvailableEvent([])), Context(state));
        Assert.Null(result.DailyTasks.RoleId);
        Assert.Null(result.TimeCube.RoleId);
        Assert.Null(result.DailyTasks.Pending);
        Assert.Null(result.TimeCube.Pending);
        Assert.Same(initial.Player, result.Player); // Python role selection retains the old player.
        Assert.Same(initial.Guild, result.Guild);
        Assert.Same(initial.Expedition, result.Expedition);
        Assert.Same(initial.Storage, result.Storage);
        Assert.Same(initial.Recovery, result.Recovery);
        Assert.Same(initial.Activities, result.Activities);
        Assert.Equal("role_selection", result.Phase);
        Assert.Equal("world_received", result.Observation!.BeforeLocal.Phase);
        Assert.Equal("role_selection", result.Observation.AfterLocal.Phase);
    }

    [Fact]
    public void SameRoleKeepsReceiptsButEveryWorldPlayerClearsActivities()
    {
        var initial = Seed();
        var state = new ServiceStateCoordinator(initial);
        var same = state.Apply(World(17), Context(state));
        Assert.Same(initial.DailyTasks.Pending, same.DailyTasks.Pending);
        Assert.Same(initial.TimeCube.Pending, same.TimeCube.Pending);
        Assert.Empty(same.Activities);
        var changed = state.Apply(World(18), Context(state));
        Assert.Equal(18u, changed.DailyTasks.RoleId);
        Assert.Equal(18u, changed.TimeCube.RoleId);
        Assert.Null(changed.DailyTasks.Pending);
        Assert.Null(changed.TimeCube.Pending);
        Assert.False(changed.TimeCube.Ready);
        Assert.Equal(17u, changed.Observation!.BeforeLocal.Player!.RoleId);
        Assert.Equal(18u, changed.Observation.AfterLocal.Player!.RoleId);
        Assert.Same(initial.Storage, changed.Storage);
        Assert.Same(initial.Expedition, changed.Expedition);
        Assert.Same(initial.Guild, changed.Guild);
    }

    [Fact]
    public void PreLocalIdentityControlsCubeGuildAndRoleActivities()
    {
        var state = new ServiceStateCoordinator(Seed());
        state.Apply(new ServerActivityEvent(23, 123, new(ActivityKind.Fishing, true, [18])), Context(state));
        Assert.DoesNotContain(ActivityKind.Fishing, state.Snapshot().Activities);
        state.Apply(new ServerTimeCubeEvent(1, new CubeInfo(1, 1, 3, 1)), Context(state));
        Assert.Equal(17u, state.Snapshot().TimeCube.RoleId);
        state.Apply(World(18), Context(state));
        var old = state.Snapshot();
        state.Apply(new ServerSocialEvent(new GuildLeaveResultEvent(0, 17)), Context(state));
        Assert.Same(old.Guild, state.Snapshot().Guild);
        state.Apply(new ServerSocialEvent(new GuildLeaveResultEvent(0, 18)), Context(state));
        Assert.False(state.Snapshot().Guild.Ready);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void BagCatalogAndElapsedTimeNeverSettleOrCreateAutomation(bool resourceHeld)
    {
        var state = new ServiceStateCoordinator(Seed());
        var input = new ServiceObservationInputs(1e12)
        {
            ResourceHeld = resourceHeld,
            DailyCatalog = new(new([new(1, 1, 100, 1, 1, [new(12, 0, 1)])], []), "synthetic-current"),
            Bag = new() { Ready = true, Reliable = true, Revision = 999, Capacity = 255 }
        };
        var daily = state.Apply(new ServerDailyTaskEvent(4, new TaskRewardNotice(1, [])), new(state.Snapshot(), input));
        Assert.True(daily.DailyTasks.Pending!.Notice);
        Assert.False(daily.DailyTasks.CatalogReady);
        Assert.Null(daily.DailyTasks.CatalogToken);
        Assert.Empty(daily.DailyTasks.Rows);
        Assert.Equal(20, daily.DailyTasks.Pending.Due);
        var cube = state.Apply(new ServerTimeCubeEvent(1, new CubeInfo(1, 0, 0, 0)), new(state.Snapshot(), input));
        Assert.True(cube.TimeCube.Pending!.CountUpdated);
        Assert.False(cube.TimeCube.Uncertain);
        Assert.Equal(15, cube.TimeCube.Pending.Due);
        state.Apply(new HeartbeatRequestEvent(), new(state.Snapshot(), input));
        Assert.Same(cube.TimeCube.Pending, state.Snapshot().TimeCube.Pending);
        Assert.Same(cube.DailyTasks.Pending, state.Snapshot().DailyTasks.Pending);
        Assert.Null(state.Snapshot().Storage.Storage.Pending);
        Assert.False(state.Snapshot().Expedition.Enabled);
    }

    [Fact]
    public void CurrentCatalogIsPerObservationAndCannotVerifyGeometry()
    {
        var state = new ServiceStateCoordinator(Seed());
        var change = new NavigationGeometryChangeEvent(62, 64, "fixture", true, 0);
        var known = new ServiceObservationInputs(1) { WorldCatalog = new([101]) };
        state.Apply(change, new(state.Snapshot(), known));
        Assert.False(state.Snapshot().Local.World.Navigation.Stale);
        state.Apply(change, Context(state)); // No fallback to the prior catalog.
        Assert.True(state.Snapshot().Local.World.Navigation.Stale);
        Assert.False(state.Snapshot().Local.World.Navigation.RuntimeGeometryVerified);
        Assert.True(state.Snapshot().Observation!.Inputs.ResourceHeld);
    }

    [Fact]
    public void StaleAndUnrelatedContextsAreRejectedBeforeDecodingOrCounting()
    {
        var state = new ServiceStateCoordinator();
        var stale = Context(state);
        state.Apply(new HeartbeatRequestEvent(), stale);
        var current = state.Snapshot();
        Assert.Throws<InvalidOperationException>(() => state.Apply(new Packet(26, 4, [1]), stale));
        Assert.Throws<InvalidOperationException>(() => state.Apply(new HeartbeatRequestEvent(),
            new(new ServiceStateSnapshot(local: current.Local), new(1))));
        Assert.Same(current, state.Snapshot());
        state.Apply(new HeartbeatRequestEvent(), Context(state));
        Assert.Equal(2, state.Snapshot().PacketCount);
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void NonFiniteTimeIsRejectedBeforeAnyObservation(double now)
    {
        var state = new ServiceStateCoordinator(Seed());
        var before = state.Snapshot();
        Assert.Throws<ArgumentOutOfRangeException>(() => state.Apply(World(18), Context(state, now)));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void ClockRegressionAndDuplicateObservationsAreNotInventedAsStaleness()
    {
        var state = new ServiceStateCoordinator();
        var value = new ServerTimeCubeEvent(1, new CubeInfo(0, 1, 3, 1));
        var first = state.Apply(value, Context(state, 200));
        var second = state.Apply(value, Context(state, 100));
        Assert.Equal(320, first.TimeCube.Deadline);
        Assert.Equal(220, second.TimeCube.Deadline);
        Assert.Equal(2, second.TimeCube.Revision);
        Assert.Equal(2, second.PacketCount);
    }

    [Fact]
    public void DecoderAndTypedReducerFailuresAreAtomicIncludingPacketCount()
    {
        var state = new ServiceStateCoordinator(Seed());
        var before = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(new Packet(124, 1, [1]), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Throws<ProtocolException>(() => state.Apply(new ServerDailyTaskEvent(1,
            new TaskSnapshot(new(0, 0, 0, 0, 0, 0, 0, 0, 0, 0), [], [], false, false)), Context(state)));
        Assert.Same(before, state.Snapshot());
        // LocalStateCoordinator alone increments before this typed failure. The new service
        // composition must not leak its private counter or partially changed world state.
        Assert.Throws<ArgumentException>(() => state.Apply(new PositionSnapshotEvent(12, 17, 63501, 1, 2,
            0, new(true)), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Throws<ProtocolException>(() => state.Apply(new ServerExpeditionEvent(13,
            new ExpeditionSnapshotEvent([], [], 0, 0)), Context(state)));
        Assert.Same(before, state.Snapshot());
        Assert.Throws<InvalidOperationException>(() => state.Apply(new BrokenEvent(), Context(state)));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void NullObservationsAndInputsNeverPublish()
    {
        var state = new ServiceStateCoordinator();
        var before = state.Snapshot();
        Assert.Throws<ArgumentNullException>(() => state.Apply((Packet)null!, Context(state)));
        Assert.Throws<ArgumentNullException>(() => state.Apply((ServerEvent)null!, Context(state)));
        Assert.Throws<ArgumentNullException>(() => state.Apply(new HeartbeatRequestEvent(), null!));
        Assert.Throws<ArgumentNullException>(() => state.Apply(new HeartbeatRequestEvent(), new(before, null!)));
        Assert.Throws<ArgumentNullException>(() => state.Apply(new HeartbeatRequestEvent(),
            new(before, new(1) { Bag = null! })));
        Assert.Throws<ArgumentNullException>(() => state.Apply(new HeartbeatRequestEvent(),
            new(before, new(1) { DailyCatalog = null! })));
        Assert.Same(before, state.Snapshot());
    }

    [Fact]
    public void UnsupportedAndMalformedMetadataEventsStillCountWithoutInventingState()
    {
        var state = new ServiceStateCoordinator();
        var initial = state.Snapshot();
        state.Apply(new UnsupportedServerDecoderEvent(99, 99, "fixture", 5), Context(state));
        state.Apply(new BattleAttributeInvalidEvent(1, 0, 1), Context(state));
        state.Apply(new UnimplementedServerEvent(255, 255, 0), Context(state));
        Assert.Equal(3, state.Snapshot().PacketCount);
        Assert.Equal(1, state.Snapshot().Local.Session.UnimplementedCount);
        Assert.Same(initial.DailyTasks, state.Snapshot().DailyTasks);
        Assert.Same(initial.TimeCube, state.Snapshot().TimeCube);
        Assert.Same(initial.Local.Battle, state.Snapshot().Local.Battle);
        Assert.False(state.Snapshot().IsCompleteState);
    }

    [Fact]
    public void OwnerAccessIsEnforcedButHistoricalPublicationsAreCrossThreadSafe()
    {
        var state = new ServiceStateCoordinator(Seed());
        var saved = state.Snapshot();
        var context = Context(state);
        foreach (var operation in new Action[] { state.AssertWriter, () => state.Snapshot(),
            () => state.Apply(new HeartbeatRequestEvent(), context), () => state.Apply(new Packet(1, 23), context) })
            Assert.IsType<InvalidOperationException>(OtherThread(operation));
        state.Apply(World(18), Context(state));
        Assert.Null(OtherThread(() =>
        {
            Assert.Equal(17u, saved.Player!.RoleId);
            Assert.NotNull(saved.TimeCube.Pending);
            Assert.NotNull(saved.DailyTasks.Pending);
            Assert.Contains(ActivityKind.Training, saved.Activities);
            Assert.Equal(0, saved.PacketCount);
        }));
    }

    private static ServiceObservationContext Context(ServiceStateCoordinator state, double now = 100) =>
        new(state.Snapshot(), new(now));

    private static ServerLayoutEvent World(uint role) => new(new WorldPlayerEvent(
        new(role, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], "Synthetic", 0)));

    private static ServiceStateSnapshot Seed()
    {
        var player = ((WorldPlayerEvent)World(17).Event).Player;
        var local = new LocalStateSnapshot(world: new WorldEventSnapshot { Player = player, Phase = "world_received" });
        var candidate = new TaskCandidate(TaskClaimKind.Task, 1, 100, 1, [], [new(12, 0, 1)]);
        return new(local, new()
        {
            RoleId = 17, Ready = true, GroupsReady = true, DailyGroup = 1, WeeklyGroup = 2,
            DailyProgress = [1, 1, 1, 1, 1, 1, 1, 1], WeeklyProgress = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            Pending = new(candidate, "synthetic", 17, 0, 20, false, 0, 1,
                ImmutableDictionary<int, long>.Empty, ImmutableDictionary<int, long>.Empty)
        }, new() { RoleId = 17, Ready = true, Count = 2, Pending = new(2, 1, false, 15) },
            guild: new() { Ready = true, Name = "Synthetic", Serial = 72, Level = 1 },
            activities: [ActivityKind.Training]);
    }

    private static Exception? OtherThread(Action operation)
    {
        Exception? error = null;
        var thread = new Thread(() => error = Record.Exception(operation));
        thread.Start(); thread.Join();
        return error;
    }

    private sealed record BrokenEvent() : ServerEvent(255, 254)
    {
        public override string Type => throw new InvalidOperationException("Synthetic late evidence failure");
    }
}
