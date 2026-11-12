using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class WorldEventContractTests
{
    [Fact]
    public void DefaultsRepresentNoPositionNoRouteAndNoGeometryVerification()
    {
        var state = new WorldEventSnapshot();
        Assert.Equal("disconnected", state.Phase); Assert.Equal(BigInteger.Zero, state.PacketCount);
        Assert.Null(state.Player); Assert.Empty(state.Positions.Entries);
        Assert.Null(state.Location.Confirmed); Assert.False(state.Location.ConfirmedIsCurrent);
        Assert.Null(state.Location.RequestedDestination); Assert.Null(state.Location.ServerDestination);
        Assert.Null(state.LocalMovement); Assert.Null(state.MovementCheck);
        Assert.Null(state.Navigation.Scene); Assert.Equal(BigInteger.Zero, state.Navigation.Revision);
        Assert.False(state.Navigation.Stale); Assert.False(state.Navigation.RuntimeGeometryVerified);
        Assert.Empty(state.Navigation.Reasons); Assert.Null(state.Navigation.HouseContext);
    }

    [Fact]
    public void ArrivalRequiresAnOwnAuthoritativeSnapshotNotTargetOrWalkOrFinishedRoute()
    {
        var entered = WorldEventReducer.Apply(new(), new ServerLayoutEvent(new WorldPlayerEvent(Player())));
        var requested = WorldEventReducer.Apply(entered, new MovementRequestEvent(50, 60));
        var walked = WorldEventReducer.Apply(requested, new WalkEvent(17, 50, 60));
        var finished = walked with { LocalMovement = new("finished", new(101, 50, 60)) };
        var waiting = WorldEventReducer.WaitForPosition(finished);
        Assert.Equal(entered.Player, waiting.Player);
        Assert.Equal(entered.Location.Confirmed, waiting.Location.Confirmed);
        Assert.Equal("waiting", waiting.MovementCheck!.Status);
        Assert.False(waiting.Location.ConfirmedIsCurrent);
        var remote = WorldEventReducer.Apply(waiting, Position(role: 18));
        Assert.Same(waiting.Location, remote.Location); Assert.Same(waiting.MovementCheck, remote.MovementCheck);
        var confirmed = WorldEventReducer.Apply(remote, Position());
        Assert.Equal("matched", confirmed.MovementCheck!.Status);
        Assert.True(confirmed.Location.ConfirmedIsCurrent);
        Assert.Null(confirmed.Location.RequestedDestination); Assert.Null(confirmed.Location.ServerDestination);
        Assert.Equal((ushort)50, confirmed.Player!.X);
        Assert.Equal((ushort)8, entered.Player!.X);
        Assert.False(confirmed.Navigation.RuntimeGeometryVerified);
    }

    [Fact]
    public void SignedWalkCannotImpersonateAnUnsignedLocalIdentity()
    {
        var state = new WorldEventSnapshot { Player = Player(uint.MaxValue) };
        var result = WorldEventReducer.Apply(state, new WalkEvent(-1, 20, 30));
        Assert.NotNull(result.Positions.Get(-1)); Assert.Null(result.Positions.Get(uint.MaxValue));
        Assert.Same(state.Location, result.Location); Assert.Null(result.MovementCheck);
        Assert.Equal((ushort)8, result.Player!.X);
    }

    [Fact]
    public void OldestLocalSlotMovesToNewestBeforeTheActualRemoteEviction()
    {
        var state = new WorldEventSnapshot { Player = Player(1) };
        for (int id = 1; id <= 2048; id++) state = WorldEventReducer.RememberPosition(state, id, 8, 9);
        var before = state;
        var result = WorldEventReducer.RememberPosition(state, 2049, 10, 11);
        Assert.Equal(2048, result.Positions.Count);
        Assert.Null(result.Positions.Get(2)); Assert.NotNull(result.Positions.Get(1));
        Assert.Equal(3, result.Positions.Entries.First().RoleId);
        Assert.Equal(1, result.Positions.Entries.Last().RoleId);
        Assert.Equal(2049, result.Positions.Entries.ElementAt(2046).RoleId);
        Assert.Equal(Enumerable.Range(1, 2048).Select(x => (long)x), before.Positions.Entries.Select(x => x.RoleId));
        var refreshed = WorldEventReducer.RememberPosition(result, 3, 12, 13);
        Assert.Equal(3, refreshed.Positions.Entries.Last().RoleId);
        Assert.Equal(2048, refreshed.Positions.Count);
        Assert.Equal(new WorldCoordinates(8, 9), result.Positions.Get(3));
        Assert.Equal(new WorldCoordinates(12, 13), refreshed.Positions.Get(3));
    }

    [Fact]
    public void OneHundredThousandUpdatesStayBoundedAndKeepLocalSlot()
    {
        var state = new WorldEventSnapshot { Player = Player(1) };
        state = WorldEventReducer.RememberPosition(state, 1, 8, 9);
        for (int id = 2; id <= 100001; id++)
            state = WorldEventReducer.RememberPosition(state, id, (ushort)(id % 65536), 1);
        Assert.Equal(WorldPositionCache.Limit, state.Positions.Count);
        Assert.Equal(new WorldCoordinates(8, 9), state.Positions.Get(1));
        Assert.NotNull(state.Positions.Get(100001)); Assert.Null(state.Positions.Get(2));
        Assert.Equal(WorldPositionCache.Limit, state.Positions.Entries.Select(x => x.RoleId).Distinct().Count());
    }

    [Fact]
    public void ClearingHistoryKeepsObservedOwnSlotNotAnInventedConfirmedCoordinate()
    {
        var entered = WorldEventReducer.Apply(new(), new ServerLayoutEvent(new WorldPlayerEvent(Player())));
        var walked = WorldEventReducer.Apply(entered, new WalkEvent(17, 50, 60));
        var remote = WorldEventReducer.Apply(walked, new WalkEvent(18, 70, 80));
        var result = WorldEventReducer.ClearPositionHistory(remote);
        Assert.Equal(1, result.Removed); Assert.Single(result.State.Positions.Entries);
        Assert.Equal(new WorldCoordinates(50, 60), result.State.Positions.Get(17));
        Assert.Equal((ushort)8, result.State.Location.Confirmed!.X);
        Assert.False(result.State.Location.ConfirmedIsCurrent);
        Assert.Equal(0, WorldEventReducer.ClearPositionHistory(result.State).Removed);
        var unknown = remote with { Player = null };
        Assert.Equal(2, WorldEventReducer.ClearPositionHistory(unknown).Removed);
    }

    [Fact]
    public void RevisionsAndPacketNumbersDoNotWrapAndCountingBelongsToCaller()
    {
        var state = new WorldEventSnapshot
        {
            Player = Player(), PacketCount = BigInteger.One << 100,
            Navigation = new() { Revision = BigInteger.One << 110 }
        };
        var changed = WorldEventReducer.Apply(state, new NavigationGeometryChangeEvent(62, 64, "floor", true, 0));
        var positioned = WorldEventReducer.Apply(changed, Position());
        Assert.Equal(state.PacketCount, positioned.PacketCount);
        Assert.Equal(state.PacketCount, positioned.Location.Confirmed!.PacketNumber);
        Assert.Equal(state.Navigation.Revision + 2, positioned.Navigation.Revision);
    }

    [Fact]
    public void GeometryNoticeDoesNotPretendToRebuildOrLearnTheFloor()
    {
        var state = new WorldEventSnapshot
        {
            Player = Player(scene: 63501),
            Navigation = new() { RuntimeGeometryVerified = true, HouseContext = new(63501, true, 2) }
        };
        var result = WorldEventReducer.Apply(state, new NavigationGeometryChangeEvent(62, 64, "house_floor_changed", true, 0));
        Assert.True(result.Navigation.Stale);
        // Exact Python port: geometry notices preserve this field; stale blocks usage separately.
        Assert.True(result.Navigation.RuntimeGeometryVerified);
        Assert.Same(state.Navigation.HouseContext, result.Navigation.HouseContext);
        Assert.Equal((byte)2, result.Navigation.HouseContext!.Floor);
        var positioned = WorldEventReducer.Apply(result, Position(scene: 63501));
        Assert.False(positioned.Navigation.RuntimeGeometryVerified);
        Assert.True(positioned.Navigation.Stale);
        Assert.False(positioned.Navigation.HouseContext!.Verified);
        Assert.Null(positioned.Navigation.HouseContext.Floor);
    }

    [Fact]
    public void UnverifiedHouseContextCannotRetainSizesAndAnotherHouseCannotBorrowThem()
    {
        var first = WorldHouseContextRules.UpdateContext(null, 63501, new(true, 1, 2, 1))!;
        var second = WorldHouseContextRules.UpdateContext(first, 63501, new(true, 2, 3, 2))!;
        var back = WorldHouseContextRules.UpdateContext(second, 63501, new(true, 1))!;
        Assert.Equal((byte)2, back.Sizes[1]); Assert.Equal((byte)3, back.Sizes[2]);
        Assert.Single(first.Sizes);
        Assert.Empty(WorldHouseContextRules.UpdateContext(second, 63502, new(true, 1))!.Sizes);
        var unverified = WorldHouseContextRules.UpdateContext(second, 63501, null)!;
        Assert.False(unverified.Verified); Assert.Null(unverified.Floor); Assert.Empty(unverified.Sizes);
        Assert.Empty(WorldHouseContextRules.UpdateContext(unverified, 63501, new(true, 1))!.Sizes);
        Assert.Null(WorldHouseContextRules.UpdateContext(second, 101, new(true, 1)));
    }

    [Fact]
    public void MutableBuildersCannotAlterPublishedNestedSnapshotsOrCatalogEvidence()
    {
        var sizes = ImmutableDictionary.CreateBuilder<byte, byte>(); sizes.Add(1, 2);
        var reasons = ImmutableArray.CreateBuilder<string>(); reasons.Add("old");
        var equipment = ImmutableArray.CreateBuilder<EquipmentAppearance>(); equipment.Add(new(1, 2));
        var stages = ImmutableHashSet.CreateBuilder<ushort>(); stages.Add(101);
        var state = new WorldEventSnapshot
        {
            Player = Player() with { Equips = equipment.ToImmutable() },
            Navigation = new() { Reasons = reasons.ToImmutable(), HouseContext = new(63501, true, 1) { Sizes = sizes.ToImmutable() } }
        };
        var catalog = new WorldSceneCatalog(stages.ToImmutable());
        var changed = WorldEventReducer.Apply(state, new NavigationGeometryChangeEvent(62, 64, "new", true, 0));
        sizes.Clear(); reasons.Clear(); equipment.Clear(); stages.Clear();
        Assert.Single(state.Player.Equips); Assert.Single(changed.Player!.Equips);
        Assert.Equal(new[] { "old" }, state.Navigation.Reasons);
        Assert.Equal(new[] { "old", "new" }, changed.Navigation.Reasons);
        Assert.Equal((byte)2, changed.Navigation.HouseContext!.Sizes[1]);
        Assert.False(WorldObstacleScope.HouseScene(101, catalog));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, byte>)changed.Navigation.HouseContext.Sizes)[1] = 3);
        Assert.Throws<NotSupportedException>(() => ((IList<string>)changed.Navigation.Reasons)[0] = "mutable");
        Assert.Throws<NotSupportedException>(() => ((IList<EquipmentAppearance>)changed.Player.Equips)[0] = new(9, 9));
    }

    [Fact]
    public void DefaultImmutableReasonsAreHandledAsEmpty()
    {
        var state = new WorldEventSnapshot { Player = Player(), Navigation = new() { Reasons = default } };
        var changed = WorldEventReducer.Apply(state, new NavigationGeometryChangeEvent(62, 64, "one", true, 0));
        Assert.Equal(new[] { "one" }, changed.Navigation.Reasons);
        Assert.Empty(WorldEventReducer.Apply(state, Position()).Navigation.Reasons);
    }

    [Fact]
    public void TypedDispatchDoesNotTrustTypeTextAndOwnLeaveDoesNothing()
    {
        var state = new WorldEventSnapshot { Player = Player() };
        ServerEvent[] unrelated = [new HeartbeatRequestEvent(), new GoldSnapshotEvent(4),
            new MovementStopEvent(1), new UnsupportedServerDecoderEvent(65, 1, "tent", 0),
            new UnimplementedServerEvent(255, 255, 0), new TypeNameOnlyEvent(),
            new ServerSocialEvent(new NearbyLeaveEvent(17))];
        foreach (var observation in unrelated) Assert.Same(state, WorldEventReducer.Apply(state, observation));
    }

    [Fact]
    public void NoCatalogOrUnverifiedAliasesRemainUnknownRatherThanOrdinaryScenes()
    {
        Assert.Null(WorldObstacleScope.HouseScene(101));
        Assert.True(WorldObstacleScope.AffectsNavigation(true, "house", 101));
        Assert.Null(WorldObstacleScope.HouseScene(61501, new([])));
        Assert.Null(WorldObstacleScope.HouseScene(61501, new([], [])));
        Assert.False(WorldObstacleScope.HouseScene(61501, new([], [61501])));
        Assert.True(WorldObstacleScope.HouseScene(63501, new([63501])));
        Assert.True(WorldObstacleScope.HouseScene(10299, new([10299])));
        Assert.Null(WorldObstacleScope.HouseScene(62001, new([], [62001])));
    }

    [Fact]
    public void NullInputsAndIncompleteSyntheticVerifiedExtensionsFailWithoutChangingInputs()
    {
        var state = new WorldEventSnapshot();
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.Apply(null!, new HeartbeatRequestEvent()));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.Apply(state, null!));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.RememberPosition(null!, 1, 2, 3));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.ClearPositionHistory(null!));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.WaitForPosition(null!));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.ConfirmLocation(null!, 1, 2, 3, "fixture"));
        Assert.Throws<ArgumentNullException>(() => WorldEventReducer.ConfirmLocation(state, 1, 2, 3, null!));
        Assert.Throws<ArgumentException>(() => WorldHouseContextRules.UpdateContext(null, 63501, new(true)));
        Assert.Throws<ArgumentException>(() => WorldHouseContextRules.UpdateContext(null, 63501, new(true, 1, 2)));
        Assert.Null(state.Location.Confirmed);
    }

    [Fact]
    public void CacheRoleIdentityIsIndependentOfCurrentCulture()
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            var state = WorldEventReducer.RememberPosition(new() { Player = Player(uint.MaxValue) }, uint.MaxValue, 8, 9);
            state = WorldEventReducer.RememberPosition(state, -1, 10, 11);
            Assert.Equal(new long[] { uint.MaxValue, -1 }, state.Positions.Entries.Select(x => x.RoleId));
            Assert.Equal(1, WorldEventReducer.ClearPositionHistory(state).Removed);
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }

    private static WorldPlayer Player(uint id = 17, ushort scene = 101) =>
        new(id, 1, scene, 8, 9, 2, 3, 4, 5, 6, 7, true, [], "synthetic", 10);
    private static PositionSnapshotEvent Position(uint role = 17, ushort scene = 101) =>
        new(12, role, scene, 50, 60, 0, new(false));
    private sealed record TypeNameOnlyEvent() : ServerEvent(255, 255)
    {
        public override string Type => "world_player";
    }
}
