using System.Globalization;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions;

public sealed partial class AccountRuntime
{
    private sealed class ServerEventSync(Guid attempt, uint role, ushort scene)
    {
        internal Guid Attempt { get; } = attempt;
        internal uint Role { get; } = role;
        internal ushort Scene { get; } = scene;
        internal int Sent { get; set; }
        internal bool Failed { get; set; }
    }

    private void ReportEventSync(ServerEventSync sync, string message, bool pending=false, bool uncertain=false)
    {
        sync.Failed |= uncertain;
        ReportAction(new("伺服器事件同步", message, pending, uncertain), sync, sync.Role, background:true);
    }

    /// <summary>Connection protocol maintenance, independent of battle AI. A received
    /// coalesced grant is consumed only at the physical write boundary. Manual NPC
    /// conversations keep their own explicit continuation/choice flow.</summary>
    private async Task SynchronizeServerEventsAsync(CancellationToken token)
    {
        ServerEventSync? sync=null;
        try
        {
            using var timer=new PeriodicTimer(TimeSpan.FromMilliseconds(100));
            while (await timer.WaitForNextTickAsync(token).ConfigureAwait(false))
            {
                var publication=PublicationSnapshot.Publication;
                if(publication is null)continue;
                var s=publication.Receive.State;
                var post=s.Local.Session.PostBattle;
                bool postReady=post.Phase=="exit_delay"&&System.Diagnostics.Stopwatch.GetTimestamp()/(double)System.Diagnostics.Stopwatch.Frequency>=post.Due;
                if(sync is not null)
                {
                    if(sync.Attempt!=publication.Receive.Attempt || sync.Role!=s.Player?.RoleId || sync.Scene!=s.Player?.Scene)
                    {
                        if(sync.Sent>0 && !sync.Failed)ReportEventSync(sync,$"已接續 {sync.Sent} 步；角色、連線或場景已切換");
                        sync=null;
                    }
                    else if(!s.Local.Session.EventFlow.Blocked&&!post.Pending)
                    {
                        if(sync.Sent>0 && !sync.Failed)ReportEventSync(sync,s.Local.Session.EventFlow.LastSource=="S20-8"
                            ?$"已完成（接續 {sync.Sent} 步）":$"已接續 {sync.Sent} 步；伺服器狀態已切換");
                        sync=null;
                    }
                }
                if(!CanSendGameActions || !connection.IsBatchDrained(publication.Receive.Attempt) ||
                    s.Local.Battle.Active==true || s.Local.Session.NpcDialogue.Active ||
                    post.Pending&&post.Phase is "fighting" or "awaiting_response" ||post.Phase=="exit_delay"&&!postReady ||
                    !postReady&&s.Local.Session.EventFlow is not { Blocked:true, AwaitingResponse:false,
                        LastSource:"S20-7" or "S20-10" or "S20-11" or "S20-13" or "S20-14" or "S20-15" or "S20-16" or "S20-17" })continue;
                long? permission;
                lock(gate)
                {
                    eventContinuation.Observe(s,publication.Receive.Events,publication.Receive.Attempt);
                    permission=postReady?(long)post.ExitPacket:eventContinuation.Permission;
                }
                if(permission is null)continue;
                sync??=new(publication.Receive.Attempt,s.Player!.RoleId,s.Player.Scene);
                try
                {
                    await ExecuteActionCoreAsync(new("event",postReady?"post_battle":"continue",Scene:sync.Scene,Key:permission.Value.ToString(CultureInfo.InvariantCulture),BattleCount:postReady?post.Battle:null),
                        token,completeReceiptAfterStop:true,sync:sync).ConfigureAwait(false);
                }
                catch(ProtocolException)
                {
                    // Superseded or busy pre-write grants are re-evaluated, not logged
                    // as repeated failures. A possibly sent operation sets uncertainty
                    // and is never retried. Its error remains in the group's row.
                }
            }
        }
        catch(OperationCanceledException) when(token.IsCancellationRequested) { }
        catch(Exception)
        {
            lock(gate)uncertainActions.Add("event");
            ReportAction(new("伺服器事件同步","同步發生錯誤，已停止接續；請重新登入同步。",Uncertain:true),
                sync ?? new object(),sync?.Role,background:true);
        }
    }
}
