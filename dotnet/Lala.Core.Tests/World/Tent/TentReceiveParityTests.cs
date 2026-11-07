using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.World;
using Lala.Core.World.Tent;
using Xunit;

namespace Lala.Core.Tests.World.Tent;

public sealed class TentReceiveParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    [Theory]
    [MemberData(nameof(TentStatePythonVectors.Sequences), MemberType = typeof(TentStatePythonVectors))]
    public void AllReceiveTransitionsAndHistoricalSnapshotsMatchPython(string name, string json)
    {
        var scenario = JsonNode.Parse(json)!;
        var steps = scenario["steps"]!.AsArray();
        var catalogNode = scenario["catalog"];
        var catalog = catalogNode is null ? null : new WorldSceneCatalog(
            catalogNode["stage_ids"]!.AsArray().Select(id => id!.GetValue<ushort>()).ToImmutableHashSet(),
            catalogNode["verified_instance_alias_ids"]!.AsArray().Select(id => id!.GetValue<ushort>()).ToImmutableHashSet());
        var role = steps[0]!["role"]?.GetValue<uint>();
        var scene = steps[0]!["scene"]?.GetValue<ushort>();
        var state = steps[0]!["expected"]!.Deserialize<TentReceiveSnapshot>(Options)!;
        var history = new List<(TentReceiveSnapshot State, JsonNode Expected)>();
        var stepNumber = 0;
        foreach (var step in steps)
        {
            if (step!["operation"] is { } operation)
            {
                ServerEvent observation;
                if (operation["direct"] is { } direct)
                    observation = new NamedEvent(direct["type"]!.GetValue<string>());
                else
                {
                    var packet = new Packet(operation["main"]!.GetValue<byte>(), operation["sub"]!.GetValue<byte>(),
                        Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                    if (step["error"] is { } error)
                    {
                        Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet, role)).Message);
                        Check(step["expected"]!, state, $"{name}, malformed step {stepNumber++}");
                        history.Add((state, step["expected"]!));
                        continue;
                    }
                    observation = ServerProtocol.Decode(packet, role);
                }
                // Caller context has the post-world-dispatch identity and scene, as in Python state.py.
                if (observation is ServerLayoutEvent { Event: WorldPlayerEvent world })
                {
                    role = world.Player.RoleId;
                    scene = world.Player.Scene;
                }
                else if (observation is PositionSnapshotEvent position && position.RoleId == role)
                    scene = position.Scene;
                state = TentReceiveReducer.Apply(state, observation, role, scene, catalog);
            }
            Assert.Equal(step!["role"]?.GetValue<uint>(), role);
            Assert.Equal(step["scene"]?.GetValue<ushort>(), scene);
            Check(step["expected"]!, state, $"{name}, step {stepNumber++}");
            history.Add((state, step["expected"]!));
        }
        foreach (var previous in history) Check(previous.Expected, previous.State, name + " historical");
    }

    [Fact]
    public void OracleHashesMatchRetainedPythonWithByteOnlyCrLfNormalization()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "wlre", "services", "world", "tent.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, hash) in JsonNode.Parse(TentStatePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), Convert.ToHexString(SHA256.HashData(CanonicalSourceBytes(
                File.ReadAllBytes(Path.Combine(root.FullName, path))))).ToLowerInvariant());
    }

    [Fact]
    public void SourceHashNormalizationPreservesInvalidUtf8AndBareCarriageReturns()
    {
        Assert.Equal(new byte[] { 255, 10, 254, 13, 0, 10, 13 },
            CanonicalSourceBytes([255, 13, 10, 254, 13, 0, 10, 13]));
    }

    private static byte[] CanonicalSourceBytes(byte[] bytes)
    {
        using var output = new MemoryStream(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
        {
            if (bytes[i] == 13 && i + 1 < bytes.Length && bytes[i + 1] == 10) continue;
            output.WriteByte(bytes[i]);
        }
        return output.ToArray();
    }

    private sealed record NamedEvent(string Name) : ServerEvent(0, 0)
    {
        public override string Type => Name;
    }

    private static JsonNode Project(TentReceiveSnapshot state)
    {
        var result = JsonSerializer.SerializeToNode(state, Options)!;
        foreach (var field in new[] { "pending", "entry_context" })
        {
            if (result[field] is not JsonObject action) continue;
            foreach (var key in new[] { "due", "furniture_received", "source_scene" })
                if (action[key] is null && !(field == "entry_context" && key == "source_scene")) action.Remove(key);
        }
        return result;
    }

    private static void Check(JsonNode expected, TentReceiveSnapshot state, string context)
    {
        var actual = Project(state);
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{context}\nExpected: {expected}\nActual: {actual}");
    }
}
