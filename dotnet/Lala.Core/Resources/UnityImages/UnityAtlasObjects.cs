using System.Collections.Frozen;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal readonly record struct UnityAtlasKey(uint A,uint B,uint C,uint D,long Value);
internal readonly record struct UnityAtlasVector(float X,float Y,float Z=0,float W=0);
internal sealed record UnityAtlasData(UnityContainerPointer Texture,UnityContainerPointer Alpha,
    SpritePixelRect Rect,UnityAtlasVector TextureOffset,UnityAtlasVector AtlasOffset,
    UnityAtlasVector Uv,float Downscale,uint Settings);
internal sealed record UnityAtlasSnapshot(string Name,IReadOnlyList<UnityContainerPointer> Sprites,
    IReadOnlyList<string> Names,FrozenDictionary<UnityAtlasKey,UnityAtlasData> RenderData,string Tag);

// Structural projection only. Packed geometry/UV/alpha are retained, never promoted
// to a pixel recipe. This does not resolve pointers, load dependencies or publish images.
internal static class UnityAtlasObjects
{
    private static float F(UnityReadCursor r)
    {float v=BitConverter.Int32BitsToSingle(r.I32());Require(float.IsFinite(v),"Nonfinite atlas field");return v;}
    private static UnityContainerPointer P(UnityReadCursor r,bool nullable=false)
    {
        var p=new UnityContainerPointer(r.I32(),r.I64());
        Require(p.FileId is >=0 and <=128 && (p.PathId!=0 || nullable&&p.FileId==0),"Invalid atlas pointer");return p;
    }
    internal static UnityAtlasSnapshot Read(ReadOnlyMemory<byte> bytes,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(bytes.Length<=2*1024*1024,"Atlas object exceeds bound");
        var r=new UnityReadCursor(bytes);string name=r.String(1024,false);
        int count=r.Count(2048,12);Require(count>0,"Missing packed sprites");
        var sprites=new UnityContainerPointer[count];var seen=new HashSet<UnityContainerPointer>();
        for(int i=0;i<count;i++){token.ThrowIfCancellationRequested();sprites[i]=P(r);Require(seen.Add(sprites[i]),"Duplicate packed sprite");}r.Align();
        count=r.Count(2048,4);var names=new string[count];var seenNames=new HashSet<string>(StringComparer.Ordinal);
        for(int i=0;i<count;i++){token.ThrowIfCancellationRequested();names[i]=r.String(1024,false);Require(seenNames.Add(names[i]),"Duplicate packed name");}r.Align();
        count=r.Count(2048,108);Require(count>0,"Missing atlas render data");
        var data=new Dictionary<UnityAtlasKey,UnityAtlasData>();
        for(int i=0;i<count;i++)
        {
            token.ThrowIfCancellationRequested();var key=new UnityAtlasKey(r.U32(),r.U32(),r.U32(),r.U32(),r.I64());
            var texture=P(r);var alpha=P(r,true);var rect=new SpritePixelRect(F(r),F(r),F(r),F(r));
            Require(rect.X>=0&&rect.Y>=0&&rect.Width>0&&rect.Height>0&&rect.X+rect.Width<=2048&&rect.Y+rect.Height<=2048,"Atlas rectangle exceeds supported bounds");
            var offset=new UnityAtlasVector(F(r),F(r));var atlasOffset=new UnityAtlasVector(F(r),F(r));var uv=new UnityAtlasVector(F(r),F(r),F(r),F(r));
            float downscale=F(r);Require(downscale>0,"Invalid atlas downscale");uint settings=r.U32();
            Require(r.Count(0)==0,"Secondary atlas textures unsupported");r.Align();
            Require(data.TryAdd(key,new(texture,alpha,rect,offset,atlasOffset,uv,downscale,settings)),"Duplicate atlas render key");
        }
        string tag=r.String(1024);Require(r.U8()==0,"Atlas variants unsupported");r.Align();r.End();token.ThrowIfCancellationRequested();
        return new(name,Array.AsReadOnly(sprites),Array.AsReadOnly(names),data.ToFrozenDictionary(),tag);
    }
}
