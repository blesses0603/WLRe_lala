using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Battle;
using Lala.Core.Tests.Inventory;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceStateParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new BigIntegerConverter() }
    };

    [Theory]
    [MemberData(nameof(ServiceStatePythonVectors.Sequences), MemberType = typeof(ServiceStatePythonVectors))]
    public void ActualStateApplySupportedProjectionsOrderAndHistoricalOutputsMatch(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var state = new ServiceStateCoordinator(new(local: new(session: new SessionEventSnapshot
            { PacketCount = BigInteger.Parse(vector["count"]!.GetValue<string>(), CultureInfo.InvariantCulture) })));
        var historical = new List<(ServiceStateSnapshot State, JsonNode Expected)> { (state.Snapshot(), vector["initial"]!) };
        Check(vector["initial"]!, state.Snapshot(), name + " initial");
        var number = 0;
        foreach (var step in vector["steps"]!.AsArray())
        {
            var before = state.Snapshot();
            var context = new ServiceObservationContext(before, new(step!["at"]!.GetValue<double>())
            {
                WorldCatalog = step["known"]!.GetValue<bool>() ? new([101]) : null
            });
            var packet = new Packet(step["main"]!.GetValue<byte>(), step["sub"]!.GetValue<byte>(),
                Convert.FromHexString(step["hex"]!.GetValue<string>()));
            if (step["error"]!.GetValue<bool>())
            {
                Assert.Throws<ProtocolException>(() => state.Apply(packet, context));
                Assert.Same(before, state.Snapshot());
            }
            else
            {
                var result = state.Apply(packet, context);
                Assert.Same(result, state.Snapshot());
                Assert.Equal(step["kind"]!.GetValue<string>(), result.Observation!.EventType);
                Equal(step["before"]!, JsonSerializer.SerializeToNode(result.Observation.BeforeLocal, Options)!, name);
                Equal(step["after"]!, JsonSerializer.SerializeToNode(result.Observation.AfterLocal, Options)!, name);
                Assert.Same(context.Inputs, result.Observation.Inputs);
                Assert.Equal(before.PacketCount + 1, result.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.BeforeLocal.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.AfterLocal.PacketCount);
                Assert.Same(before.Player, result.Observation.BeforeLocal.Player);
                Assert.Same(result.Player, result.Observation.AfterLocal.Player);
            }
            Check(step["expected"]!, state.Snapshot(), $"{name} step {number++}");
            historical.Add((state.Snapshot(), step["expected"]!));
        }
        foreach (var (snapshot, expected) in historical) Check(expected, snapshot, name + " historical");
    }

    [Fact]
    public void FullSourceObserverOrderAndExactOmissionsAreDeclared()
    {
        Assert.Equal(JsonSerializer.Deserialize<string[]>(ServiceStatePythonVectors.ObserverOrder),
            ServiceStateCoordinator.ObserverOrder.Select(stage => stage.SourceFunction));
        Assert.Equal(new[] { "apply_daily_tasks", "apply_cube", "apply_recovery", "apply_guild",
            "apply_activity", "apply_storage", "apply_expedition", "dispatch_local" },
            ServiceStateCoordinator.ObserverOrder.Where(stage => stage.Composed).Select(stage => stage.SourceFunction));
        Assert.Equal(new[] { "apply_crafting", "apply_live", "apply_points_event", "apply_party", "apply_instances",
            "apply_tent", "observe_shop_evidence", "observe_efficiency", "apply_actions", "apply_ark" },
            ServiceStateCoordinator.ObserverOrder.Where(stage => !stage.Composed).Select(stage => stage.SourceFunction));
        Assert.False(new ServiceStateSnapshot().IsCompleteState);
    }

    [Fact]
    public void OracleSourceHashesMatchRetainedPython()
    {
        var directory = RepositoryRoot();
        foreach (var (path, hash) in JsonNode.Parse(ServiceStatePythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), CanonicalSourceSha256(
                File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    public static IEnumerable<object[]> RetainedSourceHashes() =>
        JsonNode.Parse(ServiceStatePythonVectors.SourceSha256)!.AsObject()
            .Select(entry => new object[] { entry.Key, entry.Value!.GetValue<string>() });

    [Theory]
    [MemberData(nameof(RetainedSourceHashes))]
    public void RetainedSourceHashesAcceptLfAndCrlfButRejectActualContentChanges(string path, string expected)
    {
        // Exercise every real pinned source without editing repository files or decoding text.
        var lf = NormalizeCrlfPairs(File.ReadAllBytes(Path.Combine(RepositoryRoot().FullName, path)));
        var checkout = new List<byte>();
        foreach (var value in lf)
        {
            if (value == '\n') checkout.Add((byte)'\r');
            checkout.Add(value);
        }
        var crlf = checkout.ToArray();
        Assert.Equal(expected, CanonicalSourceSha256(lf));
        Assert.Equal(expected, CanonicalSourceSha256(crlf));
        Assert.NotEqual(expected, CanonicalSourceSha256([.. lf, (byte)' ']));
        Assert.NotEqual(expected, CanonicalSourceSha256([.. crlf, (byte)' ']));
        var changedLf = (byte[])lf.Clone();
        var changedCrlf = (byte[])crlf.Clone();
        changedLf[0] ^= 1;
        changedCrlf[0] ^= 1;
        Assert.NotEqual(expected, CanonicalSourceSha256(changedLf));
        Assert.NotEqual(expected, CanonicalSourceSha256(changedCrlf));
    }

    [Theory]
    [InlineData("", "")]
    [InlineData("\n", "\r\n")]
    [InlineData("中文 😀\nsecond\n", "中文 😀\r\nsecond\r\n")]
    [InlineData("one\ntwo\nthree", "one\r\ntwo\nthree")]
    [InlineData("bare\rcarriage\r", "bare\rcarriage\r")]
    [InlineData("\r\n", "\r\r\n")]
    public void SourceHashNormalizationOnlyReplacesCrlfPairs(string canonical, string checkout)
    {
        var expected = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))).ToLowerInvariant();
        Assert.Equal(expected, CanonicalSourceSha256(Encoding.UTF8.GetBytes(checkout)));
    }

    [Fact]
    public void SourceHashNormalizationPreservesNonNewlineBytesWithoutTextDecoding()
    {
        // Include a BOM, invalid UTF-8, NUL, whitespace, bare CR and a final bare CR.
        byte[] canonical = [0xef, 0xbb, 0xbf, 0, 0xff, 0xfe, 13, 42, 10, 32, 13];
        byte[] checkout = [0xef, 0xbb, 0xbf, 0, 0xff, 0xfe, 13, 42, 13, 10, 32, 13];
        var expected = Convert.ToHexString(SHA256.HashData(canonical)).ToLowerInvariant();
        Assert.Equal(expected, CanonicalSourceSha256(checkout));
        Assert.NotEqual(expected, CanonicalSourceSha256([0xef, 0xbb, 0xbf, 0, 0xff, 0xfe, 42, 10, 32, 13]));
        Assert.NotEqual(expected, CanonicalSourceSha256(canonical.AsSpan(3))); // BOM is content.
        Assert.NotEqual(expected, CanonicalSourceSha256([.. checkout, 0]));
    }

    private static DirectoryInfo RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "core", "state.py")))
            directory = directory.Parent;
        Assert.NotNull(directory);
        return directory;
    }

    private static string CanonicalSourceSha256(ReadOnlySpan<byte> source) =>
        Convert.ToHexString(SHA256.HashData(NormalizeCrlfPairs(source))).ToLowerInvariant();

    private static byte[] NormalizeCrlfPairs(ReadOnlySpan<byte> source)
    {
        // Match the generator's one-pass bytes.replace(b"\r\n", b"\n"). Preserve bare CR,
        // BOMs, invalid UTF-8 and all other bytes; no decoding, trimming or recursive replacement.
        var canonical = new byte[source.Length];
        var count = 0;
        for (var index = 0; index < source.Length; index++)
        {
            if (source[index] == '\r' && index + 1 < source.Length && source[index + 1] == '\n') continue;
            canonical[count++] = source[index];
        }
        return canonical[..count];
    }

    private static void Check(JsonNode expected, ServiceStateSnapshot state, string label)
    {
        var local = state.Local;
        Assert.Equal(local.Phase, local.World.Phase);
        Assert.Equal(local.PacketCount, local.World.PacketCount);
        Assert.Same(state.Player, local.World.Player);
        var localJson = new JsonObject
        {
            ["session"] = JsonSerializer.SerializeToNode(local.Session, Options),
            ["world"] = JsonSerializer.SerializeToNode(new
            {
                local.World.Phase, local.World.PacketCount, local.World.Player,
                Positions = local.World.Positions.Entries.ToArray(), local.World.Navigation,
                local.World.Location, local.World.LocalMovement, local.World.MovementCheck
            }, Options),
            ["battle"] = BattleEventParityTests.Project(local.Battle)
        };
        var inventory = InventoryStateParityTests.Project(state.Storage, state.Recovery);
        var expedition = state.Expedition;
        var projection = new JsonObject
        {
            ["local"] = localJson,
            ["daily_tasks"] = JsonSerializer.SerializeToNode(state.DailyTasks, Options),
            ["time_cube"] = JsonSerializer.SerializeToNode(state.TimeCube, Options),
            ["recovery"] = inventory["potion_storage"]!.DeepClone(),
            ["guild"] = state.Guild.Ready ? JsonSerializer.SerializeToNode(state.Guild, Options) : new JsonObject(),
            ["activities"] = JsonSerializer.SerializeToNode(state.Activities.Order().ToArray(), Options),
            ["storage"] = inventory["storage"]!.DeepClone(),
            ["server_stackable"] = inventory["server_stackable"]?.DeepClone(),
            ["expedition"] = JsonSerializer.SerializeToNode(new
            {
                expedition.Ready, expedition.OutpostReady, expedition.Roles, expedition.Teams,
                expedition.Quests, expedition.Level, expedition.Revision, expedition.Enabled,
                expedition.Pending, expedition.Uncertain, expedition.Status, Settings = new { }, expedition.Claimed
            }, Options)
        };
        Equal(expected, projection, label);
    }

    private static void Equal(JsonNode expected, JsonNode actual, string label)
    {
        var left = WithoutNulls(expected.DeepClone());
        var right = WithoutNulls(actual.DeepClone());
        Assert.True(JsonNode.DeepEquals(left, right), $"{label}: expected {left}; actual {right}");
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
