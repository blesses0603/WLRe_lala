using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Lala.Core.Inventory;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class InventoryPlanningParityTests
{
    private static readonly InventoryPlanningContext Context = new()
    {
        ItemNames = ImmutableDictionary<BigInteger, string>.Empty.Add(42, "測試材料").Add(43, "").Add(65535, "邊界物品")
    };

    [Theory]
    [MemberData(nameof(InventoryPlanningPythonVectors.Sequences), MemberType = typeof(InventoryPlanningPythonVectors))]
    public void EveryPureCandidateAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var steps = JsonNode.Parse(json)!.AsArray();
        var current = LiveInventoryParityTests.ReadBag(steps[0]!["expected"]!["inventory"]!);
        var history = new List<(BagReceiveSnapshot State, JsonNode Expected)>();
        var candidates = new List<(InventoryReservationCandidate Candidate, JsonNode Before, JsonNode? After)>();
        var allocationHistory = new List<(InventoryAllocationCandidate Candidate, JsonNode Expected)>();
        var stepIndex = 0;
        foreach (var step in steps)
        {
            if (step!["operation"] is { } operation)
            {
                var before = current;
                var beforeJson = Project(before);
                InventoryPlanningError? error;
                if (operation["kind"]!.GetValue<string>() == "allocate")
                {
                    var result = InventoryPlanning.Allocate(current, Big(operation["item_id"]!), Big(operation["count"]!), Context);
                    error = result.Error;
                    if (result.Success)
                    {
                        Equal(step["rows"], Rows(result), $"{name}: allocation rows");
                        allocationHistory.Add((result, step["rows"]!));
                    }
                    else Assert.Empty(result.Rows);
                    Assert.Same(before, current);
                }
                else
                {
                    var result = InventoryPlanning.PlanReservation(current,
                        [.. operation["allocations"]!.AsArray().Select(Value)],
                        operation["owner"]!.GetValue<string>(), operation["exclusive"]!.GetValue<bool>());
                    error = result.Error;
                    Assert.Same(before, result.ObservedSnapshot);
                    Equal(beforeJson, Project(result.ObservedSnapshot), name + " observed state");
                    if (result.Success)
                    {
                        Assert.NotNull(result.ProposedSnapshot);
                        current = result.ProposedSnapshot;
                    }
                    else
                    {
                        Assert.Null(result.ProposedSnapshot);
                        Assert.Same(before, current);
                    }
                    candidates.Add((result, beforeJson, result.Success ? step["expected"] : null));
                }
                Equal(step["error"], Error(error), name + " error precedence");
                Equal(beforeJson, Project(before), name + " input is immutable");
            }
            Equal(step!["expected"], Project(current), $"{name}: step {stepIndex++}");
            history.Add((current, step["expected"]!));
        }
        foreach (var (state, expected) in history) Equal(expected, Project(state), name + " historical state");
        foreach (var (candidate, before, after) in candidates)
        {
            Equal(before, Project(candidate.ObservedSnapshot), name + " historical candidate baseline");
            if (after is not null) Equal(after, Project(candidate.ProposedSnapshot!), name + " historical candidate proposal");
        }
        foreach (var (candidate, expected) in allocationHistory) Equal(expected, Rows(candidate), name + " historical allocation");
    }

    [Fact]
    public void OracleHashesMatchRawSourceBytesAndOnlyNormalizeCrlfPairs()
    {
        var directory = Root();
        foreach (var (path, hash) in JsonNode.Parse(InventoryPlanningPythonVectors.SourceSha256)!.AsObject())
        {
            var bytes = File.ReadAllBytes(Path.Combine(directory.FullName, path));
            var lf = Canonical(bytes);
            var crlf = new List<byte>();
            foreach (var value in lf)
            {
                if (value == 10) crlf.Add(13);
                crlf.Add(value);
            }
            var expected = hash!.GetValue<string>();
            Assert.Equal(expected, Hash(bytes));
            Assert.Equal(expected, Hash(lf));
            Assert.Equal(expected, Hash([.. crlf]));
            Assert.NotEqual(expected, Hash([.. bytes, (byte)' ']));
            var changed = (byte[])lf.Clone(); changed[0] ^= 1;
            Assert.NotEqual(expected, Hash(changed));
        }
        byte[] arbitrary = [0xff, 0xfe, 13, 0, 13, 10, 13, 32, 0xef, 0xbb, 0xbf];
        Assert.Equal(new byte[] { 0xff, 0xfe, 13, 0, 10, 13, 32, 0xef, 0xbb, 0xbf }, Canonical(arbitrary));
        Assert.NotEqual(Hash([0xff]), Hash([0xfe]));
        Assert.NotEqual(Hash([13]), Hash([10]));
        Assert.NotEqual(Hash([0xef, 0xbb, 0xbf, 1]), Hash([1]));
    }

    [Theory]
    [InlineData("\n")]
    [InlineData("\r\n")]
    public void GeneratedPublicationPartsAreBoundedGzipByteFixtures(string newline)
    {
        var directory = Path.Combine(Root().FullName, "dotnet", "Lala.Core.Tests", "Inventory");
        var files = Directory.GetFiles(directory, "InventoryPlanningPythonVectors*.cs");
        Assert.True(files.Length >= 2);
        foreach (var path in files)
        {
            Assert.InRange(new FileInfo(path).Length, 1, 500_000);
            var text = File.ReadAllText(path);
            var checkout = text.Replace("\r\n", "\n", StringComparison.Ordinal)
                .Replace("\n", newline, StringComparison.Ordinal);
            Assert.InRange(Encoding.UTF8.GetByteCount(checkout), 1, 500_000);
            Assert.DoesNotContain("FromBase64String", text, StringComparison.Ordinal);
            if (path.Contains(".Part", StringComparison.Ordinal))
                Assert.Contains("GzipJson.Decode([", text, StringComparison.Ordinal);
        }
    }

    [Fact]
    public void RepartitioningPreservesEveryCaseSnapshotAndGzipByte()
    {
        // Pin the ordered streams and API payloads from the original 153-case oracle.
        var directory = Path.Combine(Root().FullName, "dotnet", "Lala.Core.Tests", "Inventory");
        var compressed = Directory.GetFiles(directory, "InventoryPlanningPythonVectors.Part*.cs")
            .Order(StringComparer.Ordinal)
            .SelectMany(path => Regex.Matches(File.ReadAllText(path), @"0x([0-9a-f]{2})")
                .Select(match => Convert.ToByte(match.Groups[1].Value, 16))).ToArray();
        Assert.Equal("c69bb16f02ac09bb5b73f69df6a77edf28af7e7a19fbb9e11675b59805e09880",
            Convert.ToHexString(SHA256.HashData(compressed)).ToLowerInvariant());

        var cases = InventoryPlanningPythonVectors.Sequences().ToArray();
        Assert.Equal(153, cases.Length);
        Assert.Equal(153, cases.Select(row => (string)row[0]).Distinct(StringComparer.Ordinal).Count());
        Assert.Equal(2032, cases.Sum(row => JsonNode.Parse((string)row[1])!.AsArray().Count));
        var payload = Encoding.UTF8.GetBytes(string.Concat(cases.Select(row => $"{row[0]}\n{row[1]}\n")));
        Assert.Equal("85cf25db8d9535f1b1eeab0abaacf7ed4335ec9d2d67478ac93e302af78a4898",
            Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant());
    }

    internal static JsonObject Project(BagReceiveSnapshot state)
    {
        var full = LiveInventoryParityTests.Project(state, CompanionReceiveSnapshot.Empty);
        return new JsonObject(new[] { "inventory", "item_order", "hold_order", "available" }
            .Select(key => KeyValuePair.Create<string, JsonNode?>(key, full[key]!.DeepClone())));
    }

    private static JsonNode Rows(InventoryAllocationCandidate candidate) => new JsonArray([.. candidate.Rows.Select(row =>
        (JsonNode)new JsonObject { ["index"] = row.Index, ["count"] = Number(row.Count), ["item_id"] = Number(row.ItemId) })]);
    private static JsonNode? Error(InventoryPlanningError? error) => error is null ? null :
        new JsonObject { ["type"] = error.Type, ["message"] = error.Message };
    private static StateValue Value(JsonNode? node) => node switch
    {
        null => StateValue.Null,
        JsonObject map => StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, Value(pair.Value)))),
        JsonArray list => StateValue.List(list.Select(Value)),
        _ => node.GetValueKind() switch
        {
            JsonValueKind.String => StateValue.Scalar(node.GetValue<string>()),
            JsonValueKind.True => StateValue.Scalar(true), JsonValueKind.False => StateValue.Scalar(false),
            _ when node.ToJsonString().IndexOfAny(['.', 'e', 'E']) >= 0 => StateValue.Scalar(node.GetValue<double>()),
            _ => StateValue.Scalar(Big(node))
        }
    };
    private static BigInteger Big(JsonNode node) => BigInteger.Parse(node.ToJsonString(), CultureInfo.InvariantCulture);
    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static void Equal(JsonNode? expected, JsonNode? actual, string label) =>
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{label}: expected {expected}; actual {actual}");
    private static DirectoryInfo Root()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "services", "items", "inventory.py")))
            directory = directory.Parent;
        Assert.NotNull(directory);
        return directory;
    }
    private static byte[] Canonical(byte[] source)
    {
        var result = new List<byte>();
        for (var i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 >= source.Length || source[i + 1] != 10) result.Add(source[i]);
        return [.. result];
    }
    private static string Hash(byte[] source) => Convert.ToHexString(SHA256.HashData(Canonical(source))).ToLowerInvariant();
}
