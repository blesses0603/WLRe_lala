using System.Diagnostics;
using System.Numerics;
using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.State;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private sealed class AutomaticPauseException(string message):Exception(message);
    private string? MovementPauseReason(ServiceStateSnapshot state)
    {
        if(state.Local.Battle.Active==true||state.Local.Session.EventFlow.Blocked||state.Local.Session.PostBattle.Pending)return "等待戰鬥或戰後事件完成";
        var location=state.Local.World.Location;
        if(location.ServerDestination is{} destination&&destination.PacketNumber>location.Confirmed?.PacketNumber
            &&(location.RequestedDestination is not{} request||destination.X!=request.X||destination.Y!=request.Y))return "收到伺服器移動目的地，等待位置確認";
        lock(gate)return CurrentCatalogsLocked(out var catalog)?CoordinationReason("roaming",state,catalog!):"等待有效的角色與圖資";
    }
    private GameAutomationSettings? battleSettings;
    private (BigInteger Battle,BigInteger Bag,GameAutomationSettings Options)? maintenanceSettle;
    private double maintenanceDue;
    private bool Enabled(string kind)=>automationStatus.GetValueOrDefault(kind)?.Enabled==true;
    private (GameAction? Action,string? Hold) MaintenanceDecision(ServiceStateSnapshot state,OfflineRuntimeCandidate catalogs)
    {
        lock(gate)
        {
            var settings=battleSettings;
            if(!Enabled("battle")||settings is null||(!settings.RepairEnabled&&!settings.CleanupEnabled)||state.Local.Battle.BattleCount==0)return(null,null);
            if(Enabled("craft")||Enabled("alchemy")||state.Expedition.Pending is not null)return(null,null);
            var key=(state.Local.Battle.BattleCount,state.Bag.Revision,settings);double now=Stopwatch.GetTimestamp()/(double)Stopwatch.Frequency;
            if(maintenanceSettle!=key){maintenanceSettle=key;maintenanceDue=now+.5;}
            if(now<maintenanceDue)return(null,"等待戰後背包資料安定");
            return MaintenancePlanning.Next(state,catalogs,settings);
        }
    }
    private string? CoordinationReason(string kind,ServiceStateSnapshot state,OfflineRuntimeCandidate catalogs)
    {
        lock(gate)
        {
            if(kind!="battle"&&state.Local.Battle.Active==true)return "等待戰鬥結束";
            if(kind!="battle"&&state.Local.Session.EventFlow.Blocked)return "等待伺服器事件結束";
            if(state.Local.Battle.Active!=true&&state.Local.Session.PostBattle.Pending)return "等待戰後事件接續完成";
            if(state.Ark.Pending is not null||state.Ark.Uncertain)return kind=="ark"||kind=="battle"&&state.Local.Battle.Active==true?null:"等待方舟操作確認";
            if(kind!="guild"&&state.GuildActions.Pending is not null)return "等待組織操作確認";
            if(kind!="daily"&&(state.DailyTasks.Pending is not null||state.TimeCube.Pending is not null))return "等待領獎確認";
            if(kind is "roaming" or "expedition" or "alchemy"&&Enabled("craft"))return "等待製作接續與回覆";
            if(kind is "craft" or "expedition"&&Enabled("alchemy"))return "等待煉金接續與回覆";
            if(kind=="craft"&&(Enabled("roaming")||Enabled("expedition")))return "請先停止徘徊或遠征自動派遣";
            if(kind!="battle"&&state.Local.Battle.Active!=true&&!state.Local.Session.EventFlow.Blocked)
            {
                var maintenance=MaintenanceDecision(state,catalogs);
                if(maintenance.Action is not null||maintenance.Hold is not null)return maintenance.Hold??"等待戰後修理／整理";
                if(kind=="roaming"&&Enabled("battle")&&battleSettings is {} recovery&&FieldRecoveryPlanning.Next(state,catalogs,recovery) is not null)return "等待戰後補給完成";
            }
            return null;
        }
    }
}
