using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class ReservationPlanningParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly StateValue[] Queries = [.. JsonNode.Parse(ReservationPlanningPythonVectors.QueryJson)!.AsArray().Select(Value)];
    private static readonly string[] Fields = ["holds", "reserved", "alchemy_slots", "expedition_slots", "maintenance_slots"];

    [Theory]
    [MemberData(nameof(ReservationPlanningPythonVectors.Sequences), MemberType = typeof(ReservationPlanningPythonVectors))]
    public void EveryHelperProposalReceiveCompositionAndDeepHistoryMatchesPython(string name, string json)
    {
        var steps = JsonNode.Parse(json)!.AsArray();
        var state = LiveInventoryParityTests.ReadBag(steps[0]!["expected"]!["inventory"]!);
        var saved = ImmutableDictionary<string, InventoryReservationCheckpoint>.Empty;
        var history = new List<(BagReceiveSnapshot State, ImmutableDictionary<string, InventoryReservationCheckpoint> Saved, JsonNode Expected)>();
        var proposals = new List<(InventoryReservationCandidate Candidate, JsonNode Before, JsonNode After)>();
        var checkpointHistory = new List<(InventoryReservationCheckpoint Saved, JsonNode Expected)>();
        var index = 0;
        foreach (var step in steps)
        {
            if (step!["operation"] is { } operation)
            {
                var before = state;
                var beforeProjection = InventoryPlanningParityTests.Project(before);
                InventoryReservationCandidate? candidate = null;
                var owner = operation["owner"]?.GetValue<string>();
                var key = operation["name"]?.GetValue<string>();
                switch (operation["kind"]!.GetValue<string>())
                {
                    case "release": candidate = InventoryReservationPlanning.PlanRelease(state, owner!); break;
                    case "uncertain": candidate = InventoryReservationPlanning.PlanUncertain(state, owner!); break;
                    case "checkpoint":
                        var checkpoint = InventoryReservationPlanning.Checkpoint(state);
                        saved = saved.SetItem(key!, checkpoint);
                        checkpointHistory.Add((checkpoint, step["expected"]!["checkpoints"]![key!]!));
                        break;
                    case "restore": candidate = InventoryReservationPlanning.PlanRestore(state, saved[key!]); break;
                    case "slots": state = InventoryReservationPlanning.ProjectSlots(state, owner!); break;
                    case "receive": state = BagReceiveReducer.Apply(state, Receive(operation["event"]!)); break;
                    default: throw new InvalidOperationException("Unknown fixture operation.");
                }
                if (candidate is not null)
                {
                    Assert.True(candidate.Success); Assert.Null(candidate.Error);
                    Assert.Same(before, candidate.ObservedSnapshot); Assert.NotNull(candidate.ProposedSnapshot);
                    state = candidate.ProposedSnapshot;
                    proposals.Add((candidate, beforeProjection, InventoryPlanningParityTests.Project(state)));
                }
                Equal(beforeProjection, InventoryPlanningParityTests.Project(before), name + " immutable input");
            }
            Equal(step!["expected"], Project(state, saved), $"{name}: step {index++}");
            history.Add((state, saved, step["expected"]!));
        }
        foreach (var (snapshot, checkpoints, expected) in history)
            Equal(expected, Project(snapshot, checkpoints), name + " historical snapshot and checkpoints");
        foreach (var (candidate, before, after) in proposals)
        {
            Equal(before, InventoryPlanningParityTests.Project(candidate.ObservedSnapshot), name + " historical proposal baseline");
            Equal(after, InventoryPlanningParityTests.Project(candidate.ProposedSnapshot!), name + " historical proposal result");
        }
        foreach (var (checkpoint, expected) in checkpointHistory)
            Equal(expected, ProjectCheckpoint(checkpoint), name + " immutable saved checkpoint");
    }

    [Fact]
    public void SourceHashesAndGzipByteFixtureBoundsRemainVerified()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "wlre", "services", "items", "reservations.py")))
            root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, hash) in JsonNode.Parse(ReservationPlanningPythonVectors.SourceSha256)!.AsObject())
        {
            var bytes = File.ReadAllBytes(Path.Combine(root.FullName, path));
            var lf = new List<byte>();
            for (var i = 0; i < bytes.Length; i++)
                if (bytes[i] != 13 || i + 1 >= bytes.Length || bytes[i + 1] != 10) lf.Add(bytes[i]);
            var crlf = new List<byte>();
            foreach (var value in lf) { if (value == 10) crlf.Add(13); crlf.Add(value); }
            var expected = hash!.GetValue<string>();
            Assert.Equal(expected, LiveInventoryParityTests.CanonicalSourceHash(bytes));
            Assert.Equal(expected, LiveInventoryParityTests.CanonicalSourceHash([.. lf]));
            Assert.Equal(expected, LiveInventoryParityTests.CanonicalSourceHash([.. crlf]));
            Assert.NotEqual(expected, LiveInventoryParityTests.CanonicalSourceHash([.. lf, (byte)' ']));
            Assert.NotEqual(expected, LiveInventoryParityTests.CanonicalSourceHash([.. crlf, 0xff]));
        }
        foreach (var file in Directory.GetFiles(Path.Combine(root.FullName, "dotnet", "Lala.Core.Tests", "Inventory"),
                     "ReservationPlanningPythonVectors*.cs"))
        {
            Assert.InRange(new FileInfo(file).Length, 1, 500_000);
            var text = File.ReadAllText(file);
            Assert.DoesNotContain("FromBase64String", text, StringComparison.Ordinal);
            if (file.Contains(".Part", StringComparison.Ordinal)) Assert.Contains("GzipJson.Decode([", text, StringComparison.Ordinal);
        }
    }

    private static LiveDataEvent Receive(JsonNode node) => node["type"]!.GetValue<string>() switch
    {
        "bag_snapshot" => new BagSnapshotEvent(node["capacity"]!.GetValue<byte>(),
            [.. node["items"]!.AsArray().Select(item => item!.Deserialize<ItemSave>(Options)!)]),
        "bag_delete" => new BagDeleteEvent(node["index"]!.GetValue<byte>(), node["count"]!.GetValue<byte>(), 0),
        "bag_damage" => new BagDamageEvent(1, node["index"]!.GetValue<byte>(), node["damage"]!.GetValue<uint>(), 0),
        _ => throw new InvalidOperationException("Unknown fixture receive event.")
    };

    private static JsonNode Project(BagReceiveSnapshot state, ImmutableDictionary<string, InventoryReservationCheckpoint> saved)
    {
        var result = InventoryPlanningParityTests.Project(state);
        result["locked"] = new JsonArray([.. Queries.Select(index => (JsonNode)JsonValue.Create(InventoryReservationPlanning.Locked(state, index))!)]);
        var identities = new JsonObject();
        foreach (var (index, item) in state.Items)
        {
            var identity = InventoryReservationPlanning.Identity(item);
            identities[index.ToString(CultureInfo.InvariantCulture)] = new JsonArray(identity.ItemId,
                JsonValue.Create(identity.Serial), JsonValue.Create(identity.SerialVersion));
        }
        result["identities"] = identities;
        var checkpoints = new JsonObject();
        var fields = new JsonObject();
        var orders = new JsonObject();
        foreach (var (name, checkpoint) in saved)
        {
            var projection = ProjectCheckpoint(checkpoint);
            checkpoints[name] = projection;
            fields[name] = new JsonArray([.. projection.AsObject().Select(pair => (JsonNode)JsonValue.Create(pair.Key)!)]);
            orders[name] = new JsonArray([.. checkpoint.Holds.Select(group => (JsonNode)JsonValue.Create(group.Owner)!)]);
        }
        result["checkpoints"] = checkpoints; result["checkpoint_fields"] = fields; result["checkpoint_hold_order"] = orders;
        return result;
    }

    internal static JsonObject ProjectCheckpoint(InventoryReservationCheckpoint saved)
    {
        var state = new BagReceiveSnapshot { Holds = saved.Holds, Reserved = saved.Reserved,
            AlchemySlots = saved.AlchemySlots, ExpeditionSlots = saved.ExpeditionSlots, MaintenanceSlots = saved.MaintenanceSlots };
        var inventory = InventoryPlanningParityTests.Project(state)["inventory"]!;
        return new JsonObject(Fields.Select(field => KeyValuePair.Create<string, JsonNode?>(field, inventory[field]!.DeepClone())));
    }

    private static StateValue Value(JsonNode? node) => node switch
    {
        null => StateValue.Null,
        JsonObject map => StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, Value(pair.Value)))),
        JsonArray list => StateValue.List(list.Select(Value)),
        _ => node.GetValueKind() switch
        {
            JsonValueKind.String => StateValue.Scalar(node.GetValue<string>()),
            JsonValueKind.True => StateValue.Scalar(true), JsonValueKind.False => StateValue.Scalar(false),
            _ when node.ToJsonString().IndexOfAny(['.', 'e', 'E']) >= 0 => StateValue.Scalar(node.GetValue<double>()),
            _ => StateValue.Scalar(BigInteger.Parse(node.ToJsonString(), CultureInfo.InvariantCulture))
        }
    };
    private static void Equal(JsonNode? expected, JsonNode? actual, string label) =>
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{label}: expected {expected}; actual {actual}");
}
