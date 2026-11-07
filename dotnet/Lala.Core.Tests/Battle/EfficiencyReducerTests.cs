using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class EfficiencyReducerTests
{
    private static readonly EfficiencySubject Pet = EfficiencySubject.Companion(2);
    private static EfficiencyKnowledgeSnapshot Knowledge(uint? role = 71, long total = 10000) =>
        new(role, new(20000, 15, 0), new Dictionary<int, EfficiencyCompanion> { [2] = new(8002, new(total, 12, 0)) });
    private static EfficiencySnapshot Pending() => EfficiencyReducer.Apply(
        EfficiencyReducer.Apply(EfficiencySnapshot.Empty, Knowledge(),
            new EfficiencyBattleStart([new(71), new(8002, 71, 2)]) { ObservedAt = 0 }),
        Knowledge(), new EfficiencyAttributeSet(Pet, 36, 10000, HumanKind: 4) { ObservedAt = 1 });

    [Fact]
    public void CompletingTwoIndependentBranchesCannotMutateTheirSharedPendingInput()
    {
        var before = Pending();
        var rows = before.Rows.ToArray();
        var first = EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyEventEnd { ObservedAt = 10 });
        var second = EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyEventEnd { ObservedAt = 20, Offline = true });
        Assert.True(before.Pending);
        Assert.False(before.Offline);
        Assert.Equal(0, before.Battles);
        Assert.Equal(new[] { Pet }, before.Dirty);
        Assert.Equal(2, before.Participants.Length);
        Assert.Equal(rows, before.Rows.ToArray());
        Assert.Empty(before.Rows[Pet].History);
        Assert.Equal(10, first.Rows[Pet].LastTime);
        Assert.Equal(20, second.Rows[Pet].LastTime);
        Assert.False(first.Offline);
        Assert.True(second.Offline);
        Assert.Equal(1, first.Battles);
        Assert.Equal(1, second.Battles);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<EfficiencySubject, EfficiencyRowSnapshot>)first.Rows).Clear());
        Assert.Empty(EfficiencySnapshot.Empty.Rows);
    }

    [Fact]
    public void ThrowingClockAfterStagedRoleResetRollsBackEveryPublishedField()
    {
        var before = Pending();
        var marker = new InvalidOperationException("clock failure");
        Assert.Same(marker, Assert.Throws<InvalidOperationException>(() =>
            EfficiencyReducer.Apply(before, Knowledge(72), new EfficiencyEventEnd { Offline = true }, () => throw marker)));
        Assert.Equal(71u, before.RoleId);
        Assert.True(before.Pending);
        Assert.False(before.Offline);
        Assert.Equal(0, before.Battles);
        Assert.Single(before.Dirty);
        Assert.Equal(2, before.Participants.Length);
        Assert.Equal(8002u, before.Rows[Pet].Identity);
        var resumed = EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyEventEnd { ObservedAt = 10 });
        Assert.Equal(1, resumed.Battles);
        Assert.Equal(10000, resumed.Rows[Pet].LastTotal);
    }

    [Fact]
    public void ExplicitClockIsLazyAndRequiredOnlyForEligibleMissingTimes()
    {
        int calls = 0;
        double Clock() { calls++; return 0; }
        var before = Pending();
        EfficiencyReducer.Apply(before, Knowledge(0), new EfficiencyRefresh(), Clock);
        EfficiencyReducer.Apply(before, Knowledge(null), new EfficiencyRefresh(), Clock);
        EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyRefresh { ObservedAt = 17 }, Clock);
        Assert.Equal(0, calls);
        var completed = EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyEventEnd(), Clock);
        Assert.Equal(1, calls);
        Assert.Equal(0, completed.Rows[Pet].LastTime);
        Assert.Throws<InvalidOperationException>(() => EfficiencyReducer.Apply(before, Knowledge(72), new EfficiencyRefresh()));
        Assert.Equal(71u, before.RoleId);
        Assert.True(before.Pending);
        Assert.Equal(71u, EfficiencyReducer.Apply(before, Knowledge(0), new EfficiencyRefresh()).RoleId);
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.NegativeInfinity)]
    [InlineData(double.PositiveInfinity)]
    public void NonfiniteTimePreservesPendingButNewNonzeroRoleStillResets(double time)
    {
        var before = Pending();
        var same = EfficiencyReducer.Apply(before, Knowledge(), new EfficiencyEventEnd { ObservedAt = time, Offline = true });
        Assert.True(same.Pending);
        Assert.False(same.Offline);
        Assert.Equal(before.Rows[Pet], same.Rows[Pet]);
        var changed = EfficiencyReducer.Apply(before, Knowledge(72), new EfficiencyEventEnd { ObservedAt = time, Offline = true });
        Assert.Equal(72u, changed.RoleId);
        Assert.Empty(changed.Rows);
        Assert.False(changed.Pending);
        Assert.False(changed.Offline);
        Assert.True(before.Pending);
        Assert.Equal(71u, before.RoleId);
    }

    [Fact]
    public void UnrecognizedServerEventRefreshesAllProvidedKnowledgeWithoutCompletingBattle()
    {
        var before = Pending();
        var changed = EfficiencyReceiveReducer.Apply(before, new(71, new(42, 2, 1),
            new Dictionary<int, EfficiencyCompanion> { [3] = new(8003, new(70, 3, 0, "New pet")) }, "New name"),
            new UnimplementedServerEvent(255, 255, 0), 5, true);
        Assert.True(changed.Pending);
        Assert.Equal(0, changed.Battles);
        Assert.Equal("New name", changed.Rows[EfficiencySubject.Player].Name);
        Assert.Equal(42, changed.Rows[EfficiencySubject.Player].Experience);
        Assert.False(changed.Rows.ContainsKey(Pet));
        Assert.True(changed.Rows.ContainsKey(EfficiencySubject.Companion(3)));
        Assert.True(before.Rows.ContainsKey(Pet));
        Assert.False(before.Offline);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(256)]
    [InlineData(65535)]
    public void UnrepresentableCompanionDoesNotAliasPlayerOrPartiallyPublish(int slot)
    {
        var before = Pending();
        var value = new AttributeSetEvent(2, $"follow:{slot}", 4, (ushort)slot, 36, "exp", 1, 22, 0);
        Assert.Throws<ArgumentException>(() => EfficiencyReceiveReducer.Apply(before, Knowledge(), value, 20, true));
        Assert.True(before.Pending);
        Assert.False(before.Offline);
        Assert.Null(before.Rows[Pet].LastTotal);
        Assert.Equal(71u, EfficiencyReceiveReducer.Apply(before, Knowledge(0), value, 20).RoleId);
        Assert.Empty(EfficiencyReceiveReducer.Apply(before, Knowledge(72), value, double.NaN).Rows);
    }

    [Fact]
    public void AdaptedAttributeUsesEntityAndKeepsWrongKindParameterAndHumanKindAsRefresh()
    {
        var value = new AttributeSetEvent(2, "follow:2", 4, 3, 36, "exp", 1, 22, 0);
        Assert.Equal(Pet, Assert.IsType<EfficiencyAttributeSet>(EfficiencyReceiveReducer.Adapt(value, 0)).Subject);
        Assert.IsType<EfficiencyRefresh>(EfficiencyReceiveReducer.Adapt(value with { Kind = 35 }, 0));
        Assert.IsType<EfficiencyRefresh>(EfficiencyReceiveReducer.Adapt(value with { Parameter = uint.MaxValue }, 0));
        Assert.IsType<EfficiencyRefresh>(EfficiencyReceiveReducer.Adapt(value with { HumanKind = 9 }, 0));
        Assert.IsType<EfficiencyRefresh>(EfficiencyReceiveReducer.Adapt(value with { Entity = "player:71" }, 0));
        Assert.Equal(EfficiencySubject.Player, Assert.IsType<EfficiencyAttributeSet>(
            EfficiencyReceiveReducer.Adapt(value with { Entity = "self", HumanKind = 9 }, 0)).Subject);
    }

    [Fact]
    public void InvalidTypedBattlePayloadFailsWithoutConsumingPendingState()
    {
        var before = Pending();
        var malformed = new ServerLayoutEvent(new BattleStartEvent(1, 2, [(BattleUnit)null!]));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReceiveReducer.Apply(before, Knowledge(72), malformed, 10));
        Assert.True(before.Pending);
        Assert.Equal(71u, before.RoleId);
        Assert.Single(before.Dirty);
        Assert.Equal(1, EfficiencyReceiveReducer.Apply(before, Knowledge(), new EventEndEvent(), 20).Battles);
    }

    [Fact]
    public void NullBoundariesAreRejected()
    {
        Assert.Throws<ArgumentNullException>(() => EfficiencyReducer.Apply(null!, Knowledge(), new EfficiencyRefresh()));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReducer.Apply(EfficiencySnapshot.Empty, null!, new EfficiencyRefresh()));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReducer.Apply(EfficiencySnapshot.Empty, Knowledge(), null!));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReducer.Apply(EfficiencySnapshot.Empty, Knowledge(), new EfficiencyRefresh(), null!));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReceiveReducer.Adapt(null!, 0));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReceiveReducer.Apply(null!, Knowledge(), new EventEndEvent(), 0));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReceiveReducer.Apply(EfficiencySnapshot.Empty, null!, new EventEndEvent(), 0));
        Assert.Throws<ArgumentNullException>(() => EfficiencyReceiveReducer.Apply(EfficiencySnapshot.Empty, Knowledge(), null!, 0));
    }
}
