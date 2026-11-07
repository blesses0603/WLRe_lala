using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Social;

public sealed class SocialDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly JsonNode Vectors = JsonNode.Parse(PythonSocialVectors.Json)!;
    public static IEnumerable<object[]> ValidCases() => Cases("valid");
    public static IEnumerable<object[]> InvalidCases() => Cases("invalid");
    public static IEnumerable<object[]> IgnoredCases() => Cases("ignored");
    private static IEnumerable<object[]> Cases(string section) => Vectors[section]!.AsArray()
        .Select(v => new object[] { v!["name"]!.GetValue<string>(), v.ToJsonString() });
    private static JsonNode Vector(string name) => Vectors["valid"]!.AsArray()
        .Single(v => v!["name"]!.GetValue<string>() == name)!;
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());
    private static Packet PacketFor(JsonNode vector, ReadOnlySpan<byte> bytes) =>
        new(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), bytes);
    private static SocialPacketEvent? Decode(JsonNode vector, ReadOnlySpan<byte> bytes)
    {
        var packet = PacketFor(vector, bytes);
        return vector["family"]!.GetValue<string>() switch
        {
            "chat" => ChatDecoder.Decode(packet, vector["local"]?.GetValue<uint>()),
            "guild" => GuildDecoder.Decode(packet),
            "actions" => GuildActionsDecoder.Decode(packet),
            _ => throw new InvalidOperationException("Unknown family")
        };
    }
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
    private static void AssertPython(JsonNode vector, JsonNode? expected, SocialPacketEvent? result)
    {
        if (expected is null) { Assert.Null(result); return; }
        Assert.NotNull(result);
        Assert.Equal(vector["main"]!.GetValue<byte>(), result.Main);
        Assert.Equal(vector["sub"]!.GetValue<byte>(), result.Sub);
        Assert.Equal(expected["type"]!.GetValue<string>(), result.Type);
        var actual = JsonSerializer.SerializeToNode(result, result.GetType(), Options)!;
        if (vector["family"]!.GetValue<string>() == "actions")
        {
            // Python action dictionaries omit metadata. The typed contract intentionally
            // supplies it, checked above, without changing or omitting any decoded field.
            actual.AsObject().Remove("main"); actual.AsObject().Remove("sub");
        }
        RemoveAbsentNulls(actual, expected);
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"Expected {expected}; actual {actual}");
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryFieldMatchesRetainedPythonAndItsDispatcher(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertPython(vector, vector["expected"], Decode(vector, Bytes(vector)));
        var dispatched = ServerProtocol.Decode(PacketFor(vector, Bytes(vector)), vector["local"]?.GetValue<uint>());
        if (vector["expected"] is null) Assert.IsType<UnimplementedServerEvent>(dispatched);
        else AssertPython(vector, vector["expected"], Assert.IsAssignableFrom<SocialPacketEvent>(Assert.IsType<ServerSocialEvent>(dispatched).Event));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryMatchesPythonIncludingEarlyNoticeAndAnnouncements(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        var accepted = vector["accepted_prefixes"]!.AsObject();
        for (var length = 0; length < bytes.Length; length++)
        {
            if (accepted.TryGetPropertyValue(length.ToString(System.Globalization.CultureInfo.InvariantCulture), out var expected))
                AssertPython(vector, expected, Decode(vector, bytes.AsSpan(0, length)));
            else Assert.Throws<ProtocolException>(() => Decode(vector, bytes.AsSpan(0, length)));
        }
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void TrailingBytesMatchPythonRatherThanAssumingEveryBranchIsStrict(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; byte[] bytes = [.. Bytes(vector), 0x7e];
        var tail = vector["tail"]!;
        if (tail["error"] is { } error)
            Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() => Decode(vector, bytes)).Message);
        else AssertPython(vector, tail["expected"], Decode(vector, bytes));
    }

    [Theory, MemberData(nameof(InvalidCases))]
    public void MalformedFieldsKeepExactPythonErrorAndSubtypePrecedence(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        var exception = Assert.Throws<ProtocolException>(() => Decode(vector, Bytes(vector)));
        Assert.Equal(vector["error"]!.GetValue<string>(), exception.Message);
        Assert.DoesNotContain("PRIVATE", exception.ToString());
    }

    [Theory, MemberData(nameof(IgnoredCases))]
    public void UnknownKeysDoNotInspectTheirMalformedPayload(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        Assert.Null(Decode(vector, Bytes(vector)));
        Assert.Null(Decode(vector, []));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EachFamilyClaimsOnlyItsOwnKeysAndDiagnosticFormattingIsMetadataOnly(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var packet = PacketFor(vector, Bytes(vector));
        var result = Decode(vector, packet.Payload.Span)!;
        Assert.Equal($"{result.Type} (S{result.Main}-{result.Sub})", result.ToString());
        if (vector["family"]!.GetValue<string>() != "chat") Assert.Null(ChatDecoder.Decode(packet));
        if (vector["family"]!.GetValue<string>() != "guild") Assert.Null(GuildDecoder.Decode(packet));
        if (vector["family"]!.GetValue<string>() != "actions") Assert.Null(GuildActionsDecoder.Decode(packet));
        var serialized = JsonSerializer.Serialize(result, result.GetType(), Options);
        Assert.DoesNotContain("PRIVATE-CARD-SYNTHETIC", serialized);
        Assert.DoesNotContain("PRIVATE-SIGNATURE-SYNTHETIC", serialized);
        Assert.DoesNotContain("PRIVATE-RULES-SYNTHETIC", serialized);
    }

    [Fact]
    public void WhisperAttributionUsesExplicitLocalIdentityAndNeverInfersFromBody()
    {
        byte[] inbound = [.. new PacketWriter().U32(7).Build(), 0, 0, 0, 0, 0, 0];
        var received = Assert.IsType<ChatMessageEvent>(ChatDecoder.Decode(new(2, 3, inbound), 42));
        Assert.Equal(7u, received.RoleId); Assert.Equal(42u, received.TargetId);
        Assert.IsType<ChatNoticeEvent>(ChatDecoder.Decode(new(2, 3, inbound)));
        Assert.Throws<ProtocolException>(() => ChatDecoder.Decode(new(2, 3, inbound), 7));
        byte[] outbound = [.. new PacketWriter().U32(42).U32(7).Build(), 0, 0, 0, 0, 0, 0];
        var sentEcho = Assert.IsType<ChatMessageEvent>(ChatDecoder.Decode(new(2, 3, outbound), 42));
        Assert.Equal(42u, sentEcho.RoleId); Assert.Equal(7u, sentEcho.TargetId);
        Assert.Throws<ProtocolException>(() => ChatDecoder.Decode(new(2, 3, [1, 2, 3])));
        Assert.IsType<ChatNoticeEvent>(ChatDecoder.Decode(new(2, 3, [1, 2, 3, 4, 255, 255])));
    }

    [Fact]
    public void DecodedCollectionsAndNestedItemsAreImmutableAndOwnInput()
    {
        var chatVector = Vector("chat_27_1"); var bytes = Bytes(chatVector);
        var packet = PacketFor(chatVector, bytes); Array.Fill(bytes, (byte)0xff);
        var chat = Assert.IsType<ChatMessageEvent>(ChatDecoder.Decode(packet, 42));
        Assert.Equal("星河😀", chat.Text);
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)chat.Items)[0] = chat.Items[0]);
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)chat.Items[0].Plugins)[0] = new(0, 0));
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)chat.ReplyItems!.Value)[0] = 0);
        var rosterVector = Vector("roster_4");
        var roster = Assert.IsType<GuildRosterEvent>(Decode(rosterVector, Bytes(rosterVector)));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<uint, GuildMember>)roster.Members).Clear());
        Assert.Equal(nameof(GuildMember), roster.Members[1].ToString());
        var countVector = Vector("sell_snapshot_255");
        var counts = Assert.IsType<UiSellSnapshotEvent>(Decode(countVector, Bytes(countVector))).Counts;
        Assert.Equal(255, counts.Count); Assert.True(counts.ContainsKey(255)); Assert.False(counts.ContainsKey(0));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, byte>)counts)[1] = 0);
    }

    [Fact]
    public void DefaultAndWrappedDiagnosticsNeverPrintUserContentOrIdentifiers()
    {
        const string privateText = "PRIVATE-TEXT-SYNTHETIC";
        var message = new ChatMessageEvent(3, "密語", 123456789, ImmutableArray<ItemSave>.Empty,
            privateText, 42, 987654321, ReplyText: privateText);
        var profile = new ChatProfileEvent(18, 123456789, privateText, true);
        var member = new GuildMemberProfileEvent(123456789, privateText);
        foreach (var result in new SocialPacketEvent[] { message, profile, member })
        {
            var diagnostic = result.ToString() + new ServerSocialEvent(result);
            Assert.DoesNotContain(privateText, diagnostic);
            Assert.DoesNotContain("123456789", diagnostic);
            Assert.DoesNotContain("987654321", diagnostic);
        }
    }

    [Fact]
    public void NullPacketsFailExplicitly()
    {
        Assert.Throws<ArgumentNullException>(() => ChatDecoder.Decode(null!));
        Assert.Throws<ArgumentNullException>(() => GuildDecoder.Decode(null!));
        Assert.Throws<ArgumentNullException>(() => GuildActionsDecoder.Decode(null!));
    }
}
