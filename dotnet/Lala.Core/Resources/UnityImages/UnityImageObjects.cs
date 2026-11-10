using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using static Lala.Core.Resources.UnityReadCursor;

namespace Lala.Core.Resources;

// Exact normalized 2021.3.45f2 release shapes, reviewed against pinned UnityPy1.25.4 TPK.
// Only fingerprints ship in Core, not a class database or generic permissive tree interpreter.
internal static class UnityImageShapes
{
    internal static void Validate(int classId, IReadOnlyList<UnityTreeShape.Node> nodes)
    {
        var (count, hash) = classId switch
        {
            687078895 => (70, "b3fb80325369e2a3ea8b901de896d7dac69d9729699a29b6d617b13fa824cd33"),
            48 => (2304, "f3ed8d034e403d3917510a21390e073793d851a96523aa8fd51e756b9888b6fb"),
            200 => (22, "1589aaa777f478abc0189279b356609f4794eec7a7f52f0c1874eb5e7a8fef64"),
            21 => (107, "a9e27e0128a6337ddea3c51592bb90e48b2203fd87a3e5ce7f395d0a8e830ad7"),
            28 => (44, "1ce7de4b790393afeb3979cb673250f386b6ef5d91e78743ff8d6a52a9dce178"),
            213 => (167, "0e4602cdddd5763cb291097cd5a0359c703a6ba572a5e189dc95369935b41e01"),
            _ => throw new UnityTextAssetException("Unsupported image class")
        };
        Require(nodes.Count == count, "Unreviewed image tree node count");
        string canonical = string.Concat(nodes.Select(n => string.Create(CultureInfo.InvariantCulture,
            $"{n.Depth}|{n.Type}|{n.Name}|{n.Size}|{(n.Array ? 1 : 0)}|{(n.Align ? 1 : 0)}\n")));
        Require(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(canonical))) == hash, "Unreviewed image type tree");
    }
}
internal sealed record UnityTexturePixels(string Name, TexturePixelLayout Layout, ReadOnlyMemory<byte> Payload, int ColorSpace);
internal sealed record UnitySpritePixels(string Name, UnityContainerPointer Texture, SpritePixelRect Rect,
    UnityAtlasKey? RenderKey = null, UnityContainerPointer? Atlas = null, SpritePixelRect? LogicalRect = null);

