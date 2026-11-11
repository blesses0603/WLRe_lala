using System.Collections.Immutable;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public void Character_history_retains_only_proven_self_events_and_survives_scene_traffic()
    {
        var s=GameState(); uint role=s.Player!.RoleId;
        ServerEvent[] all=[new PositionSnapshotEvent(12,role,101,20,30,0,new(false)),
            new PositionSnapshotEvent(12,role+1,101,40,50,0,new(false)),
            new WalkEvent((int)role,21,31),new WalkEvent((int)role+1,41,51),
            new AttributeSetEvent(1,"self",null,null,1,"hp",1,123,0),
            new AttributeSetEvent(2,"follow",null,1,1,"hp",1,456,0),
            new GoldSnapshotEvent(10),new EventContinuePermissionEvent(10,0),
            new SceneNpcMoveEvent(1,20,30,1),new SceneNpcVisibilityEvent(10,1,65535),
            new UnimplementedServerEvent(90,1,5),new HeartbeatRequestEvent()];
        ImmutableArray<GameServerEvent> history=[]; long seq=0;
        foreach(var e in all)
        {
            var entry=CharacterEventLog.Scope(GameServerEvent.From(++seq,e),e,s,s);
            history=CharacterEventLog.Append(history,entry,role);
        }
        Assert.Equal(5,history.Length); Assert.All(history,e=>Assert.Equal(role,e.OwnerRoleId));
        Assert.DoesNotContain(history,e=>e.Main==22||e.Type=="unimplemented"||e.Role==role+1);
        var retained=history;
        for(int i=0;i<1000;i++)
        {
            var e=new SceneNpcMoveEvent((ushort)i,1,2,3);
            history=CharacterEventLog.Append(history,CharacterEventLog.Scope(GameServerEvent.From(++seq,e),e,s,s),role);
        }
        Assert.Equal(retained,history);
        for(int i=0;i<250;i++) history=CharacterEventLog.Append(history,new(++seq,26,4,"gold_snapshot","",OwnerRoleId:role),role);
        Assert.Equal(200,history.Length);
        Assert.Empty(CharacterEventLog.Append(history,new(++seq,22,2,"scene_npc_move",""),role+1));
        Assert.Empty(CharacterEventLog.Append(history,new(++seq,1,23,"heartbeat_request",""),null));
        Assert.Null(CharacterEventLog.Scope(new(1,26,4,"gold_snapshot",""),new GoldSnapshotEvent(10),new(),new()).OwnerRoleId);
    }

    [Fact]
    public void Repeated_timed_visibility_refreshes_are_real_scene_progress()
    {
        var guard=new EventContinuationGuard();var s=BlockedEventState();
        ImmutableArray<GameServerEvent> events=[];long seq=0;
        for(int i=0;i<80;i++)
        {
            events=events.Add(FlowPacket(++seq,22,10,1,0,30,0)).Add(FlowPacket(++seq,20,11));
            Assert.Null(guard.Observe(s,events));guard.Admit(s,events,seq);
        }
    }

    [Fact]
    public void Scene_updates_never_grant_event_continuation()
    {
        var guard=new EventContinuationGuard();var s=BlockedEventState();
        ImmutableArray<GameServerEvent> events=[FlowPacket(1,22,2,1,0,20,0,30,0,1),FlowPacket(2,22,10,1,0,255,255)];
        Assert.Null(guard.Observe(s,events)); Assert.Null(guard.Permission);
        Assert.Throws<ProtocolException>(()=>guard.Admit(s,events,null));
    }
}
