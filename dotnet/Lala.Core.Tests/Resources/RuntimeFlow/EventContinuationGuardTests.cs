using System.Collections.Immutable;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static GameServerEvent FlowPacket(long sequence,byte main,byte sub,params byte[] payload)
    {
        var packet=new Packet(main,sub,payload);return GameServerEvent.From(sequence,ServerProtocol.Decode(packet),packet);
    }
    private static ServiceStateSnapshot BlockedEventState()
    {
        var s=GameState();return CommandState.With(s,local:new(s.Local.Session with{EventFlow=new(){Blocked=true,LastSource="S20-10"}},s.Local.World,s.Local.Battle));
    }
    [Fact]
    public void Repeated_scene_effects_do_not_override_genuine_new_continuation_grants()
    {
        var state=BlockedEventState();var guard=new EventContinuationGuard();long seq=0;
        ImmutableArray<GameServerEvent> events=[FlowPacket(++seq,20,10)];
        guard.Admit(state,events,seq);
        for(int round=0;round<2;round++)
        {
            events=events.Add(FlowPacket(++seq,22,10,1,0,255,255)).Add(FlowPacket(++seq,20,11)).Add(FlowPacket(++seq,20,10));
            guard.Admit(state,events,seq);
        }
        events=events.Add(FlowPacket(++seq,22,10,1,0,255,255)).Add(FlowPacket(++seq,20,11)).Add(FlowPacket(++seq,20,10));
        guard.Admit(state,events,seq);Assert.Null(guard.Observe(state,events));
        Assert.Throws<ProtocolException>(()=>guard.Admit(state,events,seq)); // Restarting automation retains the account guard.
        var ended=CommandState.With(state,local:new(SessionEventReducer.Apply(state.Local.Session,new EventEndEvent()),state.Local.World,state.Local.Battle));
        events=events.Add(FlowPacket(++seq,20,8));Assert.Null(guard.Observe(ended,events));
        events=events.Add(FlowPacket(++seq,20,10));guard.Admit(state,events,seq);
    }
    [Fact]
    public void Distinct_event_content_progresses_but_one_permission_is_never_consumed_twice()
    {
        var state=BlockedEventState();var guard=new EventContinuationGuard();ImmutableArray<GameServerEvent> events=[];long seq=0;
        for(byte i=0;i<80;i++)
        {
            events=events.Add(FlowPacket(++seq,22,10,i,0,255,255)).Add(FlowPacket(++seq,20,11));
            Assert.Null(guard.Observe(state,events));guard.Admit(state,events,seq);
        }
        Assert.Throws<ProtocolException>(()=>guard.Admit(state,events,seq));
        events=events.Add(FlowPacket(++seq,20,10));
        Assert.Throws<ProtocolException>(()=>guard.Admit(state,events,seq-1));
        guard.Admit(state,events,seq);
        Assert.NotEqual(events[0].ContentFingerprint,events[2].ContentFingerprint);
        Assert.Null(FlowPacket(++seq,1,23).ContentFingerprint);
    }
    [Fact]
    public void Changing_payloads_do_not_introduce_an_arbitrary_protocol_step_limit()
    {
        var state=BlockedEventState();var guard=new EventContinuationGuard();ImmutableArray<GameServerEvent> events=[];long seq=0;
        for(byte i=0;i<32;i++)
        {
            events=events.Add(FlowPacket(++seq,20,13,i)).Add(FlowPacket(++seq,20,10));guard.Admit(state,events,seq);
        }
        events=events.Add(FlowPacket(++seq,20,13,33)).Add(FlowPacket(++seq,20,10));
        guard.Admit(state,events,seq);Assert.Null(guard.Observe(state,events));
        var progressed=new ServiceStateSnapshot(local:state.Local,playerKnowledge:state.PlayerKnowledge with{Stats=state.PlayerKnowledge.Stats.SetItem("hp",1)});
        Assert.Null(guard.Observe(progressed,events));Assert.Throws<ProtocolException>(()=>guard.Admit(progressed,events,seq));
    }
    [Fact]
    public void Reconnect_resets_grant_sequences_but_UI_restart_in_the_same_attempt_does_not()
    {
        var s=BlockedEventState();var guard=new EventContinuationGuard();var first=Guid.NewGuid();var second=Guid.NewGuid();
        ImmutableArray<GameServerEvent> old=[FlowPacket(100,20,10)];guard.Admit(s,old,100,first);
        Assert.Throws<ProtocolException>(()=>guard.Admit(s,old,100,first));
        ImmutableArray<GameServerEvent> fresh=[FlowPacket(1,20,10)];guard.Admit(s,fresh,1,second);
        var cleared=CommandState.With(s,local:new(s.Local.Session with{EventFlow=s.Local.Session.EventFlow with{PermissionTracked=true,PermissionPacket=null}},s.Local.World,s.Local.Battle));
        Assert.Null(guard.Observe(cleared,fresh,second));Assert.Null(guard.Permission);
    }

    [Fact]
    public void Receive_owned_permission_survives_unrelated_receipt_buffer_overflow()
    {
        var original=BlockedEventState();
        var state=CommandState.With(original,local:new(original.Local.Session with{EventFlow=original.Local.Session.EventFlow with{PermissionPacket=10}},original.Local.World,original.Local.Battle));
        var guard=new EventContinuationGuard();
        ImmutableArray<GameServerEvent> events=[FlowPacket(900,22,2,1,0,20,0,30,0,1)];
        Assert.Null(guard.Observe(state,events));Assert.Equal(10,guard.Permission);
        guard.Admit(state,events,10);Assert.Throws<ProtocolException>(()=>guard.Admit(state,events,10));
    }

    [Fact]
    public void Own_position_or_battle_transition_revokes_old_permission_but_nearby_positions_do_not()
    {
        var state=BlockedEventState();var guard=new EventContinuationGuard();
        ImmutableArray<GameServerEvent> events=[FlowPacket(1,20,10)];
        events=events.Add(new(2,12,1,"position_snapshot","",Role:state.Player!.RoleId+1));
        Assert.Null(guard.Observe(state,events));Assert.Equal(1,guard.Permission);
        events=events.Add(new(3,12,1,"position_snapshot","",Role:state.Player.RoleId));
        Assert.Null(guard.Observe(state,events));Assert.Null(guard.Permission);Assert.Throws<ProtocolException>(()=>guard.Admit(state,events,1));
        events=events.Add(FlowPacket(4,20,10));guard.Admit(state,events,4);
        events=events.Add(FlowPacket(5,20,10)).Add(new(6,11,250,"battle_start",""));
        Assert.Null(guard.Observe(state,events));Assert.Null(guard.Permission);
    }
}
