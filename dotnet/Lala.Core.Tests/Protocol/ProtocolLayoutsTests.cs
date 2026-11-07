using System.Buffers.Binary;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Protocol;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Protocol;

public class ProtocolLayoutsTests
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
    };

    public static IEnumerable<object[]> ValidCases() => Cases("valid");
    public static IEnumerable<object[]> InvalidCases() => Cases("invalid");
    private static IEnumerable<object[]> Cases(string section)
    {
        foreach (var node in JsonNode.Parse(PythonLayoutVectors.Json)![section]!.AsArray())
            yield return [node!["name"]!.GetValue<string>(), node.ToJsonString()];
    }
    private static JsonNode Vector(string name) => JsonNode.Parse(PythonLayoutVectors.Json)!["valid"]!.AsArray()
        .Single(n => n!["name"]!.GetValue<string>() == name)!;
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());
    private static Packet PacketFor(JsonNode vector, ReadOnlySpan<byte> payload) =>
        new(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), payload);
    private static object? Decode(JsonNode vector, ReadOnlySpan<byte> payload)
    {
        var reader = new PacketReader(payload);
        object? result;
        switch (vector["kind"]!.GetValue<string>())
        {
            case "roles": result = ProtocolLayouts.ReadRoleList(reader); break;
            case "world": result = ProtocolLayouts.ReadWorldPlayer(reader); break;
            case "battle": result = ProtocolLayouts.ReadBattleUnit(reader); break;
            case "layout_packet": return LayoutProtocol.Decode(PacketFor(vector, payload));
            case "social": return SocialProtocol.Decode(PacketFor(vector, payload));
            default: throw new InvalidOperationException("Unknown test vector kind");
        }
        reader.End();
        return result;
    }
    private static JsonNode? Json(object? result) => JsonSerializer.SerializeToNode(result, JsonOptions);

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void EveryDecodedFieldMatchesRetainedPython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!;
        var actual = Json(Decode(vector, Bytes(vector)));
        LazyAssert.True(JsonNode.DeepEquals(vector["expected"], actual), () => $"Expected {vector["expected"]}; actual {actual}");
    }

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryMatchesPython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        var accepted = vector["accepted_prefixes"]!.AsArray().Select(n => n!.GetValue<int>()).ToHashSet();
        for (var length = 0; length < bytes.Length; length++)
        {
            if (accepted.Contains(length)) Decode(vector, bytes.AsSpan(0, length));
            else Assert.Throws<ProtocolException>(() => Decode(vector, bytes.AsSpan(0, length)));
        }
    }

    [Theory]
    [MemberData(nameof(ValidCases))]
    public void PacketTailContractMatchesPython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!; byte[] bytes = [.. Bytes(vector), 0x7e];
        if (vector["accepts_tail"]!.GetValue<bool>())
            Assert.True(JsonNode.DeepEquals(vector["expected"], Json(Decode(vector, bytes))));
        else Assert.Throws<ProtocolException>(() => Decode(vector, bytes));
    }

    [Theory]
    [MemberData(nameof(InvalidCases))]
    public void RejectsMalformedFieldsLikePython(string name, string data)
    {
        _ = name;
        var vector = JsonNode.Parse(data)!;
        Assert.Throws<ProtocolException>(() => Decode(vector, Bytes(vector)));
    }

    [Theory]
    [InlineData("world_0")]
    [InlineData("battle_slot_0")]
    public void SingleStructureReadersLeaveTheNextStructureForTheirCaller(string name)
    {
        var vector = Vector(name); var bytes = Bytes(vector);
        var reader = new PacketReader([.. bytes, .. bytes, 0x7e]);
        object Read() => name.StartsWith("world", StringComparison.Ordinal)
            ? ProtocolLayouts.ReadWorldPlayer(reader) : ProtocolLayouts.ReadBattleUnit(reader);
        var first = Read();
        Assert.Equal(bytes.Length, reader.Offset);
        Assert.Equal(bytes.Length + 1, reader.Remaining);
        Assert.True(JsonNode.DeepEquals(Json(first), Json(Read())));
        Assert.Equal(1, reader.Remaining);
        Assert.Throws<ProtocolException>(reader.End);
        Assert.Equal(0x7e, reader.U8()); reader.End();
    }

    [Fact]
    public void RoleListHasNoCountPrefixAndPreservesDuplicateIndices()
    {
        var bytes = Bytes(Vector("roles_repeated_index_preserved"));
        var reader = new PacketReader(bytes);
        var roles = ProtocolLayouts.ReadRoleList(reader);
        Assert.Equal(2, roles.Length);
        Assert.All(roles, r => Assert.Equal(1, r.Index));
        reader.End();
    }

    [Fact]
    public void RoleBonusTotalsNeitherWrapNorClamp()
    {
        var positive = ProtocolLayouts.ReadRoleList(new PacketReader(Bytes(Vector("roles_positive_extreme"))))[0];
        Assert.True(positive.MaxHp > uint.MaxValue);
        Assert.True(positive.MaxSp > uint.MaxValue);
        var negative = ProtocolLayouts.ReadRoleList(new PacketReader(Bytes(Vector("roles_negative_extreme"))))[0];
        Assert.Equal((long)int.MinValue, negative.MaxHp);
        Assert.Equal((long)int.MinValue, negative.MaxSp);
    }

    [Theory]
    [InlineData(long.MinValue)] // Negative zero is not an integer timestamp.
    [InlineData(0x7ff0000000000000L)] // Python permits infinity.
    [InlineData(unchecked((long)0xfff0000000000000UL))]
    [InlineData(0x7ff8000000000042L)] // Preserve NaN payload bits; do not invent validation.
    public void DeleteTimePreservesIeee754Bits(long bits)
    {
        var bytes = Bytes(Vector("roles_positive_extreme"));
        var offset = 46 + bytes[1];
        BinaryPrimitives.WriteInt64LittleEndian(bytes.AsSpan(offset, 8), bits);
        var role = ProtocolLayouts.ReadRoleList(new PacketReader(bytes))[0];
        Assert.Equal(bits, BitConverter.DoubleToInt64Bits(role.DeleteTime));
    }

    [Fact]
    public void PrivateNamecardsAreAbsentFromTypedEventsAndDiagnostics()
    {
        var world = LayoutProtocol.Decode(PacketFor(Vector("world_event"), Bytes(Vector("world_event"))))!;
        var nearby = SocialProtocol.Decode(PacketFor(Vector("nearby_1"), Bytes(Vector("nearby_1"))))!;
        foreach (var result in new object[] { world, nearby })
        {
            var json = Json(result)!.ToJsonString();
            Assert.DoesNotContain("PRIVATE-NAMECARD-SYNTHETIC", json);
            Assert.DoesNotContain("PRIVATE-NAMECARD-SYNTHETIC", result.ToString());
            Assert.DoesNotContain("signature", json);
            Assert.DoesNotContain("birthday", json);
            Assert.DoesNotContain("interests", json);
            Assert.DoesNotContain("card_setting", json);
        }
        Assert.DoesNotContain("title_id", Json(nearby)!.ToJsonString());
        Assert.Contains("title_id", Json(world)!.ToJsonString());
    }

    [Fact]
    public void CollectionsAndInputAreImmutableSnapshots()
    {
        var worldBytes = Bytes(Vector("world_event"));
        var world = Assert.IsType<WorldPlayerEvent>(LayoutProtocol.Decode(new(3, 1, worldBytes)));
        var worldBefore = Json(world)!.ToJsonString();
        Array.Fill(worldBytes, (byte)255);
        Assert.Equal(worldBefore, Json(world)!.ToJsonString());
        var equipment = (IList<EquipmentAppearance>)world.Player.Equips;
        Assert.True(equipment.IsReadOnly);
        Assert.Throws<NotSupportedException>(() => equipment[0] = new(0, 0));

        var roles = Assert.IsType<RoleListAvailableEvent>(LayoutProtocol.Decode(
            PacketFor(Vector("role_list_event"), Bytes(Vector("role_list_event")))));
        Assert.Throws<NotSupportedException>(() => ((IList<RoleSnapshot>)roles.Roles).Clear());
        var teams = Assert.IsType<TeamListEvent>(SocialProtocol.Decode(new(13, 6, Bytes(Vector("team_full")))));
        Assert.Throws<NotSupportedException>(() => ((IList<TeamSnapshot>)teams.Teams).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<uint>)teams.Teams[0].Members)[0] = 0);
        var battle = Assert.IsType<BattleUnitsEvent>(LayoutProtocol.Decode(new(11, 5, Bytes(Vector("battle_units_event")))));
        Assert.Throws<NotSupportedException>(() => ((IList<BattleUnit>)battle.Units).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<EquipmentAppearance>)battle.Units[0].Equips).Clear());
    }

    [Fact]
    public void UnknownPacketsReturnNoEventAndAreNotParsed()
    {
        Assert.Null(LayoutProtocol.Decode(new(255, 255, [0xff])));
        Assert.Null(LayoutProtocol.Decode(new(11, 6, [])));
        Assert.Null(SocialProtocol.Decode(new(13, 2, [])));
        Assert.Null(SocialProtocol.Decode(new(13, 15, [4, 255])));
        Assert.Throws<ProtocolException>(() => SocialProtocol.Decode(new(13, 15, [])));
    }

    [Fact]
    public void CompletePacketsRejectValidStructuresBeyondTheirDeclaredCount()
    {
        var unit = Bytes(Vector("battle_slot_0"));
        Assert.Throws<ProtocolException>(() => LayoutProtocol.Decode(new(11, 5, [0, .. unit])));
        Assert.Throws<ProtocolException>(() => LayoutProtocol.Decode(new(11, 250, [1, 2, 0, .. unit])));
        Assert.Throws<ProtocolException>(() => LayoutProtocol.Decode(new(11, 5, [2, .. unit])));
        var player = Bytes(Vector("world_0"));
        Assert.Throws<ProtocolException>(() => LayoutProtocol.Decode(new(3, 1, [.. player, .. player])));
    }
}
