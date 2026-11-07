using System.Collections;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Activities;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Protocol;

public class ServerProtocolTests
{
    private const string Private = "SYNTHETIC-CREDENTIAL-NEVER-RETAIN";
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
    };
    public static IEnumerable<object[]> Cases() => JsonNode.Parse(PythonServerVectors.Json)!.AsArray()
        .Select(v => new object[] { v!["name"]!.GetValue<string>(), v.ToJsonString() });
    private static JsonNode Vector(string name) => JsonNode.Parse(PythonServerVectors.Json)!.AsArray()
        .Single(v => v!["name"]!.GetValue<string>() == name)!;
    private static byte[] Bytes(JsonNode v) => Convert.FromHexString(v["hex"]!.GetValue<string>());
    private static ServerEvent? Decode(JsonNode v, byte[] bytes)
    {
        var packet = new Packet(v["main"]!.GetValue<int>(), v["sub"]!.GetValue<int>(), bytes);
        return v["outbound"]!.GetValue<bool>() ? ServerProtocol.DecodeOutboundMovement(packet) : ServerProtocol.Decode(packet);
    }
    private static JsonNode? Json(object? value)
    {
        if (value is ServerLayoutEvent layout) return Json(layout.Event);
        if (value is ServerSocialEvent social) return Json(social.Event);
        if (value is ServerLiveDataEvent live) return Json(live.Event);
        if (value is ServerExpeditionEvent expedition)
        {
            var json = Json(expedition.Event)!.AsObject(); json["type"] = expedition.Type; return json;
        }
        if (value is ServerActivityEvent activity)
        {
            var e = activity.Event;
            var json = new JsonObject
            {
                ["type"] = activity.Type, ["active"] = e.Active,
                ["activity"] = e.Activity switch
                {
                    ActivityKind.Fishing => "釣魚", ActivityKind.Gathering => "採集", ActivityKind.Dancing => "跳舞",
                    ActivityKind.ToiletCrafting => "馬桶製作", ActivityKind.Training => "鍛鍊", _ => "夥伴鍛鍊"
                }
            };
            if (e.Roles is not null) json["roles"] = JsonSerializer.SerializeToNode(e.Roles);
            if (e.Initial) json["initial"] = true;
            return json;
        }
        return JsonSerializer.SerializeToNode(value, Options);
    }
    // Typed optional fields represent absent Python keys as null. Remove null keys on both sides.
    private static JsonNode? WithoutNulls(JsonNode? node)
    {
        if (node is JsonObject obj)
        {
            foreach (var (key, value) in obj.ToArray())
                if (value is null) obj.Remove(key); else WithoutNulls(value);
        }
        else if (node is JsonArray array) foreach (var value in array) WithoutNulls(value);
        return node;
    }
    private static void Check(JsonNode v, byte[] bytes, JsonNode outcome)
    {
        if (outcome["throws"]?.GetValue<bool>() == true)
        {
            var ex = Assert.Throws<ProtocolException>(() => Decode(v, bytes));
            Assert.DoesNotContain(Private, ex.ToString());
            return;
        }
        var expected = WithoutNulls(outcome["expected"]?.DeepClone());
        var actual = WithoutNulls(Json(Decode(v, bytes)));
        Assert.True(JsonNode.DeepEquals(expected, actual), $"Expected {expected}; actual {actual}");
    }

    [Theory]
    [MemberData(nameof(Cases))]
    public void EveryBranchMatchesRetainedPython(string name, string data)
    {
        _ = name; var v = JsonNode.Parse(data)!; Check(v, Bytes(v), v);
    }
    [Theory]
    [MemberData(nameof(Cases))]
    public void EveryPrefixBoundaryMatchesPythonIncludingPermissiveMalformedBranches(string name, string data)
    {
        _ = name; var v = JsonNode.Parse(data)!; var bytes = Bytes(v);
        var prefixes = v["prefixes"]!.AsArray().ToDictionary(n => n!["length"]!.GetValue<int>(), n => n!);
        for (var length = 0; length < bytes.Length; length++)
            Check(v, bytes[..length], prefixes.GetValueOrDefault(length) ?? new JsonObject { ["throws"] = true });
    }
    [Theory]
    [MemberData(nameof(Cases))]
    public void ExtensionAndTrailingByteContractsMatchPython(string name, string data)
    {
        _ = name; var v = JsonNode.Parse(data)!; Check(v, [.. Bytes(v), 0x7e], v["tail"]!);
    }

    [Fact]
    public void CredentialsUnknownPayloadsAndDiscardedExtensionsNeverAppearInResults()
    {
        foreach (var name in new[] { "account_private_echo", "unknown_255_255", "gold_limit_discard",
            "event_end_discard", "continue_extension_7", "geometry_23_76_extension", "effect_extension_1",
            "position_7_13", "dispatch_expedition_extension" })
        {
            var v = Vector(name); var result = Decode(v, Bytes(v))!;
            Assert.DoesNotContain(Private, Json(result)!.ToJsonString());
            Assert.DoesNotContain(Private, result.ToString());
            AssertNoOpaquePayload(result);
        }
        Assert.Null(ServerProtocol.DecodeOutboundMovement(new(63, 7, Encoding.ASCII.GetBytes(Private))));
    }
    private static void AssertNoOpaquePayload(object? value)
    {
        if (value is null or string || value.GetType().IsPrimitive || value.GetType().IsEnum) return;
        Assert.IsNotType<Packet>(value);
        Assert.IsNotType<byte[]>(value);
        Assert.IsNotType<ReadOnlyMemory<byte>>(value);
        Assert.IsNotType<Memory<byte>>(value);
        if (value is IEnumerable enumerable) { foreach (var item in enumerable) AssertNoOpaquePayload(item); return; }
        foreach (var property in value.GetType().GetProperties())
            if (property.GetIndexParameters().Length == 0) AssertNoOpaquePayload(property.GetValue(value));
    }

    [Theory]
    [InlineData(64, 1, "crafting")]
    public void UnportedOrContextDependentDecodersRemainExplicit(int main, int sub, string decoder)
    {
        foreach (var bytes in new[] { Array.Empty<byte>(), Encoding.ASCII.GetBytes(Private) })
        {
            var result = Assert.IsType<UnsupportedServerDecoderEvent>(ServerProtocol.Decode(new(main, sub, bytes)));
            Assert.Equal(decoder, result.Decoder);
            Assert.Equal(bytes.Length, result.PayloadBytes);
            Assert.Equal("unsupported_decoder", result.Type);
            Assert.DoesNotContain(Private, Json(result)!.ToJsonString()); AssertNoOpaquePayload(result);
        }
    }

    [Fact]
    public void UnknownSubtypesOfUnportedFamiliesRemainUnknownRatherThanClaimingServiceSupport()
    {
        foreach (var main in new[] { 2, 191, 75, 39, 10, 124, 122, 85, 186, 62, 23, 64, 65 })
            Assert.IsType<UnimplementedServerEvent>(ServerProtocol.Decode(new(main, 255, [0xff])));
    }
    [Fact]
    public void TentOpaqueAcknowledgementsAndPillarFallbackKeepTheirMeaning()
    {
        foreach (var sub in new[] { 2, 5, 8 })
            Assert.IsType<UnimplementedServerEvent>(ServerProtocol.Decode(new(65, sub, [1])));
        var empty = Assert.IsType<Lala.Core.World.Tent.TentSceneListEvent>(ServerProtocol.Decode(new(65, 3, [])));
        Assert.Empty(empty.Tents);
        var pillar = Assert.IsType<NavigationGeometryChangeEvent>(ServerProtocol.Decode(new(65, 13, [1, 2])));
        Assert.Equal("pillar_changed", pillar.Reason);
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new(65, 13, [1])));
    }

    [Fact]
    public void DelegatedModelsRemainTypedAndNamecardsAreStillDiscarded()
    {
        var vectors = JsonNode.Parse(PythonLayoutVectors.Json)!["valid"]!.AsArray();
        foreach (var name in new[] { "world_event", "nearby_1", "role_list_event", "battle_start_event" })
        {
            var v = vectors.Single(n => n!["name"]!.GetValue<string>() == name)!;
            var result = ServerProtocol.Decode(new(v["main"]!.GetValue<int>(), v["sub"]!.GetValue<int>(), Bytes(v)));
            Assert.True(result is ServerLayoutEvent or ServerSocialEvent);
            Assert.True(JsonNode.DeepEquals(v["expected"], Json(result)));
            Assert.DoesNotContain("PRIVATE-NAMECARD-SYNTHETIC", Json(result)!.ToJsonString());
            AssertNoOpaquePayload(result);
        }
    }
    [Fact]
    public void InvalidBattleAttributesDiscardAllRecordsWithoutPartialUpdates()
    {
        for (var remainder = 1; remainder <= 6; remainder++)
        {
            var result = Assert.IsType<BattleAttributeInvalidEvent>(ServerProtocol.Decode(new(51, 1, new byte[14 + remainder])));
            Assert.Equal(2, result.CompleteRecords); Assert.Equal(remainder, result.TrailingBytes);
            AssertNoOpaquePayload(result);
        }
    }
    [Fact]
    public void NestedAttackAndAttributeCollectionsAreImmutableOwnedSnapshots()
    {
        var v = Vector("attack_nested"); var bytes = Bytes(v);
        var result = Assert.IsType<AttackResultEvent>(Decode(v, bytes));
        var before = Json(result)!.ToJsonString(); Array.Fill(bytes, byte.MaxValue);
        Assert.Equal(before, Json(result)!.ToJsonString());
        Assert.Throws<NotSupportedException>(() => ((IList<AttackAction>)result.Actions).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<AttackTarget>)result.Actions[0].Targets).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<AttackAttribute>)result.Actions[0].Targets[0].Attributes).Clear());
        var attrs = Assert.IsType<BattleAttributeSetEvent>(ServerProtocol.Decode(new(51, 1, new byte[7])));
        Assert.Throws<NotSupportedException>(() => ((IList<BattleAttributeValue>)attrs.Values).Clear());
        AssertNoOpaquePayload(result);
    }
    [Fact]
    public void ShortNpcEffectsStayActiveWithoutInventingFieldsOrPermission()
    {
        for (var length = 0; length < 18; length++)
        {
            var result = Assert.IsType<NpcEffectEvent>(ServerProtocol.Decode(new(20, 1, new byte[length])));
            Assert.Equal("event_active", result.Type); Assert.Null(result.NpcEffect);
        }
    }
    [Fact]
    public void FloorExtensionNeverAssumesSizeOrInterpretsFloorChangeAsANumber()
    {
        Assert.Equal(new HouseFloorExtension(true, 4), ServerProtocol.DecodeHouseFloorExtension([3]));
        Assert.Equal(new HouseFloorExtension(true, 4), ServerProtocol.DecodeHouseFloorExtension([99, 98, 3]));
        Assert.Equal(new HouseFloorExtension(true, 4, 3, 4), ServerProtocol.DecodeHouseFloorExtension([99, 98, 3, 3, 3]));
        for (var floor = 4; floor <= 255; floor++)
            Assert.Equal(new HouseFloorExtension(false), ServerProtocol.DecodeHouseFloorExtension([(byte)floor]));
        Assert.IsType<NavigationGeometryChangeEvent>(ServerProtocol.Decode(new(62, 64, [3])));
    }
    [Fact]
    public void OutboundMovementIsDirectionSpecificAndCannotDecodeInboundRoleData()
    {
        var outbound = CandidateCommands.Walk(65535, 65534);
        Assert.Equal(new MovementRequestEvent(65535, 65534), ServerProtocol.DecodeOutboundMovement(outbound));
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(outbound));
        Assert.Throws<ProtocolException>(() => ServerProtocol.DecodeOutboundMovement(new(6, 1, new byte[8])));
    }
    [Fact]
    public void NumericNamesDoNotDependOnCurrentCulture()
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            var result = Assert.IsType<AttributeSetEvent>(ServerProtocol.Decode(new(8, 3,
                new PacketWriter().U32(uint.MaxValue).U8(1).U8(2).U32(uint.MaxValue).U32(0).Build())));
            Assert.Equal("1", result.Attribute); Assert.Equal("player:4294967295", result.Entity);
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }
}
