using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Instances;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Instances;

public sealed class InstanceReceiveReducerTests
{
    private static readonly InstanceReceiveContext Context = new() { OwnRoleId = 42, DeclaredMainCatalogMapIds = [500] };
    private static InstanceReceiveSnapshot Apply(InstanceReceiveSnapshot state, InstanceEvent observation, double at = 100.25) =>
        InstanceReceiveReducer.Apply(state, observation, Context, at);
    private static InstanceReceiveSnapshot Apply(InstanceReceiveSnapshot state, ServerEvent observation) =>
        InstanceReceiveReducer.Apply(state, observation, Context, 100.25);
    private static bool Bool(StateValue map, string key) => Assert.IsType<bool>(map[key].ScalarValue);
    private static string Text(StateValue map, string key) => Assert.IsType<string>(map[key].ScalarValue);
    private static BigInteger Int(StateValue map, string key) => BigInteger.Parse(Convert.ToString(map[key].ScalarValue, CultureInfo.InvariantCulture)!, CultureInfo.InvariantCulture);
    private static StateValue Map(params (string Key, object? Value)[] entries) => StateValue.Map(entries.Select(e => KeyValuePair.Create(e.Key,
        e.Value is StateValue value ? value : StateValue.Scalar(e.Value))));
    private static StateValue Seed(StateValue state, params (string Key, object? Value)[] entries) => StateValue.Map(state.MapValue.SetItems(Map(entries).MapValue));
    private static MainRoomPhaseEvent Room(ushort room = 500) => new(0, room, 2, 42);
    private static CoopMembersEvent Coop(ushort room = 9, bool standby = true) => new(room, 42, true, true, standby, 2, 1, 2,
        [new(42, 1, 100, 100, 30, 30), new(7, 1, 100, 100, 30, 30)]);
    private static PositionSnapshotEvent Position(uint role = 42, ushort scene = 500) => new(7, role, scene, 0, 0, 0, new(false));

    [Theory]
    [MemberData(nameof(PythonInstanceReceiveVectors.Sequences), MemberType = typeof(PythonInstanceReceiveVectors))]
    public void ActualPythonDecodeAndAllReceiveObserversMatchWithImmutableHistory(string name, string json)
    {
        var sequence = JsonNode.Parse(json)!;
        var initial = sequence["initial"]!;
        var state = new InstanceReceiveSnapshot { Main = Read(initial["main"]), Coop = Read(initial["coop"]) };
        var context = new InstanceReceiveContext
        {
            OwnRoleId = sequence["own"]?.GetValue<uint>(),
            DeclaredMainCatalogMapIds = sequence["catalog"]!.AsArray().Select(v => v!.GetValue<ushort>()).ToImmutableHashSet()
        };
        var history = new List<(InstanceReceiveSnapshot State, JsonNode Expected)> { (state, initial) };
        var index = 0;
        foreach (var step in sequence["steps"]!.AsArray())
        {
            if (step!["reset"]?.GetValue<bool>() == true) state = new();
            else if (step["event"] is { } entry)
                state = InstanceReceiveReducer.Apply(state, EntryEvent(entry), context, step["at"]!.GetValue<double>());
            else
            {
                var packet = new Packet(step["main"]!.GetValue<byte>(), step["sub"]!.GetValue<byte>(), Convert.FromHexString(step["hex"]!.GetValue<string>()));
                if (step["error"]!.GetValue<bool>()) Assert.Throws<ProtocolException>(() => InstanceDecoder.Decode(packet));
                else if (InstanceDecoder.Decode(packet) is { } observation)
                {
                    var at = step["at"]!.GetValue<double>();
                    var direct = InstanceReceiveReducer.Apply(state, observation, context, at);
                    state = InstanceReceiveReducer.Apply(state, new ServerInstanceEvent(packet.Main, packet.Sub, observation), context, at);
                    Check(Project(direct), state, $"{name} adapter {index}");
                }
            }
            Check(step["expected"]!, state, $"{name} step {index++}");
            history.Add((state, step["expected"]!));
        }
        foreach (var prior in history) Check(prior.Expected, prior.State, name + " historical");
    }

