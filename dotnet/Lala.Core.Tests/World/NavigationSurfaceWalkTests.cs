using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;
public class NavigationSurfaceWalkTests
{
    private static PreviewNavigationMesh Ramp(bool connected=true,bool upstairs=false)
    {
        var a=new NavigationPoint(0,0,0);var b=new NavigationPoint(1000,500,0);var c=new NavigationPoint(1000,500,1000);var d=new NavigationPoint(0,0,1000);
        var tris=new List<NavigationTriangle>{new(a,b,c),new(a,c,d)};
        if(upstairs)tris.Add(new(new(0,1000,0),new(1000,1000,0),new(1000,1000,1000)));
        var links=Enumerable.Range(0,tris.Count).Select(_=>new List<NavigationConnection>()).ToArray();
        if(connected){links[0].Add(new(1,1));links[1].Add(new(0,1));}
        return new([new NavigationTile(tris,tris.Select(_=>(NavigationNodeMetadata?)new NavigationNodeMetadata(0,1)))],links,sceneId:"M00042");
    }
    [Fact]
    public void Sloped_route_produces_bounded_integer_movement_steps()
    {
        var id=new OfflineNavigationIdentity("b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6","synthetic");var mesh=Ramp();
        var entry=new OfflineNavigationCacheEntry(id,42,new(),mesh);
        var stage=new StageDataRow(200,0,42,0,0,0,0,0,0,0,0,0,0,200,200,0,0);
        var preview=new OfflineLogicalNavigationPreview(id,new(id,[stage]),[entry]);
        var route=preview.Route(200,new(10,170),new(90,130));
        var live=new GameNavigationRoute(entry,route,17,1,()=>true);
        var steps=live.ExecutionSteps(default);Assert.NotEmpty(steps);Assert.Equal(new LogicalNavigationCoordinate(90,130),steps[^1]);
    }
    [Fact]
    public void Surface_validation_rejects_overlapping_floors_and_missing_directed_connections()
    {
        Assert.Throws<NavigationException>(()=>NavigationSurfaceWalk.Validate(Ramp(upstairs:true),[0,1],new(100,0,100),new(900,0,900),default));
        Assert.Throws<NavigationException>(()=>NavigationSurfaceWalk.Validate(Ramp(connected:false),[0,1],new(100,0,900),new(900,0,100),default));
        NavigationTriangle[] crossing=[new(new(0,0,0),new(1000,500,0),new(1000,500,1000)),new(new(0,500,0),new(1000,0,0),new(1000,0,1000))];
        var mesh=new PreviewNavigationMesh([new NavigationTile(crossing,[new(0,1),new(0,1)])],new[]{Array.Empty<NavigationConnection>(),Array.Empty<NavigationConnection>()},sceneId:"M00042");
        Assert.Throws<NavigationException>(()=>NavigationSurfaceWalk.Validate(mesh,[0],new(100,0,100),new(900,0,900),default));
    }
}
