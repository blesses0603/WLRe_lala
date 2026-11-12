using System.Collections.Immutable;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class AutoBattleContractTests
{
    private static readonly Lazy<JsonNode> Template = new(() => AutoBattlePythonVectors.Read()["cases"]![0]!.DeepClone());
    private static BattleCommandContext Context => BattleCommandParityTests.Context(Template.Value.DeepClone());
    private static CombatResourceActor Actor => Context.Resources.Units.Single(entry => entry.Actor.Pid == 7).Actor;
    private static AutoBattleProfile Off => new() { LowHpEnabled = false,OrderEnabled = false };

    [Theory]
    [InlineData(20,10,1001,AutoBattleReason.LowHp,1)]
    [InlineData(10,10,1002,AutoBattleReason.LowSp,2)]
    [InlineData(10,5,10001,AutoBattleReason.Fallback,3)]
    public void IndependentHpAndSpSkillsKeepStrictThresholdsAndHpFirst(long hpLimit,long spLimit,long skill,AutoBattleReason reason,int col)
    {
        var input = AutoBattlePythonVectors.Read()["cases"]!.AsArray().Single(node => node!["label"]!.GetValue<string>() == "priority sp 1 1001")!;
        var context = BattleCommandParityTests.Context(input);
        var catalog = context.Resources.Catalog;
        catalog = catalog with { Skills = catalog.Skills.SetItem(1002,catalog.Skills[1002] with { Fields = catalog.Skills[1002].Fields.SetItem("TargetKind",1) }) };
        context = context with { Resources = context.Resources with { Catalog = catalog } };
        var profile = Off with { LowHpEnabled = true,LowSpEnabled = true,
            LowHp = new() { Id = 1001,Notice = AutoBattleNotice.Player,Value = hpLimit },
            LowSp = new() { Id = 1002,Notice = AutoBattleNotice.Partner,Value = spLimit } };
        var result = AutoBattleRuleChooser.Choose(context,BattleCommandParityTests.Actor(input["actor"]!),profile);
        Assert.Equal(reason,result.Reason); Assert.Equal(skill,result.Intent!.SkillId); Assert.Equal(col,result.Intent.TargetCol);
    }

    [Theory]
    [InlineData("priority sp 1 -3",2)]
    [InlineData("priority sp 3 -3",1)]
    [InlineData("priority sp 2 -3",1)]
    [InlineData("priority sp 1 1001",2)]
    [InlineData("priority sp 3 1001",1)]
    [InlineData("priority hp 1 1001",1)]
    [InlineData("priority hp 3 1001",2)]
    [InlineData("priority sp 1 10001",4)]
    [InlineData("priority sp 3 10001",3)]
    [InlineData("priority tie",1)]
    [InlineData("priority threshold",1)]
    [InlineData("priority invalid-first",1)]
    [InlineData("priority missing",1)]
    [InlineData("priority self",1)]
    [InlineData("priority other",2)]
    public void ResourcePriorityUsesActualStatAndSkipsInvalidTargets(string label,int col)
    {
        var input = AutoBattlePythonVectors.Read()["cases"]!.AsArray().Single(node => node!["label"]!.GetValue<string>() == label)!;
        var result = AutoBattleRuleChooser.Choose(BattleCommandParityTests.Context(input),BattleCommandParityTests.Actor(input["actor"]!),AutoBattleParityTests.Profile(input["profile"]!));
        Assert.True(result.Success); Assert.Equal(col,result.Intent!.TargetCol);
        Assert.Equal(label.StartsWith("priority hp") ? AutoBattleReason.LowHp : AutoBattleReason.LowSp,result.Reason);
    }

    [Theory]
    [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public void LowSpDefenseDoesNotSelectTheTriggeringAlly(int policy)
    {
        var input = AutoBattlePythonVectors.Read()["cases"]!.AsArray().Single(node => node!["label"]!.GetValue<string>() == $"priority sp {policy} 60021")!;
        var result = AutoBattleRuleChooser.Choose(BattleCommandParityTests.Context(input),BattleCommandParityTests.Actor(input["actor"]!),AutoBattleParityTests.Profile(input["profile"]!));
        Assert.Equal(AutoBattleReason.LowSp,result.Reason); Assert.Equal(BattleCommandKind.Defend,result.Intent!.Kind);
        Assert.Equal(0,result.Intent.TargetCol); Assert.Equal(0,result.Intent.TargetRow);
    }

    [Fact]
    public void DefaultsMatchActualSourcePlayerAndPartnerProfiles()
    {
        var input = AutoBattlePythonVectors.Read();
        Assert.Equal(JsonSerializer.Serialize(AutoBattleParityTests.Profile(input["cases"]![0]!["profile"]!)),JsonSerializer.Serialize(AutoBattleProfile.PlayerDefaults));
        Assert.Equal(JsonSerializer.Serialize(AutoBattleParityTests.Profile(input["cases"]![1]!["profile"]!)),JsonSerializer.Serialize(AutoBattleProfile.PartnerDefaults));
    }

    [Theory]
    [InlineData("dead 8 plain",AutoBattleReason.DeadAlly,1,2)]
    [InlineData("dead 8 first_fly",AutoBattleReason.Fallback,3,1)]
    [InlineData("dead 8 alias",AutoBattleReason.Fallback,3,1)]
    [InlineData("dead 24 plain",AutoBattleReason.DeadAlly,1,2)]
    [InlineData("dead upgrade configured 1",AutoBattleReason.DeadAlly,2,2)]
    [InlineData("dead upgrade configured 8",AutoBattleReason.Fallback,3,1)]
    [InlineData("support upgrade configured 0",AutoBattleReason.LowHp,4,2)]
    [InlineData("support upgrade configured 1",AutoBattleReason.LowHp,4,2)]
    public void ReviveAndPreUpgradeFixturesReachDistinguishingOutcomes(string label,AutoBattleReason reason,int col,int row)
    {
        var input = AutoBattlePythonVectors.Read()["cases"]!.AsArray().Single(node => node!["label"]!.GetValue<string>() == label)!;
        var result = AutoBattleRuleChooser.Choose(BattleCommandParityTests.Context(input),BattleCommandParityTests.Actor(input["actor"]!),AutoBattleParityTests.Profile(input["profile"]!));
        Assert.Equal(reason,result.Reason);Assert.Equal(col,result.Intent!.TargetCol);Assert.Equal(row,result.Intent.TargetRow);
        Assert.True(JsonNode.DeepEquals(input["expected"],AutoBattleParityTests.Project(result)));
    }

    [Fact]
    public void NormalizationPadsShortArraysWithZeroActionsAndForcesRecoveryKindWithoutMutatingInput()
    {
        var profile = Off with { RoundActions = [],RepeatActions = [new() { Id = 60041 }],OrderActions = [],LowHp = new() { Id = -2 },LowSp = new() { Id = -3 } };
        var normalized = AutoBattleProfiles.Normalize(profile,CombatResourceCatalog.Empty);
        Assert.Equal(3,normalized.RoundActions.Length);Assert.Equal(5,normalized.RepeatActions.Length);Assert.Equal(2,normalized.OrderActions.Length);
        Assert.All(normalized.RoundActions,action => Assert.Equal(0,action.Id));Assert.All(normalized.OrderActions,action => Assert.Equal(0,action.Id));
        Assert.Equal(60041,normalized.RepeatActions[0].Id);Assert.All(normalized.RepeatActions.Skip(1),action => Assert.Equal(0,action.Id));
        Assert.Equal(AutoBattleActionKind.Item,normalized.LowHp.Kind);Assert.Equal(AutoBattleActionKind.Item,normalized.LowSp.Kind);
        Assert.Empty(profile.RoundActions);Assert.Single(profile.RepeatActions);Assert.Equal(AutoBattleActionKind.Skill,profile.LowHp.Kind);
    }

    [Theory]
    [InlineData(-4)]
    [InlineData(65536)]
    public void IdBoundsAreRejectedEvenForDisabledRules(int id) => Assert.Throws<ArgumentException>(() =>
        AutoBattleProfiles.Normalize(Off with { Dead = new() { Id = id } },CombatResourceCatalog.Empty));

    [Fact]
    public void InvalidEnumsNextItemSkillAndNullActionsAreRejected()
    {
        foreach (var action in new AutoBattleAction[] { new() { Kind = (AutoBattleActionKind)0 },new() { Target = (AutoBattleTargetPolicy)4 },
            new() { Notice = (AutoBattleNotice)0 },new() { Comparison = (AutoBattleComparison)3 },new() { Kind = AutoBattleActionKind.Item,UseNextSkill = true },
            new() { Id = -2,UseNextSkill = true } })
            Assert.Throws<ArgumentException>(() => AutoBattleProfiles.Normalize(Off with { Dead = action },CombatResourceCatalog.Empty));
        Assert.Throws<ArgumentNullException>(() => AutoBattleProfiles.Normalize(Off with { Dead = null! },CombatResourceCatalog.Empty));
        Assert.Throws<ArgumentNullException>(() => AutoBattleProfiles.Normalize(Off with { RoundActions = [null!] },CombatResourceCatalog.Empty));
    }

    [Fact]
    public void UninitializedOrOverLimitArraysCannotSilentlyBecomeDefaults()
    {
        foreach (var profile in new AutoBattleProfile[] { Off with { RoundActions = default },Off with { RepeatActions = default },Off with { OrderActions = default },
            Off with { RoundActions = [new(),new(),new(),new()] },Off with { RepeatActions = [new(),new(),new(),new(),new(),new()] },Off with { OrderActions = [new(),new(),new()] } })
            Assert.Throws<ArgumentException>(() => AutoBattleProfiles.Normalize(profile,CombatResourceCatalog.Empty));
    }

    [Fact]
    public void CatalogMembershipIsEvidenceNotInventedData()
    {
        var context = Context;
        Assert.Throws<ArgumentException>(() => AutoBattleProfiles.Normalize(Off with { Dead = new() { Id = 9999 } },context.Resources.Catalog));
        Assert.Throws<ArgumentException>(() => AutoBattleProfiles.Normalize(Off with { Dead = new() { Id = 0,Kind = AutoBattleActionKind.Item,UseNextSkill = true } },context.Resources.Catalog));
        Assert.Throws<ArgumentException>(() => AutoBattleProfiles.Normalize(Off with { Dead = new() { Id = 1001,Kind = AutoBattleActionKind.Item } },context.Resources.Catalog));
        Assert.Equal(9999,AutoBattleProfiles.Normalize(Off with { Dead = new() { Id = 9999 } },CombatResourceCatalog.Empty).Dead.Id);
    }

    [Fact]
    public void NonfiniteOrNegativeThresholdsAreRejectedAtConstruction()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new AutoBattleThreshold(-1L));
        foreach (var value in new[] { -1d,double.NaN,double.PositiveInfinity,double.NegativeInfinity })
            Assert.Throws<ArgumentOutOfRangeException>(() => new AutoBattleThreshold(value));
    }

    [Fact]
    public void StrictIntegerAndBinary64ThresholdsRemainDistinctPastTwoToThe53()
    {
        var context = Context;var enemy = context.Resources.Units[0].Actor with { Stats = context.Resources.Units[0].Actor.Stats.SetItem("hp",9007199254740993) };
        context = context with { Resources = context.Resources with { Units = [new("4:2",enemy)] } };
        var profile = Off with { EnemyHpEnabled = true,EnemyHp = new() { Id = 60021,Value = 9007199254740993L } };
        Assert.Equal(AutoBattleReason.Fallback,AutoBattleRuleChooser.Choose(context,Actor,profile).Reason);
        Assert.Equal(AutoBattleReason.EnemyHp,AutoBattleRuleChooser.Choose(context,Actor,profile with { EnemyHp = profile.EnemyHp with { Value = 9007199254740992d } }).Reason);
        Assert.Equal(AutoBattleReason.Fallback,AutoBattleRuleChooser.Choose(context,Actor,profile with { EnemyHp = profile.EnemyHp with { Value = double.MaxValue } }).Reason);
    }

    [Fact]
    public void NoActiveRoundGateAndNegativeModuloDoesNotOverflow()
    {
        var context = Context with { Active = false,Round = long.MinValue };
        var profile = Off with { RepeatEnabled = true,RepeatActions = [new() { Id = 60021 },new() { Id = 60041 }] };
        var result = AutoBattleRuleChooser.Choose(context,Actor,profile);
        Assert.Equal(AutoBattleReason.Repeat,result.Reason);Assert.Equal(BattleCommandKind.Escape,result.Intent!.Kind);
        Assert.Equal("repeatAction",result.ReasonKey);Assert.Equal("循環行動",result.ReasonText);
    }

    [Fact]
    public void EmptyOrderUsesCoordinatesFailedOrderUsesLastNonzeroPreference()
    {
        var context = Context;var profile = Off with { OrderEnabled = true,OrderActions = [] };
        Assert.Equal(3,AutoBattleRuleChooser.Choose(context,Actor,profile).Intent!.TargetCol);
        profile = profile with { OrderActions = [new() { Id = 10008,Target = AutoBattleTargetPolicy.LowestHp }] };
        context = context with { CaptureCatalog = new() };
        Assert.Equal(4,AutoBattleRuleChooser.Choose(context,Actor,profile).Intent!.TargetCol);
        profile = profile with { OrderActions = [new() { Id = 10008,Target = AutoBattleTargetPolicy.HighestHp },new() { Target = AutoBattleTargetPolicy.LowestHp }] };
        Assert.Equal(3,AutoBattleRuleChooser.Choose(context,Actor,profile).Intent!.TargetCol);
    }

    [Fact]
    public void NormalElementPreferenceIsStillHpWhileBestSkillUsesElement()
    {
        var profile = Off with { OrderEnabled = true,OrderActions = [new() { Id = 10001,Target = AutoBattleTargetPolicy.Element }] };
        Assert.Equal(4,AutoBattleRuleChooser.Choose(Context,Actor,profile).Intent!.TargetCol);
        // Reverse weights: target policy 2 is genuinely delegated for best skill.
        var context = Context;var catalog = context.Resources.Catalog;
        catalog = catalog with { ElementWeights = catalog.ElementWeights.SetItem(2,ImmutableDictionary<long,double>.Empty.Add(2,2).Add(3,0.5)) };
        context = context with { Resources = context.Resources with { Catalog = catalog } };
        Assert.Equal(3,AutoBattleRuleChooser.Choose(context,Actor,profile with { OrderActions = [new() { Id = -1,Target = AutoBattleTargetPolicy.Element }] }).Intent!.TargetCol);
    }

    [Fact]
    public void MissingStatsNeverTriggerDeathOrLowResourceRules()
    {
        var context = Context;var unknown = Actor with { Stats = Actor.Stats.Remove("hp").Remove("sp") };
        context = context with { Resources = context.Resources with { Units = [new("1:1",unknown),context.Resources.Units[0]] } };
        var profile = Off with { DeadEnabled = true,LowHpEnabled = true,LowSpEnabled = true,
            LowHp = new() { Id = 60021,Value = long.MaxValue },LowSp = new() { Id = 60041,Value = long.MaxValue } };
        Assert.Equal(AutoBattleReason.Fallback,AutoBattleRuleChooser.Choose(context,Actor,profile).Reason);
        Assert.False(unknown.Stats.ContainsKey("hp"));Assert.False(unknown.Stats.ContainsKey("sp"));
    }

    [Fact]
    public void ReachedMissingPidRetainsKeyErrorButEarlierMatchShortCircuitsIt()
    {
        var context = Context;var missing = Actor with { Pid = null,Row = 0,Stats = Actor.Stats.SetItem("hp",1) };
        var profile = Off with { LowHpEnabled = true,LowHp = new() { Id = 60021,Notice = AutoBattleNotice.Player,Value = 200L } };
        context = context with { Resources = context.Resources with { Units = context.Resources.Units.Add(new("1:0",missing)) } };
        Assert.Equal(new InventoryPlanningError("KeyError","'pid'"),AutoBattleRuleChooser.Choose(context,Actor,profile).Error);
        context = context with { Resources = context.Resources with { Units = context.Resources.Units.SetItem(4,new("1:9",missing with { Row = 9 })) } };
        Assert.Equal(AutoBattleReason.LowHp,AutoBattleRuleChooser.Choose(context,Actor,profile).Reason);
    }

    [Fact]
    public void CatalogKeyErrorStopsRatherThanSelectingLaterDefend()
    {
        var context = Context;var catalog = context.Resources.Catalog;
        context = context with { Resources = context.Resources with { Catalog = catalog with { Skills = catalog.Skills.SetItem(1001,catalog.Skills[1001] with { Fields = catalog.Skills[1001].Fields.Remove("Kind") }) } } };
        var result = AutoBattleRuleChooser.Choose(context,Actor,Off with { OrderEnabled = true,OrderActions = [new() { Id = 1001 },new() { Id = 60021 }] });
        Assert.Equal(new InventoryPlanningError("KeyError","'Kind'"),result.Error);Assert.Null(result.Intent);Assert.Null(result.Reason);
    }

    [Fact]
    public void FinalFailureDoesNotExposeLastSuppressedProtocolError()
    {
        var context = Context with { Resources = Context.Resources with { Units = [] } };
        var result = AutoBattleRuleChooser.Choose(context,Actor,Off);
        Assert.Equal(new InventoryPlanningError("ProtocolError","沒有可用行動／目標，或普攻資料不足"),result.Error);
        Assert.Null(result.Intent);Assert.Null(result.ReasonKey);Assert.Null(result.ReasonText);
    }

    [Fact]
    public void MissingIdentitiesAndInvalidStructuresAreRejectedWithoutRepair()
    {
        var context = Context;
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context,Actor with { Pid = null },Off));
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context with { Resources = context.Resources with { LocalRoleId = null } },Actor,Off));
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context with { Resources = context.Resources with { Units = default } },Actor,Off));
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context with { Resources = context.Resources with { Units = [context.Resources.Units[0],context.Resources.Units[0]] } },Actor,Off));
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context,Actor with { Equips = default },Off));
        Assert.Throws<ArgumentException>(() => AutoBattleRuleChooser.Choose(context,Actor with { Stats = null! },Off));
    }

    [Fact]
    public void RepeatedItemChoicesRemainHypotheticalAndEarlierResultsStayDetached()
    {
        var context = Context;var unit = Actor with { Stats = Actor.Stats.SetItem("hp",50) };
        context = context with { Resources = context.Resources with { Units = context.Resources.Units.SetItem(3,new("1:1",unit)) } };
        var result = AutoBattleRuleChooser.Choose(context,Actor,AutoBattleProfile.PlayerDefaults);
        Assert.Equal(BattleCommandKind.BattleItem,result.Intent!.Kind);Assert.Single(result.Intent.Allocations);
        var before = AutoBattleParityTests.Project(result).ToJsonString();
        for (var i = 0; i < 3; i++) Assert.Equal(before,AutoBattleParityTests.Project(AutoBattleRuleChooser.Choose(context,Actor,AutoBattleProfile.PlayerDefaults)).ToJsonString());
        Assert.Empty(context.Resources.Inventory.Reserved);Assert.Empty(context.Resources.Inventory.Holds);
        var changed = context with { Resources = context.Resources with { Inventory = context.Resources.Inventory with { Ready = false } } };
        Assert.Equal(AutoBattleReason.Order,AutoBattleRuleChooser.Choose(changed,Actor,AutoBattleProfile.PlayerDefaults).Reason);
        Assert.Equal(before,AutoBattleParityTests.Project(result).ToJsonString());
    }
}
