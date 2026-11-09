using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class SpritePixelTests
{
    private static SpritePixelContext Context => new("owned-exe/data/package/manifest", new string('a', 64), "CAB-owned", "Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png", 1, 2);
    private static readonly TexturePixelLayout Texture = new(4, 3, 4);
    private static readonly SpritePixelRect Rect = new(1, 0, 2, 3);
    private static byte[] Payload => Enumerable.Range(0, 48).Select(i => (byte)(i * 37 + 11)).ToArray();
    public static IEnumerable<object[]> Vectors()
    {
        using var stream = typeof(SpritePixelTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.vectors.json")!;
        using var json = JsonDocument.Parse(stream);
        foreach (var row in json.RootElement.GetProperty("vectors").EnumerateArray()) yield return new object[] { row.Clone() };
    }
    [Theory, MemberData(nameof(Vectors))]
    public void Pixel_crop_orientation_and_channels_match_pinned_UnityPy(JsonElement v)
    {
        int N(string key) => v.GetProperty(key).GetInt32();
        var candidate = BoundedSpritePixels.Decode(Context, new(N("width"), N("height"), N("format")),
            new(N("x"), N("y"), N("w"), N("h")), Convert.FromBase64String(v.GetProperty("payload").GetString()!));
        Assert.Equal(Convert.FromBase64String(v.GetProperty("pixels").GetString()!), candidate.CopyPixels());
        Assert.Equal(v.GetProperty("pixel_sha256").GetString(), candidate.PixelSha256);
        Assert.Equal(v.GetProperty("source_sha256").GetString(), candidate.TexturePayloadSha256);
        Assert.Equal(N("w"), candidate.Width); Assert.Equal(N("h"), candidate.Height);
        Assert.False(candidate.HasVerifiedProvenance);
    }
    public static IEnumerable<object[]> UnsupportedTextures()
    {
        foreach (var value in new[] { Texture with { Width = 0 }, Texture with { Height = -1 }, Texture with { Width = 2049 },
            Texture with { Height = int.MaxValue }, Texture with { Format = 10 }, Texture with { Format = 999 },
            Texture with { MipCount = 2 }, Texture with { ImageCount = 2 }, Texture with { Dimension = 3 },
            Texture with { Platform = 11 }, Texture with { Streamed = true }, Texture with { HasPlatformBlob = true } }) yield return new object[] { value };
    }
    [Theory, MemberData(nameof(UnsupportedTextures))]
    public void Unreviewed_texture_layout_is_rejected(object value) => Assert.Throws<SpritePixelException>(() => BoundedSpritePixels.Decode(Context, (TexturePixelLayout)value, Rect, Payload));
    public static IEnumerable<object[]> UnsupportedSprites()
    {
        foreach (var value in new[] { Rect with { X = -1 }, Rect with { Y = float.NaN }, Rect with { Width = float.PositiveInfinity },
            Rect with { X = .5f }, Rect with { Width = 0 }, Rect with { Width = 513 }, Rect with { X = 3 }, Rect with { Y = 1 },
            Rect with { SettingsRaw = 0 }, Rect with { SettingsRaw = 3 }, Rect with { SettingsRaw = 6 }, Rect with { SettingsRaw = 66 },
            Rect with { SettingsRaw = 130 }, Rect with { HasAtlas = true }, Rect with { HasAlphaTexture = true } }) yield return new object[] { value };
    }
    [Theory, MemberData(nameof(UnsupportedSprites))]
    public void Unreviewed_sprite_layout_is_rejected(object value) => Assert.Throws<SpritePixelException>(() => BoundedSpritePixels.Decode(Context, Texture, (SpritePixelRect)value, Payload));
    [Theory, InlineData(0), InlineData(47), InlineData(49), InlineData(192)]
    public void Exact_base_level_length_required(int size) => Assert.Throws<SpritePixelException>(() => BoundedSpritePixels.Decode(Context, Texture, Rect, new byte[size]));
    [Fact]
    public void Candidate_and_cache_own_pixels_and_reject_corrupt_cache()
    {
        var source = Payload;
        var candidate = BoundedSpritePixels.Decode(Context, Texture, Rect, source);
        var cache = new SpritePixelCache(candidate); var expected = candidate.CopyPixels();
        Array.Fill(source, (byte)0); Array.Fill(candidate.CopyPixels(), (byte)0); Array.Fill(cache.ReadComparedTo(candidate), (byte)0);
        Assert.Equal(expected, candidate.CopyPixels()); Assert.Equal(expected, cache.ReadComparedTo(candidate));
        // Deliberate cache corruption, not a production input or provenance bypass.
        ((byte[])typeof(SpritePixelCache).GetField("pixels", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.GetValue(cache)!)[0] ^= 1;
        Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(candidate));
    }
    [Fact]
    public void Cache_compares_every_source_identity_field_and_payload_not_only_selected_pixels()
    {
        var candidate = BoundedSpritePixels.Decode(Context, Texture, Rect, Payload); var cache = new SpritePixelCache(candidate);
        foreach (var changed in new[] { Context with { VersionIdentity = "other" }, Context with { BundleSha256 = new string('b',64) },
            Context with { SerializedFile = "CAB-other" }, Context with { AssetPath = "Assets/other.png" },
            Context with { SpritePathId = 3 }, Context with { TexturePathId = 4 } })
            Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(BoundedSpritePixels.Decode(changed, Texture, Rect, Payload)));
        var outsideCrop = Payload; outsideCrop[0] ^= 1;
        var next = BoundedSpritePixels.Decode(Context, Texture, Rect, outsideCrop);
        Assert.Equal(candidate.PixelSha256, next.PixelSha256);
        Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(next));
        Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(BoundedSpritePixels.Decode(Context, Texture, Rect with { Width = 1 }, Payload)));
    }
    [Fact]
    public void Same_pixels_do_not_hide_changed_decode_inputs()
    {
        var source = new byte[48];
        var candidate = BoundedSpritePixels.Decode(Context, Texture, Rect, source); var cache = new SpritePixelCache(candidate);
        foreach (var next in new[] {
            BoundedSpritePixels.Decode(Context, Texture with { Format = 14 }, Rect, source),
            BoundedSpritePixels.Decode(Context, Texture, Rect with { X = 0 }, source) })
        {
            Assert.Equal(candidate.PixelSha256, next.PixelSha256);
            Assert.Equal(candidate.TexturePayloadSha256, next.TexturePayloadSha256);
            Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(next));
        }
    }
    [Fact]
    public void Invalid_context_and_cancellation_cannot_yield_pixels()
    {
        foreach (var context in new[] { Context with { VersionIdentity = "" }, Context with { BundleSha256 = "bad" },
            Context with { SerializedFile = "\0" }, Context with { AssetPath = "Assets/../other" }, Context with { SpritePathId = 0 },
            Context with { TexturePathId = 1 } }) Assert.Throws<SpritePixelException>(() => BoundedSpritePixels.Decode(context, Texture, Rect, Payload));
        var token = new CancellationToken(true);
        Assert.Throws<OperationCanceledException>(() => BoundedSpritePixels.Decode(Context, Texture, Rect, Payload, token));
        var candidate = BoundedSpritePixels.Decode(Context, Texture, Rect, Payload);
        Assert.Throws<OperationCanceledException>(() => new SpritePixelCache(candidate).ReadComparedTo(candidate, token));
    }
    [Fact]
    public void Reviewed_maximum_dimensions_are_bounded()
    {
        var candidate = BoundedSpritePixels.Decode(Context, new(2048,2048,4), new(1536,1536,512,512), new byte[2048*2048*4]);
        Assert.Equal(512*512*4, candidate.CopyPixels().Length);
    }
}