    [Fact]
    public void EveryOracleSourceHashUsesOnlyByteCrLfNormalization()
    {
        var metadata = JsonNode.Parse(PythonInstanceReceiveVectors.Metadata())!;
        Assert.Equal(9, metadata["sources"]!.AsObject().Count);
        var root = FindRoot();
        foreach (var source in metadata["sources"]!.AsObject())
        {
            var bytes = File.ReadAllBytes(Path.Combine(root, source.Key));
            Assert.Equal(source.Value!.GetValue<string>(), Convert.ToHexString(SHA256.HashData(NormalizeCrLf(bytes))).ToLowerInvariant());
        }
        Assert.True(metadata["scenarios"]!.GetValue<int>() >= 1172);
        Assert.True(metadata["steps"]!.GetValue<int>() >= 5526);
        Assert.True(new FileInfo(Path.Combine(root, "dotnet/Lala.Core.Tests/Instances/PythonInstanceReceiveVectors.cs")).Length < 500_000);
    }

    [Theory]
    [InlineData("instance_objective", "main", 1)] [InlineData("instance_objective", "main", 2)]
    [InlineData("instance_objective", "main", 3)] [InlineData("instance_objective", "main", 4)]
    [InlineData("instance_objective", "main", 5)] [InlineData("instance_objective", "main", 6)]
    [InlineData("instance_new_info", "main", 0)] [InlineData("instance_new_info", "main", 1)]
    [InlineData("instance_new_info", "main", 2)] [InlineData("instance_new_info", "main", 3)]
    [InlineData("instance_new_info", "main", 4)] [InlineData("instance_new_info", "main", 5)]
    [InlineData("instance_new_info", "main", 6)] [InlineData("instance_new_info", "main", 98)]
    [InlineData("instance_new_info", "main", 99)] [InlineData("instance_new_info", "main", 100)]
    [InlineData("instance_new_info", "main", 101)] [InlineData("instance_new_info", "main", 102)]
    [InlineData("instance_phase", "main", 1)] [InlineData("instance_phase", "main", 2)]
    [InlineData("instance_phase", "main", 3)] [InlineData("instance_phase", "main", 4)]
    [InlineData("instance_phase", "main", 5)]
    [InlineData("instance_coop_match", "coop", 17)] [InlineData("instance_coop_match", "coop", 18)]
    public void EveryInnerKindHasSuccessfullyDecodedPythonEvidence(string type, string mode, int kind)
    {
        var metadata = JsonNode.Parse(PythonInstanceReceiveVectors.Metadata())!;
        Assert.Contains(metadata["covered"]!.AsArray(), entry => entry![0]!.GetValue<string>() == type &&
            entry[1]?.GetValue<string>() == mode && entry[2]?.GetValue<int>() == kind);
    }

    [Fact]
    public void HashNormalizationDoesNotRewriteLoneCrUnicodeOrBom()
    {
        byte[] original = [0xef, 0xbb, 0xbf, 0xff, 13, 10, 13, 0xc2, 0x85, 0xe2, 0x80, 0xa8, 10];
        Assert.Equal(new byte[] { 0xef, 0xbb, 0xbf, 0xff, 10, 13, 0xc2, 0x85, 0xe2, 0x80, 0xa8, 10 }, NormalizeCrLf(original));
        Assert.Equal(original, new byte[] { 0xef, 0xbb, 0xbf, 0xff, 13, 10, 13, 0xc2, 0x85, 0xe2, 0x80, 0xa8, 10 });
    }

