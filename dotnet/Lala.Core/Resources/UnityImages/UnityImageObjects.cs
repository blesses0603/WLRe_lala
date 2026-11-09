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
            48 => (2304, "f3ed8d034e403d3917510a21390e073793d851a96523aa8fd51e756b9888b6fb"),
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
internal sealed record UnityTexturePixels(string Name, TexturePixelLayout Layout, ReadOnlyMemory<byte> Payload);
internal sealed record UnitySpritePixels(string Name, UnityContainerPointer Texture, SpritePixelRect Rect);

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
    internal static UnityTexturePixels Texture(ReadOnlyMemory<byte> bytes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); var r = new UnityReadCursor(bytes); string name = r.String(1024, false);
        r.I32(); Require(!Bool(r), "Downscaled fallback unsupported"); Bool(r); r.Align();
        int width = r.I32(), height = r.I32(); uint complete = r.U32();
        Require(r.I32() == 0, "Stripped mips unsupported"); int format = r.I32(), mips = r.I32();
        Bool(r); Require(!Bool(r), "Preprocessed texture unsupported"); Bool(r);
        Require(!Bool(r), "Streaming mipmaps unsupported"); r.Align(); r.I32(); r.Align();
        int images = r.I32(), dimension = r.I32();
        r.I32(); r.I32(); Float(r); r.I32(); r.I32(); r.I32(); // GLTextureSettings
        r.I32(); Require(r.I32() is 0 or 1, "Unreviewed texture color space");
        EmptyAlignedArray(r); // platform blob
        int length = r.Count(16 * 1024 * 1024, 1); var payload = r.Take(length); r.Align();
        Require(r.I64() == 0 && r.U32() == 0 && r.String(1024) == "", "Streamed image resource unsupported"); r.End();
        Require(width is > 0 and <= 2048 && height is > 0 and <= 2048 && mips == 1 && images == 1 && dimension == 2,
            "Unsupported image dimensions/mips/array");
        int expected;
        try { expected = BlockTexturePixels.PayloadLength(width, height, format); }
        catch (SpritePixelException) { throw new UnityTextAssetException("Unreviewed texture compression/format"); }
        Require(length == expected && complete == length, "Texture image size mismatch");
        token.ThrowIfCancellationRequested(); return new(name, new(width, height, format), payload);
    }
    internal static UnitySpritePixels Sprite(ReadOnlyMemory<byte> bytes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested(); var r = new UnityReadCursor(bytes); string name = r.String(1024, false);
        var main = Rect(r); Floats(r, 2); Floats(r, 4);
        Require(Float(r) > 0, "Invalid sprite pixels-to-units"); Floats(r, 2); r.U32();
        Require(!Bool(r), "Polygon sprite unsupported"); r.Align();
        r.Take(24); // renderDataKey (never used for atlas fallback)
        EmptyAlignedArray(r); ZeroPointer(r); r.Align(); // tags / atlas
        var texture = Pointer(r); Require(texture.FileId == 0 && texture.PathId != 0, "Sprite texture must be same-file non-null PPtr");
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
        Require(Float(r) == 1 && settings == 2, "Unreviewed downscale/packing/tight mesh"); r.Align();
        EmptyAlignedArray(r); EmptyAlignedArray(r); r.End(); // physics shapes / bones
        Require(main.Width == rect.Width && main.Height == rect.Height && rect.Width is > 0 and <= 512 && rect.Height is > 0 and <= 512,
            "Sprite logical/render dimensions differ or exceed limit");
        Require(rect.X >= 0 && rect.Y >= 0 && rect.X <= 2048 && rect.Y <= 2048 &&
            new[] { rect.X, rect.Y, rect.Width, rect.Height }.All(v => v == MathF.Truncate(v)), "Invalid sprite crop");
        token.ThrowIfCancellationRequested(); return new(name, texture, rect with { SettingsRaw = settings });
    }
}
