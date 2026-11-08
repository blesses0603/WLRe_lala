using System.Text.Json.Nodes;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class BattleReceiveContextTests
{
    private static readonly ServerEvent Start = new ServerLayoutEvent(new BattleStartEvent(12, 3, []));
    private static ServiceStateSnapshot Apply(ReceiveStateCoordinator state, ServerEvent observation) =>
        state.Apply(observation, new(state.Snapshot(), new(123)));

    [Theory]
    [MemberData(nameof(BattleReceivePythonVectors.Sequences), MemberType = typeof(BattleReceivePythonVectors))]
    public void FullServiceThenReceiveMatchesPythonAndPreservesHistoricalSnapshots(string name, string json)
    {
        var coordinator = new ReceiveStateCoordinator(new());
        var history = new List<(ServiceStateSnapshot State, JsonNode Expected)>();
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var message = step!["message"]!;
            if (message["fresh_context"] is not null)
                coordinator = new ReceiveStateCoordinator(coordinator.Snapshot());
            else
            {
                var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                    Convert.FromHexString(message["hex"]!.GetValue<string>()));
                Apply(coordinator, ServerProtocol.Decode(packet, coordinator.Snapshot().Player?.RoleId));
            }
            var state = coordinator.Snapshot();
            var expected = step["expected"]!;
            Assert.True(JsonNode.DeepEquals(expected, Project(state)), $"{name}: {Project(state)} != {expected}");
            history.Add((state, expected));
        }
        foreach (var (state, expected) in history)
            Assert.True(JsonNode.DeepEquals(expected, Project(state)), name + " historical");
    }

    [Fact]
    public void StaleInputsAndFailedReductionDoNotAdvanceOrConsumePendingAnnouncement()
    {
        var state = new ReceiveStateCoordinator(new());
        var initial = state.Snapshot();
        var announced = Apply(state, new WarStyleEvent(16));
        Assert.Throws<InvalidOperationException>(() => state.Apply(Start, new(initial, new(123))));
        Assert.Same(announced, state.Snapshot());
        // Invalid hand-built layout fails after the local packet count has staged.
        Assert.ThrowsAny<Exception>(() => Apply(state,
            new ServerLayoutEvent(new BattleStartEvent(12, 3, default))));
        Assert.Same(announced, state.Snapshot());
        var started = Apply(state, Start);
        Assert.Equal(2, started.PacketCount); Assert.Equal(1, started.Local.Battle.BattleCount);
        Assert.Equal((byte)16, started.Local.Battle.WarStyle);
        Assert.Null(Apply(state, Start).Local.Battle.WarStyle);
        Assert.Equal(0, announced.Local.Battle.BattleCount);
        Assert.Equal((byte)16, announced.Local.Battle.WarStyle);
    }

    [Fact]
    public void StandaloneServiceStillClearsStyleAndReceiveDoesNotRunPostBattleAutomation()
    {
        var direct = new ServiceStateCoordinator();
        direct.Apply(new WarStyleEvent(16), new(direct.Snapshot(), new(123)));
        Assert.Null(direct.Apply(Start, new(direct.Snapshot(), new(123))).Local.Battle.WarStyle);
        var state = new ReceiveStateCoordinator(new());
        var world = new Packet(3, 1, new PacketWriter().U32(71).U8(0).U16(101).U16(20).U16(30)
            .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
        Apply(state, ServerProtocol.Decode(world));
        Apply(state, new WarStyleEvent(16));
        var started = Apply(state, Start);
        var exited = Apply(state, new FightExitEvent(71, 0));
        Assert.False(exited.Local.Battle.Active);
        Assert.Equal(started.Instances.Coop, exited.Instances.Coop);
        Assert.Equal(started.Local.Session.EventFlow, exited.Local.Session.EventFlow);
        Assert.True(exited.Observation!.Inputs.ResourceHeld);
        Assert.False(exited.IsCompleteState);
    }

    [Fact]
    public void CoordinatorIsSingleWriterAndSavedSnapshotIsReadableElsewhere()
    {
        var state = new ReceiveStateCoordinator(new());
        var saved = Apply(state, new WarStyleEvent(0));
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try { state.Snapshot(); } catch (Exception error) { failure = error; }
            Assert.Equal((byte)0, saved.Local.Battle.WarStyle);
        });
        thread.Start(); thread.Join();
        Assert.IsType<InvalidOperationException>(failure);
    }

    private static JsonObject Project(ServiceStateSnapshot state) => new()
    {
        ["packet_count"] = (long)state.PacketCount,
        ["battle_count"] = (long)state.Local.Battle.BattleCount,
        ["active"] = state.Local.Battle.Active,
        ["war_style"] = state.Local.Battle.WarStyle,
        ["units"] = new JsonArray(state.Local.Battle.Units.Select(unit => (JsonNode)new JsonObject
        {
            ["slot"] = unit.Slot.ToString(), ["pid"] = unit.Layout.Pid, ["exited"] = unit.Exited
        }).ToArray())
    };
}
