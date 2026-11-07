using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleEventParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    [Theory]
    [MemberData(nameof(BattleEventPythonVectors.Sequences), MemberType = typeof(BattleEventPythonVectors))]
    public void EveryTransitionAndHistoricalSnapshotMatchesRetainedPython(string name, string json)
    {
        var state = BattleEventSnapshot.Empty;
        var historical = new List<(BattleEventSnapshot State, JsonNode Expected)>();
        var index = 0;
        foreach (var step in JsonNode.Parse(json)!.AsArray())
        {
            var role = step!["role_id"]?.GetValue<uint>();
            if (step["message"] is { } message)
            {
                if (message["command"] is { } command)
                    state = BattleEventReducer.Apply(state, Command(command));
                else
                {
                    var packet = new Packet(message["main"]!.GetValue<int>(), message["sub"]!.GetValue<int>(),
                        Convert.FromHexString(message["hex"]!.GetValue<string>()));
                    var decoded = ServerProtocol.Decode(packet);
                    var before = state;
                    state = BattleEventReducer.Apply(state, decoded, role);
                    if (decoded is BattleAttributeInvalidEvent) Assert.Same(before, state);
                    // Both public entry points must use the identical typed layout transition.
                    if (decoded is ServerLayoutEvent layout)
                        Assert.True(JsonNode.DeepEquals(Project(state), Project(BattleEventReducer.Apply(before, layout.Event, role))));
                }
            }
            var expected = step["expected"]!;
            AssertSnapshot(expected, state, $"{name}, step {index++}");
            historical.Add((state, expected));
        }
        // Every published nested unit, attribute, command and report survives later events unchanged.
        foreach (var (snapshot, expected) in historical) AssertSnapshot(expected, snapshot, name + " historical");
    }

    private static BattleCommandSentEvent Command(JsonNode value) => new(
        value["col"]!.GetValue<byte>(), value["row"]!.GetValue<byte>(),
        value["target_col"]?.GetValue<byte>(), value["target_row"]?.GetValue<byte>(),
        value["skill_id"]?.GetValue<ushort>(), value["item_id"]?.GetValue<ushort>(), value["bag_index"]?.GetValue<byte>());

    private static void AssertSnapshot(JsonNode expected, BattleEventSnapshot actual, string label)
    {
        var projection = Project(actual);
        LazyAssert.True(JsonNode.DeepEquals(expected, projection), () => $"{label}: expected {expected}; actual {projection}");
    }

    internal static JsonObject Project(BattleEventSnapshot state)
    {
        var battle = new JsonObject { ["actions"] = Number(state.Actions), ["winner_side"] = state.WinnerSide };
        if (state.Stage is { } stage) battle["stage"] = stage;
        if (state.FightNumber is { } fight) battle["fight_number"] = fight;
        if (state.Round is { } round) battle["round"] = round;
        if (state.Active is { } active) battle["active"] = active;
        if (state.WarStyle is { } style) battle["war_style"] = style;
        if (state.HasLastActions) battle["last_actions"] = JsonSerializer.SerializeToNode(state.LastActions, Options);
        if (state.HasCommands)
        {
            var commands = new JsonObject();
            foreach (var command in state.Commands)
            {
                var value = JsonSerializer.SerializeToNode(command.Event, Options)!.AsObject();
                value.Remove("slot");
                value["status"] = command.Status == BattleCommandStatus.Sent ? "sent" : "resolved";
                commands[command.Slot.ToString()] = value;
            }
            battle["commands"] = commands;
        }
        var units = new JsonObject();
        foreach (var unit in state.Units)
        {
            var value = JsonSerializer.SerializeToNode(unit.Layout, Options)!.AsObject();
            value["equips"] = JsonSerializer.SerializeToNode(unit.Equips, Options);
            value["hp"] = unit.Hp;
            value["sp"] = unit.Sp;
            if (unit.Attributes.Count != 0)
            {
                var attributes = new JsonObject();
                foreach (var (kind, amount) in unit.Attributes)
                    attributes[kind.ToString(CultureInfo.InvariantCulture)] = amount;
                value["attributes"] = attributes;
            }
            if (unit.Exited) value["exited"] = true;
            units[unit.Slot.ToString()] = value;
        }
        return new()
        {
            ["battle_count"] = Number(state.BattleCount), ["battle"] = battle, ["battle_units"] = units,
            ["unit_order"] = JsonSerializer.SerializeToNode(state.Units.Select(unit => unit.Slot.ToString())),
            ["command_order"] = JsonSerializer.SerializeToNode(state.Commands.Select(command => command.Slot.ToString()))
        };
    }

    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
}
