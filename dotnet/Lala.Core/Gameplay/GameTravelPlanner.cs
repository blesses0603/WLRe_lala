using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World;
using Lala.Core.World.Portals;

namespace Lala.Core.Gameplay;

public sealed record GameTravelLeg(ushort Scene, ushort Door, ushort Destination, ushort X, ushort Y);

/// <summary>Detached itinerary only. Execution must reacquire its account-owned resources
/// and validate each physical route and server-confirmed scene transition independently.</summary>
public static class GameTravelPlanner
{
    public static ImmutableArray<GameTravelLeg> Plan(OfflineRuntimeCandidate catalog, ushort from, ushort to)
    {
        ArgumentNullException.ThrowIfNull(catalog);
        if (!catalog.Stages.ContainsKey(from) || !catalog.Stages.ContainsKey(to)) throw new NavigationException("起點或目的地缺少同版場景資料。");
        if (from == to) return [];
        var sources = catalog.PortalObservations.Reconciled;
        var edges = new Dictionary<ushort, List<GameTravelLeg>>();
        foreach (var (key, d) in sources.Destinations)
        {
            if (sources.Issues.ContainsKey(key) || !d.DestinationVerified || d.Destination is not > 0 || d.Destination == key.Scene ||
                !sources.Positions.TryGetValue(key, out var p) || !p.PositionVerified || p.X is < 0 or > 65535 || p.Y is < 0 or > 65535 ||
                !catalog.Stages.ContainsKey(d.Destination.Value) || key.Scene is >= 63501 or 10000 or 10298 or 10299 || d.Destination is >= 63501 or 10000 or 10298 or 10299) continue;
            if (!edges.TryGetValue(key.Scene, out var list)) edges[key.Scene] = list = [];
            list.Add(new(key.Scene, key.Index, d.Destination.Value, (ushort)p.X, (ushort)p.Y));
        }
        var queue = new Queue<ushort>(); queue.Enqueue(from);
        var previous = new Dictionary<ushort, GameTravelLeg?> { [from] = null };
        while (queue.TryDequeue(out var scene))
        {
            if (previous.Count > 8192) throw new NavigationException("跨圖搜尋超過配額。");
            foreach (var leg in (edges.GetValueOrDefault(scene) ?? []).OrderBy(l => l.Door))
            {
                if (!previous.TryAdd(leg.Destination, leg)) continue;
                if (leg.Destination == to)
                {
                    var result = new List<GameTravelLeg>(); ushort current = to;
                    while (current != from)
                    {
                        var step = previous[current]!; result.Add(step); current = step.Scene;
                        if (result.Count > 64) throw new NavigationException("跨圖路線超過 64 個出口。");
                    }
                    result.Reverse(); return [..result];
                }
                queue.Enqueue(leg.Destination);
            }
        }
        throw new NavigationException("找不到每一段入口與目的地均已核對的跨圖路線。");
    }
}
