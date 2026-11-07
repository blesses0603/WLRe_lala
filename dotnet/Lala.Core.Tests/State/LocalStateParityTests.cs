using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Battle;
using Lala.Core.World;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class LocalStateParityTests
{
    private static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        Converters = { new BigIntegerConverter() }
    };

    [Theory]
    [MemberData(nameof(LocalStatePythonVectors.Sequences), MemberType = typeof(LocalStatePythonVectors))]
    public void InterleavedDispatchAndHelpersMatchPythonWithoutChangingOldSnapshots(string name, string json)
    {
        var vector = JsonNode.Parse(json)!;
        var initial = vector["initial"]!;
        var session = initial["session"]!.Deserialize<SessionEventSnapshot>(Options)!;
        var worldJson = initial["world"]!.DeepClone().AsObject();
        var positions = worldJson["positions"]!.AsArray();
        worldJson.Remove("positions");
        var world = worldJson.Deserialize<WorldEventSnapshot>(Options)!;
        foreach (var position in positions)
            world = WorldEventReducer.RememberPosition(world, position!["role_id"]!.GetValue<long>(),
                position["x"]!.GetValue<ushort>(), position["y"]!.GetValue<ushort>());
        var state = new LocalStateCoordinator(new(session, world));
        var historical = new List<(LocalStateSnapshot Snapshot, JsonNode Expected)> { (state.Snapshot(), initial) };
        Check(initial, state.Snapshot(), name);
        foreach (var step in vector["steps"]!.AsArray())
        {
            Apply(state, step!);
            Check(step!["expected"]!, state.Snapshot(), name);
            historical.Add((state.Snapshot(), step["expected"]!));
        }
        foreach (var (snapshot, expected) in historical) Check(expected, snapshot, name + " historical");
    }

    private static void Apply(LocalStateCoordinator state, JsonNode step)
    {
        switch (step["operation"]!.GetValue<string>())
        {
            case "packet":
                state.Apply(new Packet(step["main"]!.GetValue<byte>(), step["sub"]!.GetValue<byte>(),
                    Convert.FromHexString(step["hex"]!.GetValue<string>())));
                break;
            case "event":
                var value = step["event"]!;
                switch (value["type"]!.GetValue<string>())
                {
                    case "battle_command_sent":
                        state.Apply(new BattleCommandSentEvent(value["col"]!.GetValue<byte>(), value["row"]!.GetValue<byte>()));
                        break;
                    case "movement_request":
                        state.Apply(new MovementRequestEvent(value["x"]!.GetValue<ushort>(), value["y"]!.GetValue<ushort>()));
                        break;
                    case "unsupported_decoder": state.Apply(new UnsupportedServerDecoderEvent(250, 1, "fixture", 0)); break;
                    default: throw new InvalidOperationException("Unknown fixture observation");
                }
                break;
            case "remember":
                state.RememberPosition(step["role_id"]!.GetValue<long>(), step["x"]!.GetValue<ushort>(), step["y"]!.GetValue<ushort>());
                break;
            case "clear": Assert.Equal(step["removed"]!.GetValue<int>(), state.ClearPositionHistory()); break;
            case "wait": state.WaitForPosition(); break;
            case "confirm":
                state.ConfirmLocation(step["scene"]!.GetValue<ushort>(), step["x"]!.GetValue<ushort>(),
                    step["y"]!.GetValue<ushort>(), step["source"]!.GetValue<string>());
                break;
            default: throw new InvalidOperationException("Unknown fixture operation");
        }
    }

    private static void Check(JsonNode expected, LocalStateSnapshot actual, string label)
    {
        Assert.Equal(actual.Phase, actual.World.Phase);
        Assert.Equal(actual.PacketCount, actual.World.PacketCount);
        Assert.Same(actual.World.Player, actual.Player);
        var projection = new JsonObject
        {
            ["session"] = JsonSerializer.SerializeToNode(actual.Session, Options),
            ["world"] = JsonSerializer.SerializeToNode(new
            {
                actual.World.Phase, actual.World.PacketCount, actual.World.Player,
                Positions = actual.World.Positions.Entries.ToArray(), actual.World.Navigation,
                actual.World.Location, actual.World.LocalMovement, actual.World.MovementCheck
            }, Options),
            ["battle"] = BattleEventParityTests.Project(actual.Battle)
        };
        var normalized = WithoutNulls(expected.DeepClone());
        LazyAssert.True(JsonNode.DeepEquals(normalized, WithoutNulls(projection)),
            () => $"{label}: expected {normalized}; actual {projection}");
    }

    [Theory]
    [MemberData(nameof(LocalStatePythonVectors.Publishers), MemberType = typeof(LocalStatePythonVectors))]
    public void CoalescingCallbackTimingForceFlushAndFailureMatchPython(string name, string json)
    {
        Assert.NotEmpty(name);
        var vector = JsonNode.Parse(json)!;
        var state = new LocalStateCoordinator();
        double now = 0, delay = 0;
        bool fail = false;
        var callbacks = new JsonArray();
        var retained = new List<(LocalStateSnapshot Snapshot, string Phase, BigInteger Count)>();
        var publisher = new LocalStatePublisher(snapshot =>
        {
            callbacks.Add(new JsonObject
            {
                ["packet_count"] = Number(snapshot.PacketCount), ["phase"] = snapshot.Phase
            });
            retained.Add((snapshot, snapshot.Phase, snapshot.PacketCount));
            now += delay;
            if (fail) throw new InvalidOperationException("synthetic callback failure");
        }, vector["interval"]!.GetValue<double>(), () => now);
        foreach (var step in vector["steps"]!.AsArray())
        {
            state.Apply(new LoginResultEvent(step!["result"]!.GetValue<byte>(), 0));
            now = step["now"]!.GetValue<double>(); delay = step["delay"]!.GetValue<double>();
            string operation = step["operation"]!.GetValue<string>();
            fail = operation == "publish_fail";
            var error = Record.Exception(() =>
            {
                if (operation == "flush") publisher.Flush(state);
                else publisher.Publish(state, step["force"]!.GetValue<bool>());
            });
            Assert.Equal(step["error"]!.GetValue<bool>(), error is not null);
            if (error is not null) Assert.IsType<InvalidOperationException>(error);
            var expected = step["expected"]!;
            Assert.Equal(expected["last"]?.GetValue<double>(), publisher.LastPublishedAt);
            Assert.Equal(expected["pending"]!.GetValue<bool>(), publisher.Pending);
            Assert.True(JsonNode.DeepEquals(expected["callbacks"], callbacks), name);
        }
        foreach (var (snapshot, phase, count) in retained)
        {
            Assert.Equal(phase, snapshot.Phase);
            Assert.Equal(count, snapshot.PacketCount);
        }
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
