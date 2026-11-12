using System.Collections.Immutable;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Tests.Catalogs.RuntimeCandidate;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CraftingPreflightTests
{
    [Theory]
    [MemberData(nameof(CraftingPreflightPythonVectors.Cases), MemberType = typeof(CraftingPreflightPythonVectors))]
    public void RetainedHelperPrefixMatchesWithoutCreatingPackets(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var input = vector["input"]!;
        var expected = vector["expected"]!;
        var context = CraftingPreflightContext.FromCallerSuppliedRows([.. input["recipes"]!.AsArray().Select(row => Recipe(row!))]);
        var crafting = Crafting(input);
        var bag = Bag(input["inventory"]!);
        var storage = Storage(input["room_storage"]!);
        var result = CraftingMaterialPreflight.Evaluate(context, (ushort)N(input, "item_id"), N(input, "count"),
            input["role"]?.GetValue<uint>(), crafting, bag, storage);
        Assert.Equal(expected["blocker"]?.GetValue<string>(), result.Blocker?.ToString());
        Assert.False(result.CanSendPackets);
        Assert.False(context.CanSendPackets);
        Assert.Equal(CraftingPreflightSource.CallerSuppliedOfflineRows, context.Source);
        Assert.Same(crafting, result.Crafting);
        Assert.Same(bag, result.Bag);
        Assert.Same(storage, result.Storage);
        Assert.Same(context, result.Recipes);
        Assert.Equal(nameof(CraftingPreflightResult), result.ToString());
        if (!result.Success)
        {
            Assert.Empty(result.Allocations);
            if (result.Blocker == CraftingPreflightBlocker.MaterialShortage)
            {
                Assert.True(result.MissingCount > 0, name);
                Assert.NotNull(result.MissingItemId);
            }
            return;
        }
        Assert.Equal((ushort)N(expected, "tool"), result.ToolIndex);
        var allocations = expected["allocations"]!.AsArray();
        Assert.Equal(allocations.Count, result.Allocations.Length);
        for (var i = 0; i < allocations.Count; i++)
        {
            var row = allocations[i]!;
            var actual = result.Allocations[i];
            Assert.Equal(row["source"]?.GetValue<string>() == "materials" ? CraftingMaterialSource.Materials : CraftingMaterialSource.Bag, actual.Source);
            Assert.Equal((ushort)N(row, "index"), actual.Index);
            Assert.Equal((ushort)N(row, "item_id"), actual.ItemId);
            Assert.Equal(N(row, "count"), actual.Count);
            Assert.Equal(Big(row, "before"), actual.Before);
            Assert.Equal(row["serial"]?.GetValue<uint>(), actual.Serial);
        }
        var materials = result.Recipe!.Recipe.Materials.GroupBy(row => row.ItemId).ToArray();
        Assert.Equal(materials.Length, result.Needs.Length);
        for (var i = 0; i < materials.Length; i++)
            Assert.Equal(new CraftingMaterialNeed(materials[i].Key, materials[i].Sum(row => (int)row.Count) * result.BatchCount), result.Needs[i]);
        Assert.Same(result, RetainWhileEvaluatingChangedInput(result));
    }

    private static CraftingPreflightResult RetainWhileEvaluatingChangedInput(CraftingPreflightResult result)
    {
        var before = result.Allocations;
        var next = CraftingMaterialPreflight.Evaluate(result.Recipes, result.ItemId, result.BatchCount, result.RoleId,
            result.Crafting, result.Bag with { Ready = false }, result.Storage);
        Assert.Equal(CraftingPreflightBlocker.BagNotReadyOrReliable, next.Blocker);
        Assert.True(result.Success);
        Assert.Equal(before, result.Allocations);
        return result;
    }

    [Fact]
    public void RetainedSourceHashesNormalizeCrLfOnly()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "wlre/services/items/crafting.py"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, value) in JsonNode.Parse(CraftingPreflightPythonVectors.SourceSha256)!.AsObject())
        {
            var raw = File.ReadAllBytes(Path.Combine(root.FullName, path));
            var bytes = raw.Where((item, index) => item != 13 || index + 1 == raw.Length || raw[index + 1] != 10).ToArray();
            Assert.Equal(value!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(bytes)));
        }
    }

    [Fact]
    public void ContextRejectsIncompleteMixedDuplicateAndOversizedObservations()
    {
        var row = SampleRecipe();
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows(default));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([null!]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row with { Recipe = null! }]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row with { Recipe = row.Recipe with { Materials = default } }]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row with { Recipe = row.Recipe with { Materials = [new(100, 0)] } }]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row with { Recipe = row.Recipe with { Materials = [new(100, 1), new(100, 1), new(100, 1), new(100, 1), new(100, 1), new(100, 1)] } }]));
        var official = row with { Recipe = row.Recipe with { RecipeId = 42 } };
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row, official]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([official, official]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([row with { Recipe = row.Recipe with { CandidateRowKey = 42 } }]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows([official with { Recipe = official.Recipe with { CandidateRowKey = 43 } }]));
        Assert.Throws<ArgumentException>(() => CraftingPreflightContext.FromCallerSuppliedRows(Enumerable.Repeat(row, SmithDataParser.MaxRecords + 1).ToImmutableArray()));
        Assert.False(CraftingPreflightContext.FromCallerSuppliedRows([]).UsesRecipeIds);
        Assert.True(CraftingPreflightContext.FromCallerSuppliedRows([official]).UsesRecipeIds);
    }

    [Fact]
    public void ActualOfflineRuntimeCandidateFeedsExistingRecipeTypesWithoutAdmission()
    {
        var fixture = RuntimeCandidateOracleCases.Case(0);
        var sources = fixture.GetProperty("inputs").EnumerateObject().ToDictionary(pair => pair.Name,
            pair => (ReadOnlyMemory<byte>)Convert.FromBase64String(pair.Value.GetString()!));
        var runtime = OfflineRuntimeCandidateDecoder.Decode(sources, "1286_2026_10_29_13_42_37_94");
        var context = CraftingPreflightContext.FromRuntime(runtime.Recipes);
        Assert.Equal(CraftingPreflightSource.OfflineRuntimeCandidate, context.Source);
        Assert.Equal(runtime.Recipes.Catalog, context.Catalog);
        Assert.False(runtime.CanSendPackets);
        Assert.False(runtime.HasVerifiedProvenance);
        Assert.False(runtime.RuntimeAdmitted);
        Assert.False(context.CanSendPackets);
        foreach (var row in context.Catalog)
        {
            var result = CraftingMaterialPreflight.Evaluate(context, row.Recipe.ItemId, 1, 7,
                new(), new(), new());
            Assert.False(result.Success);
            Assert.False(result.CanSendPackets);
        }
    }

    [Fact]
    public void InvalidImportedOrderAndSlotShapesFailClosedWithoutInventingOrder()
    {
        var (context, crafting, bag, storage) = Sample();
        CraftingPreflightResult Run(CraftingReceiveSnapshot? c = null, BagReceiveSnapshot? b = null, RoomStorageSnapshot? s = null) =>
            CraftingMaterialPreflight.Evaluate(context, 500, 1, 7, c ?? crafting, b ?? bag, s ?? storage);
        Assert.Equal(CraftingPreflightBlocker.FurnitureOrderUnknown, Run(crafting with { Furniture = crafting.Furniture with { ItemOrder = [] } }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.FurnitureOrderUnknown, Run(crafting with { Furniture = crafting.Furniture with { ItemOrder = [9, 9] } }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.FurnitureOrderUnknown, Run(crafting with { Furniture = crafting.Furniture with { ItemOrder = [8] } }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.FurnitureOrderUnknown, Run(crafting with { Furniture = crafting.Furniture with { Items = crafting.Furniture.Items.SetItem(9, new(8, 39001, 0, 0, 0)) } }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(b: bag with { Items = bag.Items.SetItem(2, bag.Items[2] with { Index = 3 }) }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(b: bag with { Items = bag.Items.SetItem(2, bag.Items[2] with { Count = -1 }) }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(b: bag with { Holds = default }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(b: bag with { AlchemySlots = default(ImmutableArray<ushort>) }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(b: bag with { Holds = Enumerable.Repeat(new StorageReservationGroup("synthetic", []), CraftingMaterialPreflight.MaxReservationGroups + 1).ToImmutableArray() }).Blocker);
        Assert.Equal(CraftingPreflightBlocker.InvalidSnapshot, Run(s: storage with { Materials = storage.Materials with { Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(1, new(2, 100, 1)) } }).Blocker);
    }

    [Fact]
    public void HugeCupboardBalanceNegativeReservationsAndZeroSlotStayNonAuthorizing()
    {
        var (context, crafting, bag, storage) = Sample();
        var enormous = BigInteger.One << 300;
        var cupboard = storage.Materials with
        {
            Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(0, new(0, 100, enormous)),
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(0, -enormous)
        };
        var result = CraftingMaterialPreflight.Evaluate(context, 500, 255, 7, crafting, bag with { Items = bag.Items.Clear() }, storage with { Materials = cupboard });
        var row = Assert.Single(result.Allocations);
        Assert.Equal((ushort)0, row.Index); // Packet write_cupboard would reject; outside this prefix.
        Assert.Equal(510, row.Count);
        Assert.Equal(enormous, row.Before);
        Assert.Null(row.Serial);
        Assert.False(result.CanSendPackets);
    }

    [Fact]
    public void MaterialFailureDiscardsEarlierPartialAllocationsAndRetainsFirstShortage()
    {
        var (_, crafting, bag, storage) = Sample();
        var recipe = SampleRecipe();
        var context = CraftingPreflightContext.FromCallerSuppliedRows([recipe with { Recipe = recipe.Recipe with { Materials = [new(100, 1), new(200, 3)] } }]);
        var result = CraftingMaterialPreflight.Evaluate(context, 500, 2, 7, crafting, bag, storage);
        Assert.Equal(CraftingPreflightBlocker.MaterialShortage, result.Blocker);
        Assert.Equal((ushort)200, result.MissingItemId);
        Assert.Equal(new BigInteger(6), result.MissingCount);
        Assert.Empty(result.Allocations);
        Assert.Equal(2, result.Needs.Length);
        Assert.Empty(bag.Holds);
        Assert.Empty(bag.Reserved);
    }

    private static RuntimeRecipe SampleRecipe() => new(new(500, 0, 0, 39001, 3, [new(100, 2)], 30, 0, 0, 0, 0, 0, 0, 1), 0);
    private static (CraftingPreflightContext, CraftingReceiveSnapshot, BagReceiveSnapshot, RoomStorageSnapshot) Sample()
    {
        var data = JsonNode.Parse((string)CraftingPreflightPythonVectors.Cases().First()[1])!["input"]!;
        return (CraftingPreflightContext.FromCallerSuppliedRows([SampleRecipe()]), Crafting(data), Bag(data["inventory"]!), Storage(data["room_storage"]!));
    }
    private static RuntimeRecipe Recipe(JsonNode row) => new(new((ushort)N(row, "item_id"), (ushort)N(row, "design_id"), (byte)N(row, "skill"),
        (ushort)N(row, "tool_id"), (byte)N(row, "output"), [.. row["materials"]!.AsArray().Select(material => new SmithMaterial((ushort)N(material!, "item_id"), (byte)N(material!, "count")))],
        (ushort)N(row, "seconds"), (byte)N(row, "skill_level"), (byte)N(row, "suggest"), (ushort)N(row, "time_id"), (byte)N(row, "limit_kind"),
        (byte)N(row, "mark_id"), (byte)N(row, "limit_times"), N(row, "order"), row["recipe_id"]?.GetValue<ushort>(), row["candidate_row_key"]?.GetValue<ushort>(),
        row["read_only"]?.GetValue<bool>()), (byte)N(row, "open_used"));
    private static CraftingReceiveSnapshot Crafting(JsonNode data)
    {
        var room = data["furniture"]!;
        var craft = data["crafting"]!;
        var queue = craft["queue"]!.AsObject();
        var items = room["items"]!.AsObject();
        return new()
        {
            Furniture = new()
            {
                Owner = room["owner"]?.GetValue<uint>(), CurrentOwner = room["current_owner"]?.GetValue<uint>(), Ready = B(room, "ready"),
                ItemOrder = [.. items.Select(pair => ushort.Parse(pair.Key))],
                Items = items.ToImmutableDictionary(pair => ushort.Parse(pair.Key), pair => new CraftFurnitureSnapshot((ushort)N(pair.Value!, "index"),
                    (ushort)N(pair.Value!, "item_id"), (ushort)N(pair.Value!, "workbench"), 0, (byte)N(pair.Value!, "status")))
            },
            Crafting = new()
            {
                Ready = B(craft, "ready"), Pending = craft["pending"]?.GetValue<string>(), Uncertain = B(craft, "uncertain"),
                QueueOrder = [.. queue.Select(pair => byte.Parse(pair.Key))],
                Queue = queue.ToImmutableDictionary(pair => byte.Parse(pair.Key), pair => new CraftScheduleRow((byte)N(pair.Value!, "index"),
                    (ushort)N(pair.Value!, "item_id"), N(pair.Value!, "elapsed"), (byte)N(pair.Value!, "count"), (uint)N(pair.Value!, "base_time"), pair.Value!["recipe_id"]?.GetValue<ushort>()))
            }
        };
    }
    private static BagReceiveSnapshot Bag(JsonNode data) => new()
    {
        Ready = B(data, "ready"), Reliable = B(data, "reliable"),
        Items = data["items"]!.AsObject().ToImmutableDictionary(pair => byte.Parse(pair.Key), pair => BagItem(pair.Value!)),
        ItemOrder = [.. data["items"]!.AsObject().Select(pair => byte.Parse(pair.Key))],
        Reserved = Reserved(data), Holds = Holds(data), AlchemySlots = Slots(data, "alchemy_slots"),
        ExpeditionSlots = Slots(data, "expedition_slots"), MaintenanceSlots = Slots(data, "maintenance_slots")
    };
    private static BagItemSnapshot BagItem(JsonNode row)
    {
        var index = (byte)N(row, "index");
        var record = new ItemSave(index, (ushort)N(row, "item_id"), 1, 0, (byte)N(row, "serial_version"), (uint)N(row, "serial"),
            null, null, (ushort)N(row, "magic_spar"), 0, 0, (byte)N(row, "beat_level"), 0, 0, null, 0, (ushort)N(row, "enhance_level"), 0, [], B(row, "locked"), 0, 0, null);
        return new(record, index, N(row, "count"), 0);
    }
    private static RoomStorageSnapshot Storage(JsonNode data)
    {
        var bucket = data["materials"]!;
        return new()
        {
            Pending = data["pending"]?.GetValue<string>(), Uncertain = B(data, "uncertain"),
            Materials = new()
            {
                Ready = B(bucket, "ready"), Reliable = B(bucket, "reliable"),
                Items = bucket["items"]!.AsObject().ToImmutableDictionary(pair => ushort.Parse(pair.Key), pair => new StorageItemSnapshot(
                    (ushort)N(pair.Value!, "index"), (ushort)N(pair.Value!, "item_id"), Big(pair.Value!, "count"))),
                ItemOrder = [.. bucket["items"]!.AsObject().Select(pair => ushort.Parse(pair.Key))],
                Reserved = Reserved(bucket), Holds = Holds(bucket), AlchemySlots = Slots(bucket, "alchemy_slots"),
                ExpeditionSlots = Slots(bucket, "expedition_slots"), MaintenanceSlots = Slots(bucket, "maintenance_slots")
            }
        };
    }
    private static ImmutableArray<ushort>? Slots(JsonNode data, string key) => data[key] is { } rows ? [.. rows.AsArray().Select(row => ushort.Parse(row!.GetValue<string>()))] : null;
    private static ImmutableDictionary<ushort, BigInteger> Reserved(JsonNode data) => data["reserved"]?.AsObject().ToImmutableDictionary(pair => ushort.Parse(pair.Key), pair => BigInteger.Parse(pair.Value!.ToJsonString())) ?? ImmutableDictionary<ushort, BigInteger>.Empty;
    private static ImmutableArray<StorageReservationGroup> Holds(JsonNode data) => data["holds"] is not { } groups ? [] : [.. groups.AsObject().Select(pair => new StorageReservationGroup(pair.Key,
        [.. pair.Value!.AsArray().Select(row => new StorageReservationSnapshot(ushort.Parse(row!["index"]!.GetValue<string>()), new((ushort)row["identity"]![0]!.GetValue<int>(),
            row["identity"]![1]?.GetValue<uint>(), row["identity"]![2]?.GetValue<byte>()), Big(row, "count"), Big(row, "remaining"), Big(row, "before"), B(row, "exclusive"), B(row, "uncertain")))]))];
    private static int N(JsonNode data, string key) => data[key]?.GetValue<int>() ?? 0;
    private static BigInteger Big(JsonNode data, string key) => data[key] is { } value ? BigInteger.Parse(value.ToJsonString()) : BigInteger.Zero;
    private static bool B(JsonNode data, string key) => data[key] is { } value && (value.ToJsonString() == "true" || int.TryParse(value.ToJsonString(), out var number) && number != 0);
}
