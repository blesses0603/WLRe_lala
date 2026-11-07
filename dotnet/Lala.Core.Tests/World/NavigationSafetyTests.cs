using System.Collections;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class NavigationSafetyTests
{
    private static readonly NavigationTriangle[] Square =
    [
        new(new(0, 0, 0), new(1000, 0, 0), new(0, 0, 1000)),
        new(new(1000, 0, 0), new(1000, 0, 1000), new(0, 0, 1000))
    ];
    private static PreviewNavigationMesh Preview() => new(
        [new NavigationTile(Square, [new(0, 1), new(17, 1)])],
        new[] { new[] { new NavigationConnection(1, 100) }, new[] { new NavigationConnection(0, 100) } });

    [Fact]
    public void CallerMutationsCannotChangeOwnedMeshOrRoute()
    {
        var triangles = Square.ToArray(); NavigationNodeMetadata?[] metadata = [new(0, 1), new(17, 1)];
        var tile = new NavigationTile(triangles, metadata);
        var first = new[] { new NavigationConnection(1, 100) };
        var connections = new[] { first, new[] { new NavigationConnection(0, 100) } };
        var mesh = new PreviewNavigationMesh([tile], connections);
        triangles[0] = default; metadata[1] = new(5000, 0); first[0] = new(99, 0); connections[1] = [];
        var route = mesh.Route(new(100, 100), new(900, 900));
        Assert.Equal(117u, route.Cost); Assert.Equal(Square[0], mesh.Faces[0]);
        Assert.True(mesh.Walkable.Contains(1)); Assert.True(mesh.Adjacency[1].ContainsKey(0));
        Assert.Throws<NotSupportedException>(() => ((IList<NavigationTriangle>)mesh.Faces)[0] = default);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<int, NavigationPoint>)mesh.Adjacency[0]).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<NavigationPoint>)route.Points)[0] = default);
        Assert.Throws<NotSupportedException>(() => ((IList<int>)route.Faces)[0] = 99);
    }

    [Fact]
    public void CheckedFallbackAndClaimAreOwnedAndNeverExecutionAuthority()
    {
        var mesh = Preview(); var route = mesh.Route(new(100, 100), new(900, 900));
        var points = route.Points.ToArray(); var faces = route.Faces.ToArray();
        var input = new PreviewRouteSnapshot(points, faces);
        points[0] = default; faces[0] = 99;
        var segments = input.Points.Zip(input.Points.Skip(1), (a, b) => new NavigationSegment(a, b)).ToArray();
        var result = NavigationMotionSafety.CheckPreview(mesh, input, segments, "test", "test");
        Assert.Equal("geometry_preview_only", result.Status);
        Assert.NotNull(result.Fallback);
        Assert.False(result.CanSendPackets); Assert.False(result.LiveMovementVerified);
        Assert.False(result.CollisionVerified); Assert.False(result.ActorClearanceVerified);
        Assert.False(result.Fallback.CanSendPackets); Assert.False(result.Fallback.LiveMovementVerified);
        Assert.True(result.Fallback.RequiresLiveControllerValidation);
        Assert.Equal(route.Points, result.Fallback.Points);
        Assert.Throws<NotSupportedException>(() => ((IList<NavigationPoint>)result.Fallback.Points)[0] = default);
        Assert.Equal("preview_authority_required", NavigationMotionSafety.CheckPreview(mesh,
            new(input.Points, input.Faces, true), segments, "test", "test").Reason);
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    [InlineData(1e308)]
    [InlineData(-1e308)]
    [InlineData(2147483648d)]
    [InlineData(-2147483649d)]
    public void InvalidAndOutOfInt3CoordinatesFailClosed(double invalid)
    {
        var bad = new NavigationPoint(invalid, 0, 0);
        Assert.Throws<NavigationException>(() => new NavigationMesh([new NavigationTile([new(bad, Square[0].B, Square[0].C)])]));
        var mesh = Preview();
        Assert.Throws<NavigationException>(() => mesh.Locate(invalid, 100));
        Assert.Throws<NavigationException>(() => mesh.Locate(100, 100, invalid));
        Assert.Throws<NavigationException>(() => mesh.Route(new(invalid, 100), new(900, 900)));
        Assert.Throws<NavigationException>(() => NavigationFunnel.SmoothCorridor(Square, bad, new(900, 0, 900)));
        Assert.Throws<NavigationException>(() => NavigationFunnel.Covered(bad, new(900, 0, 900), Square));
        Assert.Throws<NavigationException>(() => NavigationPoint.Distance(bad, default));
        Assert.Throws<NavigationException>(() => NavigationMesh.Area(bad, default, default));
        Assert.Throws<NavigationException>(() => NavigationFunnel.Area(bad, default, default));
        Assert.Throws<NavigationException>(() => new NavigationTriangle(bad, default, default).Center);
        Assert.Throws<NavigationException>(() => NavigationMotionSafety.Step([bad, new(900, 0, 900)], 0, bad, 1));
        var route = mesh.Route(new(100, 100), new(900, 900));
        Assert.Equal("invalid_points", NavigationMotionSafety.CheckPreview(mesh, new([bad, route.Points[^1]], route.Faces), [], "t", "t").Reason);
        Assert.Equal("invalid_motion", NavigationMotionSafety.CheckPreview(mesh, new(route), [new(route.Points[0], bad)], "t", "t").Reason);
    }

    [Fact]
    public void FullSignedInt3RangeProducesFiniteGeometry()
    {
        var a = new NavigationPoint(int.MinValue, int.MaxValue, int.MinValue);
        var b = new NavigationPoint(int.MaxValue, int.MaxValue, int.MinValue);
        var c = new NavigationPoint(int.MinValue, int.MaxValue, int.MaxValue);
        var triangle = new NavigationTriangle(a, b, c);
        var mesh = new NavigationMesh([new NavigationTile([triangle])]);
        Assert.True(mesh.Centers[0].IsInInt3Range);
        Assert.True(double.IsFinite(NavigationMesh.Area(a, b, c)));
        Assert.True(double.IsFinite(NavigationPoint.Distance(a, b)));
        var route = mesh.Route(new(a.X, a.Z), new(b.X, b.Z));
        Assert.Equal(4294967295d, route.Length);
        Assert.All(route.Points, p => Assert.True(p.IsInInt3Range));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void StepRejectsNonfiniteDistance(double distance) =>
        Assert.Throws<NavigationException>(() => NavigationMotionSafety.Step([new(0, 0, 0), new(100, 0, 0)], 0, default, distance));

    [Fact]
    public void EveryPublicQueryHonorsPreCancellation()
    {
        var token = new CancellationToken(true); var mesh = Preview(); var tile = new NavigationTile(Square);
        Assert.Throws<OperationCanceledException>(() => new NavigationTile(Square, cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => new NavigationMesh([tile], cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => new PreviewNavigationMesh([tile], [], cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => mesh.Locate(100, 100, cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => mesh.Route(new(100, 100), new(900, 900), cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => mesh.Route(new(100, 100), new(900, 900), null, null, true, token));
        var baseMesh = new NavigationMesh([tile]);
        Assert.Throws<OperationCanceledException>(() => baseMesh.Locate(100, 100, cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => baseMesh.Route(new(100, 100), new(900, 900), cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => NavigationFunnel.SmoothCorridor(Square, new(100, 0, 100), new(900, 0, 900), token));
        Assert.Throws<OperationCanceledException>(() => NavigationFunnel.Covered(new(100, 0, 100), new(900, 0, 900), Square, token));
        Assert.Throws<OperationCanceledException>(() => NavigationMotionSafety.Step([new(0, 0, 0), new(100, 0, 0)], 0, default, 5, token));
        Assert.Throws<OperationCanceledException>(() => NavigationMotionSafety.CheckPreview(mesh, new([], []), [], "t", "t", token));
    }

    [Fact]
    public void ConstructionCancelsDuringSourceEnumeration()
    {
        using var source = new CancellationTokenSource();
        IEnumerable<NavigationTile> Tiles()
        {
            yield return new NavigationTile([Square[0]]);
            source.Cancel();
            yield return new NavigationTile([Square[1]]);
        }
        Assert.Throws<OperationCanceledException>(() => new NavigationMesh(Tiles(), cancellationToken: source.Token));
    }

    [Fact]
    public void ConnectionSnapshotCancelsDuringSourceEnumeration()
    {
        using var source = new CancellationTokenSource();
        IEnumerable<NavigationConnection> Arcs()
        {
            yield return new(1, 100); source.Cancel(); yield return new(0, 100);
        }
        Assert.Throws<OperationCanceledException>(() => new PreviewNavigationMesh(
            [new NavigationTile(Square, [new(0, 1), new(0, 1)])], [Arcs(), []], cancellationToken: source.Token));
    }

    private sealed class CancellingTriangles(CancellationTokenSource source) : IReadOnlyList<NavigationTriangle>
    {
        public int Count => 2;
        public NavigationTriangle this[int index] => Square[index];
        public IEnumerator<NavigationTriangle> GetEnumerator()
        {
            yield return Square[0]; source.Cancel(); yield return Square[1];
        }
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }

    [Fact]
    public void ContainmentCancelsDuringTriangleEnumeration()
    {
        using var source = new CancellationTokenSource();
        Assert.Throws<OperationCanceledException>(() => NavigationFunnel.Covered(new(100, 0, 100), new(900, 0, 900),
            new CancellingTriangles(source), source.Token));
    }

    [Fact]
    public void RepeatedExactStepsKeepCornersAndFinishWithoutAuthority()
    {
        NavigationPoint[] points = [new(0, 0, 0), new(100, 0, 0), new(100, 0, 100), new(200, 0, 100)];
        var position = points[0]; var index = 0; var done = false;
        for (var i = 0; i < 100 && !done; i++)
        {
            var step = NavigationMotionSafety.Step(points, index, position, 3500d / 120);
            Assert.False(step.CanSendPackets); Assert.False(step.LiveMovementVerified);
            Assert.All(step.Segments, s => Assert.True(s.Start.X == s.End.X || s.Start.Z == s.End.Z));
            Assert.Throws<NotSupportedException>(() => ((IList<NavigationSegment>)step.Segments).Clear());
            position = step.Position; index = step.Index; done = step.Done;
        }
        Assert.True(done); Assert.Equal(points[^1], position);
    }

    [Fact]
    public void MetadataCountAndMissingOfficialFlagsFailClosed()
    {
        Assert.Throws<NavigationException>(() => new NavigationTile(Square, [new(0, 1)]));
        Assert.Equal("官方導航缺少節點旗標。", Assert.Throws<NavigationException>(() =>
            new PreviewNavigationMesh([new NavigationTile(Square)], [[], []])).Message);
        Assert.Equal("未驗證的通行模式。", Assert.Throws<NavigationException>(() =>
            new PreviewNavigationMesh([new NavigationTile([new(new(double.NaN, 0, 0), default, default)])], [], "unknown")).Message);
    }
}
