using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class LiveInventoryParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };
    private static readonly ImmutableDictionary<ushort, bool> Rules = new Dictionary<ushort, bool>
        { [42] = true, [43] = false, [65535] = true }.ToImmutableDictionary();
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> NpcSkills =
        new Dictionary<uint, ImmutableArray<uint>> { [1] = [1001, 0, 1002, 1001, 0], [2] = [0, 1002, 65535] }.ToImmutableDictionary();

    [Theory]
    [MemberData(nameof(LiveInventoryPythonVectors.Sequences), MemberType = typeof(LiveInventoryPythonVectors))]
    public void EveryReceiveTransitionAndHistoricalSnapshotMatchesPython(string name, string json)
    {
        var steps = JsonNode.Parse(json)!.AsArray();
        var bag = ReadBag(steps[0]!["expected"]!["inventory"]!);
        var companions = CompanionReceiveSnapshot.Empty;
        Assert.Empty(steps[0]!["expected"]!["companions"]!.AsObject());
        var history = new List<(BagReceiveSnapshot, CompanionReceiveSnapshot, JsonNode)>();
        var index = 0;
        foreach (var step in steps)
        {
            if (step!["operation"] is { } operation)
            {
                if (operation["reset"] is not null)
                {
                    bag = BagReceiveSnapshot.Empty; companions = CompanionReceiveSnapshot.Empty;
                }
                else
                {
                    var packet = new Packet(operation["main"]!.GetValue<int>(), operation["sub"]!.GetValue<int>(),
                        Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                    if (step["error"] is { } error)
                    {
                        var beforeBag = bag; var beforeCompanions = companions;
                        var exception = Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(packet));
                        Assert.Equal(error.GetValue<string>(), exception.Message);
                        Assert.Same(beforeBag, bag); Assert.Same(beforeCompanions, companions);
                    }
                    else
                    {
                        var decoded = ServerProtocol.Decode(packet);
                        var nextBag = BagReceiveReducer.Apply(bag, decoded, Rules);
                        var nextCompanions = CompanionReceiveReducer.Apply(companions, decoded, 7, NpcSkills);
                        if (decoded is ServerLiveDataEvent)
                        {
                            var direct = LiveDataProtocol.Decode(packet)!;
                            AssertJson(Project(nextBag, nextCompanions), Project(BagReceiveReducer.Apply(bag, direct, Rules),
                                CompanionReceiveReducer.Apply(companions, direct, 7, NpcSkills)), "common and live decoder entry points");
                        }
                        bag = nextBag; companions = nextCompanions;
                    }
                }
            }
            var expected = step["expected"]!;
            AssertJson(expected, Project(bag, companions), $"{name}, step {index++}");
            history.Add((bag, companions, expected));
        }
        foreach (var (savedBag, savedCompanions, expected) in history)
            AssertJson(expected, Project(savedBag, savedCompanions), name + " historical");
    }

    [Fact]
    public void OracleSourceHashesMatchRetainedPythonFiles()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "core", "inventory_updates.py")))
            directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(LiveInventoryPythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    // Source text hashes are checkout-independent (Windows CRLF vs Unix LF), while
    // retaining all other bytes, including a BOM should one be added to the source.
    internal static string CanonicalSourceHash(byte[] bytes)
    {
        var normalized = new byte[bytes.Length];
        var length = 0;
        for (var i = 0; i < bytes.Length; i++)
        {
            if (bytes[i] == '\r' && i + 1 < bytes.Length && bytes[i + 1] == '\n') continue;
            normalized[length++] = bytes[i];
        }
        return Convert.ToHexString(SHA256.HashData(normalized.AsSpan(0, length))).ToLowerInvariant();
    }

    internal static BagReceiveSnapshot ReadBag(JsonNode node) => new()
    {
        Ready = node["ready"]!.GetValue<bool>(), Reliable = node["reliable"]!.GetValue<bool>(),
        Capacity = node["capacity"]?.GetValue<byte>(), Revision = Big(node["revision"]!),
        UseFailed = node["use_failed"]!.GetValue<bool>(), SyncError = node["sync_error"]?.GetValue<string>(),
        LastUseResult = node["last_use_result"]?.GetValue<byte>(),
        Items = node["items"]!.AsObject().ToImmutableDictionary(entry => byte.Parse(entry.Key, CultureInfo.InvariantCulture), entry => ReadItem(entry.Value!)),
        ItemOrder = [.. node["items"]!.AsObject().Select(entry => byte.Parse(entry.Key, CultureInfo.InvariantCulture))],
        Reserved = node["reserved"]!.AsObject().ToImmutableDictionary(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture), entry => Big(entry.Value!)),
        Holds = [.. node["holds"]!.AsObject().Select(entry => new StorageReservationGroup(entry.Key,
            [.. entry.Value!.AsArray().Select(row => new StorageReservationSnapshot(
                ushort.Parse(row!["index"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                new(row["identity"]![0]!.GetValue<ushort>(), row["identity"]![1]?.GetValue<uint>(), row["identity"]![2]?.GetValue<byte>()),
                Big(row["count"]!), Big(row["remaining"]!), Big(row["before"]!),
                row["exclusive"]!.GetValue<bool>(), row["uncertain"]!.GetValue<bool>()))]))],
        AlchemySlots = Slots(node, "alchemy_slots"), ExpeditionSlots = Slots(node, "expedition_slots"), MaintenanceSlots = Slots(node, "maintenance_slots"),
        ServerStackable = node["server_stackable"]?.AsObject().ToImmutableDictionary(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture), entry => entry.Value!.GetValue<bool>()),
        FieldSupply = node["field_supply"] is { } fieldSupply ? State(fieldSupply) : null
    };
    private static BagItemSnapshot ReadItem(JsonNode node)
    {
        var copy = node.DeepClone(); copy["count"] = 0; copy["damage"] = 0;
        return new(copy.Deserialize<ItemSave>(Options)!, node["index"]!.GetValue<byte>(), node["count"]!.GetValue<int>(), node["damage"]!.GetValue<uint>());
    }
    private static ImmutableArray<ushort>? Slots(JsonNode node, string key) => node[key] is { } values ?
        [.. values.AsArray().Select(value => ushort.Parse(value!.GetValue<string>(), CultureInfo.InvariantCulture))] : null;
    private static StateValue State(JsonNode? node) => node switch
    {
        null => StateValue.Null,
        JsonObject map => StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, State(pair.Value)))),
        JsonArray list => StateValue.List(list.Select(State)),
        _ => node.GetValueKind() switch
        {
            JsonValueKind.String => StateValue.Scalar(node.GetValue<string>()),
            JsonValueKind.True => StateValue.Scalar(true), JsonValueKind.False => StateValue.Scalar(false),
            _ => StateValue.Scalar(Big(node))
        }
    };
    private static JsonNode? JsonState(StateValue state) => state.Kind switch
    {
        StateValueKind.Map => new JsonObject(state.MapValue.Select(pair => KeyValuePair.Create(pair.Key, JsonState(pair.Value)))),
        StateValueKind.List or StateValueKind.Tuple => new JsonArray([.. state.SequenceValue.Select(JsonState)]),
        _ => state.ScalarValue is BigInteger big ? Number(big) : JsonSerializer.SerializeToNode(state.ScalarValue)
    };

    internal static JsonObject Project(BagReceiveSnapshot bag, CompanionReceiveSnapshot companions)
    {
        var items = new JsonObject();
        foreach (var (slot, item) in bag.Items)
        {
            var row = JsonSerializer.SerializeToNode(item.OriginalRecord, Options)!.AsObject();
            row["index"] = item.Index; row["count"] = item.Count; row["damage"] = item.Damage;
            items[Key(slot)] = row;
        }
        var reserved = new JsonObject();
        foreach (var (slot, amount) in bag.Reserved) reserved[Key(slot)] = Number(amount);
        var holds = new JsonObject();
        foreach (var group in bag.Holds)
            holds[group.Owner] = new JsonArray([.. group.Rows.Select(row => (JsonNode)new JsonObject
            {
                ["index"] = Key(row.Index), ["identity"] = new JsonArray(row.Identity.ItemId,
                    JsonValue.Create(row.Identity.Serial), JsonValue.Create(row.Identity.SerialVersion)),
                ["count"] = Number(row.Count), ["remaining"] = Number(row.Remaining), ["before"] = Number(row.Before),
                ["exclusive"] = row.Exclusive, ["uncertain"] = row.Uncertain
            })]);
        var stackable = bag.ServerStackable is null ? null : new JsonObject();
        if (bag.ServerStackable is not null) foreach (var (id, value) in bag.ServerStackable) stackable![Key(id)] = value;
        var inventory = new JsonObject
        {
            ["ready"] = bag.Ready, ["reliable"] = bag.Reliable, ["capacity"] = bag.Capacity, ["revision"] = Number(bag.Revision),
            ["items"] = items, ["reserved"] = reserved, ["holds"] = holds, ["use_failed"] = bag.UseFailed,
            ["sync_error"] = bag.SyncError, ["last_use_result"] = bag.LastUseResult, ["server_stackable"] = stackable,
            ["field_supply"] = bag.FieldSupply is { } fieldSupply ? JsonState(fieldSupply) : null,
            ["alchemy_slots"] = JsonSlots(bag.AlchemySlots), ["expedition_slots"] = JsonSlots(bag.ExpeditionSlots),
            ["maintenance_slots"] = JsonSlots(bag.MaintenanceSlots)
        };
        var profiles = new JsonObject();
        foreach (var (slot, profile) in companions.Companions)
        {
            var stats = JsonSerializer.SerializeToNode(profile.Data, Options)!.AsObject();
            stats.Remove("skill_slots"); stats.Remove("equips");
            foreach (var (name, value) in profile.StatOverrides) stats[name] = value;
            var skills = new JsonObject();
            foreach (var (id, skill) in profile.Skills) skills[Key(id)] = JsonSerializer.SerializeToNode(skill, Options);
            var projected = new JsonObject
            {
                ["ready"] = profile.Ready, ["index"] = profile.Data.Index, ["npc_id"] = profile.Data.NpcId,
                ["skills"] = skills, ["server_skill_slots"] = JsonSerializer.SerializeToNode(profile.Data.SkillSlots, Options),
                ["stats"] = stats, ["equips"] = profile.EquipmentOverrides is { } equipment ? CombatKnowledgeParityTests.Equipment(equipment) : JsonSerializer.SerializeToNode(profile.Data.Equips, Options)
            };
            if (profile.RemovedSkillIds is { } removed)
                projected["removed_skill_ids"] = new JsonArray([.. removed.Select(id => (JsonNode)JsonValue.Create(Key(id))!)]);
            profiles[Key(slot)] = projected;
        }
        var attributes = new JsonObject();
        foreach (var (slot, rows) in companions.Attributes)
        {
            var values = new JsonObject();
            foreach (var row in rows) values[$"{row.Kind}:{row.Parameter}"] = row.Value;
            attributes[$"follow:{slot}"] = values;
        }
        var available = new JsonObject();
        foreach (ushort slot in new ushort[] { 0, 1, 2, 3, 4, 255, 65535 }) available[Key(slot)] = Number(BagReceiveReducer.Available(bag, slot));
        return new()
        {
            ["inventory"] = inventory, ["item_order"] = new JsonArray([.. bag.ItemOrder.Select(slot => (JsonNode)JsonValue.Create(Key(slot))!)]),
            ["hold_order"] = new JsonArray([.. bag.Holds.Select(group => (JsonNode)JsonValue.Create(group.Owner)!)]),
            ["available"] = available, ["companions"] = profiles, ["companions_ready"] = companions.Ready,
            ["active_npc_id"] = companions.ActiveNpcId, ["attributes"] = attributes,
            ["companion_order"] = new JsonArray([.. companions.CompanionOrder.Select(slot => (JsonNode)JsonValue.Create(Key(slot))!)])
        };
    }
    private static JsonNode? JsonSlots(ImmutableArray<ushort>? slots) => slots is { } values ?
        new JsonArray([.. values.Select(slot => (JsonNode)JsonValue.Create(Key(slot))!)]) : null;
    private static BigInteger Big(JsonNode value) => BigInteger.Parse(value.ToJsonString(), CultureInfo.InvariantCulture);
    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static string Key(uint value) => value.ToString(CultureInfo.InvariantCulture);
    private static void AssertJson(JsonNode expected, JsonNode actual, string label) =>
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{label}: expected {expected}; actual {actual}");
}
