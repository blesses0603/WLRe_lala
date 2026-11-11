using Lala.Core.Catalogs;
using Lala.Core.Gameplay;
using Lala.Core.World;
using Xunit;

namespace Lala.Core.Tests.World;

public class FourPointRoamingCircuitTests
{
    [Fact]
    public void Four_points_match_python_order_and_all_legs_remain_near_the_fixed_center()
    {
        var identity=new OfflineNavigationIdentity("b500c9c684777edb5c80671541eb1ebc51bce5ed26a81270578a6fed259363e6","synthetic");
        var a=new NavigationPoint(0,0,0);var b=new NavigationPoint(20000,0,0);var c=new NavigationPoint(20000,0,20000);var d=new NavigationPoint(0,0,20000);
        var mesh=new PreviewNavigationMesh([new NavigationTile([new(a,b,c),new(a,c,d)],[new(0,1),new(0,1)])],
            new[]{new[]{new NavigationConnection(1,1)},new[]{new NavigationConnection(0,1)}},sceneId:"M00042");
        var stage=new StageDataRow(200,0,42,0,0,0,0,0,0,0,0,0,0,2000,2000,0,0);
        var preview=new OfflineLogicalNavigationPreview(identity,new(identity,[stage]),[new(identity,42,new(),mesh)]);
        var plan=new FourPointRoamingCircuit(17,200,new(1000,1000),1);
        Assert.Equal(new LogicalNavigationCoordinate[]{new(800,1100),new(800,800),new(1200,1100),new(1200,800)},plan.Goals);
        plan.Preflight(preview,new(),CancellationToken.None);Assert.Equal(0,plan.Next);
        for(int i=0;i<4;i++)plan.Advance();Assert.Equal(0,plan.Next);
        Assert.Throws<NavigationException>(()=>plan.Validate(preview.Route(200,new(1000,1000),new(1500,1000))));
        Assert.Throws<NavigationException>(()=>new FourPointRoamingCircuit(17,200,new(0,0),1));
    }
}
