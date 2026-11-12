using System.Collections.Immutable;
using System.Numerics;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleEventReducerTests
{
    private static BattleUnit Unit(byte col = 3, byte row = 1, uint pid = 71, uint master = 0,
        uint hp = 90, ushort sp = 20) => new(16, 0, pid, 2, master, col, row, 100, 40, hp, sp,
            19, 2, 1, 3, 0, 0, 1, 2, 0, 0, "Fixture", [new(123, 456)]);
    private static BattleEventSnapshot Start(params BattleUnit[] units) =>
        BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(12, 3, [.. units]), 71);
    private static AttackAction Action(byte col = 3, byte row = 1) => new(col, row, 10001, 9, 255,
        "unknown", [new(3, 1, 255, 254, [new(25, "hp", uint.MaxValue, 2), new(26, "sp", 10, 1)])]);

    [Fact]
    public void DefaultsDoNotInventActiveRoundOrObservedCollections()
    {
        var state = BattleEventSnapshot.Empty;
        Assert.Null(state.Active); Assert.Null(state.Round); Assert.Null(state.Stage);
        Assert.Null(state.FightNumber); Assert.Null(state.WinnerSide); Assert.Null(state.WarStyle);
        Assert.False(state.HasCommands); Assert.False(state.HasLastActions);
        Assert.Equal(BigInteger.Zero, state.Actions); Assert.Equal(BigInteger.Zero, state.BattleCount);
        Assert.Empty(state.Units); Assert.Empty(state.Commands); Assert.Empty(state.LastActions);
    }

    [Fact]
    public void EveryStartCountsAndClearsOnlyBattleDomainHistory()
    {
        var start = new BattleStartEvent(12, 3, [Unit()]);
        var state = BattleEventReducer.Apply(BattleEventSnapshot.Empty, start);
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(3, 1));
        state = BattleEventReducer.Apply(state, new AttackResultEvent([Action()]));
        state = BattleEventReducer.Apply(state, new WarStyleEvent(16));
        state = BattleEventReducer.Apply(state, new WinnerEvent(255));
        state = BattleEventReducer.Apply(state, start);
        Assert.Equal(new BigInteger(2), state.BattleCount); Assert.Equal(BigInteger.Zero, state.Actions);
        Assert.True(state.Active); Assert.Equal((ushort)0, state.Round);
        Assert.Null(state.WinnerSide); Assert.Null(state.WarStyle);
        Assert.True(state.HasCommands); Assert.Empty(state.Commands);
        Assert.False(state.HasLastActions); Assert.Empty(state.LastActions);
        Assert.Single(state.Units);
    }

    [Fact]
    public void UnitAndCommandReplacementPreserveFirstInsertionOrder()
    {
        var state = Start(Unit(4, 4), Unit(1, 1, 22), Unit(4, 4, 33));
        Assert.Equal(new[] { new BattleSlot(4, 4), new BattleSlot(1, 1) }, state.Units.Select(u => u.Slot));
        Assert.Equal(33u, state.Units[0].Layout.Pid);
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(4, 4, SkillId: 10001));
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(1, 1, SkillId: 10002));
        state = BattleEventReducer.Apply(state, new AttackResultEvent([Action(4, 4)]));
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(4, 4, ItemId: 100, BagIndex: 9));
        Assert.Equal(new[] { new BattleSlot(4, 4), new BattleSlot(1, 1) }, state.Commands.Select(c => c.Slot));
        Assert.Equal(BattleCommandStatus.Sent, state.Commands[0].Status);
        Assert.Null(state.Commands[0].Event.SkillId);
        Assert.Equal((ushort)100, state.Commands[0].Event.ItemId);
    }

    [Fact]
    public void SameRoundRetainsCommandsButAnyDifferentRoundResetsThem()
    {
        var state = BattleEventReducer.Apply(Start(), new BattleCommandSentEvent(3, 1));
        var same = BattleEventReducer.Apply(state, new RoundStartEvent(0));
        Assert.Equal(state.Commands, same.Commands);
        var next = BattleEventReducer.Apply(same, new RoundStartEvent(65535));
        Assert.Empty(next.Commands);
        next = BattleEventReducer.Apply(next, new BattleCommandSentEvent(3, 1));
        Assert.Empty(BattleEventReducer.Apply(next, new RoundStartEvent(1)).Commands);
    }

    [Fact]
    public void AttackResolvesOnlyActorNotTargetAndNeverChangesHpOrSp()
    {
        var state = BattleEventReducer.Apply(Start(Unit(), Unit(1, 1)), new BattleCommandSentEvent(3, 1));
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(1, 1));
        var result = BattleEventReducer.Apply(state, new AttackResultEvent([Action(1, 1)]));
        Assert.Equal(state.Units, result.Units);
        Assert.Equal(BattleCommandStatus.Sent, result.Commands[0].Status);
        Assert.Equal(BattleCommandStatus.Resolved, result.Commands[1].Status);
        Assert.Equal(uint.MaxValue, result.LastActions[0].Targets[0].Attributes[0].Value);
        Assert.Equal((byte)2, result.LastActions[0].Targets[0].Attributes[0].Sign);
    }

    [Fact]
    public void DuplicateAndLateReportsRemainReportsEvenWithoutUnitsOrActiveBattle()
    {
        var attack = new AttackResultEvent([Action(), Action()]);
        var first = BattleEventReducer.Apply(BattleEventSnapshot.Empty, attack);
        var second = BattleEventReducer.Apply(first, attack);
        Assert.Equal(new BigInteger(4), second.Actions);
        Assert.False(second.HasCommands); Assert.Empty(second.Commands); Assert.Null(second.Active);
        second = BattleEventReducer.Apply(second, new WinnerEvent(1));
        second = BattleEventReducer.Apply(second, attack);
        Assert.False(second.Active); Assert.Equal(new BigInteger(6), second.Actions);
        second = BattleEventReducer.Apply(second, new AttackResultEvent([]));
        Assert.True(second.HasLastActions); Assert.Empty(second.LastActions);
        Assert.Equal(new BigInteger(6), second.Actions);
    }

    [Fact]
    public void AttributesAreReplacementsNotDeltasOrClampedValues()
    {
        var state = Start(Unit());
        var result = BattleEventReducer.Apply(state, new BattleAttributeSetEvent([
            new(3, 1, 25, 0), new(3, 1, 25, uint.MaxValue), new(3, 1, 26, uint.MaxValue),
            new(3, 1, 27, 111), new(3, 1, 255, 12)]));
        var unit = Assert.Single(result.Units);
        Assert.Equal(uint.MaxValue, unit.Hp); Assert.Equal(uint.MaxValue, unit.Sp);
        Assert.Equal(4, unit.Attributes.Count); Assert.Equal(111u, unit.Attributes[27]);
        Assert.Equal(90u, unit.Layout.Hp); Assert.Equal((ushort)20, unit.Layout.Sp);
        Assert.Equal(90u, state.Units[0].Hp); Assert.Empty(state.Units[0].Attributes);
    }

    [Fact]
    public void MissingUnitUpdatesAreNotBufferedAndReplacementDropsOldAttributesAndExit()
    {
        var attrs = new BattleAttributeSetEvent([new(3, 1, 25, 1)]);
        Assert.Same(BattleEventSnapshot.Empty, BattleEventReducer.Apply(BattleEventSnapshot.Empty, attrs));
        var state = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent([Unit()]));
        Assert.Equal(90u, state.Units[0].Hp); Assert.Equal(BigInteger.Zero, state.BattleCount);
        Assert.Null(state.Active); Assert.Null(state.Round);
        state = BattleEventReducer.Apply(state, attrs);
        state = BattleEventReducer.Apply(state, new BattleUnitExitEvent(3, 1, null), 71);
        var replacement = BattleEventReducer.Apply(state, new BattleUnitsEvent([Unit(hp: 12, sp: 3)]));
        Assert.Equal(12u, replacement.Units[0].Hp); Assert.Equal(3u, replacement.Units[0].Sp);
        Assert.Empty(replacement.Units[0].Attributes); Assert.False(replacement.Units[0].Exited);
        Assert.False(replacement.Active);
    }

    [Theory]
    [InlineData(null, 0, true)]
    [InlineData(0u, 0u, false)]
    [InlineData(71u, 71u, false)]
    [InlineData(71u, 72u, true)]
    [InlineData(72u, 71u, true)]
    public void UnitExitUsesOnlyCurrentKnownOwnRole(uint? role, uint pid, bool stillActive)
    {
        var state = Start(Unit(pid: pid, master: 71));
        var result = BattleEventReducer.Apply(state, new BattleUnitExitEvent(3, 1, 255), role);
        Assert.True(result.Units[0].Exited); Assert.Equal(stillActive, result.Active);
        Assert.Equal(90u, result.Units[0].Hp);
    }

    [Theory]
    [InlineData(null, 0, true)]
    [InlineData(0u, 0u, false)]
    [InlineData(71u, 71u, false)]
    [InlineData(71u, 72u, true)]
    public void FightExitDoesNotTreatIndexAsRoleIdentity(uint? role, uint exitingRole, bool stillActive)
    {
        var state = Start(Unit());
        var result = BattleEventReducer.Apply(state, new FightExitEvent(exitingRole, 71), role);
        Assert.Equal(stillActive, result.Active);
        Assert.Equal(state.Units, result.Units); Assert.False(result.Units[0].Exited);
    }

    [Fact]
    public void UnknownSlotExitAndUnrelatedTypedEventsAreTrueNoOps()
    {
        var state = Start(Unit());
        Assert.Same(state, BattleEventReducer.Apply(state, new BattleUnitExitEvent(4, 4, null), 71));
        Assert.Same(state, BattleEventReducer.Apply(state, new HeartbeatRequestEvent()));
        Assert.Same(state, BattleEventReducer.Apply(state, new UnimplementedServerEvent(250, 250, 7)));
        Assert.Same(state, BattleEventReducer.Apply(state, new RoleListAvailableEvent([])));
        Assert.Same(state, BattleEventReducer.Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([]))));
    }

    [Theory]
    [InlineData(1)] [InlineData(2)] [InlineData(3)] [InlineData(4)] [InlineData(5)] [InlineData(6)]
    [InlineData(8)] [InlineData(9)] [InlineData(10)] [InlineData(11)] [InlineData(12)] [InlineData(13)]
    [InlineData(15)] [InlineData(20)]
    public void MalformedS51DiscardsWholePacketAndCannotPartiallyOverwriteUnits(int length)
    {
        var record = new PacketWriter().U8(3).U8(1).U8(25).U32(1).Build();
        var bytes = record.Concat(record).Concat(record).Take(length).ToArray();
        var state = Start(Unit());
        var message = Assert.IsType<BattleAttributeInvalidEvent>(ServerProtocol.Decode(new Packet(51, 1, bytes)));
        Assert.Same(state, BattleEventReducer.Apply(state, message));
        var valid = ServerProtocol.Decode(new Packet(51, 1, record));
        Assert.Equal(1u, BattleEventReducer.Apply(state, valid).Units[0].Hp);
    }

    [Fact]
    public void EmptyS51IsNoOpButOtherMalformedPacketsRemainStrictDecoderErrors()
    {
        var state = Start(Unit());
        Assert.Same(state, BattleEventReducer.Apply(state, ServerProtocol.Decode(new Packet(51, 1, []))));
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new Packet(52, 1, [1])));
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new Packet(50, 1, [1])));
        Assert.Equal(90u, state.Units[0].Hp);
    }

    [Fact]
    public void LateTransitionsNeverImplicitlyReactivateTheBattle()
    {
        var state = BattleEventReducer.Apply(Start(Unit()), new WinnerEvent(7));
        state = BattleEventReducer.Apply(state, new RoundStartEvent(4));
        state = BattleEventReducer.Apply(state, new WarStyleEvent(255));
        state = BattleEventReducer.Apply(state, new BattleUnitsEvent([Unit(1, 1)]));
        state = BattleEventReducer.Apply(state, new BattleCommandSentEvent(3, 1));
        state = BattleEventReducer.Apply(state, new AttackResultEvent([Action()]));
        state = BattleEventReducer.Apply(state, new BattleAttributeSetEvent([new(3, 1, 25, 4)]));
        Assert.False(state.Active); Assert.Equal((byte)7, state.WinnerSide);
        Assert.Equal((byte)255, state.WarStyle); Assert.Equal((ushort)4, state.Round);
    }

    [Fact]
    public async Task PureReducerCanBranchSnapshotsOnIndependentThreads()
    {
        var seed = BattleEventReducer.Apply(Start(Unit()), new BattleCommandSentEvent(3, 1));
        var expected = BattleEventParityTests.Project(seed);
        var branches = await Task.WhenAll(Enumerable.Range(0, 16).Select(i => Task.Run(() =>
            BattleEventReducer.Apply(seed, new BattleAttributeSetEvent([new(3, 1, 25, (uint)i)])))));
        for (var i = 0; i < branches.Length; i++) Assert.Equal((uint)i, branches[i].Units[0].Hp);
        Assert.True(JsonNode.DeepEquals(expected, BattleEventParityTests.Project(seed)));
        Assert.Equal(BattleCommandStatus.Sent, seed.Commands[0].Status);
    }

    [Fact]
    public void CallerOwnedBuildersCannotMutatePublishedUnitsCommandsOrReports()
    {
        var equipment = ImmutableArray.CreateBuilder<EquipmentAppearance>(); equipment.Add(new(1, 2));
        var units = ImmutableArray.CreateBuilder<BattleUnit>(); units.Add(Unit() with { Equips = equipment.ToImmutable() });
        var state = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(1, 1, units.ToImmutable()));
        var command = new BattleCommandSentEvent(3, 1, 1, 1, 10001, 42, 17);
        state = BattleEventReducer.Apply(state, command);
        var actions = ImmutableArray.CreateBuilder<AttackAction>(); actions.Add(Action());
        state = BattleEventReducer.Apply(state, new AttackResultEvent(actions.ToImmutable()));
        var before = BattleEventParityTests.Project(state);
        equipment.Clear(); units.Clear(); actions.Clear(); command = command with { Col = 4, ItemId = 99 };
        Assert.True(JsonNode.DeepEquals(before, BattleEventParityTests.Project(state)));
        Assert.Equal(1, state.Units[0].Layout.Equips[0].ItemId);
        Assert.Equal((ushort)42, state.Commands[0].Event.ItemId);
    }

    [Fact]
    public void NullArgumentsAreProgrammingErrorsNotMalformedPacketFallbacks()
    {
        Assert.Throws<ArgumentNullException>(() => BattleEventReducer.Apply(null!, new RoundStartEvent(1)));
        Assert.Throws<ArgumentNullException>(() => BattleEventReducer.Apply(BattleEventSnapshot.Empty, (ServerEvent)null!));
        Assert.Throws<ArgumentNullException>(() => BattleEventReducer.Apply(BattleEventSnapshot.Empty, (LayoutEvent)null!));
        Assert.Throws<ArgumentNullException>(() => BattleEventReducer.Apply(BattleEventSnapshot.Empty, (BattleCommandSentEvent)null!));
    }
}
