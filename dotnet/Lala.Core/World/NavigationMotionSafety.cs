namespace Lala.Core.World;

/// <summary>Owned route claims to be checked, not an execution permit.</summary>
public sealed class PreviewRouteSnapshot
{
    public IReadOnlyList<NavigationPoint> Points { get; }
    public IReadOnlyList<int> Faces { get; }
    public bool? CanSendPackets { get; }
    public PreviewRouteSnapshot(IEnumerable<NavigationPoint> points, IEnumerable<int> faces, bool? canSendPackets = false)
    {
        Points = Array.AsReadOnly(points.ToArray()); Faces = Array.AsReadOnly(faces.ToArray());
        CanSendPackets = canSendPackets;
    }
    public PreviewRouteSnapshot(NavigationRoute route) : this(route.Points, route.Faces, route.CanSendPackets) { }
}

public sealed class ExactWaypointFallback
{
    public string Policy => "exact_waypoint_arrival_no_skipping";
    public IReadOnlyList<NavigationPoint> Points { get; }
    public bool GeometryContained => true;
    public string PreviewStepper => "exact_waypoint_step";
    public bool RequiresLiveControllerValidation => true;
    public bool CanSendPackets => false;
    public bool LiveMovementVerified => false;
    internal ExactWaypointFallback(IReadOnlyList<NavigationPoint> points) => Points = Array.AsReadOnly(points.ToArray());
}

public sealed class NavigationMotionCheck
{
    public bool CanSendPackets => false;
    public bool LiveMovementVerified => false;
    public bool CollisionVerified => false;
    public bool ActorClearanceVerified => false;
    public string Status { get; }
    public string? Reason { get; }
    public string? ModeledMotionContainment { get; }
    public IReadOnlyList<int> RejectedSegments { get; }
    public ExactWaypointFallback? Fallback { get; }
    public IReadOnlyList<string> RemainingRequirements { get; }
    internal NavigationMotionCheck(string reason)
    {
        Status = "rejected"; Reason = reason; RejectedSegments = Array.Empty<int>();
        RemainingRequirements = Array.Empty<string>();
    }
    internal NavigationMotionCheck(IReadOnlyList<NavigationPoint> points, IEnumerable<int> rejected)
    {
        Status = "geometry_preview_only"; RejectedSegments = Array.AsReadOnly(rejected.ToArray());
        ModeledMotionContainment = RejectedSegments.Count > 0 ? "rejected" : "contained";
        Fallback = new(points);
        RemainingRequirements = Array.AsReadOnly(new[] { "actual_collision_and_actor_clearance", "runtime_settings", "controller_and_device_validation" });
    }
}

public sealed class ExactWaypointStep
{
    public NavigationPoint Position { get; }
    public int Index { get; }
    public bool Done { get; }
    public IReadOnlyList<NavigationSegment> Segments { get; }
    public bool CanSendPackets => false;
    public bool LiveMovementVerified => false;
    internal ExactWaypointStep(NavigationPoint position, int index, bool done, IEnumerable<NavigationSegment> segments)
    {
        Position = position; Index = index; Done = done; Segments = Array.AsReadOnly(segments.ToArray());
    }
}

/// <summary>Port of navigation_motion_safety. Exact waypoint fallback is geometry-only, never movement authority.</summary>
public static class NavigationMotionSafety
{
    public const int MaxSegments = 512;
    public const int MaxTriangles = 10000;
    public const int MaxChecks = 2_000_000;
    private const double Epsilon = NavigationFunnel.Epsilon;

