using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatResourceContractTests
{
    private static CombatResourceCatalog Catalog => new()
    {
        SkillKeys = ImmutableDictionary<ushort,uint>.Empty.Add(1,1001).Add(2,1001),
        Items = ImmutableDictionary<ushort,CombatResourceItem>.Empty.Add(10,new(3,3,1001)).Add(11,new(0,11,1002)),
        Skills = ImmutableDictionary<uint,CombatResourceSkill>.Empty.Add(1001,Skill(("ID",1001),("LvLimit",9)))
            .Add(1002,Skill(("ID",1002),("LvLimit",2))),
        Characters = [new(1,2,15004,20)]
    };
    private static CombatResourceSkill Skill(params (string Key,long Value)[] values) => new()
        { Fields = values.ToImmutableDictionary(p => p.Key,p => p.Value) };
    private static PlayerKnowledgeSnapshot Known(params uint[] ids) => new()
    {
        Skills = ids.ToImmutableDictionary(id => id,id => new PlayerSkillEvidence(id,0,"S8-1")), SkillOrder = [.. ids]
    };
    private static ImmutableArray<LearnedSkillKnowledge> Learned(PlayerKnowledgeSnapshot player, CombatResourceActor? actor = null, CombatResourceCatalog? catalog = null, uint? role = 7) =>
        CombatResourceKnowledge.Learned(player,CompanionReceiveSnapshot.Empty,role,actor ?? new() { Pid = 7 },catalog ?? Catalog);
    private static CompanionSnapshot Companion(byte slot = 1, uint npc = 80, string? name = "") =>
        new(slot,npc,12,3,null,null,1,2,3,4,5,null,6,1,null,name,[],[],null,0,0,0,0,null,0);
    private static ItemSave Item(ushort id = 10) => new(null,id,1,6,2,999,null,null,3,-100,10,1,2,3,null,4,5,6,[new(7,8)],true,9,10,null);

    [Fact]
    public void RawDuplicateMappingsUseFirstRecordButExplicitS8WinsWithoutChangingItsPosition()
    {
        var p = Known(15003,1001) with { ServerSkillRecords = [new(1,3,4),new(2,7,8)] };
        var rows = Learned(p,new() { Pid = 7,Sex = 1,Head = 2 });
        Assert.Equal(new uint[] {15004,1001},rows.Select(v => v.Id));
        Assert.Equal(1001,rows[1].Level);
        p = p with { Skills = p.Skills.SetItem(1001,new(8,9,"S5-3",2)) };
        rows = Learned(p,new() { Pid = 7,Sex = 1,Head = 2 });
        Assert.Equal(3,rows[1].Level); Assert.Equal((ushort)1,rows[1].Key);
    }

    [Fact]
    public void LastKnownEquipmentLinkOverridesEvidenceAfterRemovalWithoutBorrowingProfileEquipment()
    {
        var p = Known(1001,1002) with { RemovedSkillIds = [1001,1002], Equipment = new() { Equips = [new(10)] } };
        Assert.Empty(Learned(p));
        var first = Learned(p,new() { Pid = 7,Equips = [new(10),new(99)] });
        Assert.Equal(new LearnedSkillKnowledge(1001,9,null,"目前裝備附帶"),Assert.Single(first));
        var second = Learned(p,new() { Pid = 7,Equips = [new(10),new(11),new(99)] });
        Assert.Equal(1002u,Assert.Single(second).Id); Assert.Equal(2,second[0].Level);
        Assert.Equal(new uint[] {1001,1002},p.RemovedSkillIds!.Value);
        Assert.Equal(1001, p.Skills[1001].Level);
    }

    [Fact]
    public void NoviceReplacementOverwritesInPlaceAndUsesFirstAppearanceMatch()
    {
        var p = Known(15004,15003);
        var rows = Learned(p,new() { Pid = 7,Sex = 1,Head = 2 },Catalog with { Characters = [new(1,2,15004,20),new(1,2,15005,21)] });
        Assert.Equal(15004u,Assert.Single(rows).Id); Assert.Equal(15003,rows[0].Level);
        var unchanged = Learned(p,new() { Pid = 7,Sex = 2,Head = 2 });
        Assert.Equal(new uint[] {15004,15003},unchanged.Select(v => v.Id));
    }

    [Theory]
    [InlineData(null,null,true)]
    [InlineData(null,0,false)]
    [InlineData(0,null,false)]
    [InlineData(0,0,true)]
    [InlineData(7,7,true)]
    public void UnknownRoleIsDistinctFromZeroButNullFieldIdentityPreservesPythonProfileMatching(int? role, int? pid, bool matched)
    {
        var p = Known(1001);
        var rows = Learned(p,new() { Pid = (uint?)pid },role:(uint?)role);
        Assert.Equal(matched,rows.Length == 1);
        Assert.False(p.Ready);
    }

    [Fact]
    public void ForeignActorsCanHaveEquipmentEvidenceButNeverBorrowLocalLearnedEvidence()
    {
        var rows = Learned(Known(1002),new() { Pid = 9,MasterId = 8,NpcIndex = 1,Equips = [new(10)] });
        Assert.Equal(1001u,Assert.Single(rows).Id);
    }

    [Fact]
    public void StrictImportedOrderRejectsMissingExtraAndDuplicateIdsRatherThanEnumeratingDictionary()
    {
        var p = Known(1001,1002);
        foreach (var order in new ImmutableArray<uint>[] {[],[1001],[1001,1001],[1001,999]})
            Assert.Throws<ArgumentException>(() => Learned(p with { SkillOrder = order }));
        Assert.Throws<ArgumentException>(() => Learned(p with { SkillOrder = default }));
        Assert.Throws<ArgumentException>(() => CombatResourceKnowledge.FieldContext(PlayerKnowledgeSnapshot.Empty,
            new() { Companions = ImmutableDictionary<ushort,CompanionProfileSnapshot>.Empty.Add(1,new(Companion(),ImmutableDictionary<uint,CompanionLearnedSkill>.Empty,ImmutableDictionary<string,long>.Empty)) },null,Catalog));
    }

    [Fact]
    public void MissingDefaultAndNullInputsAreRejectedWithoutInventedCatalogRows()
    {
        Assert.Throws<ArgumentNullException>(() => CombatResourceKnowledge.Learned(null!,CompanionReceiveSnapshot.Empty,7,new(),Catalog));
        Assert.Throws<ArgumentException>(() => Learned(Known(),new() { Equips = default }));
        Assert.Throws<ArgumentException>(() => Learned(Known(),new() { Equips = [null!] }));
        Assert.Throws<ArgumentException>(() => Learned(Known(),catalog:Catalog with { Characters = default }));
        Assert.Throws<ArgumentException>(() => Learned(Known(),catalog:Catalog with { Items = Catalog.Items.SetItem(10,null!) }));
        Assert.Throws<ArgumentException>(() => Learned(Known(),new() { Equips = [new(10)] },Catalog with { Skills = Catalog.Skills.SetItem(1001,new()) }));
        Assert.Throws<ArgumentException>(() => Learned(Known() with { ServerSkillRecords = default(ImmutableArray<LearnedSkill>) }));
        Assert.Throws<ArgumentException>(() => CombatResourceKnowledge.FieldContext(PlayerKnowledgeSnapshot.Empty with
            { Equipment = new() { Equips = default(ImmutableArray<KnowledgeEquipment>) } },CompanionReceiveSnapshot.Empty,null,Catalog));
    }

    [Fact]
    public void TargetDeadExceptionsAndExitFlagsPreserveShortCircuitEvaluation()
    {
        var actor = new CombatResourceActor { Col = 1,Row = 1 };
        var dead = new CombatResourceActor { Col = 3,Row = 1 };
        Assert.False(CombatResourceKnowledge.TargetValid(actor,dead with { Exited = true },new()));
        Assert.False(CombatResourceKnowledge.TargetValid(actor,dead with { IsFly = true },new()));
        Assert.True(CombatResourceKnowledge.TargetValid(actor,dead,Skill(("ID",11053),("TargetKind",0))));
        Assert.True(CombatResourceKnowledge.TargetValid(actor,dead,Skill(("ID",15253),("TargetKind",0))));
        Assert.True(CombatResourceKnowledge.TargetValid(actor,dead,Skill(("ID",1),("HitStatus",254),("TargetKind",0))));
        Assert.False(CombatResourceKnowledge.TargetValid(actor,dead,Skill(("ID",1),("HitStatus",0))));
        Assert.Throws<ArgumentException>(() => CombatResourceKnowledge.TargetValid(actor,dead,new()));
        Assert.Null(dead.Hp);
    }

    [Fact]
    public void HealEffectsKeepLastPositiveAbsoluteValueAndNeverChangeHealth()
    {
        var item = new CombatResourceItem(23) { Attributes = [new(25,200),new(26,150),new(25,101),new(25,99),new(26,100),new(27,999)] };
        var catalog = Catalog with { Items = Catalog.Items.SetItem(55,item) };
        var result = CombatResourceKnowledge.HealEffects(55,catalog);
        Assert.Equal(1,result["hp"]); Assert.Equal(50,result["sp"]); Assert.Equal(2,result.Count);
        Assert.Empty(CombatResourceKnowledge.HealEffects(55,catalog with { Items = catalog.Items.SetItem(55,item with { Kind = 24 }) }));
        Assert.Empty(CombatResourceKnowledge.HealEffects(999,catalog));
        Assert.Equal(200,item.Attributes[0].Value);
    }

    [Fact]
    public void FieldContextReturnsExplicitEquipmentReplacementAndNoInferredHp()
    {
        var original = Item(); var secondOriginal = Item(11);
        var pending = new PlayerEquipmentKnowledge { UnresolvedEquips = [original,secondOriginal], DeferredEquipUpdates = [new EquipDamageEvent(27,0,3,99),new BattleEquipEvent(7,0,3,11,999)] };
        var player = PlayerKnowledgeSnapshot.Empty with { Equipment = pending, Stats = ImmutableDictionary<string,long>.Empty.Add("max_hp",999) };
        var first = CombatResourceKnowledge.FieldContext(player,CompanionReceiveSnapshot.Empty,null,Catalog with { Items = Catalog.Items.Remove(11) });
        Assert.Single(first.Player.Equipment.UnresolvedEquips!.Value);
        Assert.Equal((uint)6,first.Actor.Equips[2].Damage); Assert.Null(first.Actor.Hp);
        Assert.Equal(2,first.Player.Equipment.DeferredEquipUpdates!.Value.Length);
        var next = CombatResourceKnowledge.FieldContext(first.Player,CompanionReceiveSnapshot.Empty,null,Catalog);
        Assert.Empty(next.Player.Equipment.UnresolvedEquips!.Value); Assert.Null(next.Player.Equipment.DeferredEquipUpdates);
        Assert.Equal(new KnowledgeEquipment(11,999),next.Actor.Equips[2]);
        Assert.Same(secondOriginal,next.Actor.Equips[6].OriginalRecord);
        Assert.Null(next.Actor.Pid); Assert.Null(next.Actor.Hp); Assert.Null(next.Actor.Sp); Assert.False(next.Player.Ready);
        Assert.Same(pending,player.Equipment); Assert.Null(player.Equipment.Equips);
        Assert.Equal((uint)6,first.Actor.Equips[2].Damage);
        Assert.Equal(1001u,Assert.Single(Learned(Known(1001),next.Actor with { Equips = [] },role:null)).Id);
    }

    [Fact]
    public void FieldContextChoosesFirstActiveNpcInSourceOrderAndKeepsServerNameEvenWhenEmpty()
    {
        var first = new CompanionProfileSnapshot(Companion(2),ImmutableDictionary<uint,CompanionLearnedSkill>.Empty,ImmutableDictionary<string,long>.Empty);
        var second = new CompanionProfileSnapshot(Companion(1,name:"other"),ImmutableDictionary<uint,CompanionLearnedSkill>.Empty,ImmutableDictionary<string,long>.Empty);
        var companions = new CompanionReceiveSnapshot { ActiveNpcId = 80,CompanionOrder = [2,1],
            Companions = ImmutableDictionary<ushort,CompanionProfileSnapshot>.Empty.Add(1,second).Add(2,first) };
        var context = CombatResourceKnowledge.FieldContext(PlayerKnowledgeSnapshot.Empty,companions,null,Catalog);
        Assert.Equal(2,context.Units.Length); Assert.Equal((ushort)2,context.Units[1].NpcIndex); Assert.Equal("",context.Units[1].Name);
        Assert.Null(context.Units[1].Hp); Assert.Null(context.Units[1].Sp); Assert.Equal(0,context.Units[1].Stats["degree"]);
        Assert.Equal("角色",context.Actor.Name); Assert.Null(context.Actor.Sex);
    }
}
