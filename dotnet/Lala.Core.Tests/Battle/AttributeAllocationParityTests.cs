using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class AttributeAllocationParityTests
{
    [Theory]
    [MemberData(nameof(AttributeAllocationPythonVectors.Sequences), MemberType = typeof(AttributeAllocationPythonVectors))]
    public void EveryReceiveTransitionAndHistoricalSnapshotMatchesStateApply(string name, string json)
    {
        var state = AttributeAllocationSnapshot.Empty;
        var history = new List<(AttributeAllocationSnapshot State, JsonNode Expected)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var before = state;
            if (step!["seed"] is { } seed) state = Read(seed);
            else if (step["message"] is { } message)
            {
                var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                    Convert.FromHexString(message["hex"]!.GetValue<string>()));
                if (step["error"] is { } error)
                {
                    Assert.Equal(error.GetValue<string>(), Assert.Throws<ProtocolException>(() =>
                    {
                        var observation = ServerProtocol.Decode(packet);
                        state = AttributeAllocationReducer.Apply(state, observation, new());
                    }).Message);
                    Assert.Same(before, state);
                }
                else
                {
                    var observation = ServerProtocol.Decode(packet);
                    var context = new AttributeAllocationContext { PlayerStats = ReadStats(step["current_stats"]!) };
                    var contextBefore = ProjectStats(context.PlayerStats);
                    state = AttributeAllocationReducer.Apply(state, observation, context);
                    if (observation is ServerLiveDataEvent live)
                        AssertJson(Project(state), Project(AttributeAllocationReducer.Apply(before, live.Event, context)), name + " direct live");
                    AssertJson(contextBefore, ProjectStats(context.PlayerStats), name + " immutable context");
                }
            }
            AssertJson(step["expected"], Project(state), $"{name}, step {index++}");
            history.Add((state, step["expected"]!));
        }
        foreach (var (snapshot, expected) in history) AssertJson(expected, Project(snapshot), name + " historical snapshot");
    }

    [Fact]
    public void OracleHasCompleteDeclaredCountsAndCapturesActualSourceOrder()
    {
        var sequences = AttributeAllocationPythonVectors.Sequences().ToArray();
        Assert.Equal(80, sequences.Length);
        var rows = sequences.SelectMany(row => JsonNode.Parse((string)row[1])!.AsArray()).ToArray();
        Assert.Equal(2098, rows.Length);
        Assert.Equal(AttributeAllocationPythonVectors.SnapshotCount, rows.Length);
        Assert.Equal(120, rows.Count(row => row!["error"] is not null));
        Assert.Equal(AttributeAllocationPythonVectors.ErrorCount, rows.Count(row => row!["error"] is not null));
        var ordering = sequences.Single(row => (string)row[0] == "same-packet-knowledge-new-local-attributes-old");
        var step = JsonNode.Parse((string)ordering[1])!.AsArray().Last()!;
        Assert.Equal(20, step["stats_before"]!["str"]!.GetValue<int>());
        Assert.Equal(22, step["current_stats"]!["str"]!.GetValue<int>());
        Assert.Equal(20, step["attributes_at_observer"]!["self"]!["28:0"]!.GetValue<int>());
        Assert.Equal(22, step["attributes_after"]!["self"]!["28:0"]!.GetValue<int>());
        Assert.False(step["player_ready"]!.GetValue<bool>()); // no readiness gate in this observer
        Assert.False(step["expected"]!["pending"]!.GetValue<bool>());
    }

    public static IEnumerable<object[]> SourceHashes() => JsonNode.Parse(AttributeAllocationPythonVectors.SourceSha256)!.AsObject()
        .Select(entry => new object[] { entry.Key, entry.Value!.GetValue<string>() });

    [Theory, MemberData(nameof(SourceHashes))]
    public void RetainedSourcesAcceptLfAndCrLfButRejectOtherByteChanges(string path, string expected)
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, path))) directory = directory.Parent;
        Assert.NotNull(directory);
        var lf = Normalize(File.ReadAllBytes(Path.Combine(directory.FullName, path)));
        var crlf = new List<byte>();
        foreach (var value in lf)
        {
            if (value == '\n') crlf.Add((byte)'\r');
            crlf.Add(value);
        }
        Assert.Equal(expected, Hash(lf)); Assert.Equal(expected, Hash(crlf.ToArray()));
        Assert.NotEqual(expected, Hash([.. lf, 0])); Assert.NotEqual(expected, Hash([.. crlf, 32]));
        lf[0] ^= 1; Assert.NotEqual(expected, Hash(lf));
    }

    [Fact]
    public void SourceHashNormalizationPreservesBomInvalidUtf8BareCrAndIsNotRecursive()
    {
        byte[] canonical = [0xef, 0xbb, 0xbf, 0xff, 0xfe, 0, 13, 42, 10, 32, 13, 10, 13];
        byte[] checkout = [0xef, 0xbb, 0xbf, 0xff, 0xfe, 0, 13, 42, 13, 10, 32, 13, 13, 10, 13];
        Assert.Equal(canonical, Normalize(checkout));
        Assert.Equal(Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant(), Hash(checkout));
        Assert.NotEqual(Hash(checkout), Hash(checkout.AsSpan(3)));
        Assert.NotEqual(Hash(checkout), Hash([.. checkout, 0]));
        Assert.Empty(Normalize([]));
    }

    private static AttributeAllocationSnapshot Read(JsonNode node) => new()
    {
        Pending = node["pending"]!.GetValue<bool>(), Acknowledged = node["acknowledged"]!.GetValue<bool>(),
        Uncertain = node["uncertain"]!.GetValue<bool>(), Expected = node["expected"] is { } stats ? ReadStats(stats) : null,
        SentAt = node["sent_at"]?.GetValue<double>(), Status = node["status"]!.GetValue<string>()
    };
    private static ImmutableDictionary<string, BigInteger> ReadStats(JsonNode node) => node.AsObject()
        .ToImmutableDictionary(entry => entry.Key, entry => BigInteger.Parse(entry.Value!.ToJsonString(), CultureInfo.InvariantCulture), StringComparer.Ordinal);
    private static JsonObject ProjectStats(ImmutableDictionary<string, BigInteger> stats) => new(stats
        .Select(entry => KeyValuePair.Create(entry.Key, JsonNode.Parse(entry.Value.ToString(CultureInfo.InvariantCulture)))));
    private static JsonObject Project(AttributeAllocationSnapshot state) => new()
    {
        ["pending"] = state.Pending, ["acknowledged"] = state.Acknowledged, ["uncertain"] = state.Uncertain,
        ["expected"] = state.Expected is { } expected ? ProjectStats(expected) : null,
        ["sent_at"] = state.SentAt, ["status"] = state.Status
    };
    private static void AssertJson(JsonNode? expected, JsonNode? actual, string label) =>
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{label}: expected {expected}; actual {actual}");
    private static string Hash(ReadOnlySpan<byte> source) => Convert.ToHexString(SHA256.HashData(Normalize(source))).ToLowerInvariant();
    private static byte[] Normalize(ReadOnlySpan<byte> source)
    {
        var bytes = new byte[source.Length]; var count = 0;
        for (var index = 0; index < source.Length; index++)
        {
            if (source[index] == '\r' && index + 1 < source.Length && source[index + 1] == '\n') continue;
            bytes[count++] = source[index];
        }
        return bytes[..count];
    }
}
