namespace Lala.Core.Resources;

internal sealed record TexturePixelContext(string VersionIdentity, string BundleSha256, string SerializedFile, string AssetPath, long TexturePathId);
// Whole Texture2D pixels have no Sprite identity, crop, packing or atlas semantics.
internal sealed class TexturePixelCandidate
{
    private readonly byte[] pixels;
    internal TexturePixelContext Context { get; }
    internal TexturePixelLayout Layout { get; }
    internal int ColorSpace { get; }
    internal string PayloadSha256 { get; }
    internal string PixelSha256 { get; }
    internal bool HasVerifiedProvenance => false;
    internal byte[] CopyPixels() => pixels.ToArray();
    internal TexturePixelCandidate(TexturePixelContext context, TexturePixelLayout layout, int colorSpace, byte[] ownedPixels, string payloadSha256)
    { Context=context;Layout=layout;ColorSpace=colorSpace;pixels=ownedPixels;PayloadSha256=payloadSha256;PixelSha256=SpritePng.Hash(pixels); }
}
internal static class BoundedTexturePixels
{
    internal static TexturePixelCandidate Decode(TexturePixelContext context, UnityTexturePixels texture, CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        static bool Identity(string value,int limit)=>!string.IsNullOrEmpty(value)&&value.Length<=limit&&!value.Contains('\0');
        BoundedSpritePixels.Check(Identity(context.VersionIdentity,4096)&&Identity(context.SerializedFile,1024)&&Identity(context.AssetPath,1024)&&
            !context.AssetPath.Contains('\\')&&context.AssetPath.Split('/').All(p=>p.Length>0&&p is not "." and not "..")&&context.TexturePathId!=0&&
            context.BundleSha256.Length==64&&context.BundleSha256.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f'),"Invalid whole-texture context");
        var layout=texture.Layout;
        BoundedSpritePixels.Check(layout.Width is >0 and <=1024&&layout.Height is >0 and <=1024&&layout.MipCount==1&&layout.ImageCount==1&&
            layout.Dimension==2&&layout.Platform==19&&!layout.Streamed&&!layout.HasPlatformBlob,"Unreviewed whole-texture dimensions or layout");
        BoundedSpritePixels.Check(texture.ColorSpace==1&&layout.Format is 4 or 10 or 12,"Whole-texture color space or format is not reviewed");
        BoundedSpritePixels.Check(texture.Payload.Length==BlockTexturePixels.PayloadLength(layout.Width,layout.Height,layout.Format),"Whole-texture payload size mismatch");
        byte[] source=texture.Payload.ToArray();string hash=SpritePng.Hash(source);
        byte[] raw=layout.Format==4?source:BlockTexturePixels.Decode(source,layout.Width,layout.Height,layout.Format,token);
        byte[] pixels=new byte[checked(layout.Width*layout.Height*4)];int stride=layout.Width*4;
        for(int y=0;y<layout.Height;y++)
        { token.ThrowIfCancellationRequested();raw.AsSpan((layout.Height-1-y)*stride,stride).CopyTo(pixels.AsSpan(y*stride,stride)); }
        token.ThrowIfCancellationRequested();return new(context,layout,texture.ColorSpace,pixels,hash);
    }
}
