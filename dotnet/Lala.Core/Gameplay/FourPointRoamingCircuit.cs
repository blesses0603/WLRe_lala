using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.World;

namespace Lala.Core.Gameplay;

/// <summary>Python Roaming / official AutoWalk offsets, converted from nav Int3 to packet XY.
/// Fixed center; full five-leg preflight includes the repeating closure.</summary>
internal sealed class FourPointRoamingCircuit
{
    internal uint Role {get;}
    internal ushort Scene {get;}
    internal LogicalNavigationCoordinate Center {get;}
    internal ImmutableArray<LogicalNavigationCoordinate> Goals {get;}
    internal int Next {get;private set;}
    internal BigInteger? BaseFix {get;set;}
    private BigInteger? preparedRevision;
    private OfflineNavigationIdentity? preparedIdentity;
    internal FourPointRoamingCircuit(uint role,ushort scene,LogicalNavigationCoordinate center,BigInteger? fix,int next=0)
    {
        Role=role;Scene=scene;Center=center;BaseFix=fix;Next=next;
        if(next is <0 or >3||!double.IsFinite(center.X)||!double.IsFinite(center.Y))throw new NavigationException("徘徊中心無效。");
        Goals=[new(center.X-200,center.Y+100),new(center.X-200,center.Y-200),new(center.X+200,center.Y+100),new(center.X+200,center.Y-200)];
        if(Goals.Any(p=>p.X is <0 or >65535||p.Y is <0 or >65535))throw new NavigationException("四點徘徊超出場景座標範圍。");
    }
    internal void Preflight(OfflineLogicalNavigationPreview preview,WorldNavigationSnapshot navigation,CancellationToken token)
    {
        if(preparedRevision==navigation.Revision&&preparedIdentity==preview.Identity)return;
        var previous=Center;
        foreach(var goal in Goals.Append(Goals[0]))
        {
            var route=preview.Route(Scene,previous,goal,navigation:navigation,cancellationToken:token);
            Validate(route);
            _=new GameNavigationRoute(preview.Load(route.ModelId,cancellationToken:token),route,Role,BaseFix,()=>true).ExecutionSteps(token);
            previous=goal;
        }
        preparedRevision=navigation.Revision;preparedIdentity=preview.Identity;
    }
    internal void Validate(OfflineLogicalNavigationRoute route)
    {
        if(route.MeshRoute.Length>8000||route.LogicalPoints.Any(p=>Math.Sqrt(Math.Pow(p.X-Center.X,2)+Math.Pow(p.Y-Center.Y,2))>300))
            throw new NavigationException("四點徘徊路線超出原版距離或中心範圍。");
    }
    internal void Advance()=>Next=(Next+1)%4;
}
