using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Expedition;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Expedition;

public sealed class ExpeditionReceiveReducerTests
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static OutpostRole Role(byte index = 1, ushort npc = 101) =>
        new(index, npc, 0, new(10, 20, 30, 40, 50, 60, 2, 7), 90, 4000000000, 255, 65535, 65535);
    private static ExpeditionTeam Team(byte index = 1, ushort minutes = 3, ushort quest = 12)
    {
        var writer = new PacketWriter().U8(index).U16(minutes);
        foreach (var value in new ushort[] { 101, 102, 0, 0, 1, 2, 0, 0, quest }) writer.U16(value);
        return Assert.IsType<ExpeditionTeamEvent>(ExpeditionDecoder.Decode(new Packet(31, 18, writer.Build()))).Team;
    }
    private static ExpeditionSnapshotEvent Snapshot(byte index = 255, byte level = 3) =>
        new(Enumerable.Range(0, 10).Select(_ => Team(index)).ToImmutableArray(),
            Enumerable.Range(0, 50).Select(i => (ushort)i).ToImmutableArray(), level, uint.MaxValue);
    private static ExpeditionReceiveSnapshot Apply(ExpeditionReceiveSnapshot state, ExpeditionEvent observation, double at = 100.25) =>
        ExpeditionReceiveReducer.Apply(state, observation, at);

    [Theory]
    [MemberData(nameof(PythonExpeditionReceiveVectors.Sequences), MemberType = typeof(PythonExpeditionReceiveVectors))]
    public void ActualPythonDecodeAndReceiveSequencesMatchWithoutChangingHistoricalSnapshots(string name, string json)
    {
        var sequence = JsonNode.Parse(json)!;
        var initial = sequence["initial"]!;
        var state = new ExpeditionReceiveSnapshot
        {
            Enabled = initial["enabled"]!.GetValue<bool>(), Pending = initial["pending"]?.GetValue<string>(),
            Uncertain = initial["uncertain"]!.GetValue<bool>(), Status = initial["status"]!.GetValue<string>(),
            Settings = ReadValue(initial["settings"]),
            Revision = BigInteger.Parse(initial["revision"]!.GetValue<string>(), CultureInfo.InvariantCulture),
            Claimed = BigInteger.Parse(initial["claimed"]!.GetValue<string>(), CultureInfo.InvariantCulture)
        };
        var history = new List<(ExpeditionReceiveSnapshot State, JsonNode Expected)> { (state, initial) };
        Check(initial, state, name);
        var stepNumber = 0;
        foreach (var step in sequence["steps"]!.AsArray())
        {
            if (step!["reset"]?.GetValue<bool>() == true) state = new();
            else
            {
                var packet = new Packet(step["main"]!.GetValue<byte>(), step["sub"]!.GetValue<byte>(),
                    Convert.FromHexString(step["hex"]!.GetValue<string>()));
                if (step["error"]!.GetValue<bool>()) Assert.Throws<ProtocolException>(() => ExpeditionDecoder.Decode(packet));
                else if (ExpeditionDecoder.Decode(packet) is { } observation)
                    state = Apply(state, observation, step["at"]!.GetValue<double>());
            }
            Check(step["expected"]!, state, $"{name} step {stepNumber++}");
            history.Add((state, step["expected"]!));
        }
        foreach (var prior in history) Check(prior.Expected, prior.State, name + " historical");
    }

    [Fact]
    public void DefaultsAndFreshStateDoNotInventServerEvidence()
    {
        var state = ExpeditionReceiveSnapshot.Empty;
        Assert.False(state.Ready); Assert.False(state.OutpostReady); Assert.Null(state.Level);
        Assert.Empty(state.Roles); Assert.Empty(state.Teams); Assert.Empty(state.Quests);
        Assert.Equal(BigInteger.Zero, state.Revision); Assert.Equal(BigInteger.Zero, state.Claimed);
        Assert.False(state.Enabled); Assert.Null(state.Pending); Assert.False(state.Uncertain);
        Assert.Equal("尚未啟動", state.Status); Assert.Empty(state.Settings.MapValue);
        var changed = Apply(state, Snapshot());
        Assert.True(changed.Ready); Assert.False(new ExpeditionReceiveSnapshot().Ready);
        Assert.False(state.Ready);
    }

    [Fact]
    public void SnapshotsReplaceOnlyTheirCollectionsAndTeamSlotsAreOrdinals()
    {
        var metadata = new ExpeditionReceiveSnapshot
        {
            Enabled = true, Pending = "claim", Uncertain = true, Status = "carried",
            Claimed = 11, Settings = StateValue.Map(("synthetic", StateValue.List(StateValue.Scalar(7))))
        };
        var state = Apply(metadata, new OutpostSnapshotEvent(0, [Role(1), Role(2), Role(1, 999)]));
        Assert.True(state.OutpostReady); Assert.False(state.Ready); Assert.Equal(2, state.Roles.Count);
        Assert.Equal((ushort)999, state.Roles[1].NpcId); // Last duplicate wins, regardless of capacity.
        state = Apply(state, new ExpeditionTeamEvent(Team(255)));
        var snapshot = Apply(state, Snapshot());
        Assert.Equal(Enumerable.Range(1, 10).Select(i => (byte)i), snapshot.Teams.Keys.Order());
        Assert.All(snapshot.Teams, entry => Assert.Equal(entry.Key, entry.Value.Index));
        Assert.Equal(Enumerable.Range(1, 50).Select(i => (byte)i), snapshot.Quests.Keys.Order());
        Assert.Same(state.Roles, snapshot.Roles); Assert.Equal((byte)3, snapshot.Level);
        var cleared = Apply(snapshot, new OutpostSnapshotEvent(255, []));
        Assert.Empty(cleared.Roles); Assert.True(cleared.OutpostReady); Assert.Same(snapshot.Teams, cleared.Teams);
        Assert.Equal(metadata.Pending, cleared.Pending); Assert.True(cleared.Uncertain); Assert.True(cleared.Enabled);
        Assert.Equal(metadata.Status, cleared.Status); Assert.Equal(metadata.Claimed, cleared.Claimed);
        Assert.Same(metadata.Settings, cleared.Settings);
    }

    [Theory]
    [InlineData(27)] [InlineData(28)] [InlineData(29)] [InlineData(30)] [InlineData(33)] [InlineData(35)] [InlineData(64)]
    public void SignedAttributeReplacementsNeverClampOrWrap(byte kind)
    {
        var state = Apply(ExpeditionReceiveSnapshot.Empty, new OutpostRoleEvent(Role()));
        foreach (var value in new[] { int.MinValue, -1, 0, int.MaxValue })
        {
            state = Apply(state, new OutpostAttributeEvent(1, kind, value));
            var role = state.Roles[1];
            var actual = kind switch
            {
                27 => role.Stats.Int, 28 => role.Stats.Str, 29 => role.Stats.Con, 30 => role.Stats.Agi,
                33 => role.Stats.Wis, 35 => role.Stats.Level, _ => role.Faith
            };
            Assert.Equal(value, actual);
        }
        var replacement = Apply(state, new OutpostRoleEvent(Role()));
        Assert.Equal(10, replacement.Roles[1].Stats.Str); Assert.Equal(90, replacement.Roles[1].Faith);
    }

    [Fact]
    public void MissingAndUnsupportedAttributeUpdatesCountButNeverBuffer()
    {
        var observations = new ExpeditionEvent[]
        {
            new OutpostRemoveEvent(1), new OutpostStatusEvent(1, 255), new OutpostFaithEvent(1, 255, 255),
            new OutpostAttributeEvent(1, 28, -1), new ExpeditionTimeEvent(1, 0)
        };
        var state = ExpeditionReceiveSnapshot.Empty;
        foreach (var observation in observations) state = Apply(state, observation);
        Assert.Equal(new BigInteger(5), state.Revision); Assert.Empty(state.Roles); Assert.Empty(state.Teams);
        state = Apply(state, new OutpostRoleEvent(Role()));
        var unknown = Apply(state, new OutpostAttributeEvent(1, 255, int.MinValue));
        Assert.Equal(state.Roles, unknown.Roles); Assert.Equal(state.Revision + 1, unknown.Revision);
        Assert.Equal(10, unknown.Roles[1].Stats.Str);
    }

    [Fact]
    public void DuplicateAndLateTimesReanchorWithoutCompletingOrClearingTeams()
    {
        var state = Apply(ExpeditionReceiveSnapshot.Empty, new ExpeditionTeamEvent(Team()), 100);
        Assert.False(state.Ready); Assert.Equal(280d, state.Teams[1].Due);
        var duplicate = Apply(state, new ExpeditionTeamEvent(Team()), 200);
        Assert.Equal(380d, duplicate.Teams[1].Due); Assert.Equal(280d, state.Teams[1].Due);
        var late = Apply(duplicate, new ExpeditionTimeEvent(1, 0), 0);
        Assert.Equal(0d, late.Teams[1].Due); Assert.Equal((ushort)12, late.Teams[1].Quest);
        Assert.Equal(new ushort[] { 101, 102, 0, 0 }, late.Teams[1].Members);
        Assert.Equal((ushort)0, late.Teams[1].Minutes); Assert.Equal(new BigInteger(3), late.Revision);
    }

    [Theory]
    [InlineData(null, false)] [InlineData("", false)]
    [InlineData("claim", true)] [InlineData("dispatch", true)] [InlineData("faith", true)]
    public void RejectionNeverClearsPendingAndDoesNotProveConsumptionWasAbsent(string? pending, bool uncertain)
    {
        var initial = new ExpeditionReceiveSnapshot { Enabled = true, Pending = pending, Claimed = 4 };
        var state = Apply(initial, new ExpeditionRejectedEvent(255, 25));
        Assert.False(state.Enabled); Assert.Equal(pending, state.Pending); Assert.Equal(uncertain, state.Uncertain);
        Assert.Equal("伺服器拒絕遠征操作（S31-25 代碼 255）", state.Status);
        state = Apply(state, Snapshot());
        Assert.Equal(uncertain, state.Uncertain); Assert.Equal(pending, state.Pending); Assert.Equal(new BigInteger(4), state.Claimed);
        var latched = Apply(initial with { Uncertain = true }, new ExpeditionRejectedEvent(0, 20));
        Assert.True(latched.Uncertain);
    }

    [Fact]
    public void AnyResultClearsOnlyItsTeamWithoutConfirmingClaimsOrKeepingOldItemsAndDue()
    {
        var initial = new ExpeditionReceiveSnapshot { Pending = "claim", Enabled = true, Uncertain = true, Claimed = 5 };
        initial = Apply(initial, new ExpeditionTeamEvent(Team()));
        var result = new ExpeditionResultEvent(255, 1, 65535, 65535, [new(10, 500, 100), new(255, uint.MaxValue, uint.MaxValue)]);
        var state = Apply(initial, result);
        var team = state.Teams[1];
        Assert.Equal((ushort)0, team.Quest); Assert.Equal((ushort)0, team.Minutes);
        Assert.Equal(new ushort[] { 0, 0, 0, 0 }, team.Members); Assert.Null(team.Items); Assert.Null(team.Due);
        Assert.Equal("claim", state.Pending); Assert.True(state.Enabled); Assert.True(state.Uncertain); Assert.Equal(new BigInteger(5), state.Claimed);
        Assert.False(state.Ready); Assert.Equal((ushort)12, initial.Teams[1].Quest);
        state = Apply(state, result with { Index = 255 });
        Assert.Equal(2, state.Teams.Count);
        state = Apply(state, new ExpeditionTimeEvent(255, 1), 10);
        Assert.Equal(70d, state.Teams[255].Due); Assert.Null(state.Teams[255].Items);
    }

    [Fact]
    public void UnknownStartsAndUnrelatedServerEventsAreTrueNoOpsIncludingRoleLists()
    {
        var state = Apply(ExpeditionReceiveSnapshot.Empty, Snapshot());
        Assert.Same(state, Apply(state, new ExpeditionStartedEvent(12)));
        Assert.Same(state, Apply(state, new FutureExpeditionEvent()));
        Assert.Same(state, ExpeditionReceiveReducer.Apply(state, new HeartbeatRequestEvent(), 1));
        Assert.Same(state, ExpeditionReceiveReducer.Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([])), 1));
        var wrapped = ExpeditionReceiveReducer.Apply(state, new ServerExpeditionEvent(21, new ExpeditionLevelEvent(9, uint.MaxValue)), 1);
        Assert.Equal((byte)9, wrapped.Level); Assert.Equal(state.Revision + 1, wrapped.Revision);
        Assert.Same(state.Teams, wrapped.Teams);
    }

    [Fact]
    public void AllByteSlotsAreRetainedButCannotGrowBeyond256AndCountersDoNotOverflow()
    {
        var state = new ExpeditionReceiveSnapshot { Revision = BigInteger.One << 100 };
        foreach (var index in Enumerable.Range(0, 256).Select(i => (byte)i))
        {
            state = Apply(state, new OutpostRoleEvent(Role(index)));
            state = Apply(state, new ExpeditionTeamEvent(Team(index)));
        }
        Assert.Equal(256, state.Roles.Count); Assert.Equal(256, state.Teams.Count);
        Assert.Equal((BigInteger.One << 100) + 512, state.Revision);
        state = Apply(state, new OutpostRoleEvent(Role(0, 65535)));
        state = Apply(state, new ExpeditionTeamEvent(Team(255, 0)));
        Assert.Equal(256, state.Roles.Count); Assert.Equal(256, state.Teams.Count);
        Assert.Equal((ushort)65535, state.Roles[0].NpcId);
    }

    [Theory]
    [InlineData(0, 50)] [InlineData(9, 50)] [InlineData(11, 50)]
    [InlineData(10, 0)] [InlineData(10, 49)] [InlineData(10, 51)]
    public void InvalidManuallyConstructedSnapshotShapesFailWithoutPartialState(int teams, int quests)
    {
        var state = Apply(ExpeditionReceiveSnapshot.Empty, Snapshot());
        var before = Project(state);
        var invalid = new ExpeditionSnapshotEvent(Enumerable.Repeat(Team(), teams).ToImmutableArray(),
            Enumerable.Repeat((ushort)1, quests).ToImmutableArray(), 0, 0);
        Assert.Throws<ProtocolException>(() => Apply(state, invalid));
        Check(before, state, "invalid shape");
    }

    [Fact]
    public void InvalidOutpostShapesFailAndFiniteClockIsRequiredOnlyWhenUsed()
    {
        var state = ExpeditionReceiveSnapshot.Empty;
        Assert.Throws<ProtocolException>(() => Apply(state, new OutpostSnapshotEvent(0, default)));
        Assert.Throws<ProtocolException>(() => Apply(state, new OutpostSnapshotEvent(0, Enumerable.Repeat(Role(), 256).ToImmutableArray())));
        foreach (var at in new[] { double.NaN, double.NegativeInfinity, double.PositiveInfinity })
        {
            Assert.Throws<ArgumentOutOfRangeException>(() => Apply(state, new ExpeditionTeamEvent(Team()), at));
            Assert.Throws<ArgumentOutOfRangeException>(() => Apply(state, Snapshot(), at));
            Assert.Same(state, Apply(state, new ExpeditionStartedEvent(0), at));
            Assert.Equal(BigInteger.One, Apply(state, new ExpeditionTimeEvent(1, 0), at).Revision);
        }
    }

    [Fact]
    public void MutableInputPacketBytesCannotChangeDecodedAndReducedTeamEvidence()
    {
        var payload = new PacketWriter().U8(1).U16(3);
        foreach (var value in new ushort[] { 101, 102, 0, 0, 1, 2, 0, 0, 12 }) payload.U16(value);
        var bytes = payload.Build();
        var observation = Assert.IsType<ExpeditionTeamEvent>(ExpeditionDecoder.Decode(new Packet(31, 18, bytes)));
        var state = Apply(ExpeditionReceiveSnapshot.Empty, observation);
        Array.Fill(bytes, (byte)255);
        Assert.Equal((ushort)101, state.Teams[1].Members[0]); Assert.Equal((ushort)1, state.Teams[1].Items!.Value[0]);
        Assert.Equal((ushort)101, observation.Team.Members[0]);
        var updated = Apply(state, new ExpeditionTimeEvent(1, 0));
        Assert.Equal(280.25d, state.Teams[1].Due); Assert.Equal(100.25d, updated.Teams[1].Due);
    }

    private sealed record FutureExpeditionEvent : ExpeditionEvent;
    private static void Check(JsonNode expected, ExpeditionReceiveSnapshot state, string context)
    {
        var actual = Project(state);
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => $"{context}\nExpected: {expected}\nActual: {actual}");
    }
    private static JsonObject Project(ExpeditionReceiveSnapshot state)
    {
        var teams = new JsonObject();
        foreach (var (index, team) in state.Teams)
        {
            var value = new JsonObject
            {
                ["index"] = team.Index, ["minutes"] = team.Minutes, ["quest"] = team.Quest,
                ["members"] = JsonSerializer.SerializeToNode(team.Members)
            };
            if (team.Items is { } items) value["items"] = JsonSerializer.SerializeToNode(items);
            if (team.Due is { } due) value["due"] = due;
            teams[index.ToString(CultureInfo.InvariantCulture)] = value;
        }
        return new JsonObject
        {
            ["ready"] = state.Ready, ["outpost_ready"] = state.OutpostReady,
            ["roles"] = JsonSerializer.SerializeToNode(state.Roles, JsonOptions), ["teams"] = teams,
            ["quests"] = JsonSerializer.SerializeToNode(state.Quests), ["level"] = state.Level,
            ["revision"] = state.Revision.ToString(CultureInfo.InvariantCulture),
            ["enabled"] = state.Enabled, ["pending"] = state.Pending, ["uncertain"] = state.Uncertain,
            ["status"] = state.Status, ["settings"] = ProjectValue(state.Settings),
            ["claimed"] = state.Claimed.ToString(CultureInfo.InvariantCulture)
        };
    }
    private static StateValue ReadValue(JsonNode? node) => node switch
    {
        null => StateValue.Null,
        JsonObject map => StateValue.Map(map.Select(pair => KeyValuePair.Create(pair.Key, ReadValue(pair.Value)))),
        JsonArray array => StateValue.List(array.Select(ReadValue)),
        _ => node.GetValueKind() switch
        {
            JsonValueKind.String => StateValue.Scalar(node.GetValue<string>()),
            JsonValueKind.True or JsonValueKind.False => StateValue.Scalar(node.GetValue<bool>()),
            JsonValueKind.Number => StateValue.Scalar(node.GetValue<long>()),
            _ => throw new InvalidOperationException("Invalid fixture scalar")
        }
    };
    private static JsonNode? ProjectValue(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => new JsonObject(value.MapValue.Select(pair => KeyValuePair.Create(pair.Key, ProjectValue(pair.Value)))),
        StateValueKind.List or StateValueKind.Tuple => new JsonArray(value.SequenceValue.Select(ProjectValue).ToArray()),
        _ => JsonSerializer.SerializeToNode(value.ScalarValue)
    };
}
