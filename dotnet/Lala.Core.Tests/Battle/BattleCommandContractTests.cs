using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class BattleCommandContractTests
{
    // Detach the one required row so repeated contract cases never retain or reparse the full corpus.
    private static readonly Lazy<JsonNode> BaselineTemplate = new(() =>
        BattleCommandPythonVectors.Read()["cases"]![0]!.DeepClone());
    private static JsonNode BaselineInput => BaselineTemplate.Value.DeepClone();
    private static BattleCommandContext Baseline => BattleCommandParityTests.Context(BaselineInput);

    [Fact]
    public void BaselineInputsAreDetachedAndNestedMutationsCannotLeakBetweenTests()
    {
        var first = BaselineInput;
        var second = BaselineInput;
        var expected = second.ToJsonString();
        Assert.Null(first.Parent);Assert.Null(second.Parent);
        Assert.NotSame(first,second);Assert.NotSame(first["catalog"],second["catalog"]);
        first["catalog"]!.AsObject().Clear();
        Assert.Equal(expected,second.ToJsonString());
        Assert.Equal(expected,BaselineInput.ToJsonString());
    }

    private static BattleCommandContext Shared(int count)
    {
        var context = Baseline;var resources = context.Resources; var skill = resources.Catalog.Skills[1001]; var bag = resources.Inventory;
        return context with { Resources = resources with
        {
            Inventory = bag with { Items = ImmutableDictionary<byte,BagItemSnapshot>.Empty.Add(2,bag.Items[2] with { Count = count }),ItemOrder = [2] },
            Catalog = resources.Catalog with { Skills = resources.Catalog.Skills.SetItem(1001,skill with { Fields = skill.Fields.SetItem("CostItemID",42).SetItem("CostItemCount",2) }) },
            Units = resources.Units.Add(new("companion_two",resources.Units[1].Actor with { Pid = 81,Row = 2 }))
        } };
    }
    private static readonly IReadOnlyDictionary<string,string> Mixed = new Dictionary<string,string> { ["1:1"] = "auto_skill",["2:1"] = "heal_hp",["2:2"] = "heal_sp" };

    [Fact]
    public void LaterActorCannotReuseEarlierHypotheticalSkillOrFoodCosts()
    {
        var context = Shared(3);
        Assert.True(BattleCommandPlanner.Action(context,context.Resources.Units[1].Actor,"heal_sp").Success);
        var result = BattleCommandPlanner.PlanRound(context,Mixed);
        Assert.False(result.Success);Assert.Empty(result.Intents);
        Assert.Equal(new InventoryPlanningError("ProtocolError","2:2：包包沒有可用的SP回復食物"),result.Error);
        Assert.Empty(context.Resources.Inventory.Reserved);Assert.Empty(context.Resources.Inventory.Holds);Assert.Equal(3,context.Resources.Inventory.Items[2].Count);
    }

    [Fact]
    public void RepeatedSuccessfulRoundsKeepPriorIntentsAndAllInputSnapshotsUnchanged()
    {
        var context = Shared(4);var result = BattleCommandPlanner.PlanRound(context,Mixed);
        Assert.True(result.Success);Assert.Equal(new[] { BattleCommandKind.LearnedSkill,BattleCommandKind.BattleItem,BattleCommandKind.BattleItem },result.Intents.Select(intent => intent.Kind));
        Assert.Equal(new BigInteger[] {2,1,1},result.Intents.SelectMany(intent => intent.Allocations).Select(cost => cost.Count));
        var json = BattleCommandParityTests.Project(result).ToJsonString();
        for (var i = 0; i < 3; i++) Assert.Equal(json,BattleCommandParityTests.Project(BattleCommandPlanner.PlanRound(context,Mixed)).ToJsonString());
        var changed = context with { Resources = context.Resources with { Inventory = context.Resources.Inventory with { Reserved = context.Resources.Inventory.Reserved.Add(2,1) } } };
        Assert.False(BattleCommandPlanner.PlanRound(changed,Mixed).Success);
        Assert.Equal(json,BattleCommandParityTests.Project(result).ToJsonString());
        Assert.Empty(context.Resources.Inventory.Reserved);Assert.Empty(context.Resources.Inventory.Holds);
        Assert.All(context.Resources.Units,unit => Assert.Equal(unit.Actor.Pid == 101 ? 40 : 100,unit.Actor.Hp));
    }

    [Fact]
    public void ExcludedActorDoesNotReserveOrValidateItsInvalidMode()
    {
        var context = Shared(2) with { CommandedSlots = ["1:1"] };
        var modes = new Dictionary<string,string>(Mixed) { ["1:1"] = "invalid" };
        Assert.True(BattleCommandPlanner.PlanRound(context,modes).Success);
        Assert.True(BattleCommandPlanner.PlanRound(context with { CommandedSlots = [] },modes,excluded:["1:1"]).Success);
    }

    [Fact]
    public void HealingActionIgnoresTargetOverrideButNormalAndCatchUseCoordinates()
    {
        var context = Baseline;var actor = context.Resources.Units[2].Actor;
        Assert.True(BattleCommandPlanner.Action(context,actor,"heal_hp","missing").Success);
        Assert.False(BattleCommandPlanner.Action(context,actor,"normal","enemy").Success);
        Assert.True(BattleCommandPlanner.Action(context,actor,"normal","3:2").Success);
        Assert.False(BattleCommandPlanner.Action(context,actor,"catch","enemy").Success);
        Assert.True(BattleCommandPlanner.Action(context,actor,"catch","3:2").Success);
    }

    [Fact]
    public void CaptureCompanionUsesDeadMastersLevelAndOwnNetNotOwnLevel()
    {
        var context = Baseline;var units = context.Resources.Units;
        var master = units[2].Actor with { Stats = units[2].Actor.Stats.SetItem("hp",0).SetItem("level",30) };
        context = context with { Resources = context.Resources with { Units = units.SetItem(2,units[2] with { Actor = master }) } };
        var companion = units[1].Actor with { Stats = units[1].Actor.Stats.SetItem("level",999),Equips = units[1].Actor.Equips.SetItem(5,new(99)) };
        var target = units[0].Actor with { Stats = units[0].Actor.Stats.SetItem("level",55) };
        Assert.True(BattleCommandPlanner.CatchAllowed(context,companion,target));
        Assert.False(BattleCommandPlanner.CatchAllowed(context,companion with { Equips = units[1].Actor.Equips },target));
        Assert.False(BattleCommandPlanner.CatchAllowed(context with { Resources = context.Resources with { Units = context.Resources.Units.RemoveAt(2) } },companion,target));
    }

    [Fact]
    public void CaptureArithmeticDoesNotOverflowInt64()
    {
        var context = Baseline;var actor = context.Resources.Units[2].Actor;var target = context.Resources.Units[0].Actor;
        Assert.True(BattleCommandPlanner.CatchAllowed(context,actor with { Stats = actor.Stats.SetItem("degree",long.MaxValue).SetItem("level",long.MinValue) },
            target with { Stats = target.Stats.SetItem("level",long.MaxValue) }));
        Assert.False(BattleCommandPlanner.CatchAllowed(context,actor with { Stats = actor.Stats.SetItem("degree",long.MinValue).SetItem("level",long.MaxValue) },
            target with { Stats = target.Stats.SetItem("level",long.MinValue) }));
    }

    [Fact]
    public void MissingRoleDoesNotClaimOwnershipAndMissingHpDoesNotClaimLiveness()
    {
        var context = Baseline.Resources;
        Assert.Empty(BattleCommandPlanner.OwnedUnits(context with { LocalRoleId = null }));
        context = context with { Units = [.. context.Units.Select(entry => entry with { Actor = entry.Actor with { Stats = entry.Actor.Stats.Remove("hp") } })] };
        Assert.Empty(BattleCommandPlanner.OwnedUnits(context));Assert.Equal(2,BattleCommandPlanner.OwnedUnits(context,false).Length);
    }

    [Fact]
    public void ActorErrorNamesPreserveEmptyNamesAndMissingNamesUseSlot()
    {
        var context = Baseline;var actor = context.Resources.Units[2].Actor;
        foreach (var name in new string?[] {null,"","角色"})
        {
            var changed = context with { Resources = context.Resources with { Units = [new("alias",actor with { Name = name })] } };
            Assert.Equal((name ?? "1:1") + "：未知戰鬥行動",BattleCommandPlanner.PlanRound(changed,new Dictionary<string,string> { ["1:1"] = "invalid" }).Error!.Message);
        }
    }

    [Fact]
    public void InactiveRoundAndUnknownModeKeepSourceErrorPrecedence()
    {
        var context = Baseline with { Active = false,Resources = new() { Units = default },CommandedSlots = default };
        Assert.Equal("等待伺服器開啟戰鬥回合",BattleCommandPlanner.PlanRound(context).Error!.Message);
        Assert.Equal("未知戰鬥行動",BattleCommandPlanner.Action(null!,null!,"invalid").Error!.Message);
    }

    [Fact]
    public void InvalidImportOrderIsRejectedRatherThanRepaired()
    {
        var context = Baseline;
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.OwnedUnits(context.Resources with { Units = default }));
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.OwnedUnits(context.Resources with { Units = [context.Resources.Units[0],context.Resources.Units[0]] }));
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.PlanRound(context with { CommandedSlots = default }));
    }

    [Fact]
    public void CaptureRejectsMissingIdentityAndReachedDefaultEquipmentButKeepsEarlyGates()
    {
        var context = Baseline;var actor = context.Resources.Units[2].Actor;var target = context.Resources.Units[0].Actor;
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.Identity(actor with { Pid = null }));
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.CatchAllowed(context,actor,target with { Pid = null }));
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.CatchAllowed(context,actor with { Equips = default },target));
        Assert.False(BattleCommandPlanner.CatchAllowed(context,actor with { Equips = default },target with { Pid = 9000 }));
        Assert.False(BattleCommandPlanner.CatchAllowed(context,actor,target with { Stats = target.Stats.Remove("level") }));
    }

    [Theory]
    [InlineData("heal_hp")]
    [InlineData("heal_sp")]
    [InlineData("auto_skill")]
    public void SuccessfulGeneralResourceCandidateWithoutActorIdentityCannotBecomeBattleIntent(string mode)
    {
        var context = Baseline;
        var actor = context.Resources.Units[2].Actor with { Pid = null };
        context = context with { Resources = context.Resources with { Catalog = context.Resources.Catalog with
            { Items = context.Resources.Catalog.Items.SetItem(0,context.Resources.Catalog.Items[0] with { SkillLink = 1001 }) } } };
        var general = mode == "auto_skill" ? CombatResourceActionCandidates.BestSkill(context.Resources,actor,context.NormalCatalog) :
            CombatResourceActionCandidates.Food(context.Resources,actor,mode == "heal_hp" ? "hp" : "sp");
        Assert.True(general.Success); Assert.Null(general.Intent!.ActorPid);
        Assert.Equal("candidate",Assert.Throws<ArgumentException>(() => BattleCommandPlanner.Action(context,actor,mode)).ParamName);
        Assert.Empty(context.Resources.Inventory.Reserved); Assert.Empty(context.Resources.Inventory.Holds);
        // A missing PID with a known master also cannot enter a round's actor sequence.
        context = context with { Resources = context.Resources with { Units = [new("missing",actor with { MasterId = 7 })] } };
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.PlanRound(context,new Dictionary<string,string> { ["1:1"] = mode }));
    }

    [Theory]
    [InlineData("heal_hp")]
    [InlineData("heal_sp")]
    public void MissingIdentityDoesNotOverrideEarlierFoodErrors(string mode)
    {
        var context = Baseline;var actor = context.Resources.Units[2].Actor with { Pid = null };
        foreach (var resources in new[]
        {
            context.Resources with { Inventory = context.Resources.Inventory with { Ready = false } },
            context.Resources with { Units = [] },
            context.Resources with { Inventory = context.Resources.Inventory with { Items = ImmutableDictionary<byte,BagItemSnapshot>.Empty,ItemOrder = [] } }
        })
        {
            var expected = CombatResourceActionCandidates.Food(resources,actor,mode == "heal_hp" ? "hp" : "sp");
            Assert.False(expected.Success);
            Assert.Equal(expected.Error,BattleCommandPlanner.Action(context with { Resources = resources },actor,mode).Error);
        }
    }

    [Fact]
    public void MissingIdentityDoesNotOverrideReachedGeneralSkillCatalogError()
    {
        var context = Baseline;var resources = context.Resources;var actor = resources.Units[2].Actor with { Pid = null };
        context = context with { Resources = resources with { Catalog = resources.Catalog with
        {
            Items = resources.Catalog.Items.SetItem(0,resources.Catalog.Items[0] with { SkillLink = 1001 }),
            Skills = resources.Catalog.Skills.SetItem(1001,resources.Catalog.Skills[1001] with { Fields = resources.Catalog.Skills[1001].Fields.Remove("TargetNPCID") })
        } } };
        var expected = CombatResourceActionCandidates.BestSkill(context.Resources,actor,context.NormalCatalog);
        Assert.Equal(new InventoryPlanningError("KeyError","'TargetNPCID'"),expected.Error);
        Assert.Equal(expected.Error,BattleCommandPlanner.Action(context,actor,"auto_skill").Error);
    }

    [Fact]
    public void OneOwnedActorStillRequiresItsIdentityBeforeSortOptimization()
    {
        var context = Baseline.Resources;
        context = context with { Units = [new("single",context.Units[1].Actor with { Pid = null })] };
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.OwnedUnits(context));
        Assert.Throws<ArgumentException>(() => BattleCommandPlanner.OwnedUnits(context,false));
    }

    [Fact]
    public void SlotAndIdentityKeepWireBoundsWithoutCultureFormatting()
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            var actor = new CombatResourceActor { Pid = uint.MaxValue,Col = int.MinValue,Row = int.MaxValue };
            Assert.Equal("-2147483648:2147483647",BattleCommandPlanner.Slot(actor));
            Assert.Equal(new BattleUnitIdentity(uint.MaxValue,0),BattleCommandPlanner.Identity(actor));
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }
}
