using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Automation;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServiceInventoryParityTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly ImmutableDictionary<ushort, bool> Rules = new Dictionary<ushort, bool>
        { [42] = true, [43] = false, [65535] = true }.ToImmutableDictionary();
    private static readonly ImmutableDictionary<uint, ImmutableArray<uint>> NpcSkills =
        new Dictionary<uint, ImmutableArray<uint>> { [1] = [1001, 0, 1002, 1001, 0], [2] = [0, 1002, 65535] }.ToImmutableDictionary();

    [Theory]
    [MemberData(nameof(ServiceInventoryPythonVectors.Sequences), MemberType = typeof(ServiceInventoryPythonVectors))]
    public void ActualStateApplyMixedInventoryObservationsAndImmutableHistoryMatch(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var initial = vector["initial"]!;
        var state = new ServiceStateCoordinator(new(local: new(session: new SessionEventSnapshot
            { PacketCount = BigInteger.Parse(vector["count"]!.GetValue<string>(), CultureInfo.InvariantCulture) }),
            timeCube: initial["services"]!["time_cube"].Deserialize<TimeCubeState>(Options),
            bag: LiveInventoryParityTests.ReadBag(initial["live"]!["inventory"]!),
            crafting: CraftingStateParityTests.Read(initial["crafting"]!)));
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
                WorldCatalog = step["known"]!.GetValue<bool>() ? new([101]) : null,
                CraftingSchedules = step["schedules"]!.GetValue<string>() == "legacy" ? CraftingScheduleContext.Legacy :
                    CraftingScheduleContext.FromRuntimeRows([new(1, 500), new(42, 65535), new(65535, 500)]),
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
                Assert.Same(before.Player, result.Observation.BeforeLocal.Player);
                Assert.Same(result.Player, result.Observation.AfterLocal.Player);
                Assert.Equal(before.PacketCount + 1, result.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.BeforeLocal.PacketCount);
                Assert.Equal(result.PacketCount, result.Observation.AfterLocal.PacketCount);
                Assert.Same(before.Bag, result.Observation.BeforeObserversBag);
                Assert.Same(result.Bag, result.Observation.AfterLiveBag);
                Assert.Same(context.Inputs, result.Observation.Inputs);
                var beforeLive = LiveInventoryParityTests.Project(result.Observation.BeforeLiveBag, CompanionReceiveSnapshot.Empty)["inventory"];
                Assert.True(JsonNode.DeepEquals(step["before_live_inventory"], beforeLive), $"{name} before apply_live bag at step {number}");
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
        foreach (var (path, hash) in JsonNode.Parse(ServiceInventoryPythonVectors.SourceSha256)!.AsObject())
            Assert.Equal(hash!.GetValue<string>(), LiveInventoryParityTests.CanonicalSourceHash(File.ReadAllBytes(Path.Combine(directory.FullName, path))));
    }

    private static void Check(JsonNode expected, ServiceStateSnapshot state, double at, string label)
    {
        ServiceStateParityTests.Check(expected["services"]!, state, label);
        var live = LiveInventoryParityTests.Project(state.Bag, state.Companions);
        LazyAssert.True(JsonNode.DeepEquals(expected["live"], live), () => $"{label}: expected live {expected["live"]}; actual {live}");
        var craft = CraftingStateParityTests.Project(state.Crafting, at);
        LazyAssert.True(JsonNode.DeepEquals(expected["crafting"], craft), () => $"{label}: expected crafting {expected["crafting"]}; actual {craft}");
        Assert.Same(state.Storage.ServerStackable, state.Bag.ServerStackable);
        foreach (var (slot, attributes) in state.Companions.Attributes)
        {
            var shared = state.Local.Session.Attributes[$"follow:{slot}"];
            Assert.Equal(attributes.Length, shared.Count);
            foreach (var value in attributes) Assert.Equal(value.Value, shared[$"{value.Kind}:{value.Parameter}"]);
        }
        Assert.Equal(state.Companions.Attributes.Count, state.Local.Session.Attributes.Keys.Count(key => key.StartsWith("follow:", StringComparison.Ordinal)));
    }
}
