using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class InventoryStateParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };
    private static readonly ushort[] ItemIds = [0, 1, 2, 42, 43, 255, 65535];
    private static readonly ushort[] Indices = [0, 1, 2, 3, 255, 65535];

    [Theory]
    [MemberData(nameof(InventoryStatePythonVectors.Sequences), MemberType = typeof(InventoryStatePythonVectors))]
    public void EveryTransitionQueryAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var steps = JsonNode.Parse(json)!.AsArray();
        var first = steps[0]!["expected"]!;
        var storage = ReadStorage(first);
        var recovery = ReadRecovery(first);
        var historical = new List<(StorageReceiveSnapshot, PotionStorageSnapshot, JsonNode)>();
        var stepIndex = 0;
        foreach (var step in steps)
        {
            var beforeStorage = storage;
            var beforeRecovery = recovery;
            if (step!["operation"] is { } operation)
            {
                if (operation["reset"] is not null)
                {
                    storage = StorageReceiveSnapshot.Empty;
                    recovery = PotionStorageSnapshot.Empty;
                }
                else
                {
                    InventoryEvent? observation = null;
                    if (operation["direct"] is { } direct) observation = ReadEvent(direct);
                    else
                    {
                        var packet = new Packet(operation["main"]!.GetValue<int>(), operation["sub"]!.GetValue<int>(),
                            Convert.FromHexString(operation["hex"]!.GetValue<string>()));
                        if (step["error"] is { } error)
                        {
                            var exception = Assert.Throws<ProtocolException>(() => Decode(packet));
                            Assert.Equal(error.GetValue<string>(), exception.Message);
                            Assert.Same(beforeStorage, storage);
                            Assert.Same(beforeRecovery, recovery);
                        }
                        else
                        {
                            observation = Decode(packet);
                            if (observation is not null)
                            {
                                // Exercise the existing common receive dispatcher too. No
                                // AccountSession/lifecycle integration or commands are involved.
                                var wrapped = Assert.IsType<ServerInventoryEvent>(ServerProtocol.Decode(packet));
                                AssertSameProjection(RoomStorageReducer.Apply(storage, observation), RecoveryReducer.Apply(recovery, observation),
                                    RoomStorageReducer.Apply(storage, wrapped), RecoveryReducer.Apply(recovery, wrapped));
                            }
                        }
                    }
                    if (observation is not null)
                    {
                        storage = RoomStorageReducer.Apply(storage, observation);
                        recovery = RecoveryReducer.Apply(recovery, observation);
                    }
                }
            }
            var expected = step["expected"]!;
            AssertProjection(expected, storage, recovery, $"{name}, step {stepIndex++}");
            historical.Add((storage, recovery, expected));
        }
        foreach (var (savedStorage, savedRecovery, expected) in historical)
            AssertProjection(expected, savedStorage, savedRecovery, name + " historical");
    }

    [Fact]
    public void OracleSourceHashesMatchRetainedPythonFiles()
    {
        var directory = RepositoryRoot();
        foreach (var (path, hash) in JsonNode.Parse(InventoryStatePythonVectors.SourceSha256)!.AsObject())
        {
            var bytes = File.ReadAllBytes(Path.Combine(directory.FullName, path));
            Assert.Equal(hash!.GetValue<string>(), CanonicalSourceSha256(bytes));
        }
    }

    public static IEnumerable<object[]> RetainedSourceHashes() =>
        JsonNode.Parse(InventoryStatePythonVectors.SourceSha256)!.AsObject()
            .Select(entry => new object[] { entry.Key, entry.Value!.GetValue<string>() });

    [Theory]
    [MemberData(nameof(RetainedSourceHashes))]
    public void RetainedSourceHashesAcceptLfAndCrlfButRejectActualContentChanges(string path, string expected)
    {
        // Exercise every real retained source against the pinned hash, not only a
        // synthetic sample. No repository file is edited to simulate Windows checkout.
        var text = File.ReadAllText(Path.Combine(RepositoryRoot().FullName, path), Encoding.UTF8)
            .Replace("\r\n", "\n", StringComparison.Ordinal);
        var lf = Encoding.UTF8.GetBytes(text);
        var crlf = Encoding.UTF8.GetBytes(text.Replace("\n", "\r\n", StringComparison.Ordinal));
        Assert.Equal(expected, CanonicalSourceSha256(lf));
        Assert.Equal(expected, CanonicalSourceSha256(crlf));
        Assert.NotEqual(expected, CanonicalSourceSha256([.. lf, (byte)' ']));
        Assert.NotEqual(expected, CanonicalSourceSha256([.. crlf, (byte)' ']));
        var changedLf = (byte[])lf.Clone();
        var changedCrlf = (byte[])crlf.Clone();
        changedLf[0] ^= 1;
        changedCrlf[0] ^= 1;
        Assert.NotEqual(expected, CanonicalSourceSha256(changedLf));
        Assert.NotEqual(expected, CanonicalSourceSha256(changedCrlf));
    }

    [Theory]
    [InlineData("", "")]
    [InlineData("\n", "\r\n")]
    [InlineData("中文 😀\nsecond\n", "中文 😀\r\nsecond\r\n")]
    [InlineData("one\ntwo\nthree", "one\r\ntwo\nthree")]
    [InlineData("bare\rcarriage\r", "bare\rcarriage\r")]
    [InlineData("\r\n", "\r\r\n")]
    public void SourceHashNormalizationOnlyReplacesCrlfPairs(string canonical, string checkout)
    {
        var expected = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        Assert.Equal(expected, CanonicalSourceSha256(Encoding.UTF8.GetBytes(checkout)));
    }

    [Fact]
    public void SourceHashNormalizationPreservesNonNewlineBytesWithoutTextDecoding()
    {
        byte[] canonical = [0, 0xff, 0xfe, 13, 42, 10, 32, 13];
        byte[] checkout = [0, 0xff, 0xfe, 13, 42, 13, 10, 32, 13];
        var expected = Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant();
        Assert.Equal(expected, CanonicalSourceSha256(checkout));
        Assert.NotEqual(expected, CanonicalSourceSha256([0, 0xff, 0xfe, 42, 10, 32, 13]));
    }

    private static DirectoryInfo RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "services", "items", "room_storage.py")))
            directory = directory.Parent;
        Assert.NotNull(directory);
        return directory;
    }

    private static string CanonicalSourceSha256(ReadOnlySpan<byte> source)
    {
        // Git text checkout may use CRLF. Match the generator's canonical LF bytes,
        // preserving bare CR, BOMs, whitespace, invalid UTF-8 and all content changes.
        var canonical = new byte[source.Length];
        var count = 0;
        for (var index = 0; index < source.Length; index++)
        {
            if (source[index] == '\r' && index + 1 < source.Length && source[index + 1] == '\n') continue;
            canonical[count++] = source[index];
        }
        return Convert.ToHexString(SHA256.HashData(canonical.AsSpan(0, count))).ToLowerInvariant();
    }

    private static InventoryEvent? Decode(Packet packet) => StorageDecoder.Decode(packet) ?? RecoveryDecoder.Decode(packet);

    private sealed record NamedEvent(string Name) : InventoryEvent(0, 0)
    {
        public override string Type => Name;
    }

    private static InventoryEvent ReadEvent(JsonNode node) => node["type"]!.GetValue<string>() switch
    {
        "storage_garage_initial" => new StorageGarageInitialEvent([.. node["items"]!.AsArray().Select(item => item!.Deserialize<ItemSave>(Options)!)]),
        "storage_materials_initial" => new StorageMaterialsInitialEvent([.. node["items"]!.AsArray().Select(Material)]),
        "storage_materials_add" => new StorageMaterialsAddEvent([.. node["items"]!.AsArray().Select(Material)]),
        "potion_balance" => new PotionBalanceEvent(node["resource"]!.GetValue<string>(), node["value"]!.GetValue<int>()),
        "potion_balance_add" => new PotionBalanceAddEvent(node["resource"]!.GetValue<string>(), node["value"]!.GetValue<int>()),
        var name => new NamedEvent(name)
    };
    private static StorageMaterial Material(JsonNode? node) => new(node!["index"]!.GetValue<ushort>(),
        node["item_id"]!.GetValue<ushort>(), node["count"]!.GetValue<ushort>());

    private static StorageReceiveSnapshot ReadStorage(JsonNode source)
    {
        var storage = source["storage"]!;
        return new()
        {
            Storage = new()
            {
                Garage = ReadBucket(storage["garage"]!), Materials = ReadBucket(storage["materials"]!),
                MaterialStackLimit = storage["material_stack_limit"]?.GetValue<ushort>(),
                ParametersReady = storage["parameters_ready"]!.GetValue<bool>(), Revision = Big(storage["revision"]!),
                LastResult = storage["last_result"]?.GetValue<byte>(), LastError = storage["last_error"]?.GetValue<byte>(),
                Pending = storage["pending"]?.GetValue<string>(), Uncertain = storage["uncertain"]!.GetValue<bool>(),
                Status = storage["status"]!.GetValue<string>()
            },
            ServerStackable = source["server_stackable"]?.AsObject().ToImmutableDictionary(
                entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture), entry => entry.Value!.GetValue<bool>())
        };
    }

    private static StorageBucketSnapshot ReadBucket(JsonNode node) => new()
    {
        Ready = node["ready"]!.GetValue<bool>(), Reliable = node["reliable"]!.GetValue<bool>(),
        Capacity = node["capacity"]?.GetValue<ushort>(),
        Items = node["items"]!.AsObject().ToImmutableDictionary(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture),
            entry => ReadItem(entry.Value!)),
        ItemOrder = [.. node["items"]!.AsObject().Select(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture))],
        Reserved = node["reserved"]!.AsObject().ToImmutableDictionary(entry => ushort.Parse(entry.Key, CultureInfo.InvariantCulture),
            entry => Big(entry.Value!)),
        Holds = [.. node["holds"]!.AsObject().Select(entry => new StorageReservationGroup(entry.Key,
            [.. entry.Value!.AsArray().Select(row => new StorageReservationSnapshot(
                ushort.Parse(row!["index"]!.GetValue<string>(), CultureInfo.InvariantCulture),
                new(row["identity"]![0]!.GetValue<ushort>(), row["identity"]![1]?.GetValue<uint>(), row["identity"]![2]?.GetValue<byte>()),
                Big(row["count"]!), Big(row["remaining"]!), Big(row["before"]!),
                row["exclusive"]!.GetValue<bool>(), row["uncertain"]!.GetValue<bool>()))]))],
        AlchemySlots = Slots(node, "alchemy_slots"), ExpeditionSlots = Slots(node, "expedition_slots"),
        MaintenanceSlots = Slots(node, "maintenance_slots")
    };

    private static StorageItemSnapshot ReadItem(JsonNode node)
    {
        ItemSave? garage = null;
        if (node["damage"] is not null)
        {
            // A seeded source snapshot has an accumulated count, not an original wire
            // count. Metadata is identical; the current BigInteger Count is projected below.
            var copy = node.DeepClone();
            copy["count"] = 0;
            garage = copy.Deserialize<ItemSave>(Options);
        }
        return new(node["index"]!.GetValue<ushort>(), node["item_id"]!.GetValue<ushort>(), Big(node["count"]!), garage);
    }
    private static ImmutableArray<ushort>? Slots(JsonNode node, string key) => node[key] is { } values
        ? [.. values.AsArray().Select(value => ushort.Parse(value!.GetValue<string>(), CultureInfo.InvariantCulture))] : null;

    private static PotionStorageSnapshot ReadRecovery(JsonNode source) => new()
    {
        Resources = source["potion_storage"]!.AsObject().ToImmutableDictionary(entry => entry.Key,
            entry => new PotionResourceSnapshot(entry.Value!["value"] is { } value ? Big(value) : null,
                Big(entry.Value["revision"]!)), StringComparer.Ordinal)
    };

    internal static JsonObject Project(StorageReceiveSnapshot receive, PotionStorageSnapshot recovery)
    {
        var storage = receive.Storage;
        var potions = new JsonObject();
        foreach (var (resource, balance) in recovery.Resources)
        {
            var row = new JsonObject { ["revision"] = Number(balance.Revision) };
            if (balance.Value is { } value) row["value"] = Number(value);
            potions[resource] = row;
        }
        var stackable = receive.ServerStackable is null ? null : new JsonObject();
        if (receive.ServerStackable is not null)
            foreach (var (item, observed) in receive.ServerStackable) stackable![Key(item)] = observed;
        var counts = new JsonObject();
        foreach (var item in ItemIds)
            counts[Key(item)] = RoomStorageReducer.ConfirmedMaterialCount(storage, item) is { } count ? Number(count) : null;
        var available = new JsonObject();
        var itemOrder = new JsonObject();
        var holdOrder = new JsonObject();
        foreach (var (name, bucket) in new[] { ("garage", storage.Garage), ("materials", storage.Materials) })
        {
            var rows = new JsonObject();
            foreach (var index in Indices) rows[Key(index)] = Number(RoomStorageReducer.Available(bucket, index));
            available[name] = rows;
            itemOrder[name] = new JsonArray([.. bucket.ItemOrder.Select(index => (JsonNode)JsonValue.Create(Key(index))!)]);
            holdOrder[name] = new JsonArray([.. bucket.Holds.Select(group => (JsonNode)JsonValue.Create(group.Owner)!)]);
        }
        return new()
        {
            ["storage"] = new JsonObject
            {
                ["garage"] = ProjectBucket(storage.Garage), ["materials"] = ProjectBucket(storage.Materials),
                ["material_stack_limit"] = storage.MaterialStackLimit, ["parameters_ready"] = storage.ParametersReady,
                ["revision"] = Number(storage.Revision), ["last_result"] = storage.LastResult, ["last_error"] = storage.LastError,
                ["pending"] = storage.Pending, ["uncertain"] = storage.Uncertain, ["status"] = storage.Status
            },
            ["potion_storage"] = potions, ["server_stackable"] = stackable,
            ["item_order"] = itemOrder, ["hold_owner_order"] = holdOrder,
            ["confirmed_counts"] = counts, ["available"] = available
        };
    }

    private static JsonObject ProjectBucket(StorageBucketSnapshot bucket)
    {
        var items = new JsonObject();
        foreach (var (index, item) in bucket.Items)
        {
            var row = item.OriginalGarageRecord is { } record ? JsonSerializer.SerializeToNode(record, Options)!.AsObject() : new JsonObject();
            row["index"] = item.Index; row["item_id"] = item.ItemId; row["count"] = Number(item.Count);
            items[Key(index)] = row;
        }
        var reserved = new JsonObject();
        foreach (var (index, count) in bucket.Reserved) reserved[Key(index)] = Number(count);
        var holds = new JsonObject();
        foreach (var group in bucket.Holds)
            holds[group.Owner] = new JsonArray([.. group.Rows.Select(row => (JsonNode)new JsonObject
            {
                ["index"] = Key(row.Index), ["identity"] = new JsonArray(row.Identity.ItemId,
                    JsonValue.Create(row.Identity.Serial), JsonValue.Create(row.Identity.SerialVersion)),
                ["count"] = Number(row.Count), ["remaining"] = Number(row.Remaining), ["before"] = Number(row.Before),
                ["exclusive"] = row.Exclusive, ["uncertain"] = row.Uncertain
            })]);
        var result = new JsonObject
        {
            ["ready"] = bucket.Ready, ["reliable"] = bucket.Reliable, ["items"] = items,
            ["capacity"] = bucket.Capacity, ["reserved"] = reserved, ["holds"] = holds
        };
        foreach (var (name, values) in new[] { ("alchemy_slots", bucket.AlchemySlots),
                     ("expedition_slots", bucket.ExpeditionSlots), ("maintenance_slots", bucket.MaintenanceSlots) })
            if (values is { } slots) result[name] = new JsonArray([.. slots.Select(slot => (JsonNode)JsonValue.Create(Key(slot))!)]);
        return result;
    }

    private static BigInteger Big(JsonNode value) => BigInteger.Parse(value.ToJsonString(), CultureInfo.InvariantCulture);
    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static string Key(ushort value) => value.ToString(CultureInfo.InvariantCulture);
    private static void AssertProjection(JsonNode expected, StorageReceiveSnapshot storage, PotionStorageSnapshot recovery, string label)
    {
        var actual = Project(storage, recovery);
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{label}: expected {expected}; actual {actual}");
    }
    private static void AssertSameProjection(StorageReceiveSnapshot expectedStorage, PotionStorageSnapshot expectedRecovery,
        StorageReceiveSnapshot actualStorage, PotionStorageSnapshot actualRecovery) =>
        AssertProjection(Project(expectedStorage, expectedRecovery), actualStorage, actualRecovery, "direct and server entry points");
}
