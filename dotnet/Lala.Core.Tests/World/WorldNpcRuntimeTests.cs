using Lala.Core.Protocol;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public class WorldNpcRuntimeTests
{
    [Fact]
    public void Movement_is_a_target_until_teleport_or_status_confirms_position()
    {
        var state=new WorldNpcRuntime().Apply(new SceneNpcMoveEvent(40000,100,200,3),10);
        var npc=state.Npcs[40000];Assert.Null(npc.X);Assert.Equal((ushort)100,npc.TargetX);
        state=state.Apply(new SceneNpcTeleportEvent(40000,120,220),11);
        npc=state.Npcs[40000];Assert.Equal((ushort)120,npc.X);Assert.Null(npc.TargetX);
        state=state.Apply(new SceneNpcStatusEvent([new(40000,0,0,0,0,1,0,0)]),12);
        Assert.Equal((ushort)120,state.Npcs[40000].X);Assert.True(state.Npcs[40000].VisibleAt(13));
    }
    [Fact]
    public void Timed_visibility_preserves_independent_callbacks_and_zero_duration_semantics()
    {
        var state=new WorldNpcRuntime().Apply(new SceneNpcVisibilityEvent(11,1,10),100);
        Assert.True(state.Npcs[1].VisibleAt(109));Assert.False(state.Npcs[1].VisibleAt(110));
        state=state.Apply(new SceneNpcShowEvent(1,1),105);
        Assert.True(state.Npcs[1].VisibleAt(106));Assert.False(state.Npcs[1].VisibleAt(111));
        state=state.Apply(new SceneNpcVisibilityEvent(10,2,0),110);
        Assert.True(state.Npcs[2].VisibleAt(110));
        state=state.Apply(new SceneNpcStatusEvent([new(3,0,0,1,2,2,0,0)]),110);
        Assert.False(state.Npcs[3].VisibleAt(110));
        var unknown=new WorldNpcRuntime().Apply(new SceneNpcVisibilityEvent(10,4,10),null);
        Assert.Null(unknown.Npcs[4].VisibleAt(110));
    }
    [Fact]
    public void Npc_updates_do_not_invent_solid_obstacles_or_modify_the_player_and_map_switch_clears_them()
    {
        var player=new WorldPlayer(17,0,100,10,20,0,0,0,0,0,0,false,[],"test",0);
        var state=WorldEventReducer.Apply(new(),new ServerLayoutEvent(new WorldPlayerEvent(player)));
        var revision=state.Navigation.Revision;
        state=WorldEventReducer.Apply(state,new SceneNpcMoveEvent(1,100,200,3),observedAt:1);
        Assert.Equal(player,state.Player);Assert.Equal(revision,state.Navigation.Revision);Assert.False(state.Navigation.Stale);
        state=WorldEventReducer.Apply(state,new PositionSnapshotEvent(12,18,101,2,3,0,new(false)));
        Assert.Single(state.NpcRuntime.Npcs);
        state=WorldEventReducer.Apply(state,new PositionSnapshotEvent(12,17,101,2,3,0,new(false)));
        Assert.Empty(state.NpcRuntime.Npcs);
    }
    [Fact]
    public void Unknown_indices_have_a_bounded_scene_history()
    {
        var state=new WorldNpcRuntime();for(int i=0;i<4100;i++)state=state.Apply(new SceneNpcMoveEvent((ushort)i,1,2,1),1);
        Assert.Equal(4096,state.Npcs.Count);Assert.True(state.Overflowed);
    }
}
