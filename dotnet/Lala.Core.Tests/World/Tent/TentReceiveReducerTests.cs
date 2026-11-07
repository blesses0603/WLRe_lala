using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.World;
using Lala.Core.World.Tent;
using Xunit;

namespace Lala.Core.Tests.World.Tent;

public sealed class TentReceiveReducerTests
{
    private static readonly TentCamp OwnCamp = new(17, 42, uint.MaxValue, 0, 255, 1);
    private static TentReceiveSnapshot Apply(TentReceiveSnapshot state, ServerEvent observation,
        uint? role = 17, ushort? scene = 100, WorldSceneCatalog? catalog = null) =>
        TentReceiveReducer.Apply(state, observation, role, scene, catalog);
    private static PositionSnapshotEvent Position(ushort scene, uint role = 17) => new(12, role, scene, 0, 0, 0, new(false));
    private static ServerInventoryEvent Room(uint owner = 17) => new(new FurnitureSnapshotEvent(owner, []));
    private static TentReceiveSnapshot Entering(bool uncertain = false) => new()
    {
        Scene = 100, SceneKnown = true, Visible = true, DeployedScene = 100, TentId = 42,
        X = 1, Y = 2, Kind = 3, Make = 4, Uncertain = uncertain,
        Pending = new("enter") { Due = 123.25 },
        EntryContext = new("enter") { SourceScene = 100, FurnitureReceived = false }
    };

    [Fact]
    public void ColdDefaultsContainNoDeploymentOrActionAuthority()
    {
        var state = TentReceiveSnapshot.Empty;
        Assert.Null(state.Scene); Assert.False(state.SceneKnown); Assert.False(state.Visible);
        Assert.Null(state.DeployedScene); Assert.Null(state.TentId); Assert.Null(state.X); Assert.Null(state.Y);
        Assert.Null(state.Kind); Assert.Null(state.Make); Assert.False(state.Inside); Assert.Null(state.AccessOpen);
        Assert.Null(state.Pending); Assert.False(state.Uncertain); Assert.Null(state.InteriorScene);
        Assert.Null(state.ReturnScene); Assert.Null(state.EntryContext);
        Assert.Equal("帳篷狀態待伺服器同步", state.Status);
        Assert.Equal(state, new TentReceiveSnapshot());
    }

    [Fact]
    public void EmptySceneListIsVisibilityEvidenceNotARetractionOrActionAcknowledgment()
    {
        var state = Apply(Entering(true), new TentAddedEvent(OwnCamp));
        var next = Apply(state, new TentSceneListEvent([]), scene: 101);
        Assert.False(next.Visible); Assert.True(next.SceneKnown); Assert.Equal((ushort)101, next.Scene);
        Assert.Equal(state.DeployedScene, next.DeployedScene); Assert.Equal(state.TentId, next.TentId);
        Assert.Equal(state.X, next.X); Assert.Equal(state.Y, next.Y);
        Assert.Same(state.Pending, next.Pending); Assert.Same(state.EntryContext, next.EntryContext);
        Assert.True(next.Uncertain); Assert.Equal(state.Status, next.Status);
    }

    [Fact]
    public void FirstDuplicateOwnCampWinsAndUnknownIdentityNeverMatchesZero()
    {
        var camps = ImmutableArray.Create(OwnCamp with { OwnerId = 18 }, OwnCamp, OwnCamp with { TentId = 9 });
        var state = Apply(TentReceiveSnapshot.Empty, new TentSceneListEvent(camps));
        Assert.Equal((ushort)42, state.TentId);
        var unknown = Apply(TentReceiveSnapshot.Empty, new TentSceneListEvent([OwnCamp with { OwnerId = 0 }]), null);
        Assert.False(unknown.Visible); Assert.True(unknown.SceneKnown);
        Assert.True(Apply(TentReceiveSnapshot.Empty, new TentSceneListEvent([OwnCamp with { OwnerId = 0 }]), 0).Visible);
        Assert.Null(Apply(TentReceiveSnapshot.Empty, new TentAddedEvent(OwnCamp), scene: null).DeployedScene);
    }

