using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.World;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.World;

public sealed class FurnitureGeometryIntegrationTests
{
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    [Theory]
    [MemberData(nameof(FurnitureGeometryPythonVectors.Sequences), MemberType = typeof(FurnitureGeometryPythonVectors))]
    public void DetailedFurnitureAndFallbackGeometryReachBothReducerAndCoordinator(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var count = BigInteger.Parse(vector["initial_count"]!.ToJsonString(), CultureInfo.InvariantCulture);
        var world = new WorldEventSnapshot { PacketCount = count };
        var catalogJson = vector["catalog"];
        WorldSceneCatalog? catalog = catalogJson is null ? null : new(
            catalogJson["stage_ids"]!.AsArray().Select(value => value!.GetValue<ushort>()).ToImmutableHashSet(),
            catalogJson["aliases"]?.AsArray().Select(value => value!.GetValue<ushort>()).ToImmutableHashSet());
        var coordinator = new LocalStateCoordinator(new(world: world), catalog);
        var retained = new List<(WorldEventSnapshot World, LocalStateSnapshot Local, JsonNode Expected)>();
        foreach (var step in vector["steps"]!.AsArray())
        {
            var packet = new Packet(step!["main"]!.GetValue<byte>(), step["sub"]!.GetValue<byte>(),
                Convert.FromHexString(step["hex"]!.GetValue<string>()));
            var observation = ServerProtocol.Decode(packet);
            Assert.Equal(step["kind"]!.GetValue<string>(), observation.Type);
            if (packet.Main == 62 && packet.Sub is 1 or 2 or 4 or 5 or 76)
                Assert.IsAssignableFrom<CraftFurnitureEvent>(Assert.IsType<ServerInventoryEvent>(observation).Event);
            world = WorldEventReducer.Apply(world with { PacketCount = world.PacketCount + 1 }, observation, catalog);
            var local = coordinator.Apply(packet);
            var expected = step["expected"]!;
            Check(expected, world, name + " direct reducer");
            Check(expected, local.World, name + " packet coordinator");
            Assert.Equal(local.Phase, local.World.Phase);
            Assert.Equal(local.PacketCount, local.World.PacketCount);
            Assert.Equal(0, local.Session.UnimplementedCount);
            retained.Add((world, local, expected));
        }
        foreach (var (oldWorld, oldLocal, expected) in retained)
        {
            Check(expected, oldWorld, name + " retained reducer");
            Check(expected, oldLocal.World, name + " retained coordinator");
        }
    }

    [Theory]
    [InlineData(1, 45)]
    [InlineData(2, 2)]
    [InlineData(4, 4)]
    [InlineData(4, 48)]
    [InlineData(5, 7)]
    [InlineData(76, 2)]
    public void InvalidDetailedFurnitureCannotFallBackToShallowGeometryOrIncrementCount(byte sub, int length)
    {
        var state = new LocalStateCoordinator();
        var initial = state.Snapshot();
        Assert.Throws<ProtocolException>(() => state.Apply(new Packet(62, sub, new byte[length - 1])));
        Assert.Same(initial, state.Snapshot());
        Assert.Throws<ProtocolException>(() => state.Apply(new Packet(62, sub, new byte[length + 1])));
        Assert.Same(initial, state.Snapshot());
        state.Apply(new Packet(62, sub, new byte[length]));
        Assert.Equal(1, state.Snapshot().PacketCount);
        Assert.Equal(sub != 4 || length > 4, state.Snapshot().World.Navigation.Stale);
        Assert.Equal(sub != 4 || length > 4 ? 1 : 0, state.Snapshot().World.Navigation.Revision);
    }

    [Fact]
    public void WrappedGeometryDoesNotInvokeInventoryOrOtherServiceObservers()
    {
        var state = new LocalStateCoordinator();
        state.Apply(new GoldSnapshotEvent(100));
        var initial = state.Snapshot();
        var result = state.Apply(new Packet(62, 2, [1, 0]));
        Assert.True(result.World.Navigation.Stale);
        Assert.Same(initial.Session.Gold, result.Session.Gold);
        Assert.Same(initial.Session.NpcDialogue, result.Session.NpcDialogue);
        Assert.Same(initial.Battle, result.Battle);
        Assert.Equal(initial.PacketCount + 1, result.PacketCount);
    }

    private static void Check(JsonNode expected, WorldEventSnapshot world, string label)
    {
        var navigation = new JsonObject
        {
            ["scene"] = world.Navigation.Scene,
            ["revision"] = Number(world.Navigation.Revision),
            ["stale"] = world.Navigation.Stale,
            ["runtime_geometry_verified"] = world.Navigation.RuntimeGeometryVerified,
            ["reasons"] = JsonSerializer.SerializeToNode(world.Navigation.Reasons, Options),
            ["house_context"] = JsonSerializer.SerializeToNode(world.Navigation.HouseContext, Options)
        };
        var actual = new JsonObject
        {
            ["phase"] = world.Phase, ["packet_count"] = Number(world.PacketCount), ["navigation"] = navigation
        };
        LazyAssert.True(JsonNode.DeepEquals(WithoutNulls(expected.DeepClone()), WithoutNulls(actual)),
            () => $"{label}: expected {expected}; actual {actual}");
    }

    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static JsonNode WithoutNulls(JsonNode node)
    {
        if (node is JsonObject obj)
            foreach (var (key, value) in obj.ToArray())
                if (value is null) obj.Remove(key); else WithoutNulls(value);
        if (node is JsonArray array)
            foreach (var value in array) if (value is not null) WithoutNulls(value);
        return node;
    }
}
