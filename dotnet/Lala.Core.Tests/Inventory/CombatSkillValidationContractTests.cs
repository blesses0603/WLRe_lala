using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatSkillValidationContractTests
{
    private static CombatResourceSkill Skill(uint id = 1001) => new()
    {
        Fields = new Dictionary<string,long> { ["ID"] = id,["Kind"] = 1,["KindSort"] = 1,["TargetKind"] = 0,
            ["ReduceSP"] = 0,["ReduceHP"] = 0,["FightWay"] = 1,["RangeKind1"] = 1,["CostItemID"] = 0,["CostItemCount"] = 0,
            ["WeaponKind1"] = 1,["WeaponKind2"] = 1,["WeaponKind3"] = 1,["WeaponKind4"] = 1,["WeaponKind5"] = 1,["LvLimit"] = 5 }.ToImmutableDictionary()
    };
    private static PlayerKnowledgeSnapshot Player(params uint[] ids) => new()
        { Skills = ids.ToImmutableDictionary(id => id,id => new PlayerSkillEvidence(1,0,"S8-1")),SkillOrder = [.. ids] };
    private static CombatResourceActor Actor => new() { Pid = 7,Equips = [new(0),new(0),new(0)],
        Stats = ImmutableDictionary<string,long>.Empty.Add("hp",100).Add("sp",100) };
    private static CombatResourceCatalog Catalog(CombatResourceSkill? row = null) => new()
        { Skills = ImmutableDictionary<uint,CombatResourceSkill>.Empty.Add(1001,row ?? Skill()) };
    private static ImmutableArray<string> Reasons(CombatResourceSkill row, CombatResourceActor? actor = null,
        PlayerKnowledgeSnapshot? player = null, BagReceiveSnapshot? bag = null, uint? role = 7) =>
        CombatResourceKnowledge.SkillReasons(player ?? Player(1001),CompanionReceiveSnapshot.Empty,role,actor ?? Actor,1001,Catalog(row),
            bag ?? BagReceiveSnapshot.Empty,InventoryPlanningContext.Empty);

    [Fact]
    public void EarlyGatesDoNotDemandUnreachedFieldsOrInventExtraDiagnostics()
    {
        var incomplete = new CombatResourceSkill();
        Assert.Equal(new[] {"此單位尚無已學／裝備授予證據"},Reasons(incomplete,player:Player()));
        Assert.Equal(new[] {"生活／被動技能，不能主動施放"},Reasons(incomplete with { Fields = incomplete.Fields.Add("Kind",9) }));
        Assert.Equal(new[] {"生活／被動技能，不能主動施放"},Reasons(incomplete with { Fields = incomplete.Fields.Add("Kind",1).Add("KindSort",4) }));
        Assert.Equal(new[] {"無可指定的戰鬥目標"},Reasons(incomplete with { Fields = incomplete.Fields.Add("Kind",1).Add("KindSort",1).Add("TargetKind",4) }));
        Assert.Throws<ArgumentException>(() => Reasons(incomplete));
        Assert.Throws<ArgumentException>(() => Reasons(Skill() with { Fields = Skill().Fields.Remove("FightWay") }));
    }

    [Fact]
    public void ReasonsPreserveSourceOrderAndUseReadOnlyAllocationWithoutInstallingReservations()
    {
        var skill = Skill() with { Fields = Skill().Fields.SetItem("ReduceHP",100).SetItem("WeaponKind2",0)
            .SetItem("CostItemID",42).SetItem("CostItemCount",1).SetItem("FightWay",3).SetItem("TargetKind",1) };
        var actor = Actor with { Exited = true,Stats = ImmutableDictionary<string,long>.Empty,
            Statuses = ImmutableDictionary<string,bool>.Empty.Add("silenced",true).Add("taunt",true) };
        var bag = BagReceiveSnapshot.Empty;
        Assert.Equal(new[] {"操作單位已陣亡／離場","SP不足／尚無SP資料","HP不足以支付技能消耗","目前武器不適用",
            "包包資料尚未同步或已失效","目前狀態封鎖輔助技能","挑戰狀態限制目標／範圍"},Reasons(skill,actor,bag:bag));
        Assert.Empty(bag.Holds); Assert.Empty(bag.Reserved); Assert.Empty(actor.Stats); Assert.Equal(BigInteger.Zero,bag.Revision);
    }

    [Theory]
    [InlineData(9007199254740894L,true)]
    [InlineData(9007199254740903L,true)]
    [InlineData(9007199254740991L,true)]
    [InlineData(9007199254740992L,true)]
    [InlineData(9007199254740993L,false)]
    [InlineData(9007199254740995L,true)]
    [InlineData(long.MaxValue,true)]
    public void HpPercentageRetainsPythonBinary64RoundingRatherThanReplacingItWithIntegerCeiling(long hp,bool rejected)
    {
        var skill = Skill() with { Fields = Skill().Fields.SetItem("ReduceHP",100) };
        var actor = Actor with { Stats = Actor.Stats.SetItem("hp",hp) };
        Assert.Equal(rejected,Reasons(skill,actor).Contains("HP不足以支付技能消耗"));
        Assert.Equal(hp,actor.Hp);
    }

    [Fact]
    public void ZeroHpCostSpCostAndKindEightKeepTheirSourceExceptions()
    {
        var row = Skill() with { Fields = Skill().Fields.SetItem("ReduceHP",100) };
        Assert.DoesNotContain("HP不足以支付技能消耗",Reasons(row with { Fields = row.Fields.SetItem("Kind",8) }));
        Assert.DoesNotContain("HP不足以支付技能消耗",Reasons(row with { Fields = row.Fields.SetItem("ReduceSP",1) }));
        Assert.DoesNotContain("HP不足以支付技能消耗",Reasons(row with { Fields = row.Fields.SetItem("ReduceHP",0) }));
    }

    [Fact]
    public void RowsSortOrdinalCategoryThenSourceSpSentinelThenNumericIdAndKeepMissingSpNull()
    {
        var catalog = Catalog() with { Skills = new Dictionary<uint,CombatResourceSkill>
        {
            [1001] = Skill(1001) with { Fields = Skill().Fields.SetItem("KindSort",4).Remove("ReduceSP") },
            [1002] = Skill(1002) with { Name = "",Fields = Skill().Fields.SetItem("KindSort",4).SetItem("ReduceSP",100000) },
            [1003] = Skill(1003) with { Fields = Skill().Fields.SetItem("KindSort",4).SetItem("ReduceSP",99999) },
            [1004] = Skill(1004) with { Fields = Skill().Fields.SetItem("KindSort",2).SetItem("ReduceSP",0) }
        }.ToImmutableDictionary() };
        var player = Player(1004,1003,1002,1001,99999);
        var old = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("zh-TW");
            var rows = CombatResourceKnowledge.SkillRows(player,CompanionReceiveSnapshot.Empty,7,Actor,catalog,BagReceiveSnapshot.Empty,InventoryPlanningContext.Empty);
            Assert.Equal(new uint[] {99999,1001,1003,1002,1004},rows.Select(r => r.Id));
            Assert.Null(rows[0].Sp); Assert.Null(rows[1].Sp); Assert.Equal("技能99999",rows[0].Name); Assert.Equal("",rows[3].Name);
            Assert.Equal(new[] {"技能不在目前版本資料表"},rows[0].Reasons);
        }
        finally { CultureInfo.CurrentCulture = old; }
    }

    [Fact]
    public void SourceUseFailedFlagIsNotAnInventedSkillCostGate()
    {
        var item = new ItemSave(1,42,3,0,0,0,null,null,0,0,0,0,0,0,null,0,0,0,[],false,0,0,null);
        var bag = new BagReceiveSnapshot { Ready = true,Reliable = true,UseFailed = true,
            Items = ImmutableDictionary<byte,BagItemSnapshot>.Empty.Add(1,new(item,1,3,0)),ItemOrder = [1] };
        var row = Skill() with { Fields = Skill().Fields.SetItem("CostItemID",42).SetItem("CostItemCount",1) };
        Assert.Empty(Reasons(row,bag:bag)); Assert.True(bag.UseFailed); Assert.Empty(bag.Reserved); Assert.Empty(bag.Holds);
    }

    [Fact]
    public void CurrentEquipmentGrantAllowsDiagnosticsWithoutInventingPlayerReadiness()
    {
        var player = Player();
        var actor = Actor with { Equips = [new(0),new(0),new(10)] };
        var catalog = Catalog() with { Items = ImmutableDictionary<ushort,CombatResourceItem>.Empty.Add(10,new(3,3,1001)) };
        var reasons = CombatResourceKnowledge.SkillReasons(player,CompanionReceiveSnapshot.Empty,7,actor,1001,catalog,
            BagReceiveSnapshot.Empty,InventoryPlanningContext.Empty);
        Assert.Empty(reasons); Assert.False(player.Ready); Assert.Empty(player.Skills);
        var removed = actor with { Equips = [] };
        Assert.Equal(new[] {"此單位尚無已學／裝備授予證據"},CombatResourceKnowledge.SkillReasons(player,
            CompanionReceiveSnapshot.Empty,7,removed,1001,catalog,BagReceiveSnapshot.Empty,InventoryPlanningContext.Empty));
    }

    [Fact]
    public void FieldContextRejectsDefaultAndNullEquipmentInImportedActiveCompanion()
    {
        var data = new CompanionSnapshot(1,80,0,1,null,null,0,0,0,0,0,null,0,0,null,null,[],[],null,0,0,0,0,null,0);
        var profile = new CompanionProfileSnapshot(data,ImmutableDictionary<uint,CompanionLearnedSkill>.Empty,ImmutableDictionary<string,long>.Empty);
        foreach (var equipment in new ImmutableArray<KnowledgeEquipment>[] {default,[null!]})
        {
            var companions = new CompanionReceiveSnapshot { ActiveNpcId = 80,CompanionOrder = [1],
                Companions = ImmutableDictionary<ushort,CompanionProfileSnapshot>.Empty.Add(1,profile with { EquipmentOverrides = equipment }) };
            Assert.Throws<ArgumentException>(() => CombatResourceKnowledge.FieldContext(Player(),companions,null,Catalog()));
        }
    }
}
