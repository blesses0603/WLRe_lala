using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>Account/attempt-owned one-use grant. Repeated protocol numbers are not proof
/// of a loop. Match Python's coalesced permission, with actual-write admission.</summary>
internal sealed class EventContinuationGuard
{
    private long observed,permission,consumed;
    private Guid? attempt;
    private (Guid?,uint?,System.Numerics.BigInteger,System.Numerics.BigInteger)? postUsed;
    internal void AdmitPostBattle(ServiceStateSnapshot state,GameAction action,Guid currentAttempt)
    {
        var p=state.Local.Session.PostBattle;
        var key=((Guid?)currentAttempt,state.Player?.RoleId,p.Battle,p.ExitPacket);
        if(p.Phase!="awaiting_response"||p.Role!=state.Player?.RoleId||p.Battle!=action.BattleCount||p.ExitPacket.ToString(System.Globalization.CultureInfo.InvariantCulture)!=action.Key||postUsed==key)
            throw new ProtocolException("戰後接續已使用或角色已變更。");
        postUsed=key;
        Observe(state,[],currentAttempt);consumed=Math.Max(consumed,permission);
    }
    internal long? Permission=>permission>consumed?permission:null;
    internal string? Observe(ServiceStateSnapshot state,ImmutableArray<GameServerEvent> events,Guid? currentAttempt=null)
    {
        if(currentAttempt is {} id&&attempt!=id)
        {attempt=id;observed=permission=consumed=0;}
        foreach(var e in events.Where(e=>e.Sequence>observed))
        {
            if(e.Type is "event_end" or "battle_start"||e.Type=="position_snapshot"&&e.Role==state.Player?.RoleId)permission=0;
            else if(e.Type=="event_continue_permission")permission=e.Sequence;
            observed=Math.Max(observed,e.Sequence);
        }
        // Grants belong to receive-owned state, not to a short diagnostic history.
        // Heavy scene traffic may evict the receipt before a scheduler wakes up.
        var flow=state.Local.Session.EventFlow;
        bool validSource=flow.LastSource is "S20-7" or "S20-10" or "S20-11" or "S20-13" or "S20-14" or "S20-15" or "S20-16" or "S20-17" or "C20-6";
        if(flow.PermissionTracked)
            permission=flow.Blocked&&validSource&&flow.PermissionPacket is {} tracked&&tracked>0&&tracked<=long.MaxValue?(long)tracked:0;
        else if(flow is{Blocked:true,AwaitingResponse:false,PermissionPacket:{} grant}&&validSource&&grant>0&&grant<=long.MaxValue&&grant>permission)
            permission=(long)grant;
        if(!flow.Blocked)permission=0;
        return null;
    }
    internal void Admit(ServiceStateSnapshot state,ImmutableArray<GameServerEvent> events,long? expectedPermission,Guid? currentAttempt=null)
    {
        Observe(state,events,currentAttempt);
        if(permission<=consumed||permission==0||expectedPermission is { } expected&&expected!=permission)
            throw new ProtocolException("事件接續許可已使用或已改變，不會重複送出。");
        consumed=permission;
    }
}
