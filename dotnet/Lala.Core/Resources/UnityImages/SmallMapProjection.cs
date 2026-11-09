using Lala.Core.Catalogs;
namespace Lala.Core.Resources;

/// <summary>A pixel in the reviewed 1024-square artwork; no movement authority.</summary>
public readonly record struct SmallMapPixel(double X,double Y);

// Mirrors Python SmallMaps.projection / Projection.packet_to_pixel for current
// official scene tables. No historical navigation origin or ratio substitution.
internal sealed class SmallMapProjection(double rate,int height,int offsetX,int offsetY)
{
    internal static SmallMapProjection? Create(StageDataRow stage)
    {
        if(stage.ModelId==0||stage.MapWidth==0||stage.MapHeight==0||stage.SmallOffsetX>1024||stage.SmallOffsetY>1024)return null;
        int width=stage.MapWidth==ushort.MaxValue?6992:stage.MapWidth;
        int height=stage.MapHeight==ushort.MaxValue?6992:stage.MapHeight;
        return new(100.0*(1024-24)/Math.Max(width,height),height,stage.SmallOffsetX,stage.SmallOffsetY);
    }
    internal bool TryProject(double x,double y,out SmallMapPixel pixel)
    {
        pixel=default;if(!double.IsFinite(x)||!double.IsFinite(y)||x<0||y<0||x>ushort.MaxValue||y>ushort.MaxValue)return false;
        double u=x*0.01*rate+offsetX,v=1024-((height-y)*0.01*rate+offsetY);
        if(!double.IsFinite(u)||!double.IsFinite(v)||u<0||v<0||u>1024||v>1024)return false;
        pixel=new(u,v);return true;
    }
}