    [Theory]
    [InlineData("open", true)] [InlineData("enter", false)] [InlineData("close", false)] [InlineData("leave", false)]
    public void VisibleReceiptOnlyClearsOpenPendingAndItsUncertainty(string action, bool clears)
    {
        var state = Entering(true) with { Pending = new(action) { Due = 0 } };
        var next = Apply(state, new TentAddedEvent(OwnCamp));
        Assert.Equal(clears, next.Pending is null); Assert.Equal(!clears, next.Uncertain);
        Assert.Same(state.EntryContext, next.EntryContext);
        Assert.Equal(action == "enter" ? "等待進入自家帳篷的伺服器確認" : "自家帳篷已由伺服器確認展開", next.Status);
    }

    [Fact]
    public void RemovalClearsOnlySourceFieldsAndUnrelatedOwnerLeftIsNoOp()
    {
        var state = Entering(true) with { Inside = true, InteriorScene = 10299, ReturnScene = 100, AccessOpen = false };
        Assert.Same(state, Apply(state, new TentOwnerLeftEvent()));
        Assert.Same(state, Apply(state, new TentRemovedEvent(18)));
        var next = Apply(state, new TentRemovedEvent(17));
        Assert.False(next.Visible); Assert.Null(next.TentId); Assert.Null(next.DeployedScene);
        Assert.Null(next.X); Assert.Null(next.Y); Assert.False(next.Inside); Assert.Null(next.InteriorScene);
        Assert.Null(next.EntryContext); Assert.Null(next.Pending); Assert.False(next.Uncertain);
        Assert.Equal(state.Scene, next.Scene); Assert.True(next.SceneKnown);
        Assert.Equal(state.Kind, next.Kind); Assert.Equal(state.Make, next.Make);
        Assert.False(next.AccessOpen); Assert.Equal(state.ReturnScene, next.ReturnScene);
    }

    [Theory]
    [InlineData(true)] [InlineData(false)]
    public void EmptyOwnFurnitureAndPositionConfirmInEitherOrderWithoutMutatingEvidence(bool furnitureFirst)
    {
        var state = Entering(true);
        var first = furnitureFirst ? Apply(state, Room()) : Apply(state, Position(10299), scene: 10299);
        var next = furnitureFirst ? Apply(first, Position(10299), scene: 10299) : Apply(first, Room(), scene: 10299);
        Assert.False(first.Inside); Assert.True(next.Inside); Assert.Equal((ushort)10299, next.InteriorScene);
        Assert.Equal((ushort)100, next.ReturnScene); Assert.Null(next.Pending); Assert.Null(next.EntryContext);
        Assert.False(next.Uncertain); Assert.False(state.EntryContext!.FurnitureReceived);
        Assert.NotNull(state.Pending); Assert.True(state.Visible); Assert.True(state.Uncertain);
        if (furnitureFirst) Assert.True(first.EntryContext!.FurnitureReceived);
        else Assert.False(first.EntryContext!.FurnitureReceived);
    }

    [Fact]
    public void UnknownOrForeignFurnitureDoesNotEstablishEntryAndLateOwnEvidenceStillCan()
    {
        var state = Entering(true) with { Pending = null };
        Assert.Same(state, Apply(state, Room(18))); Assert.Same(state, Apply(state, Room(), role: null));
        Assert.Same(state, Apply(state, new TentEntryDeniedEvent()));
        Assert.Same(state, Apply(state, new TentErrorEvent(2)));
        var moved = Apply(state, Position(10299), scene: 10299);
        Assert.True(Apply(moved, Room(), scene: 10299).Inside);
        var noContext = moved with { EntryContext = null };
        Assert.Same(noContext, Apply(noContext, Room(), scene: 10299));
    }

