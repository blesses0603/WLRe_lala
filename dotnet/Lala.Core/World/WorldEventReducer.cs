using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.Inventory;

namespace Lala.Core.World;

/// <summary>Pure offline port of state_world_events.py and state.py's position helpers.
/// All observations must be decoded/typed first. Unrelated events are no-ops. This reducer is
/// deliberately not installed in AccountSession or a transport, and never sends anything.</summary>
public static class WorldEventReducer
{
    public static WorldEventSnapshot Apply(WorldEventSnapshot state, ServerEvent observation,
        WorldSceneCatalog? currentCatalog = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation switch
        {
            ServerLayoutEvent { Event: WorldPlayerEvent world } => ApplyWorldPlayer(state, world.Player),
            PositionSnapshotEvent position => ApplyPosition(state, position),
            MovementRequestEvent request => WaitForPosition(state with
            {
                Location = state.Location with
                {
                    RequestedDestination = new(state.Player?.Scene, request.X, request.Y, "C6-1", state.PacketCount),
                    ConfirmedIsCurrent = false
                }
            }),
            NavigationGeometryChangeEvent change when WorldObstacleScope.AffectsNavigation(
                change.AffectsGeometry, change.GeometryScope, state.Player?.Scene, currentCatalog) =>
                InvalidateGeometry(state, change.Reason),
            ServerInventoryEvent { Event: CraftFurnitureEvent furniture } when WorldObstacleScope.AffectsNavigation(
                furniture.AffectsGeometry, furniture.GeometryScope, state.Player?.Scene, currentCatalog) =>
                InvalidateGeometry(state, furniture.Reason),
            WalkEvent walk => ApplyWalk(state, walk),
            ServerSocialEvent { Event: NearbyLeaveEvent leave } when leave.RoleId != state.Player?.RoleId =>
                state with { Positions = state.Positions.Remove(leave.RoleId) },
            _ => state
        };
    }

    public static WorldEventSnapshot RememberPosition(WorldEventSnapshot state, long roleId, ushort x, ushort y)
    {
        ArgumentNullException.ThrowIfNull(state);
        return state with { Positions = state.Positions.Remember(roleId, x, y, state.Player?.RoleId) };
    }

    public static (WorldEventSnapshot State, int Removed) ClearPositionHistory(WorldEventSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(state);
        var own = state.Player?.RoleId;
        var current = own is { } id ? state.Positions.Get(id) : null;
        var positions = current is not null
            ? WorldPositionCache.Empty.Remember(own!.Value, current.X, current.Y, own)
            : WorldPositionCache.Empty;
        return (state with { Positions = positions }, state.Positions.Count - positions.Count);
    }

    public static WorldEventSnapshot WaitForPosition(WorldEventSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(state);
        var target = state.Location.RequestedDestination ?? state.Location.ServerDestination;
        if (state.LocalMovement is { Status: "running" or "finished" } local) target = local.Target;
        return state with { MovementCheck = target is null ? null : new("waiting", target, state.Player?.RoleId) };
    }

