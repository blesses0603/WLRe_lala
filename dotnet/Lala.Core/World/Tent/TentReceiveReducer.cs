using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.World.Tent;

/// <summary>Pure offline port of world/tent.py defaults/apply_tent and receive helpers.
/// Supply the player's role/scene AFTER applying the world event, matching state.py's
/// dispatch order. CurrentCatalog is explicit runtime-stage evidence, never activated here.
/// Decode before Apply; malformed bytes cannot partly change an immutable prior snapshot.
/// This projection is not installed in AccountSession or any service coordinator.</summary>
public static class TentReceiveReducer
{
    public static TentReceiveSnapshot Apply(TentReceiveSnapshot state, ServerEvent observation,
        uint? ownRoleId, ushort? playerScene, WorldSceneCatalog? currentCatalog = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        switch (observation)
        {
            case ServerLayoutEvent { Event: WorldPlayerEvent }:
                return new() { Scene = playerScene };
            case PositionSnapshotEvent position when position.RoleId == ownRoleId:
                if (state.Scene == position.Scene) return state;
                var moved = state with { Scene = position.Scene, SceneKnown = false, Visible = false };
                if (state.Inside && position.Scene == state.ReturnScene)
                    moved = moved with
                    {
                        Inside = false, InteriorScene = null, Pending = null, Uncertain = false,
                        Status = "已離開自家帳篷（伺服器位置確認）"
                    };
                else if (state.Inside && IsInterior(position.Scene, currentCatalog))
                    moved = moved with { Inside = true, InteriorScene = position.Scene };
                else
                    moved = moved with
                    {
                        Inside = false,
                        Status = state.EntryContext is not null
                            ? "已切換場景，等待自家帳篷內部資料確認" : "已切換場景，等待本場景帳篷資料"
                    };
                return ConfirmEnter(moved, position.Scene, currentCatalog);
            case TentAddedEvent added:
                return ownRoleId is not null && added.Tent.OwnerId == ownRoleId
                    ? Visible(state, added.Tent, playerScene) : state;
            case TentSceneListEvent list:
                if (list.Tents.IsDefault) throw new ProtocolException("Invalid tent scene list.");
                var listed = state with { SceneKnown = true, Scene = playerScene };
                // Source next(...) selects the FIRST matching duplicate, without retaining others.
                foreach (var camp in list.Tents)
                    if (ownRoleId is not null && camp.OwnerId == ownRoleId) return Visible(listed, camp, playerScene);
                return listed with
                {
                    Visible = false,
                    Status = state.Pending is not null ? state.Status : state.DeployedScene is not null
                        ? "本場景未見自家帳篷；其他場景狀態待確認" : "本場景未見自家帳篷"
                };
            case TentRemovedEvent removed when ownRoleId is not null && removed.OwnerId == ownRoleId:
                return state with
                {
                    Visible = false, DeployedScene = null, TentId = null, X = null, Y = null,
                    Inside = false, InteriorScene = null, EntryContext = null, Pending = null,
                    Uncertain = false, Status = "伺服器已確認收起帳篷"
                };
            case TentLimitEvent when state.Pending is { Action: "open" }:
                return state with { Pending = null, Status = "伺服器拒絕：本場景帳篷已達上限" };
            case TentEntryDeniedEvent when state.Pending is { Action: "enter" }:
                return state with { Pending = null, EntryContext = null, Status = "伺服器拒絕進入帳篷" };
            case TentErrorEvent error when state.Pending is not null:
                return state with
                {
                    Pending = null, EntryContext = null,
                    Status = error.Code == 2 ? "伺服器拒絕：沒有帳篷標記" : $"帳篷操作未成功（伺服器錯誤碼 {error.Code}）"
                };
            case TentAccessEvent access:
                return state with { AccessOpen = access.AccessOpen };
            case TentAppearanceEvent appearance:
                return state with { Kind = appearance.Kind, Make = appearance.Make };
            case ServerInventoryEvent { Event: FurnitureSnapshotEvent furniture }
                when ownRoleId is not null && furniture.Owner == ownRoleId && state.EntryContext is not null:
                var furnished = ConfirmEnter(state with
                {
                    EntryContext = state.EntryContext with { FurnitureReceived = true }
                }, playerScene, currentCatalog);
                return furnished.Inside ? furnished : furnished with { Status = "自家帳篷家具已收到，等待房屋場景確認" };
            case EventRejectedEvent rejected when state.Pending is { Action: "leave" }:
                return state with { Pending = null, Status = rejected.Reason };
            default:
                // Owner-left, other identities, unrelated events and late errors are no-ops.
                return state;
        }
    }

    private static TentReceiveSnapshot Visible(TentReceiveSnapshot state, TentCamp camp, ushort? scene)
    {
        var next = state with
        {
            Scene = scene, SceneKnown = true, Visible = true, DeployedScene = scene,
            TentId = camp.TentId, X = camp.X, Y = camp.Y, Kind = camp.Kind, Make = camp.Make
        };
        if (next.Pending is { Action: "open" }) next = next with { Pending = null, Uncertain = false };
        return next with
        {
            Status = next.Pending is { Action: "enter" }
                ? "等待進入自家帳篷的伺服器確認" : "自家帳篷已由伺服器確認展開"
        };
    }

    private static TentReceiveSnapshot ConfirmEnter(TentReceiveSnapshot state, ushort? scene,
        WorldSceneCatalog? currentCatalog)
    {
        var context = state.EntryContext ?? state.Pending;
        if (context is not { Action: "enter", FurnitureReceived: true } || scene == context.SourceScene ||
            !IsInterior(scene, currentCatalog)) return state;
        return state with
        {
            Pending = null, Uncertain = false, Inside = true, InteriorScene = scene,
            ReturnScene = context.SourceScene, EntryContext = null,
            Status = "已進入自家帳篷（伺服器換圖與自家家具確認）"
        };
    }

    // Exactly tent._private_scene, NOT obstacle_scope.house_scene. Tent has no implicit
    // 63501..65500 range or instance-alias exception. A runtime and nonzero scene are required.
    private static bool IsInterior(ushort? scene, WorldSceneCatalog? currentCatalog) =>
        scene is 10299 or 10298 or 10000 ||
        (scene is > 0 && currentCatalog is not null && !currentCatalog.StageIds.Contains(scene.Value));
}
