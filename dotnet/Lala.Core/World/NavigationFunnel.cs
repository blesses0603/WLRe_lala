namespace Lala.Core.World;

/// <summary>Bounded planar portal funnel and independent X/Z containment; no collision or controller authority.</summary>
public static class NavigationFunnel
{
    public const double Epsilon = 1e-7;
    public const int MaxCorridorFaces = 512;

    // Reverse cross product, matching navigation_funnel.area rather than NavigationMesh.Area.
    public static double Area(NavigationPoint a, NavigationPoint b, NavigationPoint c)
    {
        NavigationValidation.RequirePoint(a); NavigationValidation.RequirePoint(b); NavigationValidation.RequirePoint(c);
        return (c.X - a.X) * (b.Z - a.Z) - (b.X - a.X) * (c.Z - a.Z);
    }

    /// <summary>Union of segment/triangle clipping intervals must cover the whole segment in X/Z.</summary>
    /// <remarks>This primitive does not validate height, walkability or topology. Callers must do so.</remarks>
    public static bool Covered(NavigationPoint a, NavigationPoint b, IReadOnlyList<NavigationTriangle> triangles, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        NavigationValidation.RequirePoint(a); NavigationValidation.RequirePoint(b);
        var intervals = new List<(double Lo, double Hi)>();
        foreach (var triangle in triangles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            foreach (var point in triangle.Vertices) NavigationValidation.RequirePoint(point);
            var orientation = Area(triangle.A, triangle.B, triangle.C) > 0 ? 1 : -1;
            double lo = 0, hi = 1; var rejected = false;
            foreach (var (p, q) in new[] { (triangle.A, triangle.B), (triangle.B, triangle.C), (triangle.C, triangle.A) })
            {
                var start = orientation * Area(p, q, a); var end = orientation * Area(p, q, b);
                if (start < -Epsilon && end < -Epsilon) { rejected = true; break; }
                var delta = end - start;
                if (delta > Epsilon) lo = Math.Max(lo, (-Epsilon - start) / delta);
                else if (delta < -Epsilon) hi = Math.Min(hi, (-Epsilon - start) / delta);
                if (lo > hi + Epsilon) { rejected = true; break; }
            }
            if (!rejected && lo <= hi + Epsilon) intervals.Add((Math.Max(0, lo), Math.Min(1, hi)));
        }
        cancellationToken.ThrowIfCancellationRequested();
        intervals.Sort(); double reach = 0;
        foreach (var (lo, hi) in intervals)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (lo > reach + Epsilon) return false;
            reach = Math.Max(reach, hi);
            if (reach >= 1 - Epsilon) return true;
        }
        return false;
    }

    public static IReadOnlyList<NavigationPoint> SmoothCorridor(IReadOnlyList<NavigationTriangle> triangles,
        NavigationPoint start, NavigationPoint end, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (triangles.Count is 0 or > MaxCorridorFaces) throw new NavigationException("平滑路徑走廊超出上限。");
        var points = NavigationValidation.Copy(triangles.SelectMany(t => t.Vertices).Append(start).Append(end), cancellationToken);
        if (points.Any(p => !p.IsInInt3Range)) throw new NavigationException("無效的平滑路徑座標。");
        if (points.Max(p => p.Y) - points.Min(p => p.Y) > Epsilon)
            throw new NavigationException("非水平走廊尚未驗證，不能套用平面平滑。");
        if (triangles.Any(t => Math.Abs(Area(t.A, t.B, t.C)) <= Epsilon))
            throw new NavigationException("退化三角形不能用於平滑。");
        if (!Covered(start, start, [triangles[0]], cancellationToken) || !Covered(end, end, [triangles[^1]], cancellationToken))
            throw new NavigationException("平滑端點不在指定走廊端面。");
        var portals = new List<(NavigationPoint Left, NavigationPoint Right)> { (start, start) };
        for (var i = 1; i < triangles.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var first = triangles[i - 1]; var second = triangles[i];
            var shared = first.Vertices.Intersect(second.Vertices).Order().ToArray();
            if (shared.Length != 2) throw new NavigationException("平滑走廊沒有唯一共用邊。");
            var a = shared[0]; var b = shared[1];
            portals.Add(Area(first.Center, second.Center, a) < Area(first.Center, second.Center, b) ? (a, b) : (b, a));
        }
        portals.Add((end, end));
        var apex = start; var left = start; var right = start;
        int apexIndex = 0, leftIndex = 0, rightIndex = 0, portalIndex = 1, steps = 0;
        var result = new List<NavigationPoint> { start };
        while (portalIndex < portals.Count)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (++steps > 4 * portals.Count * portals.Count) throw new NavigationException("平滑走廊未收斂。");
            var (newLeft, newRight) = portals[portalIndex];
            if (Area(apex, right, newRight) <= 0)
            {
                if (apex == right || Area(apex, left, newRight) > 0) { right = newRight; rightIndex = portalIndex; }
                else
                {
                    if (result[^1] != left) result.Add(left);
                    apex = left; apexIndex = leftIndex; left = right = apex;
                    leftIndex = rightIndex = apexIndex; portalIndex = apexIndex + 1; continue;
                }
            }
            if (Area(apex, left, newLeft) >= 0)
            {
                if (apex == left || Area(apex, right, newLeft) < 0) { left = newLeft; leftIndex = portalIndex; }
                else
                {
                    if (result[^1] != right) result.Add(right);
                    apex = right; apexIndex = rightIndex; left = right = apex;
                    leftIndex = rightIndex = apexIndex; portalIndex = apexIndex + 1; continue;
                }
            }
            portalIndex++;
        }
        if (result[^1] != end) result.Add(end);
        for (var i = 1; i < result.Count; i++)
            if (!Covered(result[i - 1], result[i], triangles, cancellationToken)) throw new NavigationException("平滑路徑離開已驗證走廊。");
        return result.AsReadOnly();
    }
}
