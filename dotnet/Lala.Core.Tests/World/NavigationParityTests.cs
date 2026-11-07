using System.Text.Json;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class NavigationParityTests
{
    private static NavigationPoint Point(JsonElement p) => new(p[0].GetDouble(), p[1].GetDouble(), p[2].GetDouble());
    private static NavigationCoordinate Coordinate(JsonElement p) => new(p[0].GetDouble(), p[1].GetDouble());
    private static NavigationPoint[] Points(JsonElement p) => p.EnumerateArray().Select(Point).ToArray();
    private static NavigationTriangle Triangle(JsonElement t) => new(Point(t[0]), Point(t[1]), Point(t[2]));
    private static double? OptionalDouble(JsonElement value, string key) =>
        value.TryGetProperty(key, out var item) && item.ValueKind != JsonValueKind.Null ? item.GetDouble() : null;
    private static string? OptionalString(JsonElement value, string key, string? fallback = null) =>
        value.TryGetProperty(key, out var item) ? item.GetString() : fallback;
    private static NavigationMesh Mesh(JsonElement vector)
    {
        var official = vector.TryGetProperty("official", out var source);
        var mesh = official ? source.GetProperty("mesh") : vector.GetProperty("mesh");
        var tiles = new List<NavigationTile>();
        foreach (var tile in mesh.GetProperty("tiles").EnumerateArray())
        {
            var vertices = Points(tile.GetProperty("vertices_b_int3"));
            var triangles = tile.GetProperty("triangles").EnumerateArray()
                .Select(t => new NavigationTriangle(vertices[t[0].GetInt32()], vertices[t[1].GetInt32()], vertices[t[2].GetInt32()])).ToArray();
            var metadata = tile.TryGetProperty("node_metadata", out var nodes)
                ? nodes.EnumerateArray().Select(n => n.ValueKind == JsonValueKind.Null ? (NavigationNodeMetadata?)null : new(n[0].GetUInt32(), n[1].GetUInt32())).ToArray()
                : null;
            if (vector.TryGetProperty("repeat_triangles", out var repeat))
            {
                triangles = Enumerable.Repeat(triangles.Single(), repeat.GetInt32()).ToArray();
                metadata = Enumerable.Repeat(metadata!.Single(), repeat.GetInt32()).ToArray();
            }
            tiles.Add(new(triangles, metadata));
        }
        if (!official) return new NavigationMesh(tiles, "M00042");
        var connections = source.GetProperty("connections").EnumerateArray().Select(row =>
            row.EnumerateArray().Select(arc => new NavigationConnection(arc[0].GetInt32(), arc[1].GetUInt32(), arc[2].GetInt32())).ToArray()).ToArray();
        if (vector.TryGetProperty("repeat_triangles", out var repeated))
            connections = Enumerable.Range(0, repeated.GetInt32()).Select(_ => Array.Empty<NavigationConnection>()).ToArray();
        return new PreviewNavigationMesh(tiles, connections, OptionalString(vector, "mode", "land")!, "M00042");
    }
    private static double[] Raw(NavigationPoint p) => [p.X, p.Y, p.Z];
    private static double[][] Raw(NavigationTriangle t) => [Raw(t.A), Raw(t.B), Raw(t.C)];
    private static double[][] Raw(NavigationSegment s) => [Raw(s.Start), Raw(s.End)];
    private static Dictionary<string, object?> RouteResult(NavigationRoute result)
    {
        var value = new Dictionary<string, object?>
        {
            ["scene_resource"] = result.SceneResource, ["coordinate_space"] = result.CoordinateSpace,
            ["network_coordinates_verified"] = result.NetworkCoordinatesVerified, ["connectivity"] = result.Connectivity,
            ["runtime_obstacles_applied"] = result.RuntimeObstaclesApplied, ["original_node_flags_applied"] = result.OriginalNodeFlagsApplied,
            ["points"] = result.Points.Select(Raw), ["faces"] = result.Faces, ["length"] = result.Length
        };
        Assert.False(result.CanSendPackets); Assert.False(result.LiveMovementVerified);
        if (result.Cost.HasValue)
        {
            value["cost"] = result.Cost; value["travel_mode"] = result.TravelMode; value["cost_policy"] = result.CostPolicy;
            value["original_walkability_applied"] = result.OriginalWalkabilityApplied; value["original_tags_applied"] = result.OriginalTagsApplied;
            value["serialized_costs_applied"] = result.SerializedCostsApplied; value["smoothing_applied"] = result.SmoothingApplied;
            value["can_send_packets"] = result.CanSendPackets; value["live_movement_verified"] = result.LiveMovementVerified;
            value["navigation_source"] = result.NavigationSource;
        }
        return value;
    }
    private static object CheckResult(NavigationMotionCheck result)
    {
        var value = new Dictionary<string, object?>
        {
            ["can_send_packets"] = result.CanSendPackets, ["live_movement_verified"] = result.LiveMovementVerified,
            ["collision_verified"] = result.CollisionVerified, ["actor_clearance_verified"] = result.ActorClearanceVerified,
            ["status"] = result.Status, ["reason"] = result.Reason, ["fallback"] = null
        };
        if (result.Fallback is { } fallback)
        {
            value["modeled_motion_containment"] = result.ModeledMotionContainment;
            value["rejected_segments"] = result.RejectedSegments; value["remaining_requirements"] = result.RemainingRequirements;
            value["fallback"] = new
            {
                policy = fallback.Policy, points = fallback.Points.Select(Raw), geometry_contained = fallback.GeometryContained,
                preview_stepper = fallback.PreviewStepper, requires_live_controller_validation = fallback.RequiresLiveControllerValidation,
                can_send_packets = fallback.CanSendPackets, live_movement_verified = fallback.LiveMovementVerified
            };
        }
        return value;
    }
    private static object Execute(JsonElement vector)
    {
        switch (vector.GetProperty("operation").GetString())
        {
            case "mesh":
                var mesh = Mesh(vector);
                var result = new Dictionary<string, object?>
                {
                    ["faces"] = mesh.Faces.Select(Raw), ["metadata"] = mesh.Metadata.Select(m => m.HasValue ? new[] {m.Value.Penalty, m.Value.Flags} : null),
                    ["centers"] = mesh.Centers.Select(Raw), ["adjacency"] = Enumerable.Range(0, mesh.Adjacency.Count)
                        .ToDictionary(i => i.ToString(System.Globalization.CultureInfo.InvariantCulture), i => mesh.Adjacency[i]
                            .ToDictionary(kv => kv.Key.ToString(System.Globalization.CultureInfo.InvariantCulture), kv => Raw(kv.Value))),
                    ["nonmanifold_edges"] = mesh.NonmanifoldEdges
                };
                if (mesh is PreviewNavigationMesh preview) { result["walkable"] = preview.Walkable.Order(); result["travel_mode"] = preview.TravelMode; }
                return result;
            case "locate":
                var coordinate = Coordinate(vector.GetProperty("coordinate"));
                var location = Mesh(vector).Locate(coordinate.X, coordinate.Z, OptionalDouble(vector, "height"));
                return new { face = location.Face, point = Raw(location.Point) };
            case "route":
                var routeMesh = Mesh(vector); var start = Coordinate(vector.GetProperty("start")); var end = Coordinate(vector.GetProperty("end"));
                var sh = OptionalDouble(vector, "start_height"); var eh = OptionalDouble(vector, "end_height");
                var route = routeMesh is PreviewNavigationMesh pm ? pm.Route(start, end, sh, eh,
                    vector.TryGetProperty("smooth", out var smooth) && smooth.GetBoolean()) : routeMesh.Route(start, end, sh, eh);
                return RouteResult(route);
            case "smooth":
                return NavigationFunnel.SmoothCorridor(vector.GetProperty("triangles").EnumerateArray().Select(Triangle).ToArray(),
                    Point(vector.GetProperty("start")), Point(vector.GetProperty("end"))).Select(Raw);
            case "covered":
                return NavigationFunnel.Covered(Point(vector.GetProperty("a")), Point(vector.GetProperty("b")),
                    vector.GetProperty("triangles").EnumerateArray().Select(Triangle).ToArray());
            case "step":
                var step = NavigationMotionSafety.Step(Points(vector.GetProperty("points")), vector.GetProperty("index").GetInt32(),
                    Point(vector.GetProperty("position")), vector.GetProperty("distance").GetDouble());
                return new { position = Raw(step.Position), index = step.Index, done = step.Done, segments = step.Segments.Select(Raw),
                    can_send_packets = step.CanSendPackets, live_movement_verified = step.LiveMovementVerified };
            case "safety":
                var claim = vector.GetProperty("route");
                var input = new PreviewRouteSnapshot(Points(claim.GetProperty("points")), claim.GetProperty("faces").EnumerateArray().Select(f => f.GetInt32()),
                    claim.TryGetProperty("can_send_packets", out var authority) && authority.ValueKind != JsonValueKind.Null ? authority.GetBoolean() : null);
                return CheckResult(NavigationMotionSafety.CheckPreview((PreviewNavigationMesh)Mesh(vector), input,
                    vector.GetProperty("segments").EnumerateArray().Select(s => new NavigationSegment(Point(s[0]), Point(s[1]))).ToArray(),
                    OptionalString(vector, "catalog", "synthetic"), OptionalString(vector, "expected_catalog", "synthetic")));
            default: throw new InvalidOperationException("Unknown vector operation.");
        }
    }

    [Theory]
    [MemberData(nameof(PythonNavigationVectors.Cases), MemberType = typeof(PythonNavigationVectors))]
    public void MatchesRetainedPython(string name, string json)
    {
        using var document = JsonDocument.Parse(json); var vector = document.RootElement;
        if (vector.TryGetProperty("error", out var error))
        {
            var exception = Assert.ThrowsAny<NavigationException>(() => Execute(vector));
            Assert.Equal(error.GetString(), exception.Message);
            if (vector.TryGetProperty("details", out var details))
            {
                var noRoute = Assert.IsType<NoPreviewRouteException>(exception);
                AssertJson(details, JsonSerializer.SerializeToElement(new { source_node = noRoute.SourceNode,
                    target_node = noRoute.TargetNode, reachable_nodes = noRoute.ReachableNodes, travel_mode = noRoute.TravelMode }), name);
            }
        }
        else AssertJson(vector.GetProperty("expected"), JsonSerializer.SerializeToElement(Execute(vector)), name);
    }
    private static void AssertJson(JsonElement expected, JsonElement actual, string path)
    {
        Assert.True(expected.ValueKind == actual.ValueKind, $"{path}: expected {expected.ValueKind}, got {actual.ValueKind}");
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
                if (expected.TryGetInt64(out var e) && actual.TryGetInt64(out var a)) Assert.Equal(e, a);
                else
                {
                    var wanted = expected.GetDouble(); var got = actual.GetDouble();
                    Assert.True(double.IsFinite(got) && Math.Abs(wanted - got) <= 1e-8 + 2e-12 * Math.Abs(wanted), $"{path}: expected {wanted:R}, got {got:R}");
                }
                break;
            default: Assert.Equal(expected.GetRawText(), actual.GetRawText()); break;
        }
    }
}
