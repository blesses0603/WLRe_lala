using System.Collections.ObjectModel;

namespace Lala.Core.World;

/// <summary>Offline shared-edge geometry port of navigation.Mesh. No live runtime or packet transport.</summary>
/// <remarks>Input coordinates are limited to signed Int3 range to keep all geometry arithmetic finite.
/// Interpolated fractional coordinates within that range remain supported. Cancellation never returns a partial route.</remarks>
public class NavigationMesh
{
    private readonly Dictionary<int, NavigationPoint>[] adjacency;
    public string? SceneId { get; }
    public IReadOnlyList<NavigationTriangle> Faces { get; }
    public IReadOnlyList<NavigationNodeMetadata?> Metadata { get; }
    public IReadOnlyList<NavigationPoint> Centers { get; }
    public IReadOnlyList<IReadOnlyDictionary<int, NavigationPoint>> Adjacency { get; }
    public int NonmanifoldEdges { get; }

    public NavigationMesh(IEnumerable<NavigationTile> tiles, string? sceneId = null, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        SceneId = sceneId;
        var faces = new List<NavigationTriangle>(); var metadata = new List<NavigationNodeMetadata?>();
        var edges = new Dictionary<(NavigationPoint, NavigationPoint), List<int>>();
        foreach (var tile in tiles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            for (var i = 0; i < tile.Triangles.Count; i++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var tri = tile.Triangles[i];
                foreach (var point in tri.Vertices) NavigationValidation.RequirePoint(point);
                if (Math.Abs(Area(tri.A, tri.B, tri.C)) < 1e-9) continue;
                var face = faces.Count; faces.Add(tri); metadata.Add(tile.Metadata[i]);
                foreach (var pair in new[] { (tri.A, tri.B), (tri.B, tri.C), (tri.C, tri.A) })
                {
                    var edge = pair.Item1.CompareTo(pair.Item2) <= 0 ? pair : (pair.Item2, pair.Item1);
                    if (!edges.TryGetValue(edge, out var matches)) edges[edge] = matches = [];
                    matches.Add(face);
                }
            }
        }
        Faces = Array.AsReadOnly(faces.ToArray()); Metadata = Array.AsReadOnly(metadata.ToArray());
        Centers = Array.AsReadOnly(NavigationValidation.Copy(faces.Select(t => t.Center), cancellationToken));
        adjacency = NavigationValidation.Copy(Enumerable.Range(0, faces.Count).Select(_ => new Dictionary<int, NavigationPoint>()), cancellationToken);
        foreach (var (edge, matches) in edges)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (matches.Count == 2)
            {
                var midpoint = new NavigationPoint((edge.Item1.X + edge.Item2.X) / 2,
                    (edge.Item1.Y + edge.Item2.Y) / 2, (edge.Item1.Z + edge.Item2.Z) / 2);
                adjacency[matches[0]][matches[1]] = midpoint; adjacency[matches[1]][matches[0]] = midpoint;
            }
            else if (matches.Count > 2) NonmanifoldEdges++;
        }
        Adjacency = Array.AsReadOnly(NavigationValidation.Copy(adjacency.Select(d => (IReadOnlyDictionary<int, NavigationPoint>)
            new ReadOnlyDictionary<int, NavigationPoint>(d)), cancellationToken));
    }
    private protected void FilterConnections(int node, Func<int, bool> allowed)
    {
        foreach (var target in adjacency[node].Keys.ToArray()) if (!allowed(target)) adjacency[node].Remove(target);
    }
    public static double Area(NavigationPoint a, NavigationPoint b, NavigationPoint c)
    {
        NavigationValidation.RequirePoint(a); NavigationValidation.RequirePoint(b); NavigationValidation.RequirePoint(c);
        return (b.X - a.X) * (c.Z - a.Z) - (b.Z - a.Z) * (c.X - a.X);
    }

    public virtual NavigationLocation Locate(double x, double z, double? height = null, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (!double.IsFinite(x) || !double.IsFinite(z) || height.HasValue && !double.IsFinite(height.Value))
            throw new NavigationException("座標必須是有限數值。");
        NavigationValidation.RequirePoint(new(x, height ?? 0, z));
        var point = new NavigationPoint(x, 0, z); var hits = new List<NavigationLocation>();
        for (var i = 0; i < Faces.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var t = Faces[i]; var total = Area(t.A, t.B, t.C);
            var u = Area(point, t.B, t.C) / total; var v = Area(t.A, point, t.C) / total; var w = 1 - u - v;
            if (Math.Min(u, Math.Min(v, w)) >= -1e-8)
            {
                var hit = new NavigationPoint(x, u * t.A.Y + v * t.B.Y + w * t.C.Y, z);
                NavigationValidation.RequirePoint(hit);
                hits.Add(new(i, hit));
            }
        }
        if (hits.Count == 0) throw new NavigationException("指定位置在導航面之外；不會自動吸附到邊界。");
        var nearest = hits[0]; var minimum = hits[0].Point.Y; var maximum = minimum;
        foreach (var hit in hits)
        {
            cancellationToken.ThrowIfCancellationRequested();
            minimum = Math.Min(minimum, hit.Point.Y); maximum = Math.Max(maximum, hit.Point.Y);
            if (height.HasValue && Math.Abs(hit.Point.Y - height.Value) < Math.Abs(nearest.Point.Y - height.Value)) nearest = hit;
        }
        if (height.HasValue) return nearest;
        if (maximum - minimum > 1e-5) throw new NavigationException("此 X/Z 有多個高度的導航面，請指定高度。");
        return hits[0];
    }

    public virtual NavigationRoute Route(NavigationCoordinate start, NavigationCoordinate end,
        double? startHeight = null, double? endHeight = null, CancellationToken cancellationToken = default)
    {
        var source = Locate(start.X, start.Z, startHeight, cancellationToken); var target = Locate(end.X, end.Z, endHeight, cancellationToken);
        // Python heapq tuple ordering is significant when route costs tie.
        var queue = new PriorityQueue<(double Cost, int Node), (double Estimate, double Cost, int Node)>();
        queue.Enqueue((0, source.Face), (NavigationPoint.Distance(Centers[source.Face], Centers[target.Face]), 0, source.Face));
        var costs = new Dictionary<int, double> { [source.Face] = 0 }; var parents = new Dictionary<int, int>();
        while (queue.TryDequeue(out var entry, out _))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (entry.Cost != costs[entry.Node]) continue;
            if (entry.Node == target.Face) return BuildRoute(source, target, parents, cancellationToken: cancellationToken);
            foreach (var neighbor in Adjacency[entry.Node].Keys)
            {
                var candidate = entry.Cost + NavigationPoint.Distance(Centers[entry.Node], Centers[neighbor]);
                if (candidate >= costs.GetValueOrDefault(neighbor, double.PositiveInfinity)) continue;
                costs[neighbor] = candidate; parents[neighbor] = entry.Node;
                queue.Enqueue((candidate, neighbor), (candidate + NavigationPoint.Distance(Centers[neighbor], Centers[target.Face]), candidate, neighbor));
            }
        }
        throw new NavigationException("兩點之間沒有可由共享邊連通的離線幾何路徑。");
    }
    private protected NavigationRoute BuildRoute(NavigationLocation source, NavigationLocation target,
        Dictionary<int, int> parents, uint? cost = null, string? travelMode = null, bool smooth = false, CancellationToken cancellationToken = default)
    {
        var faces = new List<int> { target.Face };
        while (faces[^1] != source.Face) { cancellationToken.ThrowIfCancellationRequested(); faces.Add(parents[faces[^1]]); }
        faces.Reverse(); var points = new List<NavigationPoint> { source.Point };
        for (var i = 1; i < faces.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var point = Adjacency[faces[i - 1]][faces[i]];
            if (point != points[^1]) points.Add(point);
        }
        if (target.Point != points[^1]) points.Add(target.Point);
        if (smooth) points = NavigationFunnel.SmoothCorridor(faces.Select(f => Faces[f]).ToArray(), source.Point, target.Point, cancellationToken).ToList();
        return new(SceneId, points, faces, cost, travelMode, smooth, cancellationToken);
    }
}