internal static class UnityImageObjects
{
    private static bool Bool(UnityReadCursor r) { byte v = r.U8(); Require(v <= 1, "Invalid image boolean"); return v == 1; }
    private static float Float(UnityReadCursor r)
    { float v = BitConverter.Int32BitsToSingle(r.I32()); Require(float.IsFinite(v), "Nonfinite image field"); return v; }
    private static void Floats(UnityReadCursor r, int count) { for (int i = 0; i < count; i++) Float(r); }
    private static UnityContainerPointer Pointer(UnityReadCursor r) => new(r.I32(), r.I64());
    private static void ZeroPointer(UnityReadCursor r)
    { var p = Pointer(r); Require(p.FileId == 0 && p.PathId == 0, "Unsupported image pointer"); }
    private static SpritePixelRect Rect(UnityReadCursor r) => new(Float(r), Float(r), Float(r), Float(r));
    private static void EmptyAlignedArray(UnityReadCursor r) { Require(r.Count(0) == 0, "Unsupported optional image array"); r.Align(); }
    internal sealed record TextureDescriptor(string Name,TexturePixelLayout Layout,ReadOnlyMemory<byte> Inline,int ColorSpace,string StreamPath,long Offset,uint Size);
    internal static TextureDescriptor DescribeTexture(ReadOnlyMemory<byte> bytes,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested(); var r = new UnityReadCursor(bytes); string name = r.String(1024, false);
        r.I32(); Require(!Bool(r), "Downscaled fallback unsupported"); Bool(r); r.Align();
        int width = r.I32(), height = r.I32(); uint complete = r.U32();
        Require(r.I32() == 0, "Stripped mips unsupported"); int format = r.I32(), mips = r.I32();
        Bool(r); Require(!Bool(r), "Preprocessed texture unsupported"); Bool(r);
        Require(!Bool(r), "Streaming mipmaps unsupported"); r.Align(); r.I32(); r.Align();
        int images = r.I32(), dimension = r.I32();
        r.I32(); r.I32(); Float(r); r.I32(); r.I32(); r.I32(); // GLTextureSettings
        r.I32(); int colorSpace = r.I32(); Require(colorSpace is 0 or 1, "Unreviewed texture color space");
        EmptyAlignedArray(r); // platform blob
        int length = r.Count(16 * 1024 * 1024, 1); var payload = r.Take(length); r.Align();
        long streamOffset=r.I64(); uint streamSize=r.U32(); string streamPath=r.String(1024);r.End();
        Require(streamPath.Length==0?streamOffset==0&&streamSize==0:length==0&&streamOffset>=0&&streamSize is >0 and <=16*1024*1024,"Invalid inline or streamed texture span");
        int payloadLength=streamPath.Length==0?length:checked((int)streamSize);
        Require(width is > 0 and <= 2048 && height is > 0 and <= 2048 && mips == 1 && images == 1 && dimension == 2,
            "Unsupported image dimensions/mips/array");
        int expected;
        try { expected = BlockTexturePixels.PayloadLength(width, height, format); }
        catch (SpritePixelException) { throw new UnityTextAssetException("Unreviewed texture compression/format"); }
        Require(payloadLength == expected && complete == payloadLength, "Texture image size mismatch");
        token.ThrowIfCancellationRequested(); return new(name, new(width, height, format), payload, colorSpace,streamPath,streamOffset,streamSize);
    }
    internal static UnityTexturePixels Texture(ReadOnlyMemory<byte> bytes,CancellationToken token,UnityImageArchive? archive=null,UnityFileIdentity? owner=null)
    {
        var d=DescribeTexture(bytes,token);var payload=d.Inline;
        if(d.StreamPath.Length!=0)
        {
            Require(archive is not null&&owner is not null,"Streamed image requires exact archive binding");
            payload=archive!.CopyResource(owner!,d.StreamPath,d.Offset,d.Size,token);
        }
        token.ThrowIfCancellationRequested();return new(d.Name,d.Layout,payload,d.ColorSpace);
    }
    internal static async Task<UnityTexturePixels> TextureAsync(ReadOnlyMemory<byte> bytes,StreamedUnityArchive archive,UnityFileIdentity owner,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(archive);var d=DescribeTexture(bytes,token);var payload=d.Inline;
        archive.RequireOwner(owner,token);
        if(d.StreamPath.Length!=0)payload=await archive.ReadResourceAsync(owner,d.StreamPath,d.Offset,d.Size,token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();return new(d.Name,d.Layout,payload,d.ColorSpace);
    }
    internal static UnitySpritePixels Sprite(ReadOnlyMemory<byte> bytes, CancellationToken token, bool allowAtlas = false)
    {
        token.ThrowIfCancellationRequested(); var r = new UnityReadCursor(bytes); string name = r.String(1024, false);
        var main = Rect(r); Floats(r, 2); Floats(r, 4);
        Require(Float(r) > 0, "Invalid sprite pixels-to-units"); Floats(r, 2); r.U32();
        Require(!Bool(r), "Polygon sprite unsupported"); r.Align();
        var key = new UnityAtlasKey(r.U32(),r.U32(),r.U32(),r.U32(),r.I64());
        int tags = r.Count(allowAtlas ? 16 : 0,4);
        for(int i=0;i<tags;i++){token.ThrowIfCancellationRequested();r.String(1024,false);}r.Align();
        var atlas = Pointer(r);r.Align();bool atlasMode = atlas.PathId != 0;
        Require(atlas.FileId is >=0 and <=128 && (atlasMode ? allowAtlas : atlas.FileId==0&&tags==0), "Unreviewed atlas pointer or name fallback");
        var texture = Pointer(r);
        Require(atlasMode ? texture.FileId is >=0 and <=128 && (texture.PathId!=0||texture.FileId==0) : texture.FileId == 0 && texture.PathId != 0, "Unsupported Sprite texture pointer");
        ZeroPointer(r); EmptyAlignedArray(r); // alpha / secondaryTextures
        // Full-rect decoding does not use geometry. Bound all fields nonetheless; no mesh authority escapes.
        int meshes = r.Count(128, 48);
        for (int i = 0; i < meshes; i++) { token.ThrowIfCancellationRequested(); r.Take(24); Floats(r, 6); }
        r.Align(); int indices = r.Count(1024 * 1024, 1); r.Take(indices); r.Align();
        Require(r.U32() <= 65_536, "Sprite vertex count limit");
        int channels = r.Count(16, 4); r.Take(channels * 4); r.Align();
        int vertices = r.Count(4 * 1024 * 1024, 1); r.Take(vertices); r.Align();
        EmptyAlignedArray(r); // bindpose
        var rect = Rect(r); Floats(r, 2); Floats(r, 2); uint settings = r.U32(); Floats(r, 4);
        float downscale=Float(r);
        Require(atlasMode || downscale == 1 && settings == 2, "Unreviewed downscale/packing/tight mesh"); r.Align();
        if(atlasMode)
        {
            int shapes=r.Count(64,4), points=0;
            for(int i=0;i<shapes;i++)
            {
                token.ThrowIfCancellationRequested();int count=r.Count(4096,8);points+=count;
                Require(points<=4096,"Sprite physics points exceed bound");Floats(r,count*2);r.Align();
            }
            r.Align();
        }
        else EmptyAlignedArray(r);
        EmptyAlignedArray(r); r.End(); // bones remain unsupported
        if(atlasMode)
        {
            Require(main.Width is >0 and <=512 && main.Height is >0 and <=512 && main.Width==MathF.Truncate(main.Width)&&main.Height==MathF.Truncate(main.Height),"Invalid atlas Sprite logical size");
            token.ThrowIfCancellationRequested();return new(name,texture,rect with { SettingsRaw=settings,HasAtlas=true },key,atlas,main);
        }
        Require(main.Width == rect.Width && main.Height == rect.Height && rect.Width is > 0 and <= 512 && rect.Height is > 0 and <= 512,
            "Sprite logical/render dimensions differ or exceed limit");
        Require(rect.X >= 0 && rect.Y >= 0 && rect.X <= 2048 && rect.Y <= 2048 &&
            new[] { rect.X, rect.Y, rect.Width, rect.Height }.All(v => v == MathF.Truncate(v)), "Invalid sprite crop");
        token.ThrowIfCancellationRequested(); return new(name, texture, rect with { SettingsRaw = settings });
    }
}
