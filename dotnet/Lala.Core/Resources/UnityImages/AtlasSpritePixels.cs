using System.Text.Json;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed class AtlasPixelCandidate
{
    private readonly byte[] pixels;
    internal string Name {get;}
    internal int Width {get;}
    internal int Height {get;}
    internal string InputFingerprint {get;}
    internal string PixelSha256 {get;}
    internal bool HasVerifiedProvenance=>false;
    internal byte[] CopyPixels()=>pixels.ToArray();
    internal AtlasPixelCandidate(string name,int width,int height,byte[] owned,string inputs)
    {Name=name;Width=width;Height=height;pixels=owned;InputFingerprint=inputs;PixelSha256=SpritePng.Hash(owned);}
}
// Exact selected objects only. No directory/name fallback, source admission or publication.
internal static class AtlasSpritePixels
{
    internal static AtlasPixelCandidate Extract(UnitySelectedObjects selected,UnityFileIdentity atlasFile,long atlasId,
        UnityFileIdentity spriteFile,long spriteId,string expectedName,CancellationToken token=default,UnityImageArchive? imageArchive=null)
    {
        token.ThrowIfCancellationRequested();
        var atlasObject=selected.Resolve(atlasFile,new(0,atlasId),687078895)!;
        var spriteObject=selected.Resolve(spriteFile,new(0,spriteId),213)!;
        var atlas=UnityAtlasObjects.Read(atlasObject.Object.Bytes,token);
        var sprite=UnityImageObjects.Sprite(spriteObject.Object.Bytes,token,true);
        Require(sprite.Name==expectedName && sprite.Atlas is not null && sprite.RenderKey is not null,"Sprite name or atlas identity mismatch");
        var backlink=selected.Resolve(spriteFile,sprite.Atlas!,687078895)!;
        Require(backlink.File==atlasFile&&backlink.PathId==atlasId,"Sprite points to a different atlas");
        int matches=0;
        foreach(var pointer in atlas.Sprites)
        {
            token.ThrowIfCancellationRequested();var packed=selected.Resolve(atlasFile,pointer,213)!;
            if(packed.File==spriteFile&&packed.PathId==spriteId)matches++;
        }
        Require(matches==1,"Sprite is not uniquely packed by this atlas");
        Require(atlas.RenderData.TryGetValue(sprite.RenderKey!.Value,out var entry),"Atlas render key missing");
        var textureObject=selected.Resolve(atlasFile,entry!.Texture,28)!;
        var alphaObject=selected.Resolve(atlasFile,entry.Alpha,28,true);
        var texture=UnityImageObjects.Texture(textureObject.Object.Bytes,token,imageArchive,textureObject.File);
        var alpha=alphaObject is null?null:UnityImageObjects.Texture(alphaObject.Object.Bytes,token,imageArchive,alphaObject.File);
        // Include complete immutable object bytes and identities, not just cropped pixels.
        object Stamp(UnityResolvedObject o)=>new{o.File,o.PathId,Hash=SpritePng.Hash(o.Object.Bytes.Span)};
        string inputs=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new{Archive=imageArchive is null?null:new{imageArchive.BundleName,imageArchive.SourceSha256},Atlas=Stamp(atlasObject),Sprite=Stamp(spriteObject),Texture=Stamp(textureObject),Alpha=alphaObject is null?null:Stamp(alphaObject)}));
        return Decode(sprite.Name,sprite.LogicalRect!,entry,texture,alpha,inputs,token);
    }
    internal static AtlasPixelCandidate Decode(string name,SpritePixelRect logical,UnityAtlasData entry,UnityTexturePixels texture,
        UnityTexturePixels? alpha,string inputs,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require((entry.Settings & ~0x7fU)==0 && (entry.Settings & 3)==3 && ((entry.Settings>>2)&15)<=4 && entry.Downscale==1,"Unreviewed atlas packing/rotation/downscale");
        Require((entry.Alpha.PathId!=0)==(alpha is not null),"Atlas alpha presence mismatch");
        static int Integral(float f){Require(float.IsFinite(f)&&f>=0&&f<=2048&&f==MathF.Truncate(f),"Invalid atlas crop");return (int)f;}
        int x=Integral(entry.Rect.X),y=Integral(entry.Rect.Y),w=Integral(entry.Rect.Width),h=Integral(entry.Rect.Height);
        Require(w is >0 and <=512&&h is >0 and <=512,"Atlas sprite exceeds bound");
        byte[] Raw(UnityTexturePixels t)
        {
            var l=t.Layout;Require(l.Width is >0 and <=2048&&l.Height is >0 and <=2048&&l.MipCount==1&&l.ImageCount==1&&l.Dimension==2&&l.Platform==19&&!l.Streamed&&!l.HasPlatformBlob,"Unsupported atlas texture layout");
            Require(t.ColorSpace==1&&l.Format is 4 or 10 or 12,"Unreviewed atlas texture color space/format");
            Require(t.Payload.Length==BlockTexturePixels.PayloadLength(l.Width,l.Height,l.Format),"Atlas texture size mismatch");
            Require(x<=l.Width-w&&y<=l.Height-h,"Atlas crop exceeds texture");
            var owned=t.Payload.ToArray();return l.Format==4?owned:BlockTexturePixels.Decode(owned,l.Width,l.Height,l.Format,token);
        }
        var raw=Raw(texture);byte[]? mask=null;
        if(alpha is not null){Require(alpha.Layout.Width==texture.Layout.Width&&alpha.Layout.Height==texture.Layout.Height,"Atlas alpha geometry mismatch");mask=Raw(alpha);}
        int rotation=(int)((entry.Settings>>2)&15),width=rotation==4?h:w,height=rotation==4?w:h;
        Require(logical.Width>=width&&logical.Height>=height&&logical.Width<=512&&logical.Height<=512&&logical.Width==MathF.Truncate(logical.Width)&&logical.Height==MathF.Truncate(logical.Height),"Invalid logical atlas Sprite size");
        // Python returns the transformed atlas crop, without padding to the logical rect.
        var pixels=new byte[width*height*4];
        for(int row=0;row<height;row++)
        {
            token.ThrowIfCancellationRequested();
            for(int col=0;col<width;col++)
            {
                // Invert final vertical flip, then invert UnityPy's packing transform.
                int u=col,v=height-1-row;
                (int sx,int sy)=rotation switch{0=>(u,v),1=>(w-1-u,v),2=>(u,h-1-v),3=>(w-1-u,h-1-v),4=>(v,h-1-u),_=>throw new UnityTextAssetException("Unknown rotation")};
                int src=((y+sy)*texture.Layout.Width+x+sx)*4,dst=(row*width+col)*4;
                raw.AsSpan(src,4).CopyTo(pixels.AsSpan(dst,4));if(mask is not null)pixels[dst+3]=mask[src];
            }
        }
        token.ThrowIfCancellationRequested();return new(name,width,height,pixels,inputs);
    }
}
