using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.World;

public sealed record NpcVisibilityTimer(double Due, bool Visible);
/// <summary>Server observations. A movement destination is not an arrival or a collision shape.</summary>
public sealed record WorldNpcState(ushort Index, ushort? X=null, ushort? Y=null,
    ushort? TargetX=null, ushort? TargetY=null, byte? Speed=null, bool? Visible=null,
    bool VisibilityReliable=true, ImmutableArray<NpcVisibilityTimer> Timers=default)
{
    public bool? VisibleAt(double now)
    {
        if(!VisibilityReliable||!double.IsFinite(now))return null;
        bool? value=Visible;
        foreach(var timer in Timers.IsDefault?Enumerable.Empty<NpcVisibilityTimer>():Timers.OrderBy(t=>t.Due))
            if(timer.Due<=now)value=timer.Visible;
        return value;
    }
}
/// <summary>Current scene only. No NPC radius, wall, door condition or navigation authority is inferred.</summary>
public sealed record WorldNpcRuntime
{
    public ImmutableDictionary<ushort,WorldNpcState> Npcs {get;init;}=ImmutableDictionary<ushort,WorldNpcState>.Empty;
    public BigInteger Revision {get;init;}
    public bool Overflowed {get;init;}
    internal WorldNpcRuntime Apply(ServerEvent e,double? now)
    {
        if(now is {} time&&!double.IsFinite(time))throw new ArgumentException("Invalid observation time.");
        var next=this;
        switch(e)
        {
            case SceneNpcMoveEvent move:
                next=Change(move.Index,s=>s with{TargetX=move.X,TargetY=move.Y,Speed=move.Speed});break;
            case SceneNpcTeleportEvent move:
                next=Change(move.Index,s=>s with{X=move.X,Y=move.Y,TargetX=null,TargetY=null});break;
            case SceneNpcShowEvent show:
                next=Change(show.Index,s=>SetVisible(s,show.Visibility is 1 or 3,null,now));break;
            case SceneNpcVisibilityEvent visible:
                next=Change(visible.Index,s=>SetVisible(s,visible.Visible,visible.Permanent?null:visible.Duration,now));break;
            case SceneNpcStatusEvent statuses:
                foreach(var row in statuses.Npcs)
                {
                    next=next.Change(row.Index,s=>
                    {
                        if(row.X!=0||row.Y!=0)s=s with{X=row.X,Y=row.Y,TargetX=null,TargetY=null};
                        return SetVisible(s,row.Visibility is 1 or 3,row.Duration is 0 or ushort.MaxValue?null:row.Duration,now);
                    });
                }
                break;
        }
        return next;
    }
    private WorldNpcRuntime Change(ushort index,Func<WorldNpcState,WorldNpcState> update)
    {
        if(Npcs.Count>=4096&&!Npcs.ContainsKey(index))return this with{Overflowed=true};
        var before=Npcs.GetValueOrDefault(index)??new(index);
        var after=update(before);
        return Npcs.ContainsKey(index)&&after==before?this:this with{Npcs=Npcs.SetItem(index,after),Revision=Revision+1};
    }
    private static WorldNpcState SetVisible(WorldNpcState state,bool visible,uint? duration,double? now)
    {
        var timers=state.Timers.IsDefault?ImmutableArray<NpcVisibilityTimer>.Empty:state.Timers;
        if(now is {} time)timers=[..timers.Where(t=>t.Due>time)];
        if(duration==0)return state with{Visible=!visible,Timers=timers};
        if(duration is {} seconds)
        {
            if(now is not {} timestamp||timers.Length>=64)return state with{Visible=visible,VisibilityReliable=false,Timers=timers};
            timers=timers.Add(new(timestamp+seconds,!visible));
        }
        // The official handler schedules every timer independently. A later permanent
        // command does not silently cancel older timers.
        return state with{Visible=visible,Timers=timers};
    }
}
