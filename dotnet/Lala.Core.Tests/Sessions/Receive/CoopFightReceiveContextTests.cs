using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Instances;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class CoopFightReceiveContextTests
{
    internal static Packet World(uint role = 71) => new(3, 1, new PacketWriter().U32(role).U8(0).U16(101).U16(20).U16(30)
        .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
    internal static Packet Start(uint role = 71, byte col = 3) => new(11, 250,
        new PacketWriter().U8(12).U8(3).U8(1)
            .U8(9).U8(0).U32(role).U16(2).U32(0).U8(col).U8(1).U32(100).U16(40).U32(90).U16(20)
            .U8(19).U8(2).U8(1).U8(3).U16(0).U16(0).U8(1).U8(2).U32(0).U32(0)
            .U8(0).Raw(new byte[54]).Build());
    internal static Packet Exit(uint role = 71) => new(11, 0, new PacketWriter().U32(role).U16(0).Build());
    private static ServiceStateSnapshot Apply(ReceiveStateCoordinator state, ServerEvent observation) =>
        state.Apply(observation, new(state.Snapshot(), new(123)));
    private static ServiceStateSnapshot Apply(ReceiveStateCoordinator state, Packet packet) =>
        Apply(state, ServerProtocol.Decode(packet, state.Snapshot().Player?.RoleId));

    [Theory]
    [MemberData(nameof(CoopFightReceivePythonVectors.Sequences), MemberType = typeof(CoopFightReceivePythonVectors))]
    public void ActualFullServiceThenReceiveMatchesPythonIncludingAllInstanceFields(string name, string json)
    {
        var sequence = JsonNode.Parse(json)!;
        var coop = InstanceReceiveSnapshot.Empty.Coop;
        foreach (var (key, value) in sequence["initial_coop"]!.AsObject()) coop = coop.SetKey(key, Read(value));
        var coordinator = new ReceiveStateCoordinator(new(instances: new() { Coop = coop }));
        var history = new List<(ServiceStateSnapshot State, JsonNode Expected)>();
        foreach (var step in sequence["steps"]!.AsArray())
        {
            var message = step!["message"]!;
            if (message["fresh_context"] is not null) coordinator = new(coordinator.Snapshot());
            else Apply(coordinator, new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                Convert.FromHexString(message["hex"]!.GetValue<string>())));
            var state = coordinator.Snapshot();
            var expected = step["expected"]!;
            Assert.True(JsonNode.DeepEquals(expected, Project(state)), $"{name}: {Project(state)} != {expected}");
            // The oracle records Python's real delay=None arithmetic failure. Core
            // intentionally ports only the preceding receive bookkeeping, not timers.
            if (step["excluded_source_delay_failure"]!.GetValue<bool>())
                Assert.Equal(state.Local.Battle.BattleCount,
                    state.Instances.Coop["fight_consumed_battle"].ScalarValue is BigInteger number ? number :
                        new BigInteger(Convert.ToDouble(state.Instances.Coop["fight_consumed_battle"].ScalarValue, CultureInfo.InvariantCulture)));
            history.Add((state, expected));
        }
        foreach (var (state, expected) in history)
            Assert.True(JsonNode.DeepEquals(expected, Project(state)), name + " historical");
    }

    [Theory]
    [InlineData((byte)0)] [InlineData((byte)5)]
    public void ImportedInvalidUnitColumnCannotEstablishVictory(byte col)
    {
        var state = new ReceiveStateCoordinator(new());
        Apply(state, World()); Apply(state, new Packet(186, 15, [3])); Apply(state, new WarStyleEvent(16));
        var valid = (BattleStartEvent)((ServerLayoutEvent)ServerProtocol.Decode(Start())).Event;
        Apply(state, new ServerLayoutEvent(valid with { Units = [valid.Units[0] with { Col = col }] }));
        Apply(state, new WinnerEvent(1));
        var exited = Apply(state, Exit());
        Assert.Equal(new BigInteger(2), exited.Instances.Coop["fight_count"].ScalarValue);
        Assert.Null(exited.Instances.Coop["last_fight_victory"].ScalarValue);
    }

    [Fact]
    public void StandaloneServiceRemainsPureAndReceiveBookkeepingDoesNotAuthorizeAnything()
    {
        var direct = new ServiceStateCoordinator();
        foreach (var packet in new[] { World(), new Packet(186, 15, [3]), Start(), new Packet(11, 10, [16]), new Packet(11, 12, [1]) })
            direct.Apply(packet, new(direct.Snapshot(), new(123)));
        var before = direct.Snapshot();
        var after = direct.Apply(Exit(), new(before, new(123)));
        Assert.Equal((byte)3, after.Instances.Coop["fight_count"].ScalarValue);
        Assert.Null(after.Instances.Coop["fight_consumed_battle"].ScalarValue);
        Assert.Null(after.Instances.Coop["last_fight_victory"].ScalarValue);
        var receive = new ReceiveStateCoordinator(before);
        var received = Apply(receive, Exit());
        Assert.Equal(new BigInteger(2), received.Instances.Coop["fight_count"].ScalarValue);
        Assert.Equal(before.Local.Session.EventFlow, received.Local.Session.EventFlow);
        Assert.Equal(before.Instances.Main, received.Instances.Main);
        Assert.True(received.Observation!.Inputs.ResourceHeld); Assert.False(received.IsCompleteState);
    }

    [Fact]
    public void StaleExitCannotConsumeCountOrPrivateExitContext()
    {
        var state = new ReceiveStateCoordinator(new());
        Apply(state, World()); Apply(state, new Packet(186, 15, [3])); Apply(state, new WarStyleEvent(16));
        var started = Apply(state, Start());
        var winner = Apply(state, new WinnerEvent(1));
        Assert.Throws<InvalidOperationException>(() => state.Apply(new FightExitEvent(71, 0), new(started, new(123))));
        Assert.Same(winner, state.Snapshot());
        var exited = Apply(state, Exit());
        Assert.Equal(new BigInteger(2), exited.Instances.Coop["fight_count"].ScalarValue);
        Assert.Equal(true, exited.Instances.Coop["last_fight_victory"].ScalarValue);
        Assert.Equal((byte)3, winner.Instances.Coop["fight_count"].ScalarValue);
        Assert.Null(winner.Instances.Coop["fight_consumed_battle"].ScalarValue);
    }

    [Fact]
    public void FailedOverlayDoesNotCommitServiceChangesOrConsumePrivateExitContext()
    {
        var seed = new ReceiveStateCoordinator(new());
        Apply(seed, World()); Apply(seed, new WarStyleEvent(16)); var started = Apply(seed, Start());
        // Deliberately malformed imported coop map. Unit exit has no instance
        // observer, so full service reduction succeeds before overlay validation.
        var initial = new ServiceStateSnapshot(local: started.Local, instances: new() { Coop = StateValue.Null });
        var state = new ReceiveStateCoordinator(initial);
        for (var i = 0; i < 2; i++)
        {
            Assert.Throws<InvalidOperationException>(() => Apply(state, new BattleUnitExitEvent(3, 1, null)));
            Assert.Same(initial, state.Snapshot());
            Assert.True(initial.Local.Battle.Active); Assert.False(initial.Local.Battle.Units[0].Exited);
        }
    }

    internal static JsonObject Project(ServiceStateSnapshot state) => new()
    {
        ["packet_count"] = WriteNumber(state.PacketCount), ["battle_count"] = WriteNumber(state.Local.Battle.BattleCount),
        ["active"] = state.Local.Battle.Active, ["war_style"] = state.Local.Battle.WarStyle,
        ["winner_side"] = state.Local.Battle.WinnerSide, ["role_id"] = state.Player?.RoleId,
        ["units"] = new JsonArray(state.Local.Battle.Units.Select(unit => (JsonNode)new JsonObject
        {
            ["slot"] = unit.Slot.ToString(), ["pid"] = unit.Layout.Pid, ["exited"] = unit.Exited
        }).ToArray()),
        ["instances"] = new JsonObject { ["main"] = Write(state.Instances.Main), ["coop"] = Write(state.Instances.Coop) }
    };
    private static JsonNode WriteNumber(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static StateValue Read(JsonNode? node) => node switch
    {
        null => StateValue.Null,
        JsonObject map => StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, Read(pair.Value)))),
        JsonArray items => StateValue.List(items.Select(Read)),
        _ => node.GetValueKind() switch
        {
            JsonValueKind.True => StateValue.Scalar(true), JsonValueKind.False => StateValue.Scalar(false),
            JsonValueKind.String => StateValue.Scalar(node.GetValue<string>()),
            _ => node.ToJsonString().Contains('.') ? StateValue.Scalar(node.GetValue<double>()) :
                StateValue.Scalar(BigInteger.Parse(node.ToJsonString(), CultureInfo.InvariantCulture))
        }
    };
    internal static JsonNode? Write(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => new JsonObject(value.MapValue.Select(pair => KeyValuePair.Create(pair.Key, Write(pair.Value)))),
        StateValueKind.List or StateValueKind.Tuple => new JsonArray(value.SequenceValue.Select(Write).ToArray()),
        _ => value.ScalarValue is BigInteger number ? WriteNumber(number) : JsonSerializer.SerializeToNode(value.ScalarValue)
    };
}
