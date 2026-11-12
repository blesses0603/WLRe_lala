using System.Buffers.Binary;
using System.Collections;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class LogicalNavigationPreviewTests
{
    private const string Key = "b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6";
    private static OfflineNavigationIdentity Identity(string key = Key, string version = "synthetic-1.2.3") => new(key, version);
    private static StageDataRow Stage(ushort id = 200, ushort model = 42, ushort height = 100, byte members = 0, byte rooms = 0) =>
        new(id, 0, model, members, 0, 0, 0, 0, rooms, 0, 0, 0, 0, 100, height, 0, 0);
    private static readonly NavigationTriangle Triangle = new(new(0, 0, 0), new(100, 0, 0), new(100, 0, 100));
    private static PreviewNavigationMesh Mesh(ushort model = 42, int faces = 1, int connections = 0, string mode = "land") =>
        new([new NavigationTile(Enumerable.Repeat(Triangle, faces), Enumerable.Repeat<NavigationNodeMetadata?>(new(0, 1), faces))],
            Enumerable.Range(0, faces).Select(i => i == 0 ? Enumerable.Repeat(new NavigationConnection(0, 0), connections) : []),
            mode, $"M{model:D5}");
    private static OfflineNavigationCacheEntry Cache(OfflineNavigationIdentity? identity = null, ushort model = 42,
        NavigationPoint origin = default, PreviewNavigationMesh? mesh = null) => new(identity ?? Identity(), model, origin, mesh ?? Mesh(model));
    private static OfflineLogicalNavigationPreview Preview(IEnumerable<StageDataRow>? rows = null,
        IEnumerable<OfflineNavigationCacheEntry>? cache = null, OfflineNavigationIdentity? identity = null) =>
        new(identity ?? Identity(), new(identity ?? Identity(), rows ?? [Stage()]), cache ?? [Cache(identity)]);
    private static NavigationPoint Point(JsonElement value) => new(value[0].GetDouble(), value[1].GetDouble(), value[2].GetDouble());
    private static LogicalNavigationCoordinate XY(JsonElement value) => new(value[0].GetDouble(), value[1].GetDouble());
    private static double? Height(JsonElement value, string key) => value.GetProperty(key).ValueKind == JsonValueKind.Null ? null : value.GetProperty(key).GetDouble();

    [Theory]
    [MemberData(nameof(PythonLogicalNavigationVectors.Cases), MemberType = typeof(PythonLogicalNavigationVectors))]
    public void MatchesActualPythonCacheOnlyOracle(string name, string json)
    {
        using var document = JsonDocument.Parse(json); var v = document.RootElement;
        var identity = Identity(v.GetProperty("claimed_manifest_key").GetString()!, v.GetProperty("data_version").GetString()!);
        var stages = new OfflineNavigationStages(identity, v.GetProperty("stages").EnumerateArray().Select(s =>
            Stage(s.GetProperty("id").GetUInt16(), s.GetProperty("model_id").GetUInt16(), s.GetProperty("map_height").GetUInt16(),
                s.GetProperty("max_members").GetByte(), s.GetProperty("room_capacity").GetByte())));
        var geometry = v.GetProperty("geometry");
        var tiles = geometry.GetProperty("mesh").GetProperty("tiles").EnumerateArray().Select(t =>
        {
            var vertices = t.GetProperty("vertices_b_int3").EnumerateArray().Select(Point).ToArray();
            return new NavigationTile(t.GetProperty("triangles").EnumerateArray().Select(tri =>
                new NavigationTriangle(vertices[tri[0].GetInt32()], vertices[tri[1].GetInt32()], vertices[tri[2].GetInt32()])),
                t.GetProperty("node_metadata").EnumerateArray().Select(m => (NavigationNodeMetadata?)new(m[0].GetUInt32(), m[1].GetUInt32())));
        });
        var model = v.GetProperty("model").GetUInt16(); var mode = v.GetProperty("mode").GetString()!;
        var mesh = new PreviewNavigationMesh(tiles, geometry.GetProperty("connections").EnumerateArray().Select(row =>
            row.EnumerateArray().Select(arc => new NavigationConnection(arc[0].GetInt32(), arc[1].GetUInt32(), arc[2].GetInt32()))), mode, $"M{model:D5}");
        OfflineNavigationCacheEntry[] cache = v.GetProperty("cache").GetBoolean() ? [new(identity, model, Point(v.GetProperty("origin")), mesh)] : [];
        var preview = v.TryGetProperty("synthetic_reviewed_order", out var review)
            ? new OfflineLogicalNavigationPreview(identity, stages, cache, review.GetString()!)
            : new OfflineLogicalNavigationPreview(identity, stages, cache);
        var state = v.GetProperty("navigation");
        WorldNavigationSnapshot? navigation = state.ValueKind == JsonValueKind.Null ? null : new()
        {
            Scene = state.GetProperty("scene").GetUInt16(), Stale = state.GetProperty("stale").GetBoolean(),
            Revision = state.TryGetProperty("revision", out var revision) ? revision.GetInt32() : 0
        };
        OfflineLogicalNavigationRoute Execute() => preview.Route(v.GetProperty("logical_map").GetUInt16(), XY(v.GetProperty("start")),
            XY(v.GetProperty("end")), Height(v, "start_height"), Height(v, "end_height"), navigation, mode, v.GetProperty("smooth").GetBoolean());
        if (v.TryGetProperty("error", out var error))
        {
            Assert.Equal(error.GetString(), Assert.ThrowsAny<NavigationException>(Execute).Message);
            return;
        }
        var result = Execute(); var route = result.MeshRoute;
        Assert.True(result.IsHistorical); Assert.False(result.SourceProvenanceVerified); Assert.False(result.AssetsReady);
        Assert.Equal("caller_supplied_offline_navigation_preview", result.NavigationSource);
        Assert.Same(navigation, result.InputNavigation); Assert.Equal(identity, result.Identity);
        Assert.Equal(stages.Rows[result.StageId].ModelId, result.ModelId);
        var actual = JsonSerializer.SerializeToElement(new
        {
            logical_map = result.LogicalMap, catalog_key = result.Identity.ClaimedManifestKey,
            scene_resource = route.SceneResource, points = route.Points.Select(p => new[] { p.X, p.Y, p.Z }), faces = route.Faces,
            length = route.Length, cost = route.Cost, travel_mode = route.TravelMode, smoothing_applied = route.SmoothingApplied,
            packet_points_xy_float = result.LogicalPoints.Select(p => new[] { p.X, p.Y }),
            can_send_packets = result.CanSendPackets, live_movement_verified = result.LiveMovementVerified,
            network_coordinates_verified = result.NetworkCoordinatesVerified, runtime_obstacles_applied = result.RuntimeObstaclesApplied
        });
        AssertJson(v.GetProperty("expected"), actual, name);
    }

    [Fact]
    public void PublicPinsRejectSyntheticAliasOrderEvenWhenIdentityClaimsMatch()
    {
        var rows = new[] { Stage(200, members: 4, rooms: 2), Stage(100, members: 4, rooms: 1) };
        Assert.Equal("副本場景的官方原始順序未通過驗證。", Assert.Throws<NavigationException>(() =>
            Preview(rows).Route(61501, new(8, 98), new(7, 99))).Message);
        Assert.Equal(Key, OfflineLogicalNavigationPreview.ReviewedCoordinateKey);
        Assert.Equal("1f1bd5ad718542a8469812a5cdabc12155a24ac01fdac6e2dc2506d82c3c41dd", OfflineLogicalNavigationPreview.ReviewedStageOrder);
        Assert.All(typeof(OfflineLogicalNavigationPreview).GetConstructors(), constructor =>
            Assert.DoesNotContain(constructor.GetParameters(), p => p.ParameterType == typeof(string)));
    }

    [Fact]
    public void StageParserOrderIsKeptAndNeverSorted()
    {
        var bytes = new byte[4 + 2 * StageDataParser.RecordBytes]; BinaryPrimitives.WriteInt32LittleEndian(bytes, 2);
        for (var i = 0; i < 2; i++)
        {
            var row = bytes.AsSpan(4 + i * StageDataParser.RecordBytes, StageDataParser.RecordBytes);
            BinaryPrimitives.WriteUInt16LittleEndian(row, i == 0 ? (ushort)200 : (ushort)100);
            BinaryPrimitives.WriteUInt16LittleEndian(row[8..], 42); row[21] = 4; row[24] = 1;
            BinaryPrimitives.WriteUInt16LittleEndian(row[54..], 100);
        }
        var stages = new OfflineNavigationStages(Identity(), StageDataParser.Parse(bytes).Values);
        Assert.Equal(new ushort[] { 200, 100 }, stages.OriginalOrder.Select(s => s.Id));
        var hash = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes("[200,100]")));
        var preview = new OfflineLogicalNavigationPreview(Identity(), stages, [Cache()], hash);
        Assert.Equal((ushort)200, preview.Route(61501, new(8, 98), new(7, 99)).StageId);
        Assert.Equal((ushort)100, preview.Route(61502, new(8, 98), new(7, 99)).StageId);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public void ExactCatalogAndVersionRequiredAcrossStagesAndCache(bool changeKey)
    {
        var expected = Identity(); var different = changeKey ? Identity(new string('a', 64)) : Identity(version: "synthetic-other-version");
        Assert.Throws<NavigationException>(() => new OfflineLogicalNavigationPreview(expected, new(different, [Stage()]), [Cache()]));
        Assert.Throws<NavigationException>(() => new OfflineLogicalNavigationPreview(expected, new(expected, [Stage()]), [Cache(different)]));
    }

    [Fact]
    public void ExactModelSceneModeRequiredWithoutFallback()
    {
        Assert.Throws<NavigationException>(() => Cache(model: 43, mesh: Mesh()));
        Assert.Throws<NavigationException>(() => Cache(mesh: new PreviewNavigationMesh([], [])));
        Assert.Throws<NavigationException>(() => Preview([Stage(model: 43)]).Route(200, new(8, 98), new(7, 99)));
        Assert.Throws<NavigationException>(() => Preview().Load(42, "sea"));
        Assert.Throws<NavigationException>(() => Preview().Load(42, "unknown"));
        Assert.Same(Preview().Load(42).Mesh.GetType(), typeof(PreviewNavigationMesh));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    [InlineData(double.MaxValue)]
    [InlineData(2147483648d)]
    public void NonfiniteAndOutOfRangeCoordinatesAndOriginsAreRejected(double invalid)
    {
        var preview = Preview();
        Assert.Throws<NavigationException>(() => preview.Route(200, new(invalid, 98), new(7, 99)));
        Assert.Throws<NavigationException>(() => preview.Route(200, new(8, 98), new(7, invalid)));
        Assert.Throws<NavigationException>(() => preview.Route(200, new(8, 98), new(7, 99), startHeight: invalid));
        Assert.Throws<NavigationException>(() => Cache(origin: new(invalid, 0, 0)));
        Assert.Throws<NavigationException>(() => Cache(origin: new(0, invalid, 0)));
        Assert.Throws<NavigationException>(() => Cache(origin: new(0, 0, invalid)));
    }

    [Fact]
    public void ConversionOverflowIsRejectedBeforeMeshLookup()
    {
        Assert.Contains("Int3", Assert.Throws<NavigationException>(() => Preview().Route(200, new(int.MaxValue, 98), new(7, 99))).Message);
        Assert.Contains("Int3", Assert.Throws<NavigationException>(() => Preview(cache: [Cache(origin: new(int.MinValue, 0, 0))])
            .Route(200, new(1, 98), new(7, 99))).Message);
    }

    [Fact]
    public void InputsAreOwnedAndOldResultsRemainHistorical()
    {
        var stages = new List<StageDataRow> { Stage() }; var entries = new List<OfflineNavigationCacheEntry> { Cache() };
        var preview = Preview(stages, entries); stages.Clear(); entries.Clear();
        var oldState = new WorldNavigationSnapshot { Scene = 200, Revision = 11, RuntimeGeometryVerified = true };
        var route = preview.Route(200, new(8, 98), new(7, 99), navigation: oldState);
        Assert.Equal((ushort)200, route.StageId); Assert.Equal(2, route.LogicalPoints.Length);
        Assert.False(route.CanSendPackets); Assert.False(route.MeshRoute.CanSendPackets);
        Assert.False(route.SourceProvenanceVerified); Assert.True(route.IsHistorical);
        Assert.Throws<NavigationException>(() => preview.Route(200, new(8, 98), new(7, 99), navigation: oldState with { Stale = true, Revision = 12 }));
        Assert.Same(oldState, route.InputNavigation); Assert.Equal(11, (int)route.InputNavigation!.Revision);
        Assert.False(route.LiveMovementVerified); Assert.False(route.NetworkCoordinatesVerified);
        Assert.False(route.RuntimeObstaclesApplied); Assert.False(route.AssetsReady);
        Assert.Throws<NotSupportedException>(() => ((IList)route.MeshRoute.Points).Clear());
    }

    [Fact]
    public void HouseContextAndRuntimeGeometryFlagNeverUnlockHouseRoutes()
    {
        var state = new WorldNavigationSnapshot { Scene = 63501, RuntimeGeometryVerified = true,
            HouseContext = new(63501, true, 1) { Sizes = System.Collections.Immutable.ImmutableDictionary<byte, byte>.Empty.Add(1, 2) } };
        Assert.Contains("玩家小屋", Assert.Throws<NavigationException>(() => Preview([Stage(63501)])
            .Route(63501, new(8, 98), new(7, 99), navigation: state)).Message);
    }

    [Fact]
    public void StageEnumerationHasHardLimitAndDuplicateRejection()
    {
        Assert.Throws<NavigationException>(() => new OfflineNavigationStages(Identity(), [Stage(), Stage()]));
        var yielded = 0;
        IEnumerable<StageDataRow> Oversized()
        {
            for (var i = 0; ; i++) { yielded++; yield return Stage((ushort)i); }
        }
        Assert.Throws<NavigationException>(() => new OfflineNavigationStages(Identity(), Oversized()));
        Assert.Equal(StageDataParser.MaxRecords + 1, yielded);
    }

    [Fact]
    public void PerMeshAndAggregateBudgetsAreEnforced()
    {
        Assert.Throws<NavigationException>(() => Cache(mesh: Mesh(faces: OfflineNavigationCacheEntry.MaxFaces + 1)));
        Assert.Throws<NavigationException>(() => Cache(mesh: Mesh(connections: OfflineNavigationCacheEntry.MaxConnections + 1)));
        Assert.Throws<NavigationException>(() => Preview(cache: [Cache(), Cache()]));
        var count = 0;
        IEnumerable<OfflineNavigationCacheEntry> Entries(int faces, int arcs, int amount)
        {
            for (ushort i = 0; i < amount; i++) { count++; yield return Cache(model: i, mesh: Mesh(i, faces, arcs)); }
        }
        Assert.Throws<NavigationException>(() => Preview(cache: Entries(0, 0, 257))); Assert.Equal(257, count);
        count = 0;
        Assert.Throws<NavigationException>(() => Preview(cache: Entries(10_000, 0, 11))); Assert.Equal(11, count);
        count = 0;
        Assert.Throws<NavigationException>(() => Preview(cache: Entries(1, 100_000, 11))); Assert.Equal(11, count);
    }

    [Fact]
    public void CancellationNeverReturnsPartialStagesCacheOrRoute()
    {
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel(); var token = cancellation.Token;
        Assert.Throws<OperationCanceledException>(() => new OfflineNavigationStages(Identity(), [], token));
        Assert.Throws<OperationCanceledException>(() => new OfflineLogicalNavigationPreview(Identity(), new(Identity(), []), [], token));
        Assert.Throws<OperationCanceledException>(() => Preview().Load(42, cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => Preview().Route(200, new(8, 98), new(7, 99), cancellationToken: token));
        using var during = new CancellationTokenSource();
        IEnumerable<StageDataRow> Rows() { yield return Stage(); during.Cancel(); yield return Stage(201); }
        Assert.Throws<OperationCanceledException>(() => new OfflineNavigationStages(Identity(), Rows(), during.Token));
        using var duringCache = new CancellationTokenSource();
        IEnumerable<OfflineNavigationCacheEntry> Entries() { yield return Cache(); duringCache.Cancel(); yield return Cache(model: 43); }
        Assert.Throws<OperationCanceledException>(() => new OfflineLogicalNavigationPreview(Identity(), new(Identity(), [Stage()]), Entries(), duringCache.Token));
    }

    [Theory]
    [InlineData("", "synthetic")]
    [InlineData("ABC", "synthetic")]
    [InlineData(Key, "")]
    [InlineData(Key, "bad\nversion")]
    public void InvalidIdentityClaimsAreRejected(string key, string version) => Assert.Throws<NavigationException>(() => Identity(key, version));

    private static void AssertJson(JsonElement expected, JsonElement actual, string path)
    {
        Assert.Equal(expected.ValueKind, actual.ValueKind);
        switch (expected.ValueKind)
        {
            case JsonValueKind.Object:
                Assert.Equal(expected.EnumerateObject().Select(p => p.Name).Order(), actual.EnumerateObject().Select(p => p.Name).Order());
                foreach (var property in expected.EnumerateObject()) AssertJson(property.Value, actual.GetProperty(property.Name), path + "." + property.Name);
                break;
            case JsonValueKind.Array:
                Assert.Equal(expected.GetArrayLength(), actual.GetArrayLength());
                for (var i = 0; i < expected.GetArrayLength(); i++) AssertJson(expected[i], actual[i], $"{path}[{i}]");
                break;
            case JsonValueKind.Number:
                var wanted = expected.GetDouble(); var got = actual.GetDouble();
                Assert.True(double.IsFinite(got) && Math.Abs(wanted - got) <= 1e-8 + 2e-12 * Math.Abs(wanted), $"{path}: expected {wanted:R}, got {got:R}");
                break;
            default: Assert.Equal(expected.GetRawText(), actual.GetRawText()); break;
        }
    }
}
