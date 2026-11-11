using Lala.Core.Protocol;
using Lala.Core.World.Eve;
using Lala.Core.World.Portals;

namespace Lala.Core.Gameplay;

/// <summary>Source-matched house-door index only; the account still owns sending and arrival confirmation.</summary>
internal static class TentExitResolver
{
    internal static bool IsTemplate(ushort scene) => scene is 10000 or 10298 or 10299;
    internal static ushort Resolve(EveDoorProjection doors, OfflineEventPortalProjection links, IReadOnlyDictionary<uint, string> texts, ushort? returnScene)
    {
        var explicitExits = new HashSet<ushort>(); var serverDecided = new HashSet<ushort>();
        foreach (var scene in doors.Scenes.Where(s => IsTemplate(s.SceneId)))
        {
            if (doors.Scenes.Count(s => s.SceneId == scene.SceneId) != 1) continue;
            foreach (var door in scene.Doors)
            {
                var key = new EventPortalKey(scene.SceneId, door.Index);
                if (door.Index == 0 || scene.Doors.Count(d => d.Index == door.Index) != 1 || links.Issues.ContainsKey(key) ||
                    !links.Destinations.TryGetValue(key, out var link) || !(link.MatchedStageMap == true || link.MatchedTouchRegion) || link.EventX != door.X || link.EventY != door.Y) continue;
                if (link.DestinationVerified && link.Destination is > 0 && !IsTemplate(link.Destination.Value)) explicitExits.Add(door.Index);
                else if (link.Destination is null && link.StageMarkerOnly == true && link.DoorBindingVerified &&
                    (link.StageMarkerKind == 2 || link.StageMarkerKind == 3 && link.StageMarkerEventId == 0) &&
                    !door.TouchEventIds.IsDefaultOrEmpty && returnScene is > 0 && !IsTemplate(returnScene.Value) &&
                    link.StageMarkerNameId is { } text && !string.IsNullOrWhiteSpace(texts.GetValueOrDefault(text))) serverDecided.Add(door.Index);
            }
        }
        var candidates = explicitExits.Count != 0 ? explicitExits : serverDecided;
        if (candidates.Count != 1) throw new ProtocolException("官方帳篷出口未能唯一核對，缺少或衝突的門事件不會直接觸發。");
        return candidates.Single();
    }
}
