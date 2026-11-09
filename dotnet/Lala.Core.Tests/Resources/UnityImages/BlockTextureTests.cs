using System.Text.Json;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;
namespace Lala.Core.Tests.Resources;

public sealed class BlockTextureTests
{
    [Theory, InlineData(10), InlineData(12)]
    public async Task Compressed_bundle_flows_through_extraction_png_and_independent_sqlite_readback(int format)
    {
        using var stream = typeof(BlockTextureTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.block_serialized.json")!;
        using var document = JsonDocument.Parse(stream);
        var row = document.RootElement.EnumerateArray().Single(r => r.GetProperty("format").GetInt32() == format);
        byte[] raw = Convert.FromBase64String(row.GetProperty("bundle").GetString()!);
        Assert.Equal(row.GetProperty("sha256").GetString(), SpritePng.Hash(raw));
        SpritePixelCandidate Rebuild() => UnitySpriteExtractor.Extract("Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png", "owned", [UnityFixtures.Source(raw)]);
        Assert.Equal(Convert.FromBase64String(row.GetProperty("pixels").GetString()!), Rebuild().CopyPixels());
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract("Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png", [UnityFixtures.Source(raw)]));
        string path = Path.Combine(Path.GetTempPath(), "lala-block-" + Guid.NewGuid() + ".sqlite");
        SqliteConnection Connection() => new(new SqliteConnectionStringBuilder { DataSource = path, Pooling = false }.ToString());
        try
        {
            int rechecks = 0;
            await SpritePngStore.WriteAsync(Connection(), [Rebuild()], () => rechecks++);
            var pngs = await SpritePngStore.ReadAsync(Connection(), [Rebuild()], () => rechecks++);
            Assert.Equal(2, rechecks); Assert.Equal(SpritePng.Encode(Rebuild()), pngs.Single().Value);
        }
        finally { File.Delete(path); File.Delete(path + "-journal"); }
    }
    [Theory, InlineData(10), InlineData(12)]
    public void Bounds_exact_payload_and_cancellation_remain_enforced(int format)
    {
        int size = BlockTexturePixels.PayloadLength(5, 7, format);
        foreach (int invalid in new[] { 0, size - 1, size + 1 })
            Assert.Throws<SpritePixelException>(() => BlockTexturePixels.Decode(new byte[invalid], 5, 7, format, default));
        Assert.Throws<OperationCanceledException>(() => BlockTexturePixels.Decode(new byte[size], 5, 7, format, new(true)));
        Assert.Throws<SpritePixelException>(() => BlockTexturePixels.PayloadLength(int.MaxValue, 1, format));
        Assert.Equal(2048 * 2048 * 4, BlockTexturePixels.Decode(new byte[BlockTexturePixels.PayloadLength(2048,2048,format)], 2048,2048,format,default).Length);
    }
}