    [Fact]
    public void DefaultsContainNoInventedGenerationSweepOrHeroState()
    {
        var state = InstanceReceiveSnapshot.Empty;
        foreach (var mode in new[] { state.Main, state.Coop })
        {
            Assert.False(Bool(mode, "ready")); Assert.False(Bool(mode, "completed")); Assert.Null(mode["room"].ScalarValue);
            Assert.Equal("idle", Text(mode, "phase")); Assert.Empty(mode["rooms"].SequenceValue); Assert.Empty(mode["members"].SequenceValue);
            Assert.False(mode.MapValue.ContainsKey("generation")); Assert.False(mode.MapValue.ContainsKey("sweep"));
            Assert.False(mode.MapValue.ContainsKey("hero_challenge"));
        }
        Assert.Empty(state.Main["objectives"].MapValue); Assert.False(Bool(state.Coop, "auto_claim_enabled"));
        Assert.False(state.Main.MapValue.ContainsKey("member_count")); Assert.False(state.Main.MapValue.ContainsKey("challenge_notice"));
    }

    [Fact]
    public void OnlyRoomListsSetReadyAndObserveCallerTime()
    {
        var initial = Apply(InstanceReceiveSnapshot.Empty, Room());
        Assert.False(Bool(initial.Main, "ready"));
        var list = Apply(initial, new MainRoomListEvent([]), -1.5);
        Assert.True(Bool(list.Main, "ready")); Assert.Equal(-1.5, list.Main["list_updated_at"].ScalarValue);
        Assert.False(Bool(list.Coop, "ready")); Assert.Same(initial.Coop, list.Coop);
        var reset = new InstanceReceiveSnapshot(); Assert.False(Bool(reset.Main, "ready"));
        Assert.True(Bool(list.Main, "ready"));
    }

    [Theory]
    [InlineData(double.NaN)] [InlineData(double.PositiveInfinity)] [InlineData(double.NegativeInfinity)]
    public void InvalidListTimeFailsAtomicallyButUnconsumedTimeDoesNotInventValidation(double time)
    {
        var state = InstanceReceiveSnapshot.Empty;
        Assert.Throws<ArgumentOutOfRangeException>(() => Apply(state, new MainRoomListEvent([]), time));
        Assert.False(Bool(state.Main, "ready"));
        Assert.Equal("waiting", Text(Apply(state, Room(), time).Main, "phase"));
    }

