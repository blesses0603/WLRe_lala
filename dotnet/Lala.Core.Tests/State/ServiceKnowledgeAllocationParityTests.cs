using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Automation;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Instances;
using Lala.Core.Social;
using Lala.Core.World.Tent;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Inventory;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceKnowledgeAllocationParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly ImmutableDictionary<ushort, bool> Rules = new Dictionary<ushort, bool>
        { [42] = true, [43] = false, [65535] = true }.ToImmutableDictionary();
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> NpcSkills =
        new Dictionary<uint, ImmutableArray<uint>> { [1] = [1001, 0, 1002, 1001, 0], [2] = [0, 1002, 65535] }.ToImmutableDictionary();

    [Theory]
    [MemberData(nameof(ServiceKnowledgeAllocationPythonVectors.Sequences), MemberType = typeof(ServiceKnowledgeAllocationPythonVectors))]
    public void ActualStateApplyKnowledgeAllocationAndAllPriorProjectionsMatch(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var initial = vector["initial"]!;
        var bootstrap = new ServiceStateCoordinator(new(local: new(session: new SessionEventSnapshot
            { PacketCount = BigInteger.Parse(vector["count"]!.GetValue<string>(), CultureInfo.InvariantCulture) })));
        if (vector["bootstrap"] is { } world)
            bootstrap.Apply(new Packet(3, 1, Convert.FromHexString(world.GetValue<string>())), new(bootstrap.Snapshot(), new(100)));
        var basis = bootstrap.Snapshot();
        var state = new ServiceStateCoordinator(new(local: basis.Local, dailyTasks: basis.DailyTasks, timeCube: basis.TimeCube, tent: basis.Tent,
            playerKnowledge: new() { Stats = initial["knowledge"]!["player"]!["stats"].Deserialize<ImmutableDictionary<string, long>>()! },
            attributeAllocation: ReadAllocation(initial["allocation"]!)));
        var history = new List<(ServiceStateSnapshot State, JsonNode Expected, double At)> { (state.Snapshot(), initial, 100) };
        Check(initial, state.Snapshot(), 100, name + " initial");
        var number = 0;
        foreach (var step in vector["steps"]!.AsArray())
        {
            var before = state.Snapshot();
            var at = step!["at"]!.GetValue<double>();
            var catalogs = step["catalogs"]!.GetValue<bool>();
            var context = new ServiceObservationContext(before, new(at)
            {
                WorldCatalog = step["stages"] is JsonArray stages ? new(stages.Select(v => v!.GetValue<ushort>()).ToImmutableHashSet()) : null,
                DeclaredMainCatalogMapIds = step["declared"]!.AsArray().Select(v => v!.GetValue<ushort>()).ToImmutableHashSet(),
                CraftingSchedules = CraftingScheduleContext.Legacy,
                ItemStackRules = catalogs ? Rules : null,
                NpcSkills = catalogs ? NpcSkills : null,
                KnowledgeCatalog = Catalogs[step["knowledge_catalog"]!.GetValue<int>()]
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
                Assert.Equal(step["before"]!["phase"]!.GetValue<string>(), result.Observation.BeforeLocal.Phase);
                Assert.Equal(step["after"]!["phase"]!.GetValue<string>(), result.Observation.AfterLocal.Phase);
                Assert.Equal(step["before"]!["player"]?["role_id"]?.GetValue<uint>(), result.Observation.BeforeLocal.Player?.RoleId);
                Assert.Equal(step["after"]!["player"]?["role_id"]?.GetValue<uint>(), result.Observation.AfterLocal.Player?.RoleId);
                Equal(step["before"]!["player"], JsonSerializer.SerializeToNode(result.Observation.BeforeLocal.Player, Options), name + " before-local player");
                Equal(step["after"]!["player"], JsonSerializer.SerializeToNode(result.Observation.AfterLocal.Player, Options), name + " after-local player");
                Assert.Same(before.Player, result.Observation.BeforeLocal.Player);
                Assert.Same(result.Player, result.Observation.AfterLocal.Player);
                Assert.Equal(before.PacketCount + 1, result.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.BeforeLocal.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.AfterLocal.PacketCount);
                Assert.Same(before.Bag, result.Observation.BeforeObserversBag);
                Assert.Same(result.Bag, result.Observation.AfterLiveBag);
                Assert.Same(context.Inputs, result.Observation.Inputs);
                if (step["kind"]!.GetValue<string>() == "attribute_set")
                    Equal(step["attributes_at_allocation"], JsonSerializer.SerializeToNode(before.Local.Session.Attributes, Options),
                        name + " prior local attributes at allocation");
                Assert.Same(result.PlayerKnowledge, result.Observation.AfterLivePlayerKnowledge);
                Equal(step["allocation_stats"], Stats(result.Observation.AllocationContext.PlayerStats), name + " allocation context");
                Assert.Equal(result.PlayerKnowledge.Stats.Count, result.Observation.AllocationContext.PlayerStats.Count);
                foreach (var (key, value) in result.PlayerKnowledge.Stats)
                    Assert.Equal(new BigInteger(value), result.Observation.AllocationContext.PlayerStats[key]);
                var beforeLive = LiveInventoryParityTests.Project(result.Observation.BeforeLiveBag, CompanionReceiveSnapshot.Empty)["inventory"];
                Assert.True(JsonNode.DeepEquals(step["before_live_inventory"], beforeLive), $"{name} before apply_live bag at step {number}");
            }
            Check(step["expected"]!, state.Snapshot(), at, $"{name} step {number++}");
            history.Add((state.Snapshot(), step["expected"]!, at));
        }
        foreach (var (snapshot, expected, at) in history) Check(expected, snapshot, at, name + " historical");
    }

    private static readonly CombatKnowledgeCatalog[] Catalogs =
    [
        new(),
        new() { SkillKeys = new Dictionary<ushort, uint> { [1] = 1001, [2] = 1002, [3] = 1001, [4] = 0 }.ToImmutableDictionary(),
            ItemFitTypes = new Dictionary<ushort, int> { [42] = 3, [43] = 11, [44] = 0, [45] = 9 }.ToImmutableDictionary() },
        new() { SkillKeys = new Dictionary<ushort, uint> { [1] = 2001, [2] = 1002, [3] = 1001 }.ToImmutableDictionary(),
            ItemFitTypes = new Dictionary<ushort, int> { [42] = 3, [43] = 11, [44] = 0, [45] = 9, [99] = 3, [100] = 2 }.ToImmutableDictionary() },
        new() { ItemFitTypes = new Dictionary<ushort, int> { [99] = 3, [100] = 2 }.ToImmutableDictionary() }
    ];

    [Fact]
    public void OracleSourceHashesMatchByteOnlyCrLfNormalization()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "core", "state.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(ServiceKnowledgeAllocationPythonVectors.Metadata())!["sources"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    [Fact]
    public void OracleRunsAllObserversAndRetainsMixedCoverage()
    {
        var metadata = JsonNode.Parse(ServiceKnowledgeAllocationPythonVectors.Metadata())!;
        Assert.Equal(ServiceStateCoordinator.ObserverOrder.Select(stage => stage.SourceFunction),
            metadata["order"]!.AsArray().Select(value => value!.GetValue<string>()));
        Assert.True(metadata["scenarios"]!.GetValue<int>() >= 25);
        Assert.True(metadata["checkpoints"]!.GetValue<int>() >= 900);
        var covered = metadata["covered"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
        foreach (var kind in new[] { "player_combat_data", "attribute_set", "attribute_allocation_success", "star_info",
            "player_equip_data", "equip_damage", "equip_broken", "battle_equip", "companion_snapshot", "companion_delete",
            "battle_start", "battle_units", "battle_attribute_set", "bag_snapshot", "world_player", "role_list_available",
            "team_invite", "instance_phase", "tent_added", "craft_snapshot" })
            Assert.Contains(kind, covered);
    }

    private static void Check(JsonNode expected, ServiceStateSnapshot state, double at, string label)
    {
        ServiceSocialInstanceParityTests.Check(expected, state, at, label);
        Equal(expected["knowledge"], CombatKnowledgeParityTests.Project(state.PlayerKnowledge, state.Companions,
            state.Local.Battle, state.Local.Session), label + " knowledge");
        Equal(expected["allocation"], ProjectAllocation(state.AttributeAllocation), label + " allocation");
    }

    private static AttributeAllocationSnapshot ReadAllocation(JsonNode node) => new()
    {
        Pending = node["pending"]!.GetValue<bool>(), Acknowledged = node["acknowledged"]!.GetValue<bool>(),
        Uncertain = node["uncertain"]!.GetValue<bool>(), SentAt = node["sent_at"]?.GetValue<double>(),
        Status = node["status"]!.GetValue<string>(), Expected = node["expected"]?.AsObject().ToImmutableDictionary(
            pair => pair.Key, pair => BigInteger.Parse(pair.Value!.ToJsonString(), CultureInfo.InvariantCulture))
    };
    private static JsonNode ProjectAllocation(AttributeAllocationSnapshot value) => new JsonObject
    {
        ["pending"] = value.Pending, ["acknowledged"] = value.Acknowledged, ["uncertain"] = value.Uncertain,
        ["sent_at"] = value.SentAt, ["status"] = value.Status, ["expected"] = value.Expected is { } expected ? Stats(expected) : null
    };
    private static JsonNode Stats(ImmutableDictionary<string, BigInteger> values) => new JsonObject(values.Select(pair =>
        KeyValuePair.Create(pair.Key, JsonNode.Parse(pair.Value.ToString(CultureInfo.InvariantCulture)))));
    private static void Equal(JsonNode? expected, JsonNode? actual, string label) =>
        Assert.True(JsonNode.DeepEquals(expected, actual), $"{label}: expected {expected}; actual {actual}");
}
