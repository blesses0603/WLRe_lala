using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World.Shop;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.World.Shop;

public sealed class NpcShopEvidenceParityTests
{
    [Theory]
    [MemberData(nameof(NpcShopEvidencePythonVectors.Sequences), MemberType = typeof(NpcShopEvidencePythonVectors))]
    public void EveryObservationAndRetainedHistoryMatchesPython(string name, string json)
    {
        var state = NpcShopEvidenceSnapshot.Empty;
        var history = new List<(NpcShopEvidenceSnapshot State, JsonNode Expected)>();
        var buy = new NpcShopOfflineOrder("buy", 10, 42, 2, -1500);
        var sell = new NpcShopOfflineOrder("sell", 10, 42, 2, 1500, 7);
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            if (step!["event"] is { } value)
            {
                var inventory = step["inventory"]!;
                var gold = step["gold"]!;
                state = NpcShopEvidence.Observe(state, Event(value), new(Big(step["packet"]!),
                    new BagReceiveSnapshot { Ready = inventory["ready"]!.GetValue<bool>(), Reliable = inventory["reliable"]!.GetValue<bool>(), Revision = Big(inventory["revision"]!) },
                    new SessionGoldSnapshot { Ready = gold["ready"]!.GetValue<bool>(), Reliable = gold["reliable"]!.GetValue<bool>(), Revision = Big(gold["revision"]!) }));
            }
            var expected = step!["expected"]!;
            Assert.True(JsonNode.DeepEquals(expected, Project(state.ToOfflineData())), $"{name}, step {index++}: {Project(state.ToOfflineData())} != {expected}");
            AssertOutcome(step["buy"]!, () => NpcShopEvidence.ClassifyOffline(state, buy));
            AssertOutcome(step["sell"]!, () => NpcShopEvidence.ClassifyOffline(state, sell));
            Assert.InRange(state.Events.Length, 0, NpcShopEvidence.MaxEvents);
            history.Add((state, expected));
        }
        foreach (var (old, expected) in history)
            LazyAssert.True(JsonNode.DeepEquals(expected, Project(old.ToOfflineData())), () => name + " immutable history");
    }

    [Theory]
    [MemberData(nameof(NpcShopEvidencePythonVectors.Classifications), MemberType = typeof(NpcShopEvidencePythonVectors))]
    public void OfflineClassificationAndMalformedBoundariesMatchPython(string name, string json)
    {
        _ = name;
        var root = JsonNode.Parse(json)!;
        var evidence = Data(root["evidence"]);
        var order = Data(root["order"]);
        AssertOutcome(root, () => NpcShopEvidence.ClassifyOfflineData(evidence, order));
    }

    [Fact]
    public void OracleSourceHashNormalizesOnlyCrLfBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/world/npc_shop_evidence.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, expected) in JsonNode.Parse(NpcShopEvidencePythonVectors.SourceSha256)!.AsObject())
        {
            var source = File.ReadAllBytes(Path.Combine(directory.FullName, path));
            using var normalized = new MemoryStream();
            for (var i = 0; i < source.Length; i++)
                if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
            Assert.Equal(expected!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
        }
    }

    private static void AssertOutcome(JsonNode expected, Func<NpcShopOfflineClassification> action)
    {
        if (expected["error_type"] is { } error)
        {
            switch (error.GetValue<string>())
            {
                case "ProtocolError": Assert.Equal(expected["error"]!.GetValue<string>(), Assert.Throws<ProtocolException>(action).Message); break;
                case "AttributeError": Assert.Throws<InvalidOperationException>(action); break;
                case "KeyError": Assert.Throws<KeyNotFoundException>(action); break;
                default: Assert.Fail("Unhandled source error: " + error); break;
            }
        }
        else
        {
            var actual = action();
            Assert.Equal(expected["expected"]!["status"]!.GetValue<string>(), actual.Status);
            Assert.Equal(expected["expected"]!["reason"]!.GetValue<string>(), actual.Reason);
            Assert.DoesNotContain(actual.Status, new[] { "settled", "authorized", "confirmed", "success" });
        }
    }

    internal static BigInteger Big(JsonNode node) => BigInteger.Parse(node.ToJsonString(), CultureInfo.InvariantCulture);
    internal static StateValue Data(JsonNode? node)
    {
        if (node is null) return StateValue.Null;
        if (node is JsonObject map)
        {
            if (map["$tuple"] is JsonArray tuple) return StateValue.Tuple(tuple.Select(Data));
            if (map["$float"] is { } special) return StateValue.Scalar(special.GetValue<string>() switch
            { "nan" => double.NaN, "inf" => double.PositiveInfinity, "-inf" => double.NegativeInfinity, _ => throw new InvalidOperationException() });
            return StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, Data(pair.Value))));
        }
        if (node is JsonArray array) return StateValue.List(array.Select(Data));
        var value = node.AsValue();
        if (value.TryGetValue<bool>(out var boolean)) return StateValue.Scalar(boolean);
        if (value.TryGetValue<string>(out var text)) return StateValue.Scalar(text);
        var raw = node.ToJsonString();
        return raw.IndexOfAny(['.', 'e', 'E']) >= 0 ? StateValue.Scalar(double.Parse(raw, CultureInfo.InvariantCulture)) : StateValue.Scalar(Big(node));
    }
    internal static JsonNode? Project(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => new JsonObject(value.MapValue.Select(pair => KeyValuePair.Create(pair.Key, Project(pair.Value)))),
        StateValueKind.List or StateValueKind.Tuple => new JsonArray([.. value.SequenceValue.Select(Project)]),
        _ => value.ScalarValue is BigInteger big ? JsonNode.Parse(big.ToString(CultureInfo.InvariantCulture)) : JsonSerializer.SerializeToNode(value.ScalarValue)
    };
    private static ServerEvent Event(JsonNode node)
    {
        byte Byte(string key) => node[key]!.GetValue<byte>();
        LiveDataEvent? live = node["type"]!.GetValue<string>() switch
        {
            "bag_snapshot" => new BagSnapshotEvent(Byte("capacity"), []),
            "bag_add" => new BagAddEvent(Item(node["item"]!), node["source"]?.GetValue<ushort>() ?? 0),
            "bag_delete" => new BagDeleteEvent(Byte("index"), Byte("count"), 0),
            "bag_sell" => new BagSellEvent(node["gold"]!.GetValue<uint>(), Byte("index"), Byte("count")),
            "shop_purchase_result" => new ShopPurchaseResultEvent(Byte("result")),
            "sale_notice" => new SaleNoticeEvent(Byte("result")),
            _ => null
        };
        if (live is not null) return new ServerLiveDataEvent(live);
        return node["type"]!.GetValue<string>() switch
        {
            "gold_snapshot" => new GoldSnapshotEvent(node["amount"]!.GetValue<uint>()),
            "gold_delta" => new GoldDeltaEvent(1, node["delta"]!.GetValue<long>(), false),
            "gold_limit" => new GoldLimitEvent(),
            "role_list_available" => new ServerLayoutEvent(new RoleListAvailableEvent([])),
            "login_result" => new LoginResultEvent(Byte("result"), 0),
            "event_end" => new EventEndEvent(),
            _ => new UnimplementedServerEvent(255, 255, 0)
        };
    }
    private static ItemSave Item(JsonNode item) => new(item["index"]?.GetValue<byte>(), item["item_id"]!.GetValue<ushort>(),
        item["count"]!.GetValue<byte>(), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, [], false, 0, 0, null);
}
