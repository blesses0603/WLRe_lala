using System.Collections.Immutable;
using System.Text.Json.Nodes;
using Lala.Core.Inventory;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatActionCandidateContractTests
{
    private static JsonNode Baseline => CombatActionCandidatePythonVectors.Read()["cases"]![0]!;

    [Fact]
    public void RepeatedCallsAndLaterImportedObservationsCannotAlterEarlierCandidateHistory()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        var skill = context.Catalog.Skills[1001];
        context = context with { Catalog = context.Catalog with { Skills = context.Catalog.Skills.SetItem(1001,skill with
            { Fields = skill.Fields.SetItem("CostItemID",42).SetItem("CostItemCount",4) }) } };
        var first = CombatResourceActionCandidates.Learned(context,actor,1001);
        var firstJson = CombatActionCandidateParityTests.Project(first).ToJsonString();
        Assert.True(first.Success);Assert.Equal(new ushort[] {2,9},first.Intent!.Allocations.Select(row => row.Index));
        for (var i = 0; i < 3; i++) Assert.Equal(firstJson,CombatActionCandidateParityTests.Project(CombatResourceActionCandidates.Learned(context,actor,1001)).ToJsonString());
        Assert.Empty(context.Inventory.Reserved);Assert.Empty(context.Inventory.Holds);
        var changed = context with { Inventory = context.Inventory with { Reserved = context.Inventory.Reserved.SetItem(2,3) } };
        Assert.False(CombatResourceActionCandidates.Learned(changed,actor,1001).Success);
        var revoked = context with { Player = context.Player with { RemovedSkillIds = [1001] } };
        Assert.False(CombatResourceActionCandidates.Learned(revoked,actor,1001).Success);
        Assert.Equal(firstJson,CombatActionCandidateParityTests.Project(first).ToJsonString());
        Assert.Empty(context.Inventory.Reserved);Assert.Null(context.Player.RemovedSkillIds);
    }

    [Theory]
    [InlineData(false,1001)]
    [InlineData(true,1003)]
    public void ChainAdvancementHasTheSourceTwoHopLimit(bool advance,long expected)
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        Assert.Equal(expected,CombatResourceActionCandidates.Learned(context,actor,1001,nextSkill:advance).Intent!.SkillId);
    }

    [Fact]
    public void BestSkillStopsOnCatalogKeyErrorRatherThanSilentlyTakingNormalFallback()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        var skill = context.Catalog.Skills[1001];
        context = context with { Catalog = context.Catalog with { Skills = context.Catalog.Skills.SetItem(1001,skill with { Fields = skill.Fields.Remove("TargetNPCID") }) } };
        var result = CombatResourceActionCandidates.BestSkill(context,actor,CombatActionCandidateParityTests.Normal(input["normal"]!));
        Assert.Null(result.Intent);Assert.Equal(new InventoryPlanningError("KeyError","'TargetNPCID'"),result.Error);
    }

    [Fact]
    public void NormalFallbackDoesNotInventCatalogOrMissingWireIdentity()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input) with { Player = PlayerKnowledgeSnapshot.Empty };
        var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        Assert.Throws<ArgumentNullException>(() => CombatResourceActionCandidates.BestSkill(context,actor,null!));
        Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.BestSkill(context,actor with { Pid = null },CombatActionCandidateParityTests.Normal(input["normal"]!)));
        Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.BestSkill(context with { LocalRoleId = null },actor,CombatActionCandidateParityTests.Normal(input["normal"]!)));
    }

    [Fact]
    public void InvalidTypedOrderIsRejectedRatherThanGuessed()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.Learned(context with { Units = default },actor,1001));
        Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.Learned(context with { Units = [context.Units[0],context.Units[0]] },actor,1001));
        Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.Food(context with { Inventory = context.Inventory with { ItemOrder = [] } },actor));
    }

    [Theory]
    [InlineData("")]
    [InlineData("HP")]
    [InlineData("Sp")]
    [InlineData("unknown")]
    [InlineData("ß")]
    [InlineData("hp\n")]
    [InlineData("sp'")]
    [InlineData("sp\\")]
    public void UnsupportedResourceKeysAreRejectedAtTheTypedBoundary(string resource)
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        foreach (var ready in new[] {false,true})
        {
            var observed = context with { Inventory = context.Inventory with { Ready = ready } };
            var error = Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.Food(observed,actor,resource));
            Assert.Equal("resource",error.ParamName);
            Assert.Equal(ready,observed.Inventory.Ready);
            Assert.Empty(observed.Inventory.Reserved);Assert.Empty(observed.Inventory.Holds);
        }
    }

    [Fact]
    public void NullFoodResourceIsNotSilentlyDefaultedToHp()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        Assert.Equal("resource",Assert.Throws<ArgumentNullException>(() => CombatResourceActionCandidates.Food(context,actor,null!)).ParamName);
    }

    [Fact]
    public void FieldProjectionRetainsObservedElementWithoutInventingUnknownElement()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);
        var known = context.Player with { Stats = context.Player.Stats.SetItem("element",2) };
        var projection = CombatResourceKnowledge.FieldContext(known,context.Companions,null,context.Catalog);
        Assert.Equal(2,projection.Actor.Element);
        var unknown = CombatResourceKnowledge.FieldContext(context.Player,context.Companions,null,context.Catalog);
        Assert.Null(unknown.Actor.Element);
        Assert.False(context.Player.Stats.ContainsKey("element"));
    }

    [Fact]
    public void MalformedNonFiniteElementWeightsAreRejectedAsInvalidTypedImports()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        foreach (var weight in new[] {double.NaN,double.PositiveInfinity,double.NegativeInfinity})
        {
            var catalog = context.Catalog with { ElementWeights = ImmutableDictionary<long,ImmutableDictionary<long,double>>.Empty
                .Add(1,ImmutableDictionary<long,double>.Empty.Add(2,weight)) };
            Assert.Throws<ArgumentException>(() => CombatResourceActionCandidates.Learned(context with { Catalog = catalog },actor,1001,targetKind:2));
        }
    }

    [Fact]
    public void SelectionUsesCallerBattleKeysWhileNormalFallbackUsesCoordinates()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input);var actor = CombatActionCandidateParityTests.Actor(input["actor"]!);
        context = context with { Units = [new("alias",context.Units[0].Actor)] };
        Assert.True(CombatResourceActionCandidates.Learned(context,actor,1001,"alias").Success);
        Assert.False(CombatResourceActionCandidates.Learned(context,actor,1001,"4:2").Success);
        context = context with { Player = PlayerKnowledgeSnapshot.Empty };
        Assert.False(CombatResourceActionCandidates.BestSkill(context,actor,CombatActionCandidateParityTests.Normal(input["normal"]!),"alias").Success);
        Assert.True(CombatResourceActionCandidates.BestSkill(context,actor,CombatActionCandidateParityTests.Normal(input["normal"]!),"4:2").Success);
    }

    [Fact]
    public void EquipmentEvidenceAndUnknownStatsAreNotUpgradedToServerLearningOrReadiness()
    {
        var input = Baseline;var context = CombatActionCandidateParityTests.Context(input) with { Player = PlayerKnowledgeSnapshot.Empty };
        var actor = CombatActionCandidateParityTests.Actor(input["actor"]!) with { Equips = [new(0),new(0),new(10)] };
        context = context with { Catalog = context.Catalog with { Items = context.Catalog.Items.SetItem(10,context.Catalog.Items[10] with { SkillLink = 1001 }) } };
        Assert.True(CombatResourceActionCandidates.Learned(context,actor,1001).Success);
        var missing = actor with { Stats = actor.Stats.Remove("hp").Remove("sp") };
        Assert.False(CombatResourceActionCandidates.Learned(context,missing,1001).Success);
        Assert.Null(missing.Hp);Assert.Null(missing.Sp);Assert.Empty(context.Player.Skills);Assert.False(context.Player.Ready);
    }
}
