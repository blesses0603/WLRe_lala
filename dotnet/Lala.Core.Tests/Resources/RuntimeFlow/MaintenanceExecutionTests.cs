using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;
public sealed partial class ResourceRuntimeBootstrapTests
{
    private static async Task<(OfflineRuntimeCandidate Catalog,ServiceStateSnapshot State)> MaintenanceFixture()
    {
        var c=(await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;
        var items=new Dictionary<ushort,ItemDataRow>
        {
            [100]=new(100,"修理工具",0,0,0,0,0,new(){Kind=25,Special=130}),
            [200]=new(200,"普通裝備",0,0,0,0,0,new(){Special=0,FitType=1}),
            [300]=new(300,"整理物品",0,0,0,0,0,new())
        };
        c=new(c.EveIndexes,items,c.Talks,c.Texts,c.Recipes,c.Stages,c.Doors,c.SceneNames,c.Expedition,c.Npcs,c.SourceSha256,c.PortalObservations);
        var tool=RecoveryItem(1,100);var cleanup=RecoveryItem(2,300);var equip=RecoveryItem(1,200) with{Serial=777};
        var state=new ServiceStateSnapshot(local:GameState().Local,
            bag:new(){Ready=true,Reliable=true,Items=ImmutableDictionary<byte,BagItemSnapshot>.Empty.Add(1,new(tool,1,3,0)).Add(2,new(cleanup,2,3,0)),ItemOrder=[1,2]},
            playerKnowledge:new(){Ready=true,Equipment=new(){Equips=[new(200,Damage:220,OriginalRecord:equip)]}});
        return(c,state);
    }
    [Fact]
    public async Task Repair_requires_both_exact_tool_consumption_and_same_equipment_restoration()
    {
        var(c,s)=await MaintenanceFixture();var options=new GameAutomationSettings{RepairEnabled=true,RepairItems=[100,0]};
        MaintenancePlanning.Validate(options,c);
        var action=MaintenancePlanning.Next(s,c,options).Action!;Assert.Equal("repair",action.Operation);
        var plan=ManualGameCommands.Plan(action,s,c,10,"synthetic");Assert.Equal(23,plan.Packet.Main);Assert.Equal(84,plan.Packet.Sub);
        ServiceStateSnapshot Result(int count,uint damage,uint serial=777)=>new(local:s.Local,bag:s.Bag with{Items=s.Bag.Items.SetItem(1,s.Bag.Items[1] with{Count=count})},
            playerKnowledge:s.PlayerKnowledge with{Equipment=new(){Equips=[s.PlayerKnowledge.Equipment.Equips!.Value[0] with{Damage=damage,OriginalRecord=s.PlayerKnowledge.Equipment.Equips.Value[0].OriginalRecord! with{Serial=serial}}]}});
        Assert.False(plan.Acknowledged(Result(3,0)));Assert.False(plan.Acknowledged(Result(2,220)));
        Assert.True(plan.Acknowledged(Result(2,0)));
        Assert.Throws<ProtocolException>(()=>plan.Acknowledged(Result(1,0)));
        Assert.Throws<ProtocolException>(()=>plan.Acknowledged(Result(2,0,999)));
    }
    [Fact]
    public async Task Cleanup_protects_repair_and_recovery_items_and_requires_exact_matching_receipt()
    {
        var(c,s)=await MaintenanceFixture();var options=new GameAutomationSettings{CleanupEnabled=true,RepairItems=[100,0],CleanupItems=[100,300,0,0,0,0,0,0,0,0,0,0,0,0,0]};
        var action=MaintenancePlanning.Next(s,c,options).Action!;Assert.Equal(300u,action.Target);Assert.Equal("sell",action.Operation);
        var plan=ManualGameCommands.Plan(action,s,c,10,"synthetic");Assert.Equal(27,plan.Packet.Main);Assert.Equal(3,plan.Packet.Sub);
        var changed=CommandState.With(s,bag:s.Bag with{Items=s.Bag.Items.Remove(2)});
        Assert.False(plan.Acknowledged(changed));
        plan.ObserveReceipt!(new(1,27,6,"bag_sell","",Index:99,Count:3));Assert.False(plan.Acknowledged(changed));
        plan.ObserveReceipt!(new(2,27,6,"bag_sell","",Index:2,Count:3));Assert.True(plan.Acknowledged(changed));
        Assert.Throws<ProtocolException>(()=>plan.ObserveReceipt!(new(3,27,6,"bag_sell","",Index:2,Count:1)));
        Assert.Throws<ProtocolException>(()=>plan.ObserveReceipt!(new(4,27,8,"sale_notice","",Code:0)));
        options=options with{FieldHeal=true,HpRecovery=new(){Items=[300,0,0,0,0,0,0,0,0,0]}};
        Assert.Null(MaintenancePlanning.Next(s,c,options).Action);
    }
}
