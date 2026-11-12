using Lala.Core.Catalogs;
using Lala.Core.World;

// No friend access. This claim deliberately does not authenticate synthetic geometry.
internal static class LogicalNavigationPublicCheck
{
    public static void Run()
    {
        var identity = new OfflineNavigationIdentity("b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6", "synthetic-1.2.3");
        var stage = new StageDataRow(200, 0, 42, 4, 0, 0, 0, 0, 1, 0, 0, 0, 0, 100, 65535, 0, 0);
        var mesh = new PreviewNavigationMesh([new NavigationTile([
            new(new(0, 3, 0), new(100, 3, 0), new(100, 3, 100)),
            new(new(0, 3, 0), new(100, 3, 100), new(0, 3, 100))], [new(0, 1), new(7, 1)])],
            [[new(1, 23)], [new(0, 41)]], sceneId: "M00042");
        var cache = new OfflineNavigationCacheEntry(identity, 42, new(10, 999, 20), mesh);
        var preview = new OfflineLogicalNavigationPreview(identity, new(identity, [stage]), [cache]);
        var state = new WorldNavigationSnapshot { Scene = 200, Revision = 10 };
        var route = preview.Route(200, new(9, 6988), new(3, 6982), navigation: state);
        Require(route.StageId == 200 && route.ModelId == 42 && route.MeshRoute.Cost == 30);
        Require(route.LogicalPoints[0] == new LogicalNavigationCoordinate(9, 6988));
        Require(route.LogicalPoints[^1] == new LogicalNavigationCoordinate(3, 6982));
        Require(route.MeshRoute.Points[0].Y == 3 && ReferenceEquals(state, route.InputNavigation));
        Require(route.IsHistorical && !route.SourceProvenanceVerified && !route.AssetsReady && !route.CanSendPackets);
        Require(!route.LiveMovementVerified && !route.NetworkCoordinatesVerified && !route.RuntimeObstaclesApplied && !route.MeshRoute.CanSendPackets);
        Require(ReferenceEquals(cache, preview.Load(42)));
        Reject(() => preview.Route(61501, new(9, 6988), new(3, 6982))); // Public real order pin rejects this synthetic order.
        Reject(() => preview.Route(200, new(9, 6988), new(3, 6982), navigation: state with { Stale = true }));
        var other = new OfflineNavigationIdentity(identity.ClaimedManifestKey, "different-version");
        Reject(() => new OfflineLogicalNavigationPreview(identity, new(other, [stage]), [cache]));
        Console.WriteLine("Public logical-map route preview contract passed; synthetic claims, historical offline points, no send authority.");
    }
    private static void Reject(Action action)
    {
        try { action(); } catch (NavigationException) { return; }
        throw new InvalidOperationException("Logical preview public contract did not fail closed.");
    }
    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Logical preview public contract failed.");
    }
}
