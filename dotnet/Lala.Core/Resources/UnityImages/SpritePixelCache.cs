using System.Security.Cryptography;

namespace Lala.Core.Resources;

// In-memory decoded-pixel cache record, not Python PNG/SQLite compatibility or source authority.
// Every read requires an independently rebuilt current candidate. Never trust cache hashes alone.
internal sealed class SpritePixelCache
{
    private readonly SpritePixelContext context;
    private readonly TexturePixelLayout layout;
    private readonly SpritePixelRect rectangle;
    private readonly int width, height;
    private readonly string sourceHash, pixelHash;
    private readonly byte[] pixels;
    internal SpritePixelCache(SpritePixelCandidate candidate)
    {
        context = candidate.Context; layout = candidate.TextureLayout; rectangle = candidate.Rectangle; width = candidate.Width; height = candidate.Height;
        sourceHash = candidate.TexturePayloadSha256; pixelHash = candidate.PixelSha256; pixels = candidate.CopyPixels();
    }
    internal byte[] ReadComparedTo(SpritePixelCandidate current, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        BoundedSpritePixels.Check(context == current.Context && layout == current.TextureLayout && rectangle == current.Rectangle && width == current.Width && height == current.Height &&
            sourceHash == current.TexturePayloadSha256 && pixelHash == current.PixelSha256,
            "Image cache source, version, dimensions or pixels changed");
        byte[] copy = pixels.ToArray();
        BoundedSpritePixels.Check(copy.Length == width * height * 4 && Convert.ToHexStringLower(SHA256.HashData(copy)) == current.PixelSha256,
            "Image cache pixel integrity mismatch");
        token.ThrowIfCancellationRequested(); return copy;
    }
}
