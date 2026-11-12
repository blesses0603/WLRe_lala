using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using AssetsTools.NET.Extra;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class UnitySpriteExtractorTests
{
    private const string Path = "Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png";
    private static byte[] File(string name)
    {
        using var s = typeof(UnitySpriteExtractorTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.SerializedFixtures." + name)!;
        using var m = new MemoryStream(); s.CopyTo(m); return m.ToArray();
    }
    private static SpritePixelCandidate Extract(byte[] raw, string path = Path) => UnitySpriteExtractor.Extract(path, "owned-version", [UnityFixtures.Source(UnityFixtures.Wrap(raw))]);
    [Fact]
    public void Real_writer_bundle_extracts_exact_same_file_pair_and_independent_pixels()
    {
        using var evidence = JsonDocument.Parse(File("evidence.json"));
        foreach (string name in new[] { "owned.assets", "owned.bundle" })
            Assert.Equal(evidence.RootElement.GetProperty("files").GetProperty(name).GetString(), Convert.ToHexStringLower(SHA256.HashData(File(name))));
        var candidate = UnitySpriteExtractor.Extract(Path, "owned-version", [UnityFixtures.Source(File("owned.bundle"))]);
        Assert.Equal(evidence.RootElement.GetProperty("pixels_hex").GetString(), Convert.ToHexStringLower(candidate.CopyPixels()));
        Assert.Equal(evidence.RootElement.GetProperty("pixel_sha256").GetString(), candidate.PixelSha256);
        Assert.Equal(2, candidate.Context.SpritePathId); Assert.Equal(3, candidate.Context.TexturePathId);
        Assert.False(candidate.HasVerifiedProvenance);
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(Path, [UnityFixtures.Source(File("owned.bundle"))]));
    }
    [Fact]
    public void AssetsTools_independently_reads_fixture_classes_fields_and_pointers()
    {
        var manager = new AssetsManager(); using var s = new MemoryStream(File("owned.assets"), false);
        try
        {
            var file = manager.LoadAssetsFile(s, "owned", false);
            var sprite = manager.GetBaseField(file, file.file.Metadata.AssetInfos.Single(o => o.TypeId == 213));
            var texture = manager.GetBaseField(file, file.file.Metadata.AssetInfos.Single(o => o.TypeId == 28));
            Assert.Equal(3L, sprite["m_RD"]["texture"]["m_PathID"].AsLong);
            Assert.Equal(0, sprite["m_RD"]["texture"]["m_FileID"].AsInt);
            Assert.Equal(1f, sprite["m_RD"]["textureRect"]["x"].AsFloat);
            Assert.Equal(4, texture["m_Width"].AsInt); Assert.Equal(3, texture["m_Height"].AsInt);
            Assert.Equal(4, texture["m_TextureFormat"].AsInt);
            Assert.Equal(48, texture["image data"].Value.AsByteArray.Length);
        }
        finally { manager.UnloadAll(); }
    }
    [Theory]
    [InlineData("texture-width")][InlineData("texture-complete")][InlineData("texture-format")][InlineData("texture-mips")]
    [InlineData("sprite-external")][InlineData("sprite-missing")][InlineData("sprite-wrong-class")][InlineData("sprite-name")]
    [InlineData("pair-duplicate")][InlineData("pair-external")][InlineData("pair-missing")][InlineData("tree-name")]
    public void Malformed_or_unreviewed_structure_is_rejected(string mutation)
    {
        byte[] raw = File("owned.assets");
        using var offsets = JsonDocument.Parse(File("layout.json"));
        int Offset() => offsets.RootElement.GetProperty(mutation).GetInt32();
        void Write(int at, int value) => BinaryPrimitives.WriteInt32LittleEndian(raw.AsSpan(at), value);
        // Locations are recorded by the independent UnityPy writer.
        switch (mutation)
        {
            case "texture-width": Write(Offset(), int.MaxValue); break;
            case "texture-complete": Write(Offset(), 47); break;
            case "texture-format": Write(Offset(), 10); break;
            case "texture-mips": Write(Offset(), 2); break;
            case "sprite-external": Write(Offset(), 1); break;
            case "sprite-missing": Write(Offset(), 999); break;
            case "sprite-wrong-class": Write(Offset(), 1); break;
            case "sprite-name": raw[Offset()] = (byte)'x'; break;
            case "pair-duplicate": Write(Offset(), 2); break;
            case "pair-external": Write(Offset(), 1); break;
            case "pair-missing": Write(Offset(), 999); break;
            case "tree-name":
                var needle = System.Text.Encoding.UTF8.GetBytes("m_ForcedFallbackFormat\0");
                int at = raw.AsSpan().IndexOf(needle); Assert.True(at > 0); raw[at] = (byte)'X'; break;
        }
        Assert.Throws<UnityTextAssetException>(() => Extract(raw));
    }
    [Fact]
    public void Pair_order_is_irrelevant_but_pairing_across_files_is_forbidden()
    {
        Assert.Equal(Extract(File("owned.assets")).CopyPixels(), Extract(File("reversed.assets")).CopyPixels());
        var sprite = UnityFixtures.Source(UnityFixtures.Wrap(File("sprite-only.assets")), "sprite.bundle");
        var texture = UnityFixtures.Source(UnityFixtures.Wrap(File("texture-only.assets")), "texture.bundle");
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path, "owned", [sprite]));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path, "owned", [texture]));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path, "owned", [sprite, texture]));
    }
    [Fact]
    public void Source_checksums_and_full_input_identity_remain_required()
    {
        byte[] bytes = File("owned.bundle"); var source = UnityFixtures.Source(bytes);
        bytes[^1] ^= 1;
        Assert.Throws<BundleSourceException>(() => VerifiedBundleSource.Verify(source.Spec, bytes, BundleAcquisition.Cache));
        var a = UnitySpriteExtractor.Extract(Path, "version-a", [source]);
        var b = UnitySpriteExtractor.Extract(Path, "version-b", [source]);
        var renamed = UnitySpriteExtractor.Extract(Path, "version-a", [UnityFixtures.Source(File("owned.bundle"), "renamed.bundle")]);
        Assert.Equal(a.PixelSha256, b.PixelSha256); Assert.Equal(a.PixelSha256, renamed.PixelSha256);
        var cache = new SpritePixelCache(a);
        Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(b));
        Assert.Throws<SpritePixelException>(() => cache.ReadComparedTo(renamed));
    }
    [Fact]
    public void Truncated_serialized_files_never_yield_a_candidate()
    {
        byte[] raw = File("owned.assets");
        foreach (int length in new[] { 0, 1, 47, 48, raw.Length / 2, raw.Length - 1 })
            Assert.Throws<UnityTextAssetException>(() => Extract(raw[..length]));
    }
    [Fact]
    public void Exact_path_bundle_ambiguity_and_cancellation_are_rejected()
    {
        var source = UnityFixtures.Source(File("owned.bundle"));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path.ToLowerInvariant(), "owned", [source]));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path, "owned", [source, source]));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.Extract(Path, "owned", [source, UnityFixtures.Source(File("owned.bundle"), "other.bundle")]));
        Assert.Throws<OperationCanceledException>(() => UnitySpriteExtractor.Extract(Path, "owned", [source], new(true)));
    }
}
