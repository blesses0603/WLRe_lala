using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Xunit;
namespace Lala.Core.Tests.Protocol;

public sealed class ExpeditionDecoderTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    public static IEnumerable<object[]> Cases() => JsonDocument.Parse(PythonExpeditionPacketVectors.Json).RootElement.EnumerateArray().Select(e => new object[] { e.Clone() });
    [Theory, MemberData(nameof(Cases))]
    public void PythonParity(JsonElement sample)
    {
        var packet = new Packet(31, sample.GetProperty("sub").GetInt32(), Convert.FromHexString(sample.GetProperty("hex").GetString()!));
        var actual = ExpeditionDecoder.Decode(packet); Assert.NotNull(actual);
        var expected = JsonNode.Parse(sample.GetProperty("expected").GetRawText())!.AsObject();
        var kind = expected["type"]!.GetValue<string>(); expected.Remove("type");
        var typeNames = new Dictionary<string, Type>
        {
            ["outpost_snapshot"] = typeof(OutpostSnapshotEvent),
            ["outpost_role"] = typeof(OutpostRoleEvent),
            ["outpost_remove"] = typeof(OutpostRemoveEvent),
            ["outpost_status"] = typeof(OutpostStatusEvent),
            ["outpost_faith"] = typeof(OutpostFaithEvent),
            ["outpost_attribute"] = typeof(OutpostAttributeEvent),
            ["expedition_snapshot"] = typeof(ExpeditionSnapshotEvent),
            ["expedition_started"] = typeof(ExpeditionStartedEvent),
            ["expedition_result"] = typeof(ExpeditionResultEvent),
            ["expedition_time"] = typeof(ExpeditionTimeEvent),
            ["expedition_team"] = typeof(ExpeditionTeamEvent),
            ["expedition_quests"] = typeof(ExpeditionQuestsEvent),
            ["expedition_rejected"] = typeof(ExpeditionRejectedEvent),
            ["expedition_level"] = typeof(ExpeditionLevelEvent)
        };
        Assert.Equal(typeNames[kind], actual.GetType());
        var normalized = JsonSerializer.SerializeToNode(actual, actual.GetType(), Options);
        Assert.True(JsonNode.DeepEquals(expected, normalized), $"Expected {expected}, actual {normalized}");
    }
    [Theory, MemberData(nameof(Cases))]
    public void StrictPacketLengths(JsonElement sample)
    {
        int sub = sample.GetProperty("sub").GetInt32(); var bytes = Convert.FromHexString(sample.GetProperty("hex").GetString()!);
        if (sub == 15)
        {
            for (int size = 0; size <= bytes.Length; size++)
                Assert.Equal(size, Assert.IsType<ExpeditionStartedEvent>(ExpeditionDecoder.Decode(new(31, sub, bytes.AsSpan(0, size)))).ExtensionBytes);
            return;
        }
        Assert.Throws<ProtocolException>(() => ExpeditionDecoder.Decode(new(31, sub, bytes.Concat(new byte[] { 0 }).ToArray())));
        for (int size = 0; size < bytes.Length; size++)
        {
            // Reward packets are intentionally variable-length after their six-byte prefix.
            if (sub == 16 && size >= 6 && (size - 6) % 9 == 0) continue;
            Assert.Throws<ProtocolException>(() => ExpeditionDecoder.Decode(new(31, sub, bytes.AsSpan(0, size))));
        }
    }
    [Fact]
    public void UnknownAndImmutable()
    {
        Assert.Null(ExpeditionDecoder.Decode(new(1, 6, new byte[] { 1 })));
        Assert.Null(ExpeditionDecoder.Decode(new(31, 255, new byte[] { 1 })));
        var packet = new Packet(31, 18, new byte[21]); var team = Assert.IsType<ExpeditionTeamEvent>(ExpeditionDecoder.Decode(packet)).Team;
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)team.Members)[0] = 7);
        var started = Assert.IsType<ExpeditionStartedEvent>(ExpeditionDecoder.Decode(new(31, 15, new byte[] { 1, 2, 3 })));
        Assert.Equal(3, started.ExtensionBytes);
    }
}
