using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static class MaintenancePlanning
{
    internal static void Validate(GameAutomationSettings options,OfflineRuntimeCandidate catalog)
    {
        if(options.RepairBelow is <0 or >249 || options.RepairItems.IsDefault || options.RepairItems.Length!=2 ||options.CleanupItems.IsDefault||options.CleanupItems.Length!=15
            ||options.RepairItems.Any(i=>i!=0&&!MaintenanceKnowledge.IsRepair(catalog.Items,i))||options.CleanupItems.Any(i=>i!=0&&!catalog.Items.ContainsKey(i)))
            throw new ProtocolException("修理／整理設定或同版物品資料無效。");
    }
    internal static (GameAction? Action,string? Hold) Next(ServiceStateSnapshot s,OfflineRuntimeCandidate c,GameAutomationSettings settings)
    {
        if(!settings.RepairEnabled&&!settings.CleanupEnabled)return(null,null);
        if(!s.Bag.Ready||!s.Bag.Reliable||s.Bag.UseFailed)return(null,"等待可靠背包資料後才能檢查修理／整理。");
        bool missing=false;
        if(settings.RepairEnabled&&MaintenanceKnowledge.RepairTargets(c.Items,s.PlayerKnowledge,s.Companions,settings.RepairBelow).FirstOrDefault() is{} target)
        {
            var supply=MaintenanceKnowledge.SelectRepairSupply(c.Items,s.Bag,settings.RepairItems);
            if(supply is not null)return(new("maintenance","repair",supply.ItemId,supply.Index,Scene:s.Player!.Scene,
                Values:ImmutableDictionary<string,int>.Empty.Add("npc",target.NpcIndex).Add("equip",target.EquipIndex).Add("target",target.Equipment.ItemId)),null);
            missing=true;
        }
        if(settings.CleanupEnabled)
        {
            var protectedItems=settings.RepairItems.ToHashSet();
            if(settings.FieldHeal){protectedItems.UnionWith(settings.HpRecovery.Items);protectedItems.UnionWith(settings.SpRecovery.Items);}
            foreach(var id in settings.CleanupItems)
            {
                if(id==0||protectedItems.Contains(id)||MaintenanceKnowledge.CleanupAction(c.Items,id) is not{} classification)continue;
                var row=s.Bag.Items.OrderBy(p=>p.Key).Select(p=>p.Value).FirstOrDefault(row=>row.ItemId==id&&MaintenanceKnowledge.SlotAvailable(s.Bag,row.Index)&&s.Bag.AlchemySlots?.Contains(row.Index)!=true);
                if(row is not null)return(new("maintenance",classification==MaintenanceCleanupClassification.Sell?"sell":"delete",id,row.Index,Math.Min(255,row.Count),Scene:s.Player!.Scene),null);
            }
        }
        return(null,missing?"需修復裝備，等待背包內指定修理道具。":null);
    }
}

internal static partial class ManualGameCommands
{
    private static GameActionPlan Maintenance(GameAction a,ServiceStateSnapshot s,OfflineRuntimeCandidate c)
    {
        Require(a.Index is >0 and <=255&&a.Count is >0 and <=255&&s.Bag.Ready&&s.Bag.Reliable&&!s.Bag.UseFailed,"修理／整理背包尚未就緒。");
        Require(s.Bag.Items.TryGetValue((byte)a.Index,out var item)&&item.ItemId==a.Target&&item.Count>=a.Count
            &&MaintenanceKnowledge.SlotAvailable(s.Bag,(byte)a.Index)&&s.Bag.AlchemySlots?.Contains((ushort)a.Index)!=true,"修理／整理格位已變更或已被保留。");
        var before=item!;bool Same(BagItemSnapshot after)=>after.ItemId==before.ItemId&&after.OriginalRecord.Serial==before.OriginalRecord.Serial&&after.OriginalRecord.SerialVersion==before.OriginalRecord.SerialVersion;
        KnowledgeEquipment? equipment=null;ushort npc=0;int equip=0;Packet packet;
        if(a.Operation=="repair")
        {
            Require(a.Count==1&&MaintenanceKnowledge.IsRepair(c.Items,before.ItemId)&&before.Damage<250&&a.Values is not null,"修復道具無效。");
            npc=checked((ushort)a.Values!.GetValueOrDefault("npc"));equip=a.Values.GetValueOrDefault("equip");
            equipment=MaintenanceKnowledge.Equipment(s.PlayerKnowledge,s.Companions,npc,equip);
            Require(equipment is not null&&equipment.ItemId==a.Values.GetValueOrDefault("target")&&equipment.Damage is >0 and <250
                &&MaintenanceKnowledge.RepairTargets(c.Items,s.PlayerKnowledge,s.Companions,249).Any(t=>t.NpcIndex==npc&&t.EquipIndex==equip),"待修復裝備已變更。");
            Require(npc<=255,"夥伴索引超出修復協議範圍。");
            packet=new(23,84,new PacketWriter().U8(2).U16(equipment!.ItemId).U8(equip).U8(npc).U8(1).U16(a.Index).U16(before.ItemId).U16(1).Build());
        }
        else
        {
            Require(a.Operation is "sell" or "delete"&&MaintenanceKnowledge.CleanupAction(c.Items,before.ItemId)==(a.Operation=="sell"?MaintenanceCleanupClassification.Sell:MaintenanceCleanupClassification.Delete),"物品不允許指定整理方式。");
            packet=a.Operation=="sell"?new(27,3,[(byte)a.Index,(byte)a.Count]):new(23,124,[(byte)a.Index,(byte)a.Count,2]);
        }
        bool receipt=false;
        return new(packet,"maintenance",a.Operation=="repair"?"戰後修復":"戰後整理",next=>next,next=>
        {
            Require(next.Bag.Reliable,"修理／整理期間背包資料失效。");
            var after=next.Bag.Items.GetValueOrDefault((byte)a.Index);
            Require(after is null||Same(after),"修理／整理格位被替換，停止接續。");
            bool spent=after is null?before.Count==a.Count:after.Count==before.Count-a.Count;
            if(a.Operation!="repair")return receipt&&spent;
            var target=MaintenanceKnowledge.Equipment(next.PlayerKnowledge,next.Companions,npc,equip);
            Require(after is null?before.Count==1:after.Count>=before.Count-1&&after.Count<=before.Count,"修復道具扣除數量不符。");
            Require(target is not null&&target.ItemId==equipment!.ItemId&&target.OriginalRecord?.Serial==equipment.OriginalRecord?.Serial&&target.OriginalRecord?.SerialVersion==equipment.OriginalRecord?.SerialVersion,"待修復裝備已替換。");
            return (spent||after is not null&&after.Damage>before.Damage)&&target!.Damage==0;
        }){ObserveReceipt=e=>
        {
            if(e.Type=="sale_notice"&&e.Code==0&&a.Operation=="sell")throw new ProtocolException("伺服器拒絕販售。");
            if(e.Type==(a.Operation=="sell"?"bag_sell":"bag_delete")&&e.Index==a.Index)
            {Require(e.Count==a.Count,"修理／整理扣除數量不符。");receipt=true;}
        }};
    }
}
