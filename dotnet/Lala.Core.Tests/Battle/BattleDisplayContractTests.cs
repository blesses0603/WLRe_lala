using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleDisplayContractTests
{
    private static BattleUnit Unit(string name = "角色", byte col = 3, byte row = 1) =>
        new(16, 0, 71, 0, 0, col, row, 100, 40, 90, 20, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, name, []);
    private static BattleEventSnapshot State() =>
        BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(12, 3, [Unit()]));
    private static AttackAction Action() => new(3, 1, 10001, 255, 254, "不得覆蓋固定名稱",
        [new(3, 1, 255, 254, [new(25, "ignored", uint.MaxValue, 2), new(26, "ignored", 0, 1)])]);

    [Fact]
    public void RenderingDoesNotDeriveHpResolveCommandsCountActionsOrChangeAnyInput()
    {
        var state = BattleEventReducer.Apply(State(), new BattleCommandSentEvent(3, 1, SkillId: 10001));
        state = BattleEventReducer.Apply(state, new BattleAttributeSetEvent([new(3, 1, 25, 7), new(3, 1, 26, uint.MaxValue)]));
        var report = new AttackResultEvent([Action(), Action()]);
        var beforeState = JsonSerializer.Serialize(state);
        var beforeReport = JsonSerializer.Serialize(report);
        var lines = BattleDisplayRules.AttackLines(report, state);
        Assert.Equal(2, lines.Length);
        Assert.All(lines, line => Assert.Equal("角色(3:1) → 角色(3:1)｜空手普攻(10001)｜HP 爆擊傷害 4294967295、SP 傷害 0", line));
        Assert.Equal(beforeState, JsonSerializer.Serialize(state));
        Assert.Equal(beforeReport, JsonSerializer.Serialize(report));
        Assert.Equal(7u, state.Units[0].Hp);
        Assert.Equal(uint.MaxValue, state.Units[0].Sp);
        Assert.Equal(BattleCommandStatus.Sent, state.Commands[0].Status);
        Assert.Empty(state.LastActions);
        Assert.False(state.HasLastActions);
    }

    [Fact]
    public void InactiveExitedAndZeroHpUnitsRemainNamedWithoutFiltering()
    {
        var state = BattleEventReducer.Apply(State(), new BattleUnitExitEvent(3, 1, null), 71);
        state = BattleEventReducer.Apply(state, new BattleAttributeSetEvent([new(3, 1, 25, 0)]));
        Assert.False(state.Active);
        Assert.True(state.Units[0].Exited);
        Assert.Equal("角色(3:1)", BattleDisplayRules.UnitLabel(state, new(3, 1)));
        Assert.Single(BattleDisplayRules.AttackLines(new([Action()]), state));
    }

    [Fact]
    public void RenderingDoesNotSubstitutePreviouslyRetainedActionsForEmptyReport()
    {
        var state = BattleEventReducer.Apply(State(), new AttackResultEvent([Action()]));
        var lines = BattleDisplayRules.AttackLines(new([]), state);
        Assert.False(lines.IsDefault);
        Assert.Empty(lines);
        Assert.Single(state.LastActions);
        Assert.Empty(BattleDisplayRules.AttackLines(new([Action() with { Targets = [] }]), state));
    }

    [Fact]
    public void HistoricalOutputIsImmutableAndUnaffectedByLaterReplacementSnapshots()
    {
        var state = State();
        var report = new AttackResultEvent([Action()]);
        var lines = BattleDisplayRules.AttackLines(report, state);
        var original = lines[0];
        var newState = BattleEventReducer.Apply(state, new BattleUnitsEvent([Unit("改名")]));
        var newReport = report with { Actions = [Action() with { SkillId = 65535, SkillName = "新技能" }] };
        var next = BattleDisplayRules.AttackLines(newReport, newState);
        Assert.NotEqual(original, next[0]);
        Assert.Equal(original, lines[0]);
        Assert.Equal("角色(3:1)", BattleDisplayRules.UnitLabel(state, new(3, 1)));
        Assert.Throws<NotSupportedException>(() => ((IList<string>)lines)[0] = "changed");
    }

    [Fact]
    public void AttackMetadataIsNotInventedAsAdditionalEffectOrOutcomeText()
    {
        var action = Action();
        var state = State();
        var before = BattleDisplayRules.AttackLines(new([action]), state);
        var changed = action with
        {
            SkillLevel = 0, FightArea = 0,
            Targets = [action.Targets[0] with { AttackResult = 0, HitAction = 0 }]
        };
        Assert.Equal(before.ToArray(), BattleDisplayRules.AttackLines(new([changed]), state).ToArray());
    }

    [Fact]
    public void NullAndEmptyNamesUseSourceFallbackWhileWhitespaceSurvives()
    {
        foreach (var name in new[] { null, "", " " })
        {
            var state = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent([Unit(name!)]));
            Assert.Equal(name == " " ? " (3:1)" : "未知單位(3:1)", BattleDisplayRules.UnitLabel(state, new(3, 1)));
            var action = Action() with { SkillId = 65535, SkillName = name! };
            var line = Assert.Single(BattleDisplayRules.AttackLines(new([action]), state));
            Assert.Contains(name == " " ? "｜ (65535)｜" : "｜技能(65535)｜", line);
        }
    }

    [Fact]
    public async Task ConcurrentRenderingUsesOnlyItsExplicitImmutableInputs()
    {
        var state = State();
        var report = new AttackResultEvent([Action()]);
        var expected = BattleDisplayRules.AttackLines(report, state);
        var results = await Task.WhenAll(Enumerable.Range(0, 32)
            .Select(_ => Task.Run(() => BattleDisplayRules.AttackLines(report, state))));
        Assert.All(results, result => Assert.Equal(expected.ToArray(), result.ToArray()));
    }

    [Fact]
    public void NullPublicInputsAreRejectedWithoutChangingState()
    {
        Assert.Throws<ArgumentNullException>(() => BattleDisplayRules.UnitLabel(null!, new(3, 1)));
        Assert.Throws<ArgumentNullException>(() => BattleDisplayRules.AttackLines(null!, State()));
        Assert.Throws<ArgumentNullException>(() => BattleDisplayRules.AttackLines(new([]), null!));
    }
}
