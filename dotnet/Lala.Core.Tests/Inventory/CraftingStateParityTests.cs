using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CraftingStateParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly JsonSerializerOptions Optional = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    [Theory]
    [MemberData(nameof(CraftingStatePythonVectors.Sequences), MemberType = typeof(CraftingStatePythonVectors))]
    public void EveryTransitionTimingQueryAndRetainedSnapshotMatchesPython(string name, string json)
    {
        var scenario = JsonNode.Parse(json)!;
        var steps = scenario["steps"]!.AsArray();
        var role = scenario["role"]?.GetValue<uint>();
        var schedules = scenario["context"]!.GetValue<string>() == "legacy" ? CraftingScheduleContext.Legacy :
            CraftingScheduleContext.FromRuntimeRows([new(1, 500), new(42, 65535), new(65535, 500)]);
        var state = Read(steps[0]!["expected"]!);
        var history = new List<(CraftingReceiveSnapshot State, JsonNode Expected, double At)>();
        var stepNumber = 0;
        foreach (var step in steps)
        {
            var at = step!["at"]!.GetValue<double>();
            if (step["operation"] is { } operation)
            {
                if (operation["reset"] is not null) state = CraftingReceiveSnapshot.Empty;
                else if (operation["direct"] is { } direct)
                {
                    if (direct["type"]!.GetValue<string>() == "initial_data_complete")
                        state = CraftingReducer.Apply(state, new InitialDataCompleteEvent(), role, at);
                    else state = CraftingReducer.Apply(state, ReadEvent(direct), role, at);
                }
                else
                {
                    var packet = new Packet(operation["main"]!.GetValue<byte>(), operation["sub"]!.GetValue<byte>(),
                        Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                    if (step["error"] is { } error)
                    {
                        var exception = Assert.Throws<ProtocolException>(() => CraftingDecoder.Decode(packet, schedules));
                        Assert.Equal(error.GetValue<string>(), exception.Message);
                    }
                    else if (CraftingDecoder.Decode(packet, schedules) is { } observation)
                    {
                        var wrapped = Assert.IsType<ServerInventoryEvent>(ServerProtocol.Decode(packet, role, schedules));
                        var next = CraftingReducer.Apply(state, observation, role, at);
                        Assert.True(JsonNode.DeepEquals(Project(next, at), Project(CraftingReducer.Apply(state, wrapped, role, at), at)));
                        state = next;
                    }
                }
            }
            Check(step["expected"]!, state, at, $"{name}, step {stepNumber++}");
            history.Add((state, step["expected"]!, at));
        }
        foreach (var prior in history) Check(prior.Expected, prior.State, prior.At, name + " historical");
    }

    [Fact]
    public void OracleHashesMatchTheRetainedPythonSources()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "wlre", "services", "items", "crafting.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, hash) in JsonNode.Parse(CraftingStatePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), Convert.ToHexString(SHA256.HashData(CanonicalSourceBytes(File.ReadAllBytes(Path.Combine(root.FullName, path))))).ToLowerInvariant());
    }

    [Fact]
    public void SourceHashNormalizationPreservesNonUtf8BytesAndBareCarriageReturns()
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

    private sealed record NamedEvent(string Name) : InventoryEvent(0, 0)
    {
        public override string Type => Name;
    }

    private static InventoryEvent ReadEvent(JsonNode node) => node["type"]!.GetValue<string>() switch
    {
        "craft_snapshot" => new CraftSnapshotEvent([.. node["rows"]!.AsArray().Select(row => row!.Deserialize<CraftScheduleRow>(Optional)!)], node["active"]!.GetValue<byte>()),
        "craft_completed" => new CraftCompletedEvent(node["index"]!.GetValue<byte>(), 0),
        var name => new NamedEvent(name)
    };

    internal static CraftingReceiveSnapshot Read(JsonNode expected)
    {
        var craft = expected["crafting"]!;
        var room = expected["furniture"]!;
        return new()
        {
            Crafting = new()
            {
                Ready = craft["ready"]!.GetValue<bool>(),
                Queue = craft["queue"]!.AsObject().ToImmutableDictionary(entry => byte.Parse(entry.Key, CultureInfo.InvariantCulture),
                    entry => entry.Value!.Deserialize<CraftScheduleRow>(Optional)!),
                QueueOrder = [.. expected["queue_order"]!.AsArray().Select(index => index!.GetValue<byte>())],
                Active = craft["active"]!.GetValue<byte>(), StartedAt = craft["started_at"]?.GetValue<double>(),
                Running = craft["running"]!.GetValue<bool>(), AutoContinue = craft["auto_continue"]!.GetValue<bool>(),
                Pending = craft["pending"]?.GetValue<string>(), CompletionRequested = craft["completion_requested"]!.GetValue<bool>(),
                Completed = BigInteger.Parse(craft["completed"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                Status = craft["status"]!.GetValue<string>(), Revision = BigInteger.Parse(craft["revision"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                HumanIndex = craft["human_index"]!.GetValue<byte>(), HumanId = craft["human_id"]!.GetValue<uint>(),
                Uncertain = craft["uncertain"]!.GetValue<bool>(), SyncSource = craft["sync_source"]?.GetValue<string>()
            },
            Furniture = new()
            {
                Owner = room["owner"]?.GetValue<uint>(), CurrentOwner = room["current_owner"]?.GetValue<uint>(),
                Ready = room["ready"]!.GetValue<bool>(),
                Items = room["items"]!.AsObject().ToImmutableDictionary(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture),
                    entry => entry.Value!.Deserialize<CraftFurnitureSnapshot>(Optional)!),
                Revision = BigInteger.Parse(room["revision"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                PersonalBatch = room["personal_batch"]?.GetValue<bool>(),
                ItemOrder = [.. expected["furniture_order"]!.AsArray().Select(index => index!.GetValue<ushort>())]
            }
        };
    }

    internal static JsonNode Project(CraftingReceiveSnapshot state, double at)
    {
        var c = state.Crafting;
        var craft = JsonSerializer.SerializeToNode(new
        {
            c.Ready, c.Active, c.StartedAt, c.Running, c.AutoContinue, c.Pending, c.CompletionRequested,
            Completed = c.Completed.ToString(CultureInfo.InvariantCulture), c.Status,
            Revision = c.Revision.ToString(CultureInfo.InvariantCulture), c.HumanIndex, c.HumanId, c.Uncertain
        }, Options)!.AsObject();
        craft["queue"] = JsonSerializer.SerializeToNode(c.Queue, Optional);
        if (c.SyncSource is not null) craft["sync_source"] = c.SyncSource;
        var f = state.Furniture;
        var room = JsonSerializer.SerializeToNode(new { f.Owner, f.CurrentOwner, f.Ready,
            Revision = f.Revision.ToString(CultureInfo.InvariantCulture) }, Options)!.AsObject();
        room["items"] = JsonSerializer.SerializeToNode(f.Items, Optional);
        if (f.PersonalBatch.HasValue) room["personal_batch"] = f.PersonalBatch.Value;
        var elapsed = new JsonObject();
        foreach (var (index, row) in c.Queue)
            elapsed[index.ToString(CultureInfo.InvariantCulture)] = JsonSerializer.SerializeToNode(new[]
            {
                CraftingReducer.Elapsed(c, row, at - 100), CraftingReducer.Elapsed(c, row, at), CraftingReducer.Elapsed(c, row, at + 100000)
            });
        return new JsonObject { ["crafting"] = craft, ["furniture"] = room, ["elapsed"] = elapsed,
            ["queue_order"] = JsonSerializer.SerializeToNode(c.QueueOrder), ["furniture_order"] = JsonSerializer.SerializeToNode(f.ItemOrder) };
    }

    private static void Check(JsonNode expected, CraftingReceiveSnapshot state, double at, string context)
    {
        var actual = Project(state, at);
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{context}\nExpected: {expected}\nActual: {actual}");
    }
}