    public static WorldEventSnapshot ConfirmLocation(WorldEventSnapshot state, ushort scene, ushort x,
        ushort y, string source)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(source);
        var confirmation = new WorldPosition(scene, x, y, source, state.PacketCount);
        var check = state.MovementCheck;
        if (check is { Status: "waiting" or "different_position", RoleId: not null } &&
            check.RoleId == state.Player?.RoleId)
        {
            var status = check.Target.Scene != scene ? "scene_changed" :
                check.Target.X == x && check.Target.Y == y ? "matched" : "different_position";
            check = check with { Status = status, Confirmation = confirmation };
        }
        return state with
        {
            MovementCheck = check,
            Location = new() { Confirmed = confirmation, ConfirmedIsCurrent = true }
        };
    }

    private static WorldEventSnapshot ApplyWorldPlayer(WorldEventSnapshot state, WorldPlayer player)
    {
        var result = state with { Player = player, Positions = WorldPositionCache.Empty, Phase = "world_received" };
        result = RememberPosition(result, player.RoleId, player.X, player.Y);
        result = ConfirmLocation(result, player.Scene, player.X, player.Y, "S3-1");
        return result with { Navigation = new() { Scene = player.Scene, Revision = state.Navigation.Revision + 1 } };
    }

    private static WorldEventSnapshot ApplyPosition(WorldEventSnapshot state, PositionSnapshotEvent observation)
    {
        if (state.Player is not { } player || observation.RoleId != player.RoleId)
            return RememberPosition(state, observation.RoleId, observation.X, observation.Y);
        var sameScene = observation.Scene == player.Scene;
        var result = state with
        {
            Player = player with { Scene = observation.Scene, X = observation.X, Y = observation.Y },
            Positions = sameScene ? state.Positions : WorldPositionCache.Empty
        };
        result = RememberPosition(result, observation.RoleId, observation.X, observation.Y);
        result = ConfirmLocation(result, observation.Scene, observation.X, observation.Y, observation.Source);
        return result with
        {
            Navigation = new()
            {
                Scene = observation.Scene, Revision = state.Navigation.Revision + 1,
                Stale = sameScene && state.Navigation.Stale,
                Reasons = sameScene && !state.Navigation.Reasons.IsDefault ? state.Navigation.Reasons : [],
                HouseContext = WorldHouseContextRules.UpdateContext(state.Navigation.HouseContext,
                    observation.Scene, observation.HouseFloor)
            }
        };
    }

    private static WorldEventSnapshot ApplyWalk(WorldEventSnapshot state, WalkEvent observation)
    {
        var result = RememberPosition(state, observation.RoleId, observation.X, observation.Y);
        if (observation.RoleId != state.Player?.RoleId) return result;
        return WaitForPosition(result with
        {
            Location = result.Location with
            {
                ServerDestination = new(state.Player?.Scene, observation.X, observation.Y, "S6-1", state.PacketCount),
                ConfirmedIsCurrent = false
            }
        });
    }

    private static WorldEventSnapshot InvalidateGeometry(WorldEventSnapshot state, string reason)
    {
        var reasons = state.Navigation.Reasons.IsDefault ? ImmutableArray<string>.Empty : state.Navigation.Reasons;
        reasons = reasons.Add(reason);
        if (reasons.Length > 10) reasons = reasons.RemoveRange(0, reasons.Length - 10);
        return state with
        {
            Navigation = state.Navigation with
            {
                Stale = true, Revision = state.Navigation.Revision + 1, Reasons = reasons
            }
        };
    }
}

public static class WorldHouseContextRules
{
    public const ushort HouseMin = 63501;
    public const ushort HouseMax = 65500;

    /// <summary>Port of house_navigation.update_context for typed decoded S7/S12 extensions.
    /// Unverified/missing evidence discards prior floor and sizes. No default house model is invented.</summary>
    public static WorldHouseContext? UpdateContext(WorldHouseContext? previous, ushort scene,
        HouseFloorExtension? extension)
    {
        if (scene is < HouseMin or > HouseMax) return null;
        if (extension is not { Verified: true }) return new(scene, false);
        if (extension.Floor is null || (extension.Size is not null && extension.SizeFloor is null))
            throw new ArgumentException("A verified house extension requires its decoded floor and size-floor fields.", nameof(extension));
        var sizes = previous is { Verified: true } && previous.Scene == scene
            ? previous.Sizes : ImmutableDictionary<byte, byte>.Empty;
        if (extension.Size is { } size) sizes = sizes.SetItem(extension.SizeFloor!.Value, size);
        return new(scene, true, extension.Floor) { Sizes = sizes };
    }
}

public static class WorldObstacleScope
{
    /// <summary>Three-valued house_scene decision with runtime lookup replaced by explicit current
    /// catalog evidence. Known houses win over catalog entries. Unknown is never assumed ordinary.</summary>
    public static bool? HouseScene(ushort? scene, WorldSceneCatalog? currentCatalog = null)
    {
        if (scene is null) return null;
        if (scene is 10299 or 10298 or 10000 || scene is >= WorldHouseContextRules.HouseMin and <= WorldHouseContextRules.HouseMax)
            return true;
        if (currentCatalog is null) return null;
        if (currentCatalog.StageIds.Contains(scene.Value)) return false;
        if (scene is >= 61501 and <= 62000 && currentCatalog.VerifiedInstanceAliasIds?.Contains(scene.Value) == true)
            return false;
        return null;
    }

    public static bool AffectsNavigation(bool affectsGeometry, string? geometryScope, ushort? scene,
        WorldSceneCatalog? currentCatalog = null) => affectsGeometry &&
            (geometryScope != "house" || HouseScene(scene, currentCatalog) is not false);
}