    [Theory]
    [InlineData(0, false, false)] [InlineData(0, true, false)]
    [InlineData(10000, false, true)] [InlineData(10298, false, true)] [InlineData(10299, false, true)]
    [InlineData(63501, false, false)] [InlineData(63501, true, true)]
    [InlineData(65535, false, false)] [InlineData(65535, true, true)]
    [InlineData(61501, true, true)]
    public void PrivateSceneClassificationNeedsRuntimeExceptThreeTemplates(int scene, bool runtime, bool expected)
    {
        // Alias evidence does not override tent._private_scene, unlike obstacle_scope.
        var catalog = runtime ? new WorldSceneCatalog([], [61501]) : null;
        var furnished = Apply(Entering(), Room());
        var next = Apply(furnished, Position((ushort)scene), scene: (ushort)scene, catalog: catalog);
        Assert.Equal(expected, next.Inside);
        var known = Apply(furnished, Position((ushort)scene), scene: (ushort)scene,
            catalog: new WorldSceneCatalog([(ushort)scene]));
        Assert.Equal(scene is 10000 or 10298 or 10299, known.Inside);
    }

    [Fact]
    public void SameScenePositionDoesNotReconfirmButFurnitureCan()
    {
        var state = Entering(true) with { Scene = 10299 };
        Assert.Same(state, Apply(state, Position(10299), scene: 10299));
        Assert.True(Apply(state, Room(), scene: 10299).Inside);
        var fallback = state with { EntryContext = null, Pending = new("enter") { SourceScene = 100, FurnitureReceived = true } };
        Assert.Same(fallback, Apply(fallback, Position(10299), scene: 10299));
        Assert.True(Apply(fallback, Position(10298), scene: 10298).Inside);
    }

    [Fact]
    public void ReturnSceneWinsOverPrivateSceneAndOtherSceneKeepsUnclearedInteriorEvidence()
    {
        var state = Entering(true) with { Inside = true, InteriorScene = 10299, ReturnScene = 101, EntryContext = null };
        var ordinary = Apply(state, Position(102), scene: 102);
        Assert.False(ordinary.Inside); Assert.Equal(state.InteriorScene, ordinary.InteriorScene);
        Assert.Same(state.Pending, ordinary.Pending); Assert.True(ordinary.Uncertain);
        var returned = Apply(state, Position(101), scene: 101, catalog: new WorldSceneCatalog([]));
        Assert.False(returned.Inside); Assert.Null(returned.InteriorScene); Assert.Null(returned.Pending);
        Assert.False(returned.Uncertain); Assert.Equal((ushort)101, returned.ReturnScene);
        Assert.Equal("已離開自家帳篷（伺服器位置確認）", returned.Status);
        var floor = Apply(state, Position(10298), scene: 10298);
        Assert.True(floor.Inside); Assert.Equal((ushort)10298, floor.InteriorScene); Assert.Equal(state.Status, floor.Status);
    }

    [Fact]
    public void DenialAndErrorsKeepUncertaintyWhileClearingOnlyTheirSpecificContext()
    {
        var state = Entering(true);
        var denied = Apply(state, new TentEntryDeniedEvent());
        Assert.Null(denied.Pending); Assert.Null(denied.EntryContext); Assert.True(denied.Uncertain);
        Assert.Same(denied, Apply(denied, new TentErrorEvent(2)));
        var error = Apply(state, new TentErrorEvent(255));
        Assert.Equal("帳篷操作未成功（伺服器錯誤碼 255）", error.Status); Assert.True(error.Uncertain);
        var limited = Apply(state with { Pending = new("open") }, new TentLimitEvent());
        Assert.Null(limited.Pending); Assert.Same(state.EntryContext, limited.EntryContext); Assert.True(limited.Uncertain);
        var rejected = Apply(state with { Pending = new("leave") }, new EventRejectedEvent(1, "合成拒絕"));
        Assert.Null(rejected.Pending); Assert.Same(state.EntryContext, rejected.EntryContext); Assert.True(rejected.Uncertain);
        Assert.Equal("合成拒絕", rejected.Status);
    }