    [Fact]
    public void SuccessCodeWithoutRoomOrPendingIsNotCreationOrJoinEvidence()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, new MainResultEvent("create", 0));
        state = Apply(state, new MainResultEvent("join", 0));
        state = Apply(state, new CoopResultEvent(9, null)); state = Apply(state, new CoopResultEvent(10, null));
        Assert.Null(state.Main["room"].ScalarValue); Assert.Null(state.Coop["room"].ScalarValue);
        Assert.Null(state.Main["create_result"].ScalarValue); Assert.Null(state.Main["join_result"].ScalarValue);
        Assert.Null(state.Coop["create_result"].ScalarValue); Assert.Null(state.Coop["join_result"].ScalarValue);
    }

    [Fact]
    public void MismatchedAndEarlyRosterCannotBecomeCurrentRoom()
    {
        var original = InstanceReceiveSnapshot.Empty;
        Assert.Same(original, Apply(original, new MainMembersEvent(500, [new(42)])));
        Assert.Same(original, Apply(original, new MainMemberJoinedEvent(1, 42, 500)));
        var state = Apply(original, Room());
        Assert.Same(state, Apply(state, new MainMembersEvent(501, [new(42)])));
        Assert.Empty(state.Main["members"].SequenceValue);
    }

    [Fact]
    public void DuplicateScoresAccumulateBeyondFixedWidthAndKeepOldSnapshot()
    {
        var big = BigInteger.One << 90;
        var state = new InstanceReceiveSnapshot { Main = Seed(InstanceReceiveSnapshot.Empty.Main,
            ("objectives", Map(("scores", Map(("42", Map(("normal", big), ("boss", 0)))))))) };
        var next = Apply(state, new MainObjectiveRolesEvent(5, [42, 42]));
        Assert.Equal(big + 2, Int(next.Main["objectives"]["scores"]["42"], "normal"));
        Assert.Equal(big, Int(state.Main["objectives"]["scores"]["42"], "normal"));
    }

    [Fact]
    public void DeclaredCatalogAloneCannotConfirmEntryOrMintActionAuthority()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, Room()); state = Apply(state, new MainPhaseSignalEvent(3));
        var emptyContext = new InstanceReceiveContext { OwnRoleId = 42 };
        var noCatalog = InstanceReceiveReducer.Apply(state, Position(), emptyContext, 0);
        var otherRole = Apply(state, Position(7)); var otherScene = Apply(state, Position(scene: 501));
        Assert.Equal("started", Text(noCatalog.Main, "phase")); Assert.Equal("started", Text(otherRole.Main, "phase"));
        Assert.Equal("started", Text(otherScene.Main, "phase"));
        var confirmed = Apply(state, Position());
        Assert.Equal("entered", Text(confirmed.Main, "phase")); Assert.Equal("confirmed", Text(confirmed.Main, "enter_result"));
        Assert.Null(confirmed.Main["enter_pending"].ScalarValue); Assert.False(Bool(confirmed.Main, "completed"));
        Assert.Equal(500, Int(confirmed.Main, "entered_scene"));
    }

    [Fact]
    public void WorldPlayerUsesPreLocalDispatchOwnRoleRatherThanIncomingRole()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, Room()); state = Apply(state, new MainPhaseSignalEvent(3));
        ServerEvent World(uint role) => new ServerLayoutEvent(new WorldPlayerEvent(new(role, 0, 500, 0, 0, 0, 0, 0, 0, 0, 0, false, [], "synthetic", 0)));
        var newRole = Apply(state, World(77));
        Assert.Equal("started", Text(newRole.Main, "phase")); Assert.Null(newRole.Main["enter_result"].ScalarValue);
        var currentRole = Apply(newRole, World(42));
        Assert.Equal("entered", Text(currentRole.Main, "phase")); Assert.Equal("confirmed", Text(currentRole.Main, "enter_result"));
        Assert.Equal("started", Text(state.Main, "phase"));
    }

    [Fact]
    public void BattleAndWinnerDoNotProveDungeonCompletionOrAwardContents()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, Room()); state = Apply(state, new MainPhaseSignalEvent(3));
        state = Apply(state, Position()); state = Apply(state, new ServerLayoutEvent(new BattleStartEvent(0, 0, [])));
        Assert.True(Bool(state.Main, "battle_active"));
        state = Apply(state, new WinnerEvent(1));
        Assert.False(Bool(state.Main, "completed")); Assert.False(Bool(state.Main, "battle_active")); Assert.Equal("entered", Text(state.Main, "phase"));
        state = Apply(state, new MainCompletedEvent()); Assert.True(Bool(state.Main, "completed"));
        Assert.Empty(state.Coop["received_awards"].SequenceValue);
    }

    [Fact]
    public void RoomExitMarksPendingStartAndEntryUncertainWithoutClearingPriorUncertainty()
    {
        var state = new InstanceReceiveSnapshot { Main = Seed(InstanceReceiveSnapshot.Empty.Main,
            ("start_pending", Map(("room_id", 500))), ("enter_pending", Map(("room_id", 500)))) };
        state = Apply(state, Room()); state = Apply(state, new MainPhaseSignalEvent(4));
        Assert.True(Bool(state.Main, "start_uncertain")); Assert.True(Bool(state.Main, "enter_uncertain"));
        Assert.Null(state.Main["start_pending"].ScalarValue); Assert.Null(state.Main["enter_pending"].ScalarValue);
        state = Apply(state, Room()); state = Apply(state, new MainPhaseSignalEvent(3));
        Assert.True(Bool(state.Main, "start_uncertain")); Assert.True(Bool(state.Main, "enter_uncertain"));
    }

    [Fact]
    public void LateCoopCreateRequiresAttemptIdentityAndFirstSlotHost()
    {
        var state = new InstanceReceiveSnapshot { Coop = Seed(InstanceReceiveSnapshot.Empty.Coop,
            ("create_uncertain", true), ("create_attempt", Map(("kind", 2), ("npc_id", 1)))) };
        var wrong = Apply(state, Coop() with { Members = [new(7, 0, 1, 1, 1, 1), new(42, 0, 1, 1, 1, 1)] });
        Assert.True(Bool(wrong.Coop, "create_uncertain"));
        var right = Apply(wrong, Coop() with { Created = false });
        Assert.False(Bool(right.Coop, "create_uncertain")); Assert.Equal(9, Int(right.Coop, "create_result"));
        Assert.Null(right.Coop["create_attempt"].ScalarValue); Assert.True(Bool(state.Coop, "create_uncertain"));
    }

    [Fact]
    public void StandbySignalDoesNotResolveAttemptButMatchingRosterDoes()
    {
        var state = new InstanceReceiveSnapshot { Coop = Seed(InstanceReceiveSnapshot.Empty.Coop,
            ("standby_uncertain", true), ("standby_attempt", Map(("room_id", 9), ("target", true)))) };
        state = Apply(state, new CoopStandbyEvent(true)); Assert.True(Bool(state.Coop, "standby_uncertain"));
        state = Apply(state, Coop()); Assert.False(Bool(state.Coop, "standby_uncertain")); Assert.True(Bool(state.Coop, "standby_result"));
    }

    [Fact]
    public void RewardBeforeFirstRoomPreservesCompletionButConfirmedRoomChangeResets()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, new CoopRewardStatusEvent(3, 3, 1, 1, 1));
        state = Apply(state, Coop()); Assert.True(Bool(state.Coop, "completed")); Assert.Equal("S186-11", Text(state.Coop, "completion_source"));
        var next = Apply(state, Coop(10)); Assert.False(Bool(next.Coop, "completed")); Assert.Null(next.Coop["reward"].ScalarValue);
        Assert.True(Bool(state.Coop, "completed"));
    }

    [Fact]
    public void UncertainRewardsSurviveRoomChangesAndLateReceiptsCannotResolveAbsentPending()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, Coop());
        state = state with { Coop = Seed(state.Coop, ("reward_uncertain", true), ("reward", Map(("open_reward", 1))),
            ("received_awards", StateValue.List(Map(("kind", 1), ("id", 111), ("value", 3))))) };
        var next = Apply(state, Coop(10)); next = Apply(next, new CoopRewardReceiptEvent([new(1, 999, 4)]));
        Assert.True(Bool(next.Coop, "reward_uncertain")); Assert.Equal(1, Int(next.Coop["reward"], "open_reward"));
        Assert.Equal(111, Int(next.Coop["received_awards"][0], "id")); Assert.Null(next.Coop["claim_result"].ScalarValue);
    }

    [Fact]
    public void ClosedChestWithoutReceiptIsExplicitlyUnverifiedAndEmptyReceiptIsNotSuccess()
    {
        var state = new InstanceReceiveSnapshot { Coop = Seed(InstanceReceiveSnapshot.Empty.Coop, ("claim_pending", Map(("started", 1)))) };
        state = Apply(state, new CoopRewardReceiptEvent([])); Assert.NotNull(state.Coop["claim_pending"].MapValue);
        state = Apply(state, new CoopRewardStatusEvent(3, 3, 0, 0, 1));
        Assert.Equal("server_closed_unverified_awards", Text(state.Coop, "claim_result")); Assert.Empty(state.Coop["received_awards"].SequenceValue);
        state = Apply(state, new CoopRewardReceiptEvent([new(1, 2, 3)])); Assert.Empty(state.Coop["received_awards"].SequenceValue);
    }

    [Fact]
    public void CatalogDungeonNoticeDoesNotBecomeHeroChallengeProgress()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, new MainNewInfoTextEvent(99, "synthetic", 222));
        Assert.Equal(222, Int(state.Main["challenge_notice"], "npc_id")); Assert.False(Bool(state.Main, "completed"));
        Assert.Null(state.Main["room"].ScalarValue); Assert.Empty(state.Main["objectives"].MapValue);
    }

    [Fact]
    public void DefaultsAndImportsRetainNoCallerOwnedMutableContainers()
    {
        var roles = new List<StateValue> { Map(("role_id", 42)) };
        var pending = new Dictionary<string, StateValue> { ["room_id"] = StateValue.Scalar(500) };
        var state = new InstanceReceiveSnapshot { Main = Seed(InstanceReceiveSnapshot.Empty.Main,
            ("members", StateValue.List(roles)), ("join_pending", StateValue.Map(pending))) };
        roles.Clear(); pending["room_id"] = StateValue.Scalar(999);
        Assert.Single(state.Main["members"].SequenceValue); Assert.Equal(500, Int(state.Main["join_pending"], "room_id"));
        var changed = Apply(state, new MainResultEvent("join", 0));
        Assert.False(state.Main["join_pending"].MapValue.ContainsKey("accepted")); Assert.True(Bool(changed.Main["join_pending"], "accepted"));
        Assert.Empty(InstanceReceiveSnapshot.Empty.Main["members"].SequenceValue);
    }

    [Fact]
    public void RoleListAndUnknownPacketsDoNotInventLifecycleReset()
    {
        var state = Apply(InstanceReceiveSnapshot.Empty, Room());
        Assert.Same(state, Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([]))));
        Assert.Same(state, Apply(state, new InitialDataCompleteEvent()));
        Assert.Same(state, Apply(state, new UnimplementedServerEvent(255, 255, 10)));
    }

    private static ServerEvent EntryEvent(JsonNode e) => e["type"]!.GetValue<string>() switch
    {
        "instance_members" => new ServerInstanceEvent(186, 3, new CoopMembersEvent(e["room_id"]!.GetValue<ushort>(),
            e["host_id"]?.GetValue<uint>(), e["created"]!.GetValue<bool>(), e["joined"]!.GetValue<bool>(),
            e["standby"]!.GetValue<bool>(), e["kind"]!.GetValue<byte>(), e["npc_id"]!.GetValue<byte>(), e["capacity"]!.GetValue<byte>(),
            e["members"]!.AsArray().Select(m => new CoopInstanceMember(m!["role_id"]!.GetValue<uint>(), m["status"]!.GetValue<byte>(),
                m["hp"]!.GetValue<uint>(), m["max_hp"]!.GetValue<uint>(), m["sp"]!.GetValue<uint>(), m["max_sp"]!.GetValue<uint>())).ToImmutableArray())),
        "position_snapshot" => Position(e["role_id"]!.GetValue<uint>(), e["scene"]!.GetValue<ushort>()),
        "world_player" => new ServerLayoutEvent(new WorldPlayerEvent(new(e["player"]!["role_id"]!.GetValue<uint>(), 0,
            e["player"]!["scene"]!.GetValue<ushort>(), 0, 0, 0, 0, 0, 0, 0, 0, false, [], "synthetic", 0))),
        "battle_start" => new ServerLayoutEvent(new BattleStartEvent(0, 0, [])),
        "fight_exit" => new FightExitEvent(e["role_id"]!.GetValue<uint>(), 0),
        "winner" => new WinnerEvent(e["side"]!.GetValue<byte>()),
        _ => throw new InvalidOperationException("Unsupported synthetic observation")
    };
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
    private static JsonNode Project(InstanceReceiveSnapshot state) => new JsonObject { ["main"] = Write(state.Main), ["coop"] = Write(state.Coop) };
    private static void Check(JsonNode expected, InstanceReceiveSnapshot state, string where)
    {
        var actual = Project(state);
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{where}\nExpected {expected.ToJsonString()}\nActual {actual.ToJsonString()}");
    }
    private static string FindRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "wlre/services/instances.py"))) return directory.FullName;
        throw new DirectoryNotFoundException("Retained Python source root not found.");
    }
    private static byte[] NormalizeCrLf(byte[] bytes)
    {
        var output = new List<byte>(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
            if (bytes[i] != 13 || i + 1 == bytes.Length || bytes[i + 1] != 10) output.Add(bytes[i]);
        return output.ToArray();
    }
}
