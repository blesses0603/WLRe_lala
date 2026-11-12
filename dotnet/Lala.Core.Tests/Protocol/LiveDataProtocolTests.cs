using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Protocol;

public class LiveDataProtocolTests
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };
    public static IEnumerable<object[]> ValidCases() => Cases("valid");
    public static IEnumerable<object[]> InvalidCases() => Cases("invalid");
    private static IEnumerable<object[]> Cases(string section)
    {
        foreach (var vector in JsonNode.Parse(PythonLiveDataVectors.Json)![section]!.AsArray())
            yield return [vector!["name"]!.GetValue<string>(), vector.ToJsonString()];
    }
    private static JsonNode Vector(string name) => JsonNode.Parse(PythonLiveDataVectors.Json)!["valid"]!.AsArray()
        .Single(v => v!["name"]!.GetValue<string>() == name)!;
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());
    private static Packet PacketFor(JsonNode vector, ReadOnlySpan<byte> payload) =>
        new(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), payload);
    private static object? Decode(JsonNode vector, ReadOnlySpan<byte> payload)
    {
        if (vector["kind"]!.GetValue<string>() == "packet")
            return LiveDataProtocol.Decode(PacketFor(vector, payload));
        var reader = new PacketReader(payload);
        var result = ReadLayout(vector, reader);
        reader.End();
        return result;
    }
    private static object ReadLayout(JsonNode vector, PacketReader reader)
    {
        byte? index = vector["index"]?.GetValue<byte>();
        var npcId = vector["npc_id"]!.GetValue<uint>();
        return vector["kind"]!.GetValue<string>() switch
        {
            "item" => LiveDataLayouts.ReadItem(reader, index),
            "equip" => LiveDataLayouts.ReadItem(reader, index, true),
            "companion" => LiveDataLayouts.ReadCompanion(reader, index, npcId),
            "simple_companion" => LiveDataLayouts.ReadCompanion(reader, index, npcId, true),
            "player" => LiveDataLayouts.ReadPlayerInfo(reader),
            _ => throw new InvalidOperationException("Unknown layout vector")
        };
    }
    private static JsonNode? Json(object? result) => JsonSerializer.SerializeToNode(result, JsonOptions);

    // Typed optional fields are null for fields absent from Python's variant dictionary.
    // Remove only those absent nulls; explicit Python nulls (item index, active npc) remain
    // required, and extra non-null fields or different values always fail comparison.
    private static void RemoveAbsentNulls(JsonNode? actual, JsonNode? expected)
    {
        if (actual is JsonObject obj && expected is JsonObject wanted)
        {
            foreach (var pair in obj.ToArray())
            {
                if (pair.Value is null && !wanted.ContainsKey(pair.Key)) obj.Remove(pair.Key);
                else RemoveAbsentNulls(pair.Value, wanted[pair.Key]);
            }
        }
        else if (actual is JsonArray array && expected is JsonArray wantedArray)
            for (var i = 0; i < Math.Min(array.Count, wantedArray.Count); i++)
                RemoveAbsentNulls(array[i], wantedArray[i]);
    }
    private static void AssertPython(JsonNode? expected, object? decoded)
    {
        var actual = Json(decoded);
        RemoveAbsentNulls(actual, expected);
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"Expected {expected}; actual {actual}");
    }

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void EveryDecodedFieldMatchesRetainedPython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!;
        AssertPython(vector["expected"], Decode(vector, Bytes(vector)));
    }

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryMatchesPythonIncludingValidShorterSnapshots(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        var accepted = vector["accepted_prefixes"]!.AsArray().Select(n => n!.GetValue<int>()).ToHashSet();
        for (var length = 0; length < bytes.Length; length++)
        {
            if (accepted.Contains(length))
                AssertPython(vector["prefix_results"]![length.ToString(System.Globalization.CultureInfo.InvariantCulture)],
                    Decode(vector, bytes.AsSpan(0, length)));
            else Assert.Throws<ProtocolException>(() => Decode(vector, bytes.AsSpan(0, length)));
        }
    }

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void CompletePacketTrailingByteBehaviorMatchesPython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!; byte[] bytes = [.. Bytes(vector), 0x7e];
        if (vector["accepts_tail"]!.GetValue<bool>()) AssertPython(vector["expected"], Decode(vector, bytes));
        else Assert.Throws<ProtocolException>(() => Decode(vector, bytes));
    }

    [Theory]
    [MemberData(nameof(InvalidCases))]
    public void MalformedFieldsAndUnsupportedDamageKindsMatchPythonRejection(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!;
        Assert.Throws<ProtocolException>(() => Decode(vector, Bytes(vector)));
    }

    [Theory]
    [InlineData("item_False_locked_0")]
    [InlineData("item_True_locked_0")]
    [InlineData("companion_0")]
    [InlineData("simple_companion_0")]
    [InlineData("player_5")]
    public void SingleStructureReadersLeaveTheNextStructureForTheirCaller(string name)
    {
        var vector = Vector(name); var bytes = Bytes(vector);
        var reader = new PacketReader([.. bytes, .. bytes, 0x7e]);
        AssertPython(vector["expected"], ReadLayout(vector, reader));
        Assert.Equal(bytes.Length, reader.Offset);
        Assert.Equal(bytes.Length + 1, reader.Remaining);
        AssertPython(vector["expected"], ReadLayout(vector, reader));
        Assert.Equal(1, reader.Remaining);
        Assert.Throws<ProtocolException>(reader.End);
        Assert.Equal(0x7e, reader.U8()); reader.End();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void FiniteItemTimesPreserveExactIeee754Bits(bool equip)
    {
        var vector = Vector($"item_{equip}_locked_0"); var bytes = Bytes(vector);
        var offset = equip ? 10 : 19;
        long[] bits = [long.MinValue, 0, 1, long.MinValue + 1, 0x7fefffffffffffff,
            unchecked((long)0xffefffffffffffffUL), 0x3ff0000000000001];
        foreach (var value in bits)
        {
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(offset, 8), value);
            BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(offset + 8, 8), value);
            var item = LiveDataLayouts.ReadItem(new PacketReader(bytes), null, equip);
            Assert.Equal(value, BitConverter.DoubleToInt64Bits(item.AvailableTime));
            Assert.Equal(value, BitConverter.DoubleToInt64Bits(item.LimitedTime));
        }
    }

    [Fact]
    public void CompanionVariantsKeepTheirDifferentSignednessAndFieldOrder()
    {
        var fullBytes = Bytes(Vector("companion_0"));
        BinaryPrimitives.WriteInt32LittleEndian(fullBytes.AsSpan(0, 4), int.MinValue);
        BinaryPrimitives.WriteInt32LittleEndian(fullBytes.AsSpan(5, 4), int.MinValue);
        var full = LiveDataLayouts.ReadCompanion(new PacketReader(fullBytes), 255, ushort.MaxValue);
        var simpleBytes = Bytes(Vector("simple_companion_0"));
        BinaryPrimitives.WriteUInt32LittleEndian(simpleBytes.AsSpan(12, 4), uint.MaxValue);
        var simple = LiveDataLayouts.ReadCompanion(new PacketReader(simpleBytes), null, uint.MaxValue, true);
        Assert.Equal((long)int.MinValue, full.Exp);
        Assert.Equal(int.MinValue, full.Hp);
        Assert.Equal((long)uint.MaxValue, simple.Exp);
        Assert.Equal(uint.MaxValue, simple.NpcId);
        Assert.Null(simple.Index); Assert.Null(simple.Hp); Assert.Null(simple.Sp);
        Assert.Null(simple.Name); Assert.Null(simple.Die); Assert.Null(simple.SkillPotential);
        Assert.Null(simple.SublimeCount); Assert.Null(simple.PartyIndex);
        foreach (var companion in new[] { full, simple })
        {
            Assert.Equal((ushort)101, companion.Str); Assert.Equal((ushort)202, companion.Con);
            Assert.Equal((ushort)303, companion.Int); Assert.Equal((ushort)404, companion.Wis);
            Assert.Equal((ushort)505, companion.Agi);
            Assert.Equal(5, companion.SkillSlots.Length); Assert.Equal(9, companion.Equips.Length);
            Assert.Equal(Enumerable.Range(1, 9).Select(i => (byte?)i), companion.Equips.Select(i => i.Index));
            Assert.All(companion.Equips, item => { Assert.Equal(1, item.Count); Assert.Null(item.Durable); });
        }
    }

    [Fact]
    public void SnapshotsPreserveDuplicateIndicesAndDoNotInventCountOrCapacityValidation()
    {
        var bag = Assert.IsType<BagSnapshotEvent>(LiveDataProtocol.Decode(new(23, 5, Bytes(Vector("bag_multiple_duplicate_index")))));
        Assert.Equal(0, bag.Capacity); Assert.Equal(2, bag.Items.Length);
        Assert.All(bag.Items, item => Assert.Equal((byte)255, item.Index));
        var companions = Assert.IsType<CompanionSnapshotEvent>(LiveDataProtocol.Decode(new(15, 8, Bytes(Vector("companions_duplicate_index")))));
        Assert.Equal(2, companions.Companions.Length);
        Assert.All(companions.Companions, companion => Assert.Equal((byte)255, companion.Index));
        var equips = Assert.IsType<PlayerEquipDataEvent>(LiveDataProtocol.Decode(new(23, 11, Bytes(Vector("player_equips_10")))));
        Assert.Equal(10, equips.Equips.Length); Assert.All(equips.Equips, item => Assert.Null(item.Index));
    }

    [Fact]
    public void AllCollectionsAndNestedCollectionsAreImmutableOwnedSnapshots()
    {
        var bagBytes = Bytes(Vector("bag_multiple_duplicate_index"));
        var bag = Assert.IsType<BagSnapshotEvent>(LiveDataProtocol.Decode(new(23, 5, bagBytes)));
        var before = Json(bag)!.ToJsonString(); Array.Fill(bagBytes, (byte)0xff);
        Assert.Equal(before, Json(bag)!.ToJsonString());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)bag.Items).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)bag.Items[0].Plugins)[0] = new(0, 0));
        var companions = Assert.IsType<CompanionSnapshotEvent>(LiveDataProtocol.Decode(new(15, 8, Bytes(Vector("companions_duplicate_index")))));
        Assert.Throws<NotSupportedException>(() => ((IList<CompanionSnapshot>)companions.Companions).Clear());
        var companion = companions.Companions[0];
        Assert.Throws<NotSupportedException>(() => ((IList<CompanionSkillSlot>)companion.SkillSlots).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)companion.Equips).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)companion.Equips[0].Plugins).Clear());
        var player = LiveDataLayouts.ReadPlayerInfo(new PacketReader(Bytes(Vector("player_256"))));
        Assert.Equal(256, player.Skills.Length);
        Assert.Throws<NotSupportedException>(() => ((IList<LearnedSkill>)player.Skills).Clear());
    }

    [Fact]
    public void UnknownPacketsReturnNoEventWithoutParsingButKnownDamageKindsAreStrict()
    {
        Assert.Null(LiveDataProtocol.Decode(new(255, 255, [0xff])));
        Assert.Null(LiveDataProtocol.Decode(new(23, 12)));
        Assert.Null(LiveDataProtocol.Decode(new(19, 3, [0xff])));
        Assert.Throws<ProtocolException>(() => LiveDataProtocol.Decode(new(23, 140)));
        Assert.Throws<ProtocolException>(() => LiveDataProtocol.Decode(new(23, 140, [255])));
    }

    [Fact]
    public void ShopAcknowledgementIsNotAnInventoryOrBalanceUpdate()
    {
        var acknowledgement = Assert.IsType<ShopPurchaseResultEvent>(LiveDataProtocol.Decode(new(27, 1, [0])));
        Assert.Equal(0, acknowledgement.Result);
        Assert.Equal("shop_purchase_result", acknowledgement.Type);
        Assert.DoesNotContain("gold", Json(acknowledgement)!.ToJsonString());
        Assert.DoesNotContain("items", Json(acknowledgement)!.ToJsonString());
        Assert.Throws<ProtocolException>(() => LiveDataProtocol.Decode(new(27, 1, [0, 0, 0, 0])));
    }
}
