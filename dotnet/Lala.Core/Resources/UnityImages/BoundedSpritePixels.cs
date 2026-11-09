using System.Security.Cryptography;

namespace Lala.Core.Resources;

internal sealed class SpritePixelException(string message) : Exception(message);

// Parsed-field observations only. NOT proof that a serialized object belongs to a bundle.
// The production SerializedFile walker does not yet accept image classes.
internal sealed record SpritePixelContext(string VersionIdentity, string BundleSha256, string SerializedFile,
    string AssetPath, long SpritePathId, long TexturePathId);
internal sealed record TexturePixelLayout(int Width, int Height, int Format, int MipCount = 1,
    int ImageCount = 1, int Dimension = 2, int Platform = 19, bool Streamed = false, bool HasPlatformBlob = false);
internal sealed record SpritePixelRect(float X, float Y, float Width, float Height, uint SettingsRaw = 2,
    bool HasAtlas = false, bool HasAlphaTexture = false);

/// <summary>Owned top-down RGBA candidate. No provenance, currentness, catalog or send authority.</summary>
internal sealed class SpritePixelCandidate
{
    private readonly byte[] pixels;
    internal SpritePixelContext Context { get; }
    internal TexturePixelLayout TextureLayout { get; }
    internal SpritePixelRect Rectangle { get; }
    internal int Width { get; }
    internal int Height { get; }
    internal string TexturePayloadSha256 { get; }
    internal string PixelSha256 { get; }
    internal bool HasVerifiedProvenance => false;
    internal byte[] CopyPixels() => pixels.ToArray();
    internal SpritePixelCandidate(SpritePixelContext context, TexturePixelLayout texture, SpritePixelRect rect, int width, int height, byte[] ownedPixels, string sourceHash)
    {
        Context = context; TextureLayout = texture; Rectangle = rect; Width = width; Height = height; pixels = ownedPixels;
        TexturePayloadSha256 = sourceHash; PixelSha256 = Convert.ToHexStringLower(SHA256.HashData(pixels));
    }
}

/// <summary>Reviewed uncompressed base-level Texture2D bytes and unpacked full-rect Sprite subset.
/// Does not parse SerializedFile, resolve PPtrs, download sources or activate images.</summary>
internal static class BoundedSpritePixels
{
    internal const int MaximumTextureSide = 2048, MaximumSpriteSide = 512;
    internal static SpritePixelCandidate Decode(SpritePixelContext context, TexturePixelLayout texture,
        SpritePixelRect rect, ReadOnlySpan<byte> payload, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); ValidateContext(context);
        Check(texture.Width is > 0 and <= MaximumTextureSide && texture.Height is > 0 and <= MaximumTextureSide,
            "Texture dimensions outside reviewed limit");
        Check(texture.MipCount == 1 && texture.ImageCount == 1 && texture.Dimension == 2 && texture.Platform == 19 &&
            !texture.Streamed && !texture.HasPlatformBlob, "Unreviewed mip, array, platform or streamed texture");
        int stride = texture.Format switch { 3 => 3, 4 or 5 or 14 => 4, _ => throw new SpritePixelException("Unreviewed TextureFormat") };
        Check(payload.Length == texture.Width * texture.Height * stride, "Texture byte length differs from exact base level");
        // UnityPy1.25.4: rectangle packingMode=1, unpacked, no rotation, full-rect mesh, reserved bits zero.
        Check(rect.SettingsRaw == 2 && !rect.HasAtlas && !rect.HasAlphaTexture, "Unreviewed packed, tight, atlas or alpha sprite");
        int x = Integral(rect.X), y = Integral(rect.Y), width = Integral(rect.Width), height = Integral(rect.Height);
        Check(width is > 0 and <= MaximumSpriteSide && height is > 0 and <= MaximumSpriteSide &&
            x <= texture.Width && width <= texture.Width - x && y <= texture.Height && height <= texture.Height - y,
            "Sprite rectangle outside texture or limit");
        // Own the source before hashing and reading. Caller memory cannot mutate the retained result.
        byte[] source = payload.ToArray();
        string sourceHash = Convert.ToHexStringLower(SHA256.HashData(source));
        byte[] output = new byte[width * height * 4];
        for (int row = 0; row < height; row++)
        {
            token.ThrowIfCancellationRequested();
            // UnityPy crops the unflipped texture, then vertically flips the cropped Sprite.
            int input = ((y + height - 1 - row) * texture.Width + x) * stride;
            for (int col = 0; col < width; col++, input += stride)
            {
                int target = (row * width + col) * 4;
                output[target] = source[input + (texture.Format == 5 ? 1 : texture.Format == 14 ? 2 : 0)];
                output[target + 1] = source[input + (texture.Format == 5 ? 2 : 1)];
                output[target + 2] = source[input + (texture.Format == 5 ? 3 : texture.Format == 14 ? 0 : 2)];
                output[target + 3] = texture.Format == 3 ? (byte)255 : source[input + (texture.Format == 5 ? 0 : 3)];
            }
        }
        token.ThrowIfCancellationRequested(); return new(context, texture, rect, width, height, output, sourceHash);
    }
    private static int Integral(float value)
    {
        Check(float.IsFinite(value) && value >= 0 && value <= MaximumTextureSide && value == MathF.Truncate(value), "Nonintegral or invalid Sprite rectangle");
        return (int)value;
    }
    internal static void ValidateContext(SpritePixelContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        Check(Valid(context.VersionIdentity, 4096) && Valid(context.SerializedFile, 1024) && Valid(context.AssetPath, 1024) &&
            context.AssetPath.Split('/').All(p => p.Length > 0 && p is not "." and not "..") && !context.AssetPath.Contains('\\') &&
            context.SpritePathId != 0 && context.TexturePathId != 0 && context.SpritePathId != context.TexturePathId &&
            context.BundleSha256 is { Length: 64 } && context.BundleSha256.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f'), "Invalid image source context");
    }
    private static bool Valid(string value, int max) => !string.IsNullOrEmpty(value) && value.Length <= max && !value.Contains('\0');
    internal static void Check(bool condition, string message) { if (!condition) throw new SpritePixelException(message); }
}
