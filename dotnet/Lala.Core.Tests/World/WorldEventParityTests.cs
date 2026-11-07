using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Protocol;
using Lala.Core.World;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class WorldEventParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new BigIntegerConverter() }
    };

    [Theory]
    [MemberData(nameof(WorldEventPythonVectors.Sequences), MemberType = typeof(WorldEventPythonVectors))]
    public void EveryCheckpointMatchesRetainedPythonAndEarlierSnapshotsStayImmutable(string name, string json)
    {
        Assert.NotEmpty(name);
        var vector = JsonNode.Parse(json)!;
        var state = ReadState(vector["initial"]!);
        var catalog = ReadCatalog(vector["catalog"]);
        Check(vector["initial"]!, state);
        var retained = new List<(WorldEventSnapshot State, JsonNode Expected)> { (state, vector["initial"]!) };
        foreach (var step in vector["steps"]!.AsArray())
        {
            var input = state;
            var before = Project(input).ToJsonString();
            state = ApplyStep(state, step!, catalog);
            Assert.Equal(before, Project(input).ToJsonString());
            Check(step!["expected"]!, state);
            retained.Add((state, step["expected"]!));
        }
        foreach (var (snapshot, expected) in retained) Check(expected, snapshot);
    }

    [Theory]
    [MemberData(nameof(WorldEventPythonVectors.Scopes), MemberType = typeof(WorldEventPythonVectors))]
    public void ObstacleClassificationMatchesPythonWithExplicitCatalogEvidence(string name, string json)
    {
        Assert.NotEmpty(name);
        var vector = JsonNode.Parse(json)!;
        var scene = vector["scene"]?.GetValue<ushort>();
        var catalog = ReadCatalog(vector["catalog"]);
        Assert.Equal(vector["expected"]!["house"]?.GetValue<bool>(), WorldObstacleScope.HouseScene(scene, catalog));
        Assert.Equal(vector["expected"]!["affects"]!.GetValue<bool>(), WorldObstacleScope.AffectsNavigation(
            vector["affects_geometry"]!.GetValue<bool>(), vector["geometry_scope"]?.GetValue<string>(), scene, catalog));
    }

    private static WorldEventSnapshot ApplyStep(WorldEventSnapshot state, JsonNode step, WorldSceneCatalog? catalog)
    {
        switch (step["operation"]!.GetValue<string>())
        {
            case "packet":
                var packet = new Packet(step["main"]!.GetValue<int>(), step["sub"]!.GetValue<int>(),
                    Convert.FromHexString(step["hex"]!.GetValue<string>()));
                return WorldEventReducer.Apply(state with { PacketCount = state.PacketCount + 1 }, ServerProtocol.Decode(packet), catalog);
            case "event":
                var value = step["event"]!;
                ServerEvent observation = value["type"]!.GetValue<string>() switch
                {
                    "movement_request" => new MovementRequestEvent(value["x"]!.GetValue<ushort>(), value["y"]!.GetValue<ushort>()),
                    "navigation_geometry_change" => new NavigationGeometryChangeEvent(62, 64, value["reason"]!.GetValue<string>(),
                        value["affects_geometry"]!.GetValue<bool>(), 0),
                    _ => throw new InvalidOperationException("Unsupported synthetic world event")
                };
                return WorldEventReducer.Apply(state with { PacketCount = state.PacketCount + 1 }, observation, catalog);
            case "remote_walk_range":
                int start = step["start"]!.GetValue<int>(), count = step["count"]!.GetValue<int>();
                for (int role = start; role < start + count; role++)
                    state = WorldEventReducer.Apply(state with { PacketCount = state.PacketCount + 1 }, new WalkEvent(role, (ushort)(role % 65536), 1), catalog);
                return state;
            case "remember":
                return WorldEventReducer.RememberPosition(state, step["role_id"]!.GetValue<long>(),
                    step["x"]!.GetValue<ushort>(), step["y"]!.GetValue<ushort>());
            case "clear":
                var cleared = WorldEventReducer.ClearPositionHistory(state);
                Assert.Equal(step["removed"]!.GetValue<int>(), cleared.Removed);
                return cleared.State;
            case "wait": return WorldEventReducer.WaitForPosition(state);
            case "confirm": return WorldEventReducer.ConfirmLocation(state, step["scene"]!.GetValue<ushort>(),
                step["x"]!.GetValue<ushort>(), step["y"]!.GetValue<ushort>(), step["source"]!.GetValue<string>());
            default: throw new InvalidOperationException("Unsupported synthetic operation");
        }
    }

    private static WorldSceneCatalog? ReadCatalog(JsonNode? catalog) => catalog is null ? null : new(
        catalog["stage_ids"]!.AsArray().Select(x => x!.GetValue<ushort>()).ToImmutableHashSet(),
        catalog["verified_instance_alias_ids"]?.AsArray().Select(x => x!.GetValue<ushort>()).ToImmutableHashSet());

    private static WorldEventSnapshot ReadState(JsonNode value)
    {
        var player = value["player"]?.Deserialize<WorldPlayer>(Options);
        var positions = WorldPositionCache.Empty;
        foreach (var position in value["positions"]!.AsArray())
            positions = positions.Remember(position!["role_id"]!.GetValue<long>(), position["x"]!.GetValue<ushort>(),
                position["y"]!.GetValue<ushort>(), player?.RoleId);
        return new()
        {
            Phase = value["phase"]!.GetValue<string>(), PacketCount = value["packet_count"]!.Deserialize<BigInteger>(Options),
            Player = player, Positions = positions,
            Navigation = value["navigation"]!.Deserialize<WorldNavigationSnapshot>(Options)!,
            Location = value["location"]!.Deserialize<WorldLocationSnapshot>(Options)!,
            LocalMovement = value["local_movement"]?.Deserialize<WorldLocalMovement>(Options),
            MovementCheck = value["movement_check"]?.Deserialize<WorldMovementCheck>(Options)
        };
    }

    private static JsonNode Project(WorldEventSnapshot state) => JsonSerializer.SerializeToNode(new
    {
        state.Phase, state.PacketCount, state.Player, Positions = state.Positions.Entries.ToArray(),
        state.Navigation, state.Location, state.LocalMovement, state.MovementCheck
    }, Options)!;

    private static void Check(JsonNode expected, WorldEventSnapshot state)
    {
        var actual = WithoutNulls(Project(state));
        expected = WithoutNulls(expected.DeepClone());
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"Expected {expected}; actual {actual}");
    }

    private static JsonNode WithoutNulls(JsonNode node)
    {
        if (node is JsonObject obj)
            foreach (var (key, value) in obj.ToArray())
                if (value is null) obj.Remove(key); else WithoutNulls(value);
        if (node is JsonArray array)
            foreach (var value in array) if (value is not null) WithoutNulls(value);
        return node;
    }

    private sealed class BigIntegerConverter : JsonConverter<BigInteger>
    {
        public override BigInteger Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            using var value = JsonDocument.ParseValue(ref reader);
            return BigInteger.Parse(value.RootElement.GetRawText(), CultureInfo.InvariantCulture);
        }
        public override void Write(Utf8JsonWriter writer, BigInteger value, JsonSerializerOptions options) =>
            writer.WriteRawValue(value.ToString(CultureInfo.InvariantCulture));
    }
}