    [Fact]
    public void AppearanceAndAccessDoNotConfirmVisibilityOrResolveActions()
    {
        var state = Entering(true) with { Visible = false };
        var appearance = Apply(state, new TentAppearanceEvent(255, 0));
        var access = Apply(appearance, new TentAccessEvent(false, true));
        Assert.False(access.Visible); Assert.False(access.AccessOpen); Assert.Equal((byte)255, access.Kind);
        Assert.Equal((byte)0, access.Make); Assert.Equal(state.Status, access.Status);
        Assert.Same(state.Pending, access.Pending); Assert.Same(state.EntryContext, access.EntryContext); Assert.True(access.Uncertain);
    }

    [Fact]
    public void WorldReducerThenTentReducerUsesNewIdentityAndResetsOnWorldPlayerOnly()
    {
        var player = new WorldPlayer(uint.MaxValue, 0, 65535, 0, 0, 0, 0, 0, 0, 0, 0, false, [], "合成", 0);
        var observation = new ServerLayoutEvent(new WorldPlayerEvent(player));
        var world = WorldEventReducer.Apply(new WorldEventSnapshot(), observation);
        var state = Apply(Entering(true), observation, world.Player!.RoleId, world.Player.Scene);
        Assert.Equal(new TentReceiveSnapshot { Scene = 65535 }, state);
        Assert.Same(state, Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([]))));
        Assert.Same(state, Apply(state, new InitialDataCompleteEvent()));
        var position = Position(101, uint.MaxValue);
        world = WorldEventReducer.Apply(world, position);
        state = Apply(state, position, world.Player!.RoleId, world.Player.Scene);
        Assert.Equal((ushort)101, state.Scene); Assert.False(state.SceneKnown);
        state = Apply(state, new TentAddedEvent(OwnCamp with { OwnerId = uint.MaxValue }), world.Player.RoleId, world.Player.Scene);
        Assert.True(state.Visible); Assert.Equal((ushort)101, state.DeployedScene);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(255)] [InlineData(256)] [InlineData(4096)] [InlineData(8192)]
    public void CampCountsHaveNoInventedCapsOrRetainedSceneList(int count)
    {
        var other = OwnCamp with { OwnerId = 18 };
        var tents = Enumerable.Repeat(other, count).Append(OwnCamp).ToImmutableArray();
        var state = Apply(TentReceiveSnapshot.Empty, new TentSceneListEvent(tents));
        Assert.Equal((ushort)42, state.TentId); Assert.True(state.Visible);
        Assert.Equal(17, typeof(TentReceiveSnapshot).GetProperties().Count(property => !property.GetMethod!.IsStatic));
    }

    [Fact]
    public void InvalidTypedListsAndNullArgumentsFailWithoutMutatingSnapshots()
    {
        var state = Entering(true);
        Assert.Throws<ProtocolException>(() => Apply(state, new TentSceneListEvent(default)));
        Assert.Throws<ArgumentNullException>(() => Apply(null!, new TentOwnerLeftEvent()));
        Assert.Throws<ArgumentNullException>(() => Apply(state, null!));
        Assert.True(state.Visible); Assert.NotNull(state.Pending); Assert.False(state.EntryContext!.FurnitureReceived);
    }

    [Fact]
    public void OnlyPublicReducerOperationIsReceiveAndDiagnosticStringsDoNotExposeEvidence()
    {
        Assert.Equal(nameof(TentReceiveSnapshot), Entering().ToString());
        Assert.Equal(nameof(TentActionObservation), Entering().Pending!.ToString());
        Assert.Equal("Apply", Assert.Single(typeof(TentReceiveReducer).GetMethods(
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public)).Name);
    }
}