public sealed class NoPreviewRouteException(int source, int target, int reached, string travelMode)
    : NavigationException("官方連線與通行標籤沒有允許的路徑。")
{
    public int SourceNode { get; } = source;
    public int TargetNode { get; } = target;
    public int ReachableNodes { get; } = reached;
    public string TravelMode { get; } = travelMode;
}

/// <summary>Port of navigation_preview.PreviewMesh, including directed costs, penalties and travel tags.</summary>
public sealed class PreviewNavigationMesh : NavigationMesh
{
    private readonly IReadOnlyList<NavigationConnection>[] connections;
    private readonly HashSet<int> walkable;
    internal long ConnectionCount => connections.Sum(row => (long)row.Count);
    public string TravelMode { get; }
    public IReadOnlySet<int> Walkable { get; }
    public PreviewNavigationMesh(IEnumerable<NavigationTile> tiles, IEnumerable<IEnumerable<NavigationConnection>> connections,
        string travelMode = "land", string? sceneId = null, CancellationToken cancellationToken = default)
        : base(ValidateMode(tiles, travelMode, cancellationToken), sceneId, cancellationToken)
    {
        var mask = travelMode switch { "land" => 9, "sea" => 4, "sky" => 15, _ => throw new NavigationException("未驗證的通行模式。") };
        TravelMode = travelMode;
        this.connections = NavigationValidation.Copy(connections.Select(c => (IReadOnlyList<NavigationConnection>)
            Array.AsReadOnly(NavigationValidation.Copy(c, cancellationToken))), cancellationToken);
        if (Faces.Count != this.connections.Length) throw new NavigationException("Degenerate official geometry requires separate review");
        walkable = [];
        for (var i = 0; i < Faces.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var node = Metadata[i] ?? throw new NavigationException("官方導航缺少節點旗標。");
            if ((node.Flags & 1) != 0 && (mask & (1L << (int)((node.Flags >> 19) & 31))) != 0) walkable.Add(i);
        }
        // A frozen set prevents callers from changing traversal authority after construction.
        Walkable = System.Collections.Frozen.FrozenSet.ToFrozenSet(walkable);
        for (var i = 0; i < Faces.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var allowed = new HashSet<int>();
            foreach (var connection in this.connections[i])
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (walkable.Contains(connection.Target)) allowed.Add(connection.Target);
            }
            var sourceAllowed = walkable.Contains(i);
            FilterConnections(i, target => sourceAllowed && allowed.Contains(target));
        }
    }
    private static IEnumerable<NavigationTile> ValidateMode(IEnumerable<NavigationTile> tiles, string mode, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (mode is not ("land" or "sea" or "sky")) throw new NavigationException("未驗證的通行模式。");
        return tiles;
    }
    public override NavigationLocation Locate(double x, double z, double? height = null, CancellationToken cancellationToken = default)
    {
        var result = base.Locate(x, z, height, cancellationToken);
        if (!walkable.Contains(result.Face)) throw new NavigationException("Official node is not walkable");
        return result;
    }
    public override NavigationRoute Route(NavigationCoordinate start, NavigationCoordinate end,
        double? startHeight = null, double? endHeight = null, CancellationToken cancellationToken = default) => Route(start, end, startHeight, endHeight, false, cancellationToken);

    public NavigationRoute Route(NavigationCoordinate start, NavigationCoordinate end,
        double? startHeight, double? endHeight, bool smooth, CancellationToken cancellationToken = default)
    {
        var source = Locate(start.X, start.Z, startHeight, cancellationToken); var target = Locate(end.X, end.Z, endHeight, cancellationToken);
        var costs = new Dictionary<int, uint> { [source.Face] = 0 }; var parents = new Dictionary<int, int>();
        var queue = new PriorityQueue<(uint Cost, int Node), (uint Cost, int Node)>();
        queue.Enqueue((0, source.Face), (0, source.Face));
        while (queue.TryDequeue(out var entry, out _))
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (entry.Cost != costs[entry.Node]) continue;
            if (entry.Node == target.Face) return BuildRoute(source, target, parents, entry.Cost, TravelMode, smooth, cancellationToken);
            foreach (var connection in connections[entry.Node])
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (!Adjacency[entry.Node].ContainsKey(connection.Target)) continue;
                var value = (ulong)entry.Cost + connection.Cost + Metadata[connection.Target]!.Value.Penalty;
                if (value > uint.MaxValue) throw new NavigationException("路徑成本超出已驗證範圍。");
                if (costs.TryGetValue(connection.Target, out var old) && value >= old) continue;
                costs[connection.Target] = (uint)value; parents[connection.Target] = entry.Node;
                queue.Enqueue(((uint)value, connection.Target), ((uint)value, connection.Target));
            }
        }
        throw new NoPreviewRouteException(source.Face, target.Face, costs.Count, TravelMode);
    }
}
