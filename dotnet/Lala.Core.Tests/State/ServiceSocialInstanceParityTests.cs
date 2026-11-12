using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Automation;
using Lala.Core.Inventory;
using Lala.Core.Instances;
using Lala.Core.Social;
using Lala.Core.World.Tent;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceSocialInstanceParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly ImmutableDictionary<ushort, bool> Rules = new Dictionary<ushort, bool>
        { [42] = true, [43] = false, [65535] = true }.ToImmutableDictionary();
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> NpcSkills =
        new Dictionary<uint, ImmutableArray<uint>> { [1] = [1001, 0, 1002, 1001, 0], [2] = [0, 1002, 65535] }.ToImmutableDictionary();

    [Theory]
    [MemberData(nameof(ServiceSocialInstancePythonVectors.Sequences), MemberType = typeof(ServiceSocialInstancePythonVectors))]
    public void ActualStateApplyMixedPartyInstancesTentAndAllPriorProjectionsMatch(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var initial = vector["initial"]!;
        var bootstrap = new ServiceStateCoordinator(new(local: new(session: new SessionEventSnapshot
            { PacketCount = BigInteger.Parse(vector["count"]!.GetValue<string>(), CultureInfo.InvariantCulture) })));
        if (vector["bootstrap"] is { } world)
            bootstrap.Apply(new Packet(3, 1, Convert.FromHexString(world.GetValue<string>())), new(bootstrap.Snapshot(), new(100)));
        var basis = bootstrap.Snapshot();
        var partyNode = initial["party"]!;
        var state = new ServiceStateCoordinator(new(local: basis.Local, dailyTasks: basis.DailyTasks, timeCube: basis.TimeCube,
            party: new PartyEventSnapshot
            {
                Teams = initial["team_order"]!.AsArray().Select(key => partyNode["teams"]![key!.GetValue<string>()].Deserialize<TeamSnapshot>(Options)!).ToImmutableArray(),
                Nearby = partyNode["nearby"].Deserialize<ImmutableDictionary<uint, NearbyPlayer>>(Options)!,
                Requests = partyNode["requests"].Deserialize<ImmutableDictionary<string, PartyRequest>>(Options)!,
                Outbound = partyNode["outbound"].Deserialize<ImmutableDictionary<string, PartyOutboundRequest>>(Options)!,
                Enabled = partyNode["enabled"]?.GetValue<bool>(), EnabledRequested = partyNode["enabled_requested"]?.GetValue<bool>(),
                Status = partyNode["status"]!.GetValue<string>()
            }, instances: new() { Main = Read(initial["instances"]!["main"]), Coop = Read(initial["instances"]!["coop"]) },
            tent: initial["tent"].Deserialize<TentReceiveSnapshot>(Options)));
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
                NpcSkills = catalogs ? NpcSkills : null
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
                var beforeLive = LiveInventoryParityTests.Project(result.Observation.BeforeLiveBag, CompanionReceiveSnapshot.Empty)["inventory"];
                LazyAssert.True(JsonNode.DeepEquals(step["before_live_inventory"], beforeLive), () => $"{name} before apply_live bag at step {number}");
            }
            Check(step["expected"]!, state.Snapshot(), at, $"{name} step {number++}");
            history.Add((state.Snapshot(), step["expected"]!, at));
        }
        foreach (var (snapshot, expected, at) in history) Check(expected, snapshot, at, name + " historical");
    }

    [Fact]
    public void OracleSourceHashesMatchCanonicalRetainedPythonBytes()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre", "core", "state.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        foreach (var (path, hash) in JsonNode.Parse(ServiceSocialInstancePythonVectors.Metadata())!["sources"]!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    [Fact]
    public void RealOracleRetainsAllObserversAndMixedCoverage()
    {
        var metadata = JsonNode.Parse(ServiceSocialInstancePythonVectors.Metadata())!;
        Assert.Equal(ServiceStateCoordinator.ObserverOrder.Select(stage => stage.SourceFunction),
            metadata["order"]!.AsArray().Select(value => value!.GetValue<string>()));
        Assert.True(metadata["scenarios"]!.GetValue<int>() >= 22);
        Assert.True(metadata["checkpoints"]!.GetValue<int>() >= 679);
        var covered = metadata["covered"]!.AsArray().Select(value => value!.GetValue<string>()).ToArray();
        foreach (var kind in new[] { "world_player", "role_list_available", "position_snapshot", "team_invite", "team_join",
                     "instance_room_list", "instance_reward_receipt", "instance_phase", "instance_members", "instance_coop_match", "tent_scene_list", "tent_error",
                     "team_answer", "team_flag", "social_rejected", "nearby_leave", "navigation_geometry_change", "battle_start", "fight_exit", "winner", "event_rejected" })
            Assert.Contains(kind, covered);
    }

    internal static void Check(JsonNode expected, ServiceStateSnapshot state, double at, string label)
    {
        ServiceStateParityTests.Check(expected["services"]!, state, label);
        var live = LiveInventoryParityTests.Project(state.Bag, state.Companions);
        LazyAssert.True(JsonNode.DeepEquals(expected["live"], live), () => $"{label}: expected live {expected["live"]}; actual {live}");
        var craft = CraftingStateParityTests.Project(state.Crafting, at);
        LazyAssert.True(JsonNode.DeepEquals(expected["crafting"], craft), () => $"{label}: expected crafting {expected["crafting"]}; actual {craft}");
        Equal(expected["party"], ProjectParty(state.Party), label + " party");
        Equal(expected["own_team"], JsonSerializer.SerializeToNode(state.Party.OwnTeam(state.Player?.RoleId), Options), label + " own team");
        Assert.Equal(expected["team_order"]!.AsArray().Select(value => value!.GetValue<string>()),
            state.Party.Teams.Select(team => team.LeaderId.ToString(CultureInfo.InvariantCulture)));
        Equal(expected["instances"], new JsonObject { ["main"] = Write(state.Instances.Main), ["coop"] = Write(state.Instances.Coop) }, label + " instances");
        Equal(expected["tent"], ProjectTent(state.Tent), label + " tent");
        Assert.Same(state.Storage.ServerStackable, state.Bag.ServerStackable);
        foreach (var (slot, attributes) in state.Companions.Attributes)
        {
            var shared = state.Local.Session.Attributes[$"follow:{slot}"];
            Assert.Equal(attributes.Length, shared.Count);
            foreach (var value in attributes) Assert.Equal(value.Value, shared[$"{value.Kind}:{value.Parameter}"]);
        }
        Assert.Equal(state.Companions.Attributes.Count, state.Local.Session.Attributes.Keys.Count(key => key.StartsWith("follow:", StringComparison.Ordinal)));
    }
    private static void Equal(JsonNode? expected, JsonNode? actual, string label) =>
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{label}: expected {expected}; actual {actual}");

    private static JsonObject ProjectParty(PartyEventSnapshot state)
    {
        var teams = new JsonObject();
        foreach (var team in state.Teams)
            teams.Add(team.LeaderId.ToString(CultureInfo.InvariantCulture), JsonSerializer.SerializeToNode(team, Options));
        var result = new JsonObject
        {
            ["teams"] = teams, ["nearby"] = JsonSerializer.SerializeToNode(state.Nearby, Options),
            ["requests"] = JsonSerializer.SerializeToNode(state.Requests, Options),
            ["outbound"] = JsonSerializer.SerializeToNode(state.Outbound, Options),
            ["enabled"] = state.Enabled, ["status"] = state.Status
        };
        if (state.EnabledRequested is { } requested) result["enabled_requested"] = requested;
        return result;
    }

    private static JsonNode ProjectTent(TentReceiveSnapshot state)
    {
        var result = JsonSerializer.SerializeToNode(state, Options)!;
        foreach (var field in new[] { "pending", "entry_context" })
        {
            if (result[field] is not JsonObject action) continue;
            foreach (var key in new[] { "due", "furniture_received", "source_scene" })
                if (action[key] is null && !(field == "entry_context" && key == "source_scene")) action.Remove(key);
        }
        return result;
    }

    private static StateValue Read(JsonNode? node)
    {
        if (node is null) return StateValue.Null;
        if (node is JsonObject map)
        {
            if (map.TryGetPropertyValue("$tuple", out var tuple)) return StateValue.Tuple(tuple!.AsArray().Select(Read));
            return StateValue.Map(map.Select(e => KeyValuePair.Create(e.Key, Read(e.Value))));
        }
        if (node is JsonArray list) return StateValue.List(list.Select(Read));
        var element = JsonSerializer.SerializeToElement(node);
        return element.ValueKind switch
        {
            JsonValueKind.String => StateValue.Scalar(element.GetString()),
            JsonValueKind.True or JsonValueKind.False => StateValue.Scalar(element.GetBoolean()),
            JsonValueKind.Number => StateValue.Scalar(element.GetRawText().Contains('.') ? (object)element.GetDouble() : BigInteger.Parse(element.GetRawText(), CultureInfo.InvariantCulture)),
            _ => throw new InvalidOperationException()
        };
    }
    private static JsonNode? Write(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => new JsonObject(value.MapValue.Select(e => KeyValuePair.Create(e.Key, Write(e.Value)))),
        StateValueKind.List => new JsonArray(value.SequenceValue.Select(Write).ToArray()),
        StateValueKind.Tuple => new JsonObject { ["$tuple"] = new JsonArray(value.SequenceValue.Select(Write).ToArray()) },
        _ => value.ScalarValue is BigInteger big ? JsonNode.Parse(big.ToString(CultureInfo.InvariantCulture)) : JsonSerializer.SerializeToNode(value.ScalarValue)
    };
}
