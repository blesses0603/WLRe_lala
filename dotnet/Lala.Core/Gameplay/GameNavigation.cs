using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.World;

namespace Lala.Core.Gameplay;

public sealed record GameNavigationStatus(bool Running, string Message, ushort? Scene = null,
    double? EstimatedX = null, double? EstimatedY = null, int Completed = 0, int Total = 0);
public sealed record GameNavigationTarget(ushort Scene, ushort X, ushort Y, bool Synchronize = false, string Mode = "land", bool Smooth = false);

/// <summary>Owner-created route for one exact resource/account/scene/geometry and starting fix.
/// A retained route is revoked by correction, replacement, geometry change or disconnect.</summary>
public sealed class GameNavigationRoute
{
    private readonly Func<bool> current;
    internal OfflineNavigationCacheEntry Entry { get; }
    internal OfflineLogicalNavigationRoute Route { get; }
    internal BigInteger? BaseFix { get; }
    internal uint Role { get; }
    public ushort Scene => Route.LogicalMap;
    public ImmutableArray<LogicalNavigationCoordinate> Points => Route.LogicalPoints;
    public bool IsCurrent => current();
    internal GameNavigationRoute(OfflineNavigationCacheEntry entry, OfflineLogicalNavigationRoute route, uint role, BigInteger? fix, Func<bool> current)
        => (Entry, Route, Role, BaseFix, this.current) = (entry, route, role, fix, current);
    internal ImmutableArray<LogicalNavigationCoordinate> ExecutionSteps(CancellationToken token)
    {
        // Match the source land controller: 3.5 world units / second = 350 logical
        // units / second, one report every 200 ms. Never teleport to a distant waypoint.
        if (Route.MeshRoute.Points.Count is < 1 or > 512 || Route.MeshRoute.Points.Max(p => p.Y) - Route.MeshRoute.Points.Min(p => p.Y) > 1e-6)
            throw new NavigationException("此路線含斜坡或超過步數配額，尚不能執行。");
        var steps = ImmutableArray.CreateBuilder<LogicalNavigationCoordinate>();
        var previous = Points[0];
        var triangles = Entry.Mesh.Faces.Where((face, i) => Entry.Mesh.Walkable.Contains(i) && face.Vertices.All(v => Math.Abs(v.Y - Route.MeshRoute.Points[0].Y) < 1e-6)).ToArray();
        var startNav = Route.MeshRoute.Points[0];
        double navX = startNav.X, navZ = startNav.Z;
        for (int i = 1; i < Points.Length; i++)
        {
            var target = Points[i]; double distance = Math.Sqrt(Math.Pow(target.X - previous.X, 2) + Math.Pow(target.Y - previous.Y, 2));
            int parts = Math.Max(1, (int)Math.Ceiling(distance / 70));
            var from = previous;
            for (int part = 1; part <= parts; part++)
            {
                token.ThrowIfCancellationRequested();
                var step = new LogicalNavigationCoordinate(Math.Round(from.X + (target.X - from.X) * part / parts), Math.Round(from.Y + (target.Y - from.Y) * part / parts));
                if (step.X is < 0 or > 65535 || step.Y is < 0 or > 65535 || steps.Count >= 10000) throw new NavigationException("移動座標或步數超出配額。");
                double x = navX + (step.X - previous.X) * 10, z = navZ - (step.Y - previous.Y) * 10;
                if (!NavigationFunnel.Covered(new(navX, startNav.Y, navZ), new(x, startNav.Y, z), triangles, token))
                    throw new NavigationException("整數移動步伐超出可行走網格，已拒絕此路線。");
                if (step != previous) steps.Add(step);
                navX = x; navZ = z; previous = step;
            }
        }
        return steps.ToImmutable();
    }
}
