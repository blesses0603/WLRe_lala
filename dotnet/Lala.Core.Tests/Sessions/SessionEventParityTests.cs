using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions;

public sealed class SessionEventParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new BigIntegerConverter() }
    };

    [Theory]
    [MemberData(nameof(SessionEventPythonVectors.Sequences), MemberType = typeof(SessionEventPythonVectors))]
    public void EveryCheckpointMatchesRetainedPythonAndStaysImmutable(string name, string json)
    {
        Assert.NotEmpty(name);
        var vector = JsonNode.Parse(json)!;
        var state = vector["initial"]!.Deserialize<SessionEventSnapshot>(Options)!;
        Check(vector["initial"]!, state);
        var retained = new List<(SessionEventSnapshot State, JsonNode Expected)> { (state, vector["initial"]!) };
        foreach (var step in vector["steps"]!.AsArray())
        {
            // Match State.apply's caller-owned packet counter, not an invented reducer side effect.
            var input = state with { PacketCount = state.PacketCount + 1 };
            var inputBefore = JsonSerializer.Serialize(input, Options);
            state = SessionEventReducer.Apply(input, Decode(step!));
            Assert.Equal(inputBefore, JsonSerializer.Serialize(input, Options));
            Check(step!["expected"]!, state);
            retained.Add((state, step["expected"]!));
        }
        foreach (var (snapshot, expected) in retained) Check(expected, snapshot);
    }

    private static ServerEvent Decode(JsonNode step)
    {
        if (step["packet"] is { } packet)
            return ServerProtocol.Decode(new(packet["main"]!.GetValue<int>(), packet["sub"]!.GetValue<int>(),
                Convert.FromHexString(packet["hex"]!.GetValue<string>())));
        var value = step["event"]!;
        Assert.Equal("gold_delta", value["type"]!.GetValue<string>());
        return new GoldDeltaEvent(value["sub"]!.GetValue<byte>(), value["delta"]!.GetValue<long>(), value["notify"]!.GetValue<bool>());
    }

    private static void Check(JsonNode expected, SessionEventSnapshot state)
    {
        var actual = WithoutNulls(JsonSerializer.SerializeToNode(state, Options)!);
        expected = WithoutNulls(expected.DeepClone());
        Assert.True(JsonNode.DeepEquals(expected, actual), $"Expected {expected}; actual {actual}");
    }

    private static JsonNode WithoutNulls(JsonNode node)
    {
        if (node is JsonObject obj)
            foreach (var (key, value) in obj.ToArray())
                if (value is null) obj.Remove(key); else WithoutNulls(value);
        if (node is JsonArray array)
            foreach (var value in array) if (value is not null) WithoutNulls(value);
        return node;
    }

    private sealed class BigIntegerConverter : JsonConverter<BigInteger>
    {
        public override BigInteger Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        {
            using var value = JsonDocument.ParseValue(ref reader);
            return BigInteger.Parse(value.RootElement.GetRawText(), CultureInfo.InvariantCulture);
        }
        public override void Write(Utf8JsonWriter writer, BigInteger value, JsonSerializerOptions options) =>
            writer.WriteRawValue(value.ToString(CultureInfo.InvariantCulture));
    }
}
