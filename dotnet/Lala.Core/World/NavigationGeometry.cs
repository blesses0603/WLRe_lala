namespace Lala.Core.World;

public class NavigationException(string message) : ArgumentException(message);

public readonly record struct NavigationPoint(double X, double Y, double Z) : IComparable<NavigationPoint>
{
    public bool IsFinite => double.IsFinite(X) && double.IsFinite(Y) && double.IsFinite(Z);
    // Coordinates may be fractional after interpolation, but must remain in the decoded Int3 domain.
    public bool IsInInt3Range => IsFinite && X >= int.MinValue && X <= int.MaxValue &&
        Y >= int.MinValue && Y <= int.MaxValue && Z >= int.MinValue && Z <= int.MaxValue;
    public int CompareTo(NavigationPoint other)
    {
        var x = X.CompareTo(other.X);
        if (x != 0) return x;
        var y = Y.CompareTo(other.Y);
        return y != 0 ? y : Z.CompareTo(other.Z);
    }
    public static double Distance(NavigationPoint a, NavigationPoint b)
    {
        NavigationValidation.RequirePoint(a); NavigationValidation.RequirePoint(b);
        // Scaling avoids intermediate overflow just as Python math.dist does.
        var x = Math.Abs(a.X - b.X); var y = Math.Abs(a.Y - b.Y); var z = Math.Abs(a.Z - b.Z);
        var scale = Math.Max(x, Math.Max(y, z));
        return scale == 0 ? 0 : double.IsPositiveInfinity(scale) ? scale :
            scale * Math.Sqrt(Math.Pow(x / scale, 2) + Math.Pow(y / scale, 2) + Math.Pow(z / scale, 2));
    }
}

public readonly record struct NavigationCoordinate(double X, double Z);
public readonly record struct NavigationTriangle(NavigationPoint A, NavigationPoint B, NavigationPoint C)
{
    public IEnumerable<NavigationPoint> Vertices { get { yield return A; yield return B; yield return C; } }
    public NavigationPoint Center
    {
        get
        {
            NavigationValidation.RequirePoint(A); NavigationValidation.RequirePoint(B); NavigationValidation.RequirePoint(C);
            return new((A.X + B.X + C.X) / 3, (A.Y + B.Y + C.Y) / 3, (A.Z + B.Z + C.Z) / 3);
        }
    }
}
public readonly record struct NavigationSegment(NavigationPoint Start, NavigationPoint End);
public readonly record struct NavigationNodeMetadata(uint Penalty, uint Flags);
public readonly record struct NavigationConnection(int Target, uint Cost, int Edge = 0);
public readonly record struct NavigationLocation(int Face, NavigationPoint Point);

/// <summary>Owned offline tile input, already decoded from vertices_b_int3.</summary>
public sealed class NavigationTile
{
    public IReadOnlyList<NavigationTriangle> Triangles { get; }
    public IReadOnlyList<NavigationNodeMetadata?> Metadata { get; }
    public NavigationTile(IEnumerable<NavigationTriangle> triangles, IEnumerable<NavigationNodeMetadata?>? metadata = null,
        CancellationToken cancellationToken = default)
    {
        var owned = NavigationValidation.Copy(triangles, cancellationToken);
        var nodes = metadata is null ? new NavigationNodeMetadata?[owned.Length] : NavigationValidation.Copy(metadata, cancellationToken);
        if (nodes.Length != owned.Length) throw new NavigationException("無效的三角形節點資料。");
        Triangles = Array.AsReadOnly(owned); Metadata = Array.AsReadOnly(nodes);
    }
}

/// <summary>Immutable offline result. It never grants permission to send movement packets.</summary>
public sealed class NavigationRoute
{
    public string? SceneResource { get; }
    public IReadOnlyList<NavigationPoint> Points { get; }
    public IReadOnlyList<int> Faces { get; }
    public double Length { get; }
    public uint? Cost { get; }
    public string? TravelMode { get; }
    public bool SmoothingApplied { get; }
    public string CoordinateSpace => "navcache_vertices_b_int3";
    public bool NetworkCoordinatesVerified => false;
    public bool RuntimeObstaclesApplied => false;
    public bool OriginalNodeFlagsApplied => false;
    public bool CanSendPackets => false;
    public bool LiveMovementVerified => false;
    public bool OriginalWalkabilityApplied => Cost.HasValue;
    public bool OriginalTagsApplied => Cost.HasValue;
    public bool SerializedCostsApplied => Cost.HasValue;
    public string Connectivity => Cost.HasValue ? "official_serialized_connections" : "reconstructed_shared_edges";
    public string? CostPolicy => Cost.HasValue ? "arcs_plus_target_penalties_zero_tag_penalties" : null;
    public string? NavigationSource => Cost.HasValue ? "official_versioned_database_preview" : null;
    internal NavigationRoute(string? scene, IEnumerable<NavigationPoint> points, IEnumerable<int> faces,
        uint? cost = null, string? travelMode = null, bool smooth = false, CancellationToken cancellationToken = default)
    {
        SceneResource = scene;
        Points = Array.AsReadOnly(NavigationValidation.Copy(points, cancellationToken));
        Faces = Array.AsReadOnly(NavigationValidation.Copy(faces, cancellationToken));
        Cost = cost; TravelMode = travelMode; SmoothingApplied = smooth;
        for (var i = 1; i < Points.Count; i++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            Length += NavigationPoint.Distance(Points[i - 1], Points[i]);
        }
    }
}

internal static class NavigationValidation
{
    internal static void RequirePoint(NavigationPoint point)
    {
        if (!point.IsFinite) throw new NavigationException("座標必須是有限數值。");
        if (!point.IsInInt3Range) throw new NavigationException("導航座標超出 Int3 範圍。");
    }
    internal static T[] Copy<T>(IEnumerable<T> source, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var result = new List<T>();
        foreach (var item in source) { cancellationToken.ThrowIfCancellationRequested(); result.Add(item); }
        cancellationToken.ThrowIfCancellationRequested();
        return result.ToArray();
    }
}
