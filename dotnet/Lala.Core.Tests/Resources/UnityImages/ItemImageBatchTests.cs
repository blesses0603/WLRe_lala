using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

internal static class ImageBatchFixtures
{
    internal static (YooAssetManifest Manifest, Dictionary<string, IReadOnlyList<VerifiedBundleSource>> Sources) Inputs()
    {
        using var s = typeof(ImageBatchFixtures).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.SerializedFixtures.owned.assets")!;
        using var m = new MemoryStream(); s.CopyTo(m); byte[] original = m.ToArray();
        var index = BundleSourceFixtures.Index("main-valid"); var assets = new JsonArray(); var bundles = new JsonArray();
        var bytes = new List<byte[]>();
        for (int i = 0; i < 2; i++)
        {
            byte[] raw = original.ToArray();
            if (i == 1) for (int p = 0; p <= raw.Length - 5; p++)
                if (raw.AsSpan(p, 5).SequenceEqual("s1000"u8)) raw[p + 4] = (byte)'1';
            byte[] bundle = UnityFixtures.Wrap(raw); bytes.Add(bundle);
            var a = index["assets"]![0]!.DeepClone(); a["path"] = ItemImageMapping.Prefix + $"s{1000+i}.png"; a["bundle_id"] = i; assets.Add(a);
            var b = index["bundles"]![0]!.DeepClone(); b["name"] = $"image{i}.bundle"; b["dependency_ids"] = new JsonArray();
            b["file_size"] = (long)bundle.Length; b["file_hash"] = Convert.ToHexStringLower(MD5.HashData(bundle));
            b["file_crc"] = ManifestIdentity.Crc32LittleEndian(bundle); bundles.Add(b);
        }
        index["assets"] = assets; index["bundles"] = bundles;
        var manifest = YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));
        var sources = new Dictionary<string, IReadOnlyList<VerifiedBundleSource>>(StringComparer.Ordinal);
        for (int i = 0; i < 2; i++) sources.Add(ItemImageMapping.Prefix + $"s{1000+i}.png",
            new[] { VerifiedBundleSource.Verify(new("1.3.21", manifest, manifest.Bundles[i]), bytes[i], BundleAcquisition.Cache) });
        return (manifest, sources);
    }
    internal static Dictionary<ushort, ItemDataRow> Items(ushort icon = 1001) => new()
    { [1] = new(1, "owned", 0, 0, 0, 1, 0, new ReviewedItemDetails { IconId = icon, ItemW = 1, ItemH = 1 }) };
    internal static ItemImageBatch Batch(string identity = "owned")
    { var (manifest, sources) = Inputs(); return ItemImageBatch.Create(manifest, "1.3.21", identity, Items(), sources); }
}

public sealed class ItemImageBatchTests
{
    [Fact]
    public async Task Different_exact_closures_share_complete_fingerprint_and_roundtrip_cache()
    {
        var batch = ImageBatchFixtures.Batch(); Assert.Equal(2, batch.Pixels.Length);
        Assert.All(batch.Pixels, p => Assert.Equal(batch.Fingerprint, p.Context.VersionIdentity));
        Assert.Equal(2, batch.Pixels.Select(p => p.Context.BundleSha256).Distinct().Count());
        string path = Path.Combine(Path.GetTempPath(), "lala-batch-" + Guid.NewGuid() + ".sqlite");
        SqliteConnection Connection() => new(new SqliteConnectionStringBuilder { DataSource = path, Pooling = false }.ToString());
        try
        {
            await SpritePngStore.WriteAsync(Connection(), batch.Pixels, () => { });
            var again = ImageBatchFixtures.Batch(); var rows = await SpritePngStore.ReadAsync(Connection(), again.Pixels, () => { });
            var readback = new ItemImageReadback(again, rows);
            Assert.Equal(SpritePng.Encode(batch.Pixels[1]), readback.CopyPng(1));
            Assert.Equal(SpritePng.Encode(batch.Pixels[0]), readback.CopyPng(65535));
            Array.Fill(readback.CopyPng(1), (byte)0); Assert.Equal(SpritePng.Encode(batch.Pixels[1]), readback.CopyPng(1));
        }
        finally { File.Delete(path); }
    }
    [Fact]
    public void Wrong_closure_cannot_resolve_from_another_images_selected_bundle()
    {
        var (manifest, sources) = ImageBatchFixtures.Inputs(); var paths = sources.Keys.ToArray();
        sources[paths[0]] = sources[paths[1]];
        Assert.Throws<SpritePixelException>(() => ItemImageBatch.Create(manifest, "1.3.21", "owned", ImageBatchFixtures.Items(), sources));
        Assert.Throws<UnityTextAssetException>(() => UnitySpriteExtractor.ExtractMany(sources, "owned"));
    }
    [Fact]
    public void Mapping_metadata_and_version_changes_change_every_images_fingerprint()
    {
        var (manifest, sources) = ImageBatchFixtures.Inputs();
        var original = ItemImageBatch.Create(manifest, "1.3.21", "owned", ImageBatchFixtures.Items(), sources);
        var mapping = ItemImageBatch.Create(manifest, "1.3.21", "owned", ImageBatchFixtures.Items(1000), sources);
        var version = ItemImageBatch.Create(manifest, "1.3.21", "new", ImageBatchFixtures.Items(), sources);
        Assert.NotEqual(original.Fingerprint, mapping.Fingerprint); Assert.NotEqual(original.Fingerprint, version.Fingerprint);
        Assert.Equal(original.Pixels[0].PixelSha256, mapping.Pixels[0].PixelSha256);
        var items = ImageBatchFixtures.Items(); items[1] = items[1] with { OpenUsed = 2 };
        Assert.NotEqual(original.Fingerprint, ItemImageBatch.Create(manifest, "1.3.21", "owned", items, sources).Fingerprint);
    }
    [Fact]
    public void Incomplete_duplicate_and_cancelled_batches_reject()
    {
        var (manifest, sources) = ImageBatchFixtures.Inputs(); var path = sources.Keys.First();
        sources[path] = new[] { sources[path][0], sources[path][0] };
        Assert.Throws<SpritePixelException>(() => ItemImageBatch.Create(manifest, "1.3.21", "owned", ImageBatchFixtures.Items(), sources));
        sources.Remove(path);
        Assert.Throws<SpritePixelException>(() => ItemImageBatch.Create(manifest, "1.3.21", "owned", ImageBatchFixtures.Items(), sources));
        using var cts = new CancellationTokenSource(); cts.Cancel();
        Assert.ThrowsAny<OperationCanceledException>(() => UnitySpriteExtractor.ExtractMany(sources, "owned", cts.Token));
    }
}
