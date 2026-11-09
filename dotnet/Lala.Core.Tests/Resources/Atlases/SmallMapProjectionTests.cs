using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SmallMapProjectionTests
{
    private static StageDataRow Stage(ushort width,ushort height,ushort x=0,ushort y=0)=>new(1,0,10001,0,0,0,0,0,0,0,0,99,77,width,height,x,y);
    // Expected pixels obtained from the repository's real Python Projection
    // with SmallMaps.projection's current-scene height and zero origin.
    [Theory]
    [InlineData(1000,2000,12,8,500,1000,262,516)]
    [InlineData(65535,65535,12,12,3496,3496,512,512)]
    [InlineData(10000,1000,0,0,10000,1000,1000,1024)]
    [InlineData(1,1,0,0,0,0,0,24)]
    [InlineData(65535,3000,10,20,100,200,24.302059496567505,603.5423340961099)]
    [InlineData(3000,65535,1024,1024,0,6992,1024,0)]
    public void Current_scene_projection_matches_Python_and_does_not_apply_packet_ratios(ushort w,ushort h,ushort ox,ushort oy,double x,double y,double u,double v)
    {var projection=SmallMapProjection.Create(Stage(w,h,ox,oy));Assert.NotNull(projection);Assert.True(projection.TryProject(x,y,out var pixel));Assert.Equal(u,pixel.X,9);Assert.Equal(v,pixel.Y,9);}
    [Theory][InlineData(0,1000,0,0)][InlineData(1000,0,0,0)][InlineData(1000,1000,1025,0)][InlineData(1000,1000,0,1025)]
    public void Missing_or_invalid_geometry_has_no_projection(ushort w,ushort h,ushort ox,ushort oy)=>Assert.Null(SmallMapProjection.Create(Stage(w,h,ox,oy)));
    [Theory][InlineData(double.NaN,0)][InlineData(0,double.PositiveInfinity)][InlineData(-1,0)][InlineData(0,-1)][InlineData(65536,0)][InlineData(2000,0)][InlineData(0,2000)]
    public void Nonfinite_negative_overflow_or_off_artwork_position_is_hidden(double x,double y)
    {Assert.False(SmallMapProjection.Create(Stage(1000,1000))!.TryProject(x,y,out var pixel));Assert.Equal(default,pixel);}
    [Fact]
    public void Requests_recheck_currentness_and_missing_geometry_never_guesses()
    {
        var snapshot=new SmallMapPngSnapshot(new("source","batch",1),new(){{10001,[1,2,3]}});var projection=SmallMapProjection.Create(Stage(1000,2000,12,8));
        bool current=true;var request=new SmallMapRenderRequest(snapshot,10001,()=>current,projection);
        Assert.True(request.TryProjectPosition(500,1000,out var pixel));Assert.Equal(new SmallMapPixel(262,516),pixel);
        current=false;Assert.False(request.TryProjectPosition(500,1000,out _));
        int checks=0;var race=new SmallMapRenderRequest(snapshot,10001,()=>++checks==1,projection);Assert.False(race.TryProjectPosition(500,1000,out var late));Assert.Equal(default,late);
        var absent=new SmallMapRenderRequest(snapshot,10001,()=>true);Assert.False(absent.TryProjectPosition(500,1000,out _));
        Assert.Null(SmallMapProjection.Create(Stage(1000,1000) with{ModelId=0}));
    }
}
