using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class InventoryDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly JsonNode Vectors = JsonNode.Parse(PythonInventoryVectors.Json)!;
    public static IEnumerable<object[]> ValidCases() => Cases("valid");
    public static IEnumerable<object[]> InvalidCases() => Cases("invalid");
    public static IEnumerable<object[]> IgnoredCases() => Cases("ignored");
    public static IEnumerable<object[]> BoundaryCases() => Cases("boundaries");
    private static IEnumerable<object[]> Cases(string section) => Vectors[section]!.AsArray()
        .Select(row => new object[] { row!["name"]!.GetValue<string>(), row.ToJsonString() });
    private static JsonNode Vector(string name) => Vectors["valid"]!.AsArray()
        .Single(row => row!["name"]!.GetValue<string>() == name)!;
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());

    private static CraftingScheduleContext Context(string name)
    {
        var rows = Vectors["contexts"]![name];
        return rows is null ? CraftingScheduleContext.Legacy : CraftingScheduleContext.FromRuntimeRows(
            rows.AsArray().Select(row => new CraftingRecipeIdentity(row!["recipe_id"]?.GetValue<int>(), row["item_id"]!.GetValue<int>())));
    }

    private static InventoryEvent? Decode(JsonNode vector, ReadOnlySpan<byte> payload)
    {
        var packet = new Packet(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), payload);
        return vector["family"]!.GetValue<string>() switch
        {
            "storage" => StorageDecoder.Decode(packet),
            "recovery" => RecoveryDecoder.Decode(packet),
            "crafting" => CraftingDecoder.Decode(packet, packet.Main == 64 && packet.Sub is 1 or 16
                ? Context(vector["context"]?.GetValue<string>() ?? "legacy") : null),
            _ => throw new InvalidOperationException("Unknown family")
        };
    }

    private static void RemoveAbsentNulls(JsonNode? actual, JsonNode? expected)
    {
        if (actual is JsonObject obj && expected is JsonObject wanted)
        {
            foreach (var pair in obj.ToArray())
                if (pair.Value is null && !wanted.ContainsKey(pair.Key)) obj.Remove(pair.Key);
                else RemoveAbsentNulls(pair.Value, wanted[pair.Key]);
        }
        else if (actual is JsonArray array && expected is JsonArray wantedArray)
            for (var i = 0; i < Math.Min(array.Count, wantedArray.Count); i++) RemoveAbsentNulls(array[i], wantedArray[i]);
    }

    private static void AssertJson(JsonNode? expected, JsonNode? actual)
    {
        RemoveAbsentNulls(actual, expected);
        Assert.True(JsonNode.DeepEquals(expected, actual), $"Expected {expected}; actual {actual}");
    }

    private static void AssertOutcome(JsonNode vector, JsonNode outcome, byte[] payload)
    {
        if (outcome["error"] is { } error)
        {
            var exception = outcome["error_kind"]!.GetValue<string>() == "context"
                ? Assert.Throws<ArgumentException>(() => Decode(vector, payload))
                : (Exception)Assert.Throws<ProtocolException>(() => Decode(vector, payload));
            Assert.Equal(error.GetValue<string>(), exception.Message);
            Assert.DoesNotContain("PRIVATE", exception.ToString());
        }
        else
        {
            var result = Decode(vector, payload);
            AssertJson(outcome["expected"], result is null ? null : JsonSerializer.SerializeToNode(result, result.GetType(), Options));
        }
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryDecodedFieldMatchesPython(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector, Bytes(vector));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void DispatcherRetainsEveryInventoryFieldAndExplicitScheduleContext(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        var packet = new Packet(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), Bytes(vector));
        var context = packet.Main == 64 && packet.Sub is 1 or 16
            ? Context(vector["context"]?.GetValue<string>() ?? "legacy") : null;
        var result = Assert.IsType<ServerInventoryEvent>(ServerProtocol.Decode(packet, null, context));
        AssertJson(vector["expected"], JsonSerializer.SerializeToNode(result.Event, result.Event.GetType(), Options));
        if (context is not null)
            Assert.IsType<UnsupportedServerDecoderEvent>(ServerProtocol.Decode(packet));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryMatchesExactPythonOutcome(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        foreach (var prefix in vector["prefixes"]!.AsObject())
            AssertOutcome(vector, prefix.Value!, bytes[..int.Parse(prefix.Key, System.Globalization.CultureInfo.InvariantCulture)]);
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void TrailingBytesMatchSourceIncludingFixedRecordLengthChecks(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector["tail"]!, [.. Bytes(vector), 0x7e]);
    }

    [Theory, MemberData(nameof(InvalidCases))]
    public void MalformedFieldsAndCatalogPrecedenceMatchPython(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector, Bytes(vector));
    }

    [Theory, MemberData(nameof(IgnoredCases))]
    public void UnknownKeysAndNonstorageHouseErrorsRemainUnclaimed(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        Assert.Null(Decode(vector, Bytes(vector)));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void DecoderFamiliesDoNotOverlapAndDiagnosticFormattingIsMetadataOnly(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        var packet = new Packet(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), Bytes(vector));
        var family = vector["family"]!.GetValue<string>(); var result = Decode(vector, packet.Payload.Span)!;
        Assert.Equal($"{result.Type} (S{result.Main}-{result.Sub})", result.ToString());
        if (family != "storage") Assert.Null(StorageDecoder.Decode(packet));
        if (family != "recovery") Assert.Null(RecoveryDecoder.Decode(packet));
        if (family != "crafting") Assert.Null(CraftingDecoder.Decode(packet));
        Assert.DoesNotContain("PRIVATE", JsonSerializer.Serialize(result, result.GetType(), Options));
    }

    [Theory, MemberData(nameof(BoundaryCases))]
    public void MaximumCountsMatchPythonWithoutArtificialFrameLimitsOrByteLoopOverflow(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var count = vector["count"]!.GetValue<int>();
        var writer = new PacketWriter(); var pattern = vector["pattern"]!.GetValue<string>();
        switch (pattern)
        {
            case "garage":
                var item = Convert.FromHexString(Vectors["item_hex"]!.GetValue<string>());
                writer.U8(count);
                for (var i = 0; i < count; i++) writer.U8(i).Raw(item);
                break;
            case "materials":
                writer.U8(1).U8(1).U16(count);
                for (var i = 0; i < count; i++) writer.U16(i).U16(65535).U16(65535);
                break;
            case "targets":
                writer.U8(5).U8(4).U8(count);
                for (var i = 0; i < count; i++) writer.U8(i);
                break;
            case "schedule":
                var schedule = Convert.FromHexString(Vectors["schedule_hex"]!.GetValue<string>());
                for (var i = 0; i < count; i++) writer.U8(i + 1).Raw(schedule.AsSpan(1));
                writer.U8(255);
                break;
            case "furniture":
                var furniture = Convert.FromHexString(Vectors["furniture_hex"]!.GetValue<string>());
                writer.U32(uint.MaxValue);
                for (var i = 0; i < count; i++) writer.U16(i).Raw(furniture.AsSpan(2));
                break;
            default: throw new InvalidOperationException("Unknown boundary pattern");
        }
        var bytes = writer.Build(); var result = Decode(vector, bytes)!;
        Assert.Equal(vector["type"]!.GetValue<string>(), result.Type);
        var actual = JsonSerializer.SerializeToNode(result, result.GetType(), Options)!;
        var rows = actual[vector["field"]!.GetValue<string>()]!.AsArray();
        Assert.Equal(count, rows.Count);
        AssertJson(vector["first"], rows[0]); AssertJson(vector["last"], rows[^1]);
        AssertOutcome(vector, vector["truncated"]!, bytes[..^1]);
        AssertOutcome(vector, vector["tail"]!, [.. bytes, 0x7e]);
    }

    [Fact]
    public void ScheduleLayoutMustBeExplicitAndMissingContextNeverGuessesLegacy()
    {
        foreach (var sub in new[] { 1, 16 })
        {
            Assert.Throws<InvalidOperationException>(() => CraftingDecoder.Decode(new(64, sub)));
            Assert.Throws<InvalidOperationException>(() => CraftingDecoder.Decode(new(64, sub, [0])));
        }
        Assert.IsType<CraftSnapshotEvent>(CraftingDecoder.Decode(new(64, 1, [0]), CraftingScheduleContext.Legacy));
        Assert.IsType<CraftStartedEvent>(CraftingDecoder.Decode(new(64, 2, [0])));
        Assert.Null(CraftingDecoder.Decode(new(64, 255)));
        Assert.Throws<ArgumentNullException>(() => CraftingScheduleContext.FromRuntimeRows(null!));
        Assert.Same(CraftingScheduleContext.Legacy, CraftingScheduleContext.FromRuntimeRows([]));
        Assert.Same(CraftingScheduleContext.Legacy, CraftingScheduleContext.FromRuntimeRows([new(null, 0)]));
    }

    [Fact]
    public void RecipeIdentityIsNotAProductIdAndContextOwnsItsSnapshot()
    {
        var source = new List<CraftingRecipeIdentity> { new(42, 500), new(1, 500) };
        var context = CraftingScheduleContext.FromRuntimeRows(source); source.Clear();
        var payload = Convert.FromHexString(Vectors["schedule_hex"]!.GetValue<string>());
        var legacy = Assert.IsType<CraftAddedEvent>(CraftingDecoder.Decode(new(64, 16, payload), CraftingScheduleContext.Legacy));
        var selected = Assert.IsType<CraftAddedEvent>(CraftingDecoder.Decode(new(64, 16, payload), context));
        Assert.Equal((ushort)42, legacy.Row.ItemId); Assert.Null(legacy.Row.RecipeId);
        Assert.Equal((ushort)500, selected.Row.ItemId); Assert.Equal((ushort)42, selected.Row.RecipeId);
        var unknown = CraftingScheduleContext.FromRuntimeRows([new(1, 42)]);
        Assert.Equal("新版製作排程包含未知配方，請重新同步資源", Assert.Throws<ProtocolException>(() => CraftingDecoder.Decode(new(64, 16, payload), unknown)).Message);
    }

    [Fact]
    public void NonstorageErrorKindsReadBothHeaderBytesBeforeIgnoringTail()
    {
        for (var kind = 0; kind <= byte.MaxValue; kind++)
        {
            if (kind == 1) continue;
            Assert.Throws<ProtocolException>(() => StorageDecoder.Decode(new(62, 25, [(byte)kind])));
            Assert.Null(StorageDecoder.Decode(new(62, 25, [(byte)kind, 255])));
            Assert.Null(StorageDecoder.Decode(new(62, 25, [(byte)kind, 255, 0, 255])));
        }
        Assert.Throws<ProtocolException>(() => StorageDecoder.Decode(new(62, 25, [1, 255, 0])));
    }

    [Fact]
    public void NestedCollectionsAreImmutableAndOwnThePayload()
    {
        var vector = Vector("garage_initial_3"); var bytes = Bytes(vector); var packet = new Packet(62, 7, bytes);
        Array.Fill(bytes, (byte)0); var garage = Assert.IsType<StorageGarageInitialEvent>(StorageDecoder.Decode(packet));
        Assert.Equal(ushort.MaxValue, garage.Items[0].ItemId);
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)garage.Items)[0] = garage.Items[1]);
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)garage.Items[0].Plugins)[0] = new(0, 0));
        var materials = Assert.IsType<StorageMaterialsInitialEvent>(Decode(Vector("materials_initial_4"), Bytes(Vector("materials_initial_4"))));
        Assert.Throws<NotSupportedException>(() => ((IList<StorageMaterial>)materials.Items).Clear());
        var potion = Assert.IsType<PotionUsedEvent>(Decode(Vector("used_3_3"), Bytes(Vector("used_3_3"))));
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)potion.Targets)[0] = 0);
        var furniture = Assert.IsType<FurnitureSnapshotEvent>(Decode(Vector("furniture_snapshot_3"), Bytes(Vector("furniture_snapshot_3"))));
        Assert.Throws<NotSupportedException>(() => ((IList<FurnitureRecord>)furniture.Furniture).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)furniture.Furniture[0].Contents)[0] = 65535);
        Assert.Equal(nameof(FurnitureRecord), furniture.Furniture[0].ToString());
        Assert.DoesNotContain(uint.MaxValue.ToString(System.Globalization.CultureInfo.InvariantCulture), furniture.ToString());
    }

    [Fact]
    public void NullPacketsFailExplicitly()
    {
        Assert.Throws<ArgumentNullException>(() => StorageDecoder.Decode(null!));
        Assert.Throws<ArgumentNullException>(() => RecoveryDecoder.Decode(null!));
        Assert.Throws<ArgumentNullException>(() => CraftingDecoder.Decode(null!));
    }
}