    public static NavigationMotionCheck CheckPreview(PreviewNavigationMesh mesh, PreviewRouteSnapshot route,
        IReadOnlyList<NavigationSegment> segments, string? catalogKey, string? expectedCatalogKey, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (string.IsNullOrEmpty(catalogKey) || catalogKey != expectedCatalogKey) return new("catalog_mismatch");
        if (route.CanSendPackets != false) return new("preview_authority_required");
        var points = route.Points; var faces = route.Faces;
        if (points.Count is < 2 or > MaxSegments || points.Any(p => !p.IsInInt3Range)) return new("invalid_points");
        if (faces.Count is 0 or > MaxSegments || faces.Any(f => !mesh.Walkable.Contains(f))) return new("forbidden_faces");
        for (var i = 1; i < faces.Count; i++)
            if (!mesh.Adjacency[faces[i - 1]].ContainsKey(faces[i])) return new("forbidden_connection");
        if (points.Max(p => p.Y) - points.Min(p => p.Y) > Epsilon) return new("nonplanar");
        var height = points[0].Y;
        if (faces.Any(f => mesh.Faces[f].Vertices.Any(p => Math.Abs(p.Y - height) > Epsilon))) return new("nonplanar");
        var samePlane = new List<NavigationTriangle>();
        for (var face = 0; face < mesh.Faces.Count; face++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (mesh.Walkable.Contains(face) && mesh.Faces[face].Vertices.All(p => Math.Abs(p.Y - height) <= Epsilon))
                samePlane.Add(mesh.Faces[face]);
        }
        var triangles = samePlane.ToArray();
        if (triangles.Length is 0 or > MaxTriangles || segments.Count > MaxSegments ||
            ((long)points.Count + segments.Count) * triangles.Length > MaxChecks) return new("geometry_budget");
        if (!NavigationFunnel.Covered(points[0], points[0], [mesh.Faces[faces[0]]], cancellationToken) ||
            !NavigationFunnel.Covered(points[^1], points[^1], [mesh.Faces[faces[^1]]], cancellationToken)) return new("endpoint_outside_corridor");
        var corridor = faces.Select(f => mesh.Faces[f]).ToArray();
        for (var i = 1; i < points.Count; i++)
            if (!NavigationFunnel.Covered(points[i - 1], points[i], corridor, cancellationToken)) return new("ideal_path_not_contained");
        if (segments.Count == 0 || segments.Any(s => !s.Start.IsInInt3Range || !s.End.IsInInt3Range)) return new("invalid_motion");
        if (segments.Any(s => Math.Abs(s.Start.Y - height) > Epsilon || Math.Abs(s.End.Y - height) > Epsilon)) return new("nonplanar_motion");
        if (NavigationPoint.Distance(segments[0].Start, points[0]) > Epsilon) return new("discontinuous_motion");
        for (var i = 1; i < segments.Count; i++)
            if (NavigationPoint.Distance(segments[i - 1].End, segments[i].Start) > Epsilon) return new("discontinuous_motion");
        if (NavigationPoint.Distance(segments[^1].End, points[^1]) > 400.000001) return new("motion_endpoint_outside_threshold");
        var rejected = Enumerable.Range(0, segments.Count)
            .Where(i => !NavigationFunnel.Covered(segments[i].Start, segments[i].End, triangles, cancellationToken));
        return new(points, rejected);
    }

    /// <summary>Consume distance through every corner, returning each segment rather than a shortcut chord.</summary>
    /// <remarks>Call only with validated fallback points and unchanged geometry. No packets are produced.</remarks>
    public static ExactWaypointStep Step(IReadOnlyList<NavigationPoint> points, int index, NavigationPoint position, double distance, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (points.Count is < 2 or > MaxSegments || points.Any(p => !p.IsInInt3Range) || !position.IsInInt3Range ||
            index < 0 || index >= points.Count - 1 || !double.IsFinite(distance) || distance < 0 || distance > 1e9)
            throw new NavigationException("Invalid exact-waypoint preview step");
        if (points.Max(p => p.Y) - points.Min(p => p.Y) > Epsilon) throw new NavigationException("Nonplanar preview step");
        var start = points[index]; var end = points[index + 1]; var edge = NavigationPoint.Distance(start, end);
        if (Math.Abs(NavigationPoint.Distance(start, position) + NavigationPoint.Distance(position, end) - edge) > Epsilon)
            throw new NavigationException("Position left the validated segment");
        var segments = new List<NavigationSegment>(); var done = false;
        for (var step = 0; step < MaxSegments; step++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            end = points[index + 1]; var remaining = NavigationPoint.Distance(position, end);
            if (distance < remaining)
            {
                if (distance > 0)
                {
                    // Preserve Python's multiplication/division order at waypoint thresholds.
                    var target = new NavigationPoint(position.X + (end.X - position.X) * distance / remaining,
                        position.Y + (end.Y - position.Y) * distance / remaining,
                        position.Z + (end.Z - position.Z) * distance / remaining);
                    segments.Add(new(position, target)); position = target;
                }
                return new(position, index, done, segments);
            }
            if (remaining > 0) segments.Add(new(position, end));
            position = end; distance -= remaining;
            if (index == points.Count - 2) { done = true; return new(position, index, done, segments); }
            index++;
        }
        throw new NavigationException("Exact waypoint budget exceeded");
    }
}
