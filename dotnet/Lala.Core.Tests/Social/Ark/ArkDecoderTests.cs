using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.World;
using Lala.Core.Social.Ark;
using Xunit;

namespace Lala.Core.Tests.Social.Ark;

public sealed class ArkDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly JsonNode[] Vectors = PythonArkVectors.JsonParts.SelectMany(part => JsonNode.Parse(part)!.AsArray()).Cast<JsonNode>().ToArray();
    public static IEnumerable<object[]> AllCases() => Cases(Vectors);
    public static IEnumerable<object[]> ValidCases() => Cases(Vectors.Where(v => v["expected"] is not null));
    private static IEnumerable<object[]> Cases(IEnumerable<JsonNode> values) => values.Select(v => new object[] { v["name"]!.GetValue<string>(), v.ToJsonString() });
    private static byte[] Bytes(JsonNode vector) => Convert.FromHexString(vector["hex"]!.GetValue<string>());
    private static ArkEvent? Decode(JsonNode vector, ReadOnlySpan<byte> bytes) => ArkDecoder.Decode(new(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), bytes));
    private static JsonNode Vector(string name) => Vectors.Single(v => v["name"]!.GetValue<string>() == name);

    private static JsonNode? PythonShape(ArkEvent? result)
    {
        if (result is null) return null;
        var actual = JsonSerializer.SerializeToNode(result, result.GetType(), Options)!.AsObject();
        // Python Ark dictionaries lack packet metadata; the typed API supplies and tests it.
        actual.Remove("main"); actual.Remove("sub");
        foreach (var field in actual.Where(p => p.Value is null).Select(p => p.Key).ToArray()) actual.Remove(field);
        return actual;
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void CommonDispatcherPreservesTypedArkObservations(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        var packet = new Packet(vector["main"]!.GetValue<int>(), vector["sub"]!.GetValue<int>(), Bytes(vector));
        var actual = Assert.IsAssignableFrom<ArkEvent>(ServerProtocol.Decode(packet));
        Assert.True(JsonNode.DeepEquals(PythonShape(Decode(vector, Bytes(vector))), PythonShape(actual)));
    }

    private static JsonNode? Canonical(JsonNode? value) => value switch
    {
        JsonObject obj => new JsonObject(obj.OrderBy(p => p.Key, StringComparer.Ordinal)
            .Select(p => new KeyValuePair<string, JsonNode?>(p.Key, Canonical(p.Value)))),
        JsonArray array => new JsonArray(array.Select(Canonical).ToArray()),
        _ => value?.DeepClone()
    };

    private static void AssertOutcome(JsonNode vector, JsonNode outcome, ReadOnlySpan<byte> bytes)
    {
        // A copy lets the lambda retain the payload without capturing a span.
        var data = bytes.ToArray();
        if (outcome["error"] is { } error)
        {
            Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() => Decode(vector, data)).Message);
            return;
        }
        var result = Decode(vector, data);
        if (result is not null)
        {
            Assert.Equal(vector["main"]!.GetValue<byte>(), result.Main);
            Assert.Equal(vector["sub"]!.GetValue<byte>(), result.Sub);
            Assert.Equal($"{result.Type} (S{result.Main}-{result.Sub})", result.ToString());
        }
        var actual = PythonShape(result);
        if (outcome["sha256"] is { } hash)
        {
            var json = Canonical(actual)?.ToJsonString() ?? "null";
            Assert.Equal(hash.GetValue<string>(), Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant());
        }
        else Assert.True(JsonNode.DeepEquals(outcome["expected"], actual), $"Expected {outcome["expected"]}; actual {actual}");
    }

    [Theory, MemberData(nameof(AllCases))]
    public void AllFieldsUnknownKeysAndMalformedErrorsMatchRetainedPython(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector, Bytes(vector));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryTruncationBoundaryKeepsExactPythonOutcomeAndErrorPrecedence(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!; var bytes = Bytes(vector);
        var prefixes = vector["prefixes"]!.AsArray();
        Assert.Equal(bytes.Length, prefixes.Count);
        for (var length = 0; length < bytes.Length; length++)
            AssertOutcome(vector, prefixes[length]!, bytes.AsSpan(0, length));
    }

    [Theory, MemberData(nameof(ValidCases))]
    public void EveryRecognizedBranchRetainsStrictTrailingBytePolicy(string name, string data)
    {
        _ = name; var vector = JsonNode.Parse(data)!;
        AssertOutcome(vector, vector["tail"]!, [.. Bytes(vector), 0x7e]);
    }

    [Fact]
    public void NestedSnapshotCollectionsAreImmutableAndDoNotAliasInput()
    {
        var vector = Vector("snapshot_two_agents"); var source = Bytes(vector);
        var packet = new Packet(191, 1, source); Array.Fill(source, (byte)0xff);
        var snapshot = Assert.IsType<ArkSnapshotEvent>(ArkDecoder.Decode(packet));
        Assert.Equal((byte)8, snapshot.Ship.Planet);
        Assert.Equal(new byte[] { 1, 255 }, snapshot.Ship.Agents);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, ArkAgent>)snapshot.Agents).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)snapshot.Agents[1].Skills)[0] = 0);
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)snapshot.Ship.Agents)[0] = 0);
        var events = Assert.IsType<ArkEventsEvent>(Decode(Vector("events_all_kinds"), Bytes(Vector("events_all_kinds"))));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, ArkEventRow>)events.Events).Clear());
        var main = Assert.IsType<ArkMainEventsEvent>(Decode(Vector("main_events_all_kinds"), Bytes(Vector("main_events_all_kinds"))));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, ArkEventRow>)main.Events).Clear());
    }

    [Fact]
    public void QuestionRewardAndDispatchCollectionsAreImmutable()
    {
        var question = Assert.IsType<ArkQuestionEvent>(Decode(Vector("question_1_0"), Bytes(Vector("question_1_0"))));
        Assert.Throws<NotSupportedException>(() => ((IList<uint>)question.Options)[0] = 0);
        var fight = Assert.IsType<ArkFightResultEvent>(Decode(Vector("fight_awards_32_65535"), Bytes(Vector("fight_awards_32_65535"))));
        Assert.Throws<NotSupportedException>(() => ((IList<ArkAward>)fight.Awards!.Value)[0] = new(0, 0, 0));
        var reward = Assert.IsType<ArkCollectRewardEvent>(Decode(Vector("collect_reward_255"), Bytes(Vector("collect_reward_255"))));
        Assert.Throws<NotSupportedException>(() => ((IList<ArkCollectedItem>)reward.Items)[0] = new(0, 0));
        var dispatch = Assert.IsType<ArkDispatchEvent>(Decode(Vector("dispatch_agents_1_255_1"), Bytes(Vector("dispatch_agents_1_255_1"))));
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)dispatch.Agents)[0] = 0);
    }

    [Fact]
    public void NoAdditionalRuntimeKnowledgeOrActionIsInferredFromValidObservations()
    {
        // Source accepts any nonzero byte identifiers, and a successful fight may have ID 0.
        var dispatch = Assert.IsType<ArkDispatchEvent>(ArkDecoder.Decode(new(191, 3, [1, 1, 254, 255, 1, 0])));
        Assert.Equal(new byte[] { 254, 255 }, dispatch.Agents);
        var fight = Assert.IsType<ArkFightResultEvent>(ArkDecoder.Decode(new(191, 15, [1, 0, 0, 0])));
        Assert.Equal((ushort)0, fight.Id); Assert.Empty(fight.Awards!.Value);
        var loss = Assert.IsType<ArkFightResultEvent>(ArkDecoder.Decode(new(191, 15, [0])));
        Assert.Null(loss.Id); Assert.Null(loss.Awards);
        Assert.Throws<ProtocolException>(() => ArkDecoder.Decode(new(191, 15, [0, 0])));
        Assert.Single(typeof(ArkDecoder).GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static));
        Assert.Throws<ArgumentNullException>(() => ArkDecoder.Decode(null!));
    }

    [Fact]
    public void TheseServiceObservationsDoNotInventWorldGeometryUpdates()
    {
        var state = new WorldEventSnapshot { Navigation = new() { Revision = 42, Stale = false } };
        foreach (var vector in Vectors.Where(v => v["expected"] is not null))
            Assert.Same(state, WorldEventReducer.Apply(state, Decode(vector, Bytes(vector))!));
    }
}
