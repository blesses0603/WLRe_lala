using System.Diagnostics;
using System.Collections.Immutable;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private sealed class BattleRoundAdvancedException:Exception;
    private sealed class BattleBatchBusyException:Exception;
    private async Task SendBattleRoundAsync(GameAutomationSettings settings,CancellationToken token)
    {
        if(!await actionLane.WaitAsync(0,token).ConfigureAwait(false))return;
        object operation=new();uint? role=null;int sent=0;
        try
        {
            var publication=PublicationSnapshot.Publication;
            if(publication?.Catalogs is not {} catalogs||!connection.IsBatchDrained(publication.Receive.Attempt))return;
            var basis=publication.Receive.State;role=basis.Player?.RoleId;
            // The existing policy checks special styles, deaths and party escape rules.
            if(NextAutomaticAction("battle",settings,token) is not {Kind:"battle"})return;
            ImmutableHashSet<Lala.Core.Battle.BattleSlot> submitted;
            lock(gate)submitted=basis.Local.Battle.Units.Where(u=>battleSubmissions.HasSubmitted(basis,u.Layout.Col,u.Layout.Row,publication.Receive.Attempt)).Select(u=>u.Slot).ToImmutableHashSet();
            var plans=AutomaticBattleRound.Plan(basis,catalogs,settings,resources.CurrentResourceKey!,Stopwatch.GetTimestamp()/(double)Stopwatch.Frequency,submitted);
            if(plans.IsEmpty)return;
            string label=$"戰鬥第 {basis.Local.Battle.Round} 回合";
            ReportAction(new(label,$"準備送出 {plans.Length} 個單位指令",true),operation,role);
            foreach(var entry in plans)
            {
                using var writeDeadline=CancellationTokenSource.CreateLinkedTokenSource(sent==0?token:stop.Token);
                writeDeadline.CancelAfter(TimeSpan.FromSeconds(20));
                while(true)
                {
                try
                {
                await connection.SendGameAsync(publication.Receive.Attempt,()=>
                {
                    lock(gate)
                    {
                        var receive=connection.Publication;
                        if(!CurrentCatalogsLocked(out var currentCatalogs)||!ReferenceEquals(currentCatalogs,catalogs)||receive?.Attempt!=publication.Receive.Attempt
                            ||receive.State.Player?.RoleId!=role||receive.State.Player?.Scene!=basis.Player!.Scene||uncertainActions.Count!=0)
                            throw new ProtocolException("戰鬥下令期間角色、連線或資源已變更。");
                        var current=receive.State;
                        if(current.Local.Battle.Active!=true||current.Local.Battle.BattleCount!=basis.Local.Battle.BattleCount||current.Local.Battle.Round!=basis.Local.Battle.Round)
                            throw new BattleRoundAdvancedException();
                        if(!connection.IsBatchDrained(receive.Attempt))throw new BattleBatchBusyException();
                        if(entry.Plan.BattleItem is {} item)
                        {
                            var actual=current.Bag.Items.GetValueOrDefault(item.Index);
                            if(!current.Bag.Reliable||actual is null||actual.ItemId!=item.ItemId||actual.OriginalRecord.Serial!=item.OriginalRecord.Serial
                                ||actual.OriginalRecord.SerialVersion!=item.OriginalRecord.SerialVersion||BagReceiveReducer.Available(current.Bag,item.Index)<1)
                                throw new ProtocolException("本回合待用物品已變更，停止剩餘下令。");
                        }
                        battleSubmissions.Admit(current,entry.Action,receive.Attempt);
                    }
                    sent++;return entry.Plan.Packet;
                },writeDeadline.Token).ConfigureAwait(false);
                break;
                }
                catch(BattleBatchBusyException){await Task.Delay(10,writeDeadline.Token).ConfigureAwait(false);}
                }
                await connection.ApplyCommandAsync(publication.Receive.Attempt,entry.Plan.AfterWrite!,stop.Token).ConfigureAwait(false);
            }
            ReportAction(new(label,$"已送出 {sent} 個單位指令，等待伺服器回合結果"),operation,role);
        }
        catch(BattleRoundAdvancedException)
        {if(sent>0)ReportAction(new("戰鬥下令",$"已送出 {sent} 個單位；伺服器已切換回合，撤銷剩餘舊指令"),operation,role);}
        catch(Exception error)
        {
            if(sent>0)lock(gate)uncertainActions.Add("battle");
            string message=error is ProtocolException reason?reason.Message:"戰鬥下令未完成。";
            ReportAction(new("戰鬥下令",message+(sent>0?" 已停止重送；請重新登入同步。":" 本回合未送出。"),Uncertain:sent>0),operation,role);
            throw new AutomaticStopException(message);
        }
        finally{actionLane.Release();}
    }
}
