using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class LocalStateContractTests
{
    [Fact]
    public void InitialProjectionsInheritSharedValuesOrRejectConflicts()
    {
        var session = new SessionEventSnapshot { Phase = "role_selection", PacketCount = BigInteger.Pow(2, 90) };
        var onlySession = new LocalStateSnapshot(session: session);
        Assert.Same(session, onlySession.Session);
        Assert.Equal(session.Phase, onlySession.World.Phase);
        Assert.Equal(session.PacketCount, onlySession.World.PacketCount);
        var world = new WorldEventSnapshot { Phase = "world_received", PacketCount = 12 };
        var onlyWorld = new LocalStateSnapshot(world: world);
        Assert.Same(world, onlyWorld.World);
        Assert.Equal(world.Phase, onlyWorld.Session.Phase);
        Assert.Equal(world.PacketCount, onlyWorld.Session.PacketCount);
        Assert.Throws<ArgumentException>(() => new LocalStateSnapshot(session, world));
        Assert.Throws<ArgumentException>(() => new LocalStateSnapshot(session, new()
            { Phase = session.Phase, PacketCount = session.PacketCount + 1 }));
        Assert.Throws<ArgumentException>(() => new LocalStateSnapshot(session, new()
            { Phase = "different", PacketCount = session.PacketCount }));
    }

    [Fact]
    public void IgnoredUnsupportedAndUnimplementedEventsEachCountExactlyOnce()
    {
        var coordinator = new LocalStateCoordinator();
        var old = coordinator.Snapshot();
        coordinator.Apply(new HeartbeatRequestEvent());
        coordinator.Apply(new UnsupportedServerDecoderEvent(23, 1, "inventory", 0));
        coordinator.Apply(new BattleAttributeInvalidEvent(1, 0, 1));
        coordinator.Apply(new Packet(255, 255));
        var snapshot = coordinator.Snapshot();
        Assert.Equal(4, snapshot.PacketCount);
        Assert.Equal(1, snapshot.Session.UnimplementedCount);
        Assert.Same(old.Battle, snapshot.Battle);
        Assert.Equal(0, old.PacketCount);
        Assert.Equal("disconnected", snapshot.Phase);
    }

    [Fact]
    public void BadPacketDecodingDoesNotCountOrPublishPartialState()
    {
        var state = new LocalStateCoordinator();
        var initial = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(new Packet(26, 4, [1])));
        Assert.Same(initial, state.Snapshot());
        state.Apply(new Packet(26, 4, [10, 0, 0, 0]));
        Assert.Equal(1, state.Snapshot().PacketCount);
        Assert.Equal(10u, state.Snapshot().Session.Gold.Amount);
    }

    [Fact]
    public void NullObservationsDoNotAdvanceCounters()
    {
        var state = new LocalStateCoordinator();
        var initial = state.Snapshot();
        Assert.Throws<ArgumentNullException>(() => state.Apply((Packet)null!));
        Assert.Throws<ArgumentNullException>(() => state.Apply((ServerEvent)null!));
        Assert.Throws<ArgumentNullException>(() => state.Apply((BattleCommandSentEvent)null!));
        Assert.Same(initial, state.Snapshot());
    }

    [Fact]
    public void TypedReducerFailureStillCountsTheObservationBeforeDispatch()
    {
        var state = WithWorld();
        var initial = state.Snapshot();
        Assert.Throws<ArgumentException>(() => state.Apply(new PositionSnapshotEvent(12, 17,
            63501, 1, 2, 0, new(true))));
        var failed = state.Snapshot();
        Assert.Equal(initial.PacketCount + 1, failed.PacketCount);
        Assert.Equal(failed.PacketCount, failed.World.PacketCount);
        Assert.Same(initial.Player, failed.Player);
        Assert.Same(initial.World.Location, failed.World.Location);
    }

    [Fact]
    public void GeometryCatalogContextIsExplicitAndLocalToCoordinator()
    {
        var initial = WithWorld().Snapshot();
        var unknownCatalog = new LocalStateCoordinator(initial);
        var ordinaryCatalog = new LocalStateCoordinator(initial, new(ImmutableHashSet.Create<ushort>(101)));
        var observation = new NavigationGeometryChangeEvent(62, 64, "fixture", true, 0);
        unknownCatalog.Apply(observation);
        ordinaryCatalog.Apply(observation);
        Assert.True(unknownCatalog.Snapshot().World.Navigation.Stale);
        Assert.False(ordinaryCatalog.Snapshot().World.Navigation.Stale);
        Assert.False(initial.World.Navigation.Stale);
        Assert.Equal(unknownCatalog.Snapshot().PacketCount, ordinaryCatalog.Snapshot().PacketCount);
    }

    [Fact]
    public void AllCoordinatorAccessRequiresOwnerButCapturedSnapshotsMayCrossThreads()
    {
        var state = WithWorld();
        var captured = state.Snapshot();
        Action[] operations = [state.AssertWriter, () => state.Snapshot(),
            () => state.Apply(new HeartbeatRequestEvent()), () => state.Apply(new Packet(1, 23)),
            () => state.Apply(new BattleCommandSentEvent(3, 1)),
            () => state.RememberPosition(18, 1, 2), () => state.ClearPositionHistory(),
            state.WaitForPosition, () => state.ConfirmLocation(101, 1, 2, "fixture")];
        foreach (var operation in operations)
            Assert.IsType<InvalidOperationException>(OnOtherThread(operation));
        Assert.Null(OnOtherThread(() =>
        {
            Assert.Equal(17u, captured.Player!.RoleId);
            Assert.Equal(captured.PacketCount, captured.World.PacketCount);
            Assert.Single(captured.World.Positions.Entries);
        }));
        Assert.Same(captured, state.Snapshot());
    }

    [Fact]
    public void PublisherOwnerAndCoordinatorOwnerAreBothCheckedBeforeSideEffects()
    {
        var state = new LocalStateCoordinator();
        var callbacks = 0;
        var clocks = 0;
        var publisher = new LocalStatePublisher(_ => callbacks++, 1, () => ++clocks);
        Action[] operations = [() => publisher.Publish(state), () => publisher.Flush(state),
            () => _ = publisher.Pending, () => _ = publisher.LastPublishedAt];
        foreach (var operation in operations)
            Assert.IsType<InvalidOperationException>(OnOtherThread(operation));
        LocalStateCoordinator? foreign = null;
        Assert.Null(OnOtherThread(() => foreign = new()));
        Assert.Throws<InvalidOperationException>(() => publisher.Publish(foreign!));
        Assert.Throws<InvalidOperationException>(() => publisher.Flush(foreign!));
        Assert.False(publisher.Pending);
        Assert.Null(publisher.LastPublishedAt);
        Assert.Equal(0, callbacks);
        Assert.Equal(0, clocks);
    }

    [Fact]
    public void CallbackReceivesCoherentImmediateStateAndStaysIndependentOfLaterUpdates()
    {
        var state = new LocalStateCoordinator();
        double now = 0;
        var received = new List<LocalStateSnapshot>();
        var publisher = new LocalStatePublisher(received.Add, 10, () => now);
        state.Apply(new GoldSnapshotEvent(100));
        publisher.Publish(state);
        var old = Assert.Single(received);
        state.Apply(new GoldDeltaEvent(2, -5, false));
        publisher.Publish(state);
        state.Apply(new LoginResultEvent(0, 0));
        publisher.Publish(state);
        Assert.Equal(95u, state.Snapshot().Session.Gold.Amount);
        Assert.Equal(3, state.Snapshot().PacketCount);
        Assert.Single(received);
        now = 10;
        publisher.Flush(state);
        Assert.Equal(2, received.Count);
        Assert.Equal("authenticated", received[1].World.Phase);
        Assert.Equal(3, received[1].World.PacketCount);
        Assert.Equal(100u, old.Session.Gold.Amount);
        Assert.Equal("disconnected", old.Phase);
    }

    [Fact]
    public void CallbackClockExceptionRetainsPendingAndPreviousSuccessfulTimestamp()
    {
        var state = new LocalStateCoordinator();
        int calls = 0, clocks = 0;
        var publisher = new LocalStatePublisher(_ => calls++, 0, () =>
        {
            clocks++;
            if (clocks == 4) throw new InvalidOperationException("clock unavailable after callback");
            return clocks;
        });
        publisher.Publish(state);
        Assert.Equal(2d, publisher.LastPublishedAt);
        Assert.Throws<InvalidOperationException>(() => publisher.Publish(state));
        Assert.True(publisher.Pending);
        Assert.Equal(2d, publisher.LastPublishedAt);
        Assert.Equal(2, calls);
        publisher.Flush(state);
        Assert.False(publisher.Pending);
        Assert.Equal(6d, publisher.LastPublishedAt);
        Assert.Equal(3, calls);
    }

    private static Exception? OnOtherThread(Action action)
    {
        Exception? error = null;
        var thread = new Thread(() => error = Record.Exception(action));
        thread.Start(); thread.Join();
        return error;
    }

    private static LocalStateCoordinator WithWorld()
    {
        var state = new LocalStateCoordinator();
        // Synthetic S3-1 fixture, no account credentials or live capture.
        state.Apply(new Packet(3, 1, Convert.FromHexString(
            "11000000016500080009000203040500000006000000070101080009000000000000000000000000000A00")));
        return state;
    }
}
