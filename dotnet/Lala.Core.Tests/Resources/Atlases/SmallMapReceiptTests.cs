using System.IO.Compression;
using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;
using Microsoft.Data.Sqlite;
namespace Lala.Core.Tests.Resources;
public sealed class SmallMapReceiptTests:IDisposable
{
    private readonly string dbPath=Path.Combine(Path.GetTempPath(),"lala-smallmap-"+Guid.NewGuid()+".sqlite");
    private SqliteConnection Connection()=>new(new SqliteConnectionStringBuilder{DataSource=dbPath,Pooling=false}.ToString());
    public void Dispose(){File.Delete(dbPath);File.Delete(dbPath+"-journal");}
    private void Execute(string sql)
    {using var c=Connection();c.Open();using var cmd=c.CreateCommand();cmd.CommandText=sql;cmd.ExecuteNonQuery();}
    private static JsonElement Row(int index)
    {using var d=JsonDocument.Parse(typeof(SmallMapReceiptTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.smallmaps.json")!);return d.RootElement.GetProperty("cases")[index].Clone();}
    internal static (YooAssetManifest Manifest,BundleStreamReceipt Receipt,byte[] Bytes,byte[] ManifestBytes) Fixture(int index=0)
    {
        var bytes=Convert.FromBase64String(Row(index).GetProperty("bytes").GetString()!);var j=BundleSourceFixtures.Index("main-valid");
        j["header"]!["package_version"]=EmojiSourcePlan.MainVersion;
        var bundle=j["bundles"]![0]!.DeepClone();bundle["name"]="owned.bundle";bundle["dependency_ids"]=new JsonArray();bundle["file_size"]=(long)bytes.Length;
        bundle["file_hash"]=Convert.ToHexStringLower(MD5.HashData(bytes));bundle["file_crc"]=ManifestIdentity.Crc32LittleEndian(bytes);j["bundles"]=new JsonArray(bundle);
        var asset=j["assets"]![0]!.DeepClone();asset["bundle_id"]=0;asset["path"]=SmallMapSourcePlan.Prefix+"SmallMap2D_10001.png";var assets=new JsonArray();
        for(int n=0;n<Row(index).GetProperty("models").GetInt32();n++){var a=asset.DeepClone();a["path"]=SmallMapSourcePlan.Prefix+"SmallMap2D_"+(10001+n)+".png";assets.Add(a);}j["assets"]=assets;
        var manifestBytes=BundleSourceFixtures.Encode(j);var m=YooAssetManifest.Parse(manifestBytes);return(m,new(new("1.3.23",m,m.Bundles[0]),Convert.ToHexStringLower(SHA256.HashData(bytes))),bytes,manifestBytes);
    }
    private sealed class Cache(byte[] bytes):IBundleSourceCacheReader
    {
        internal int Opens;
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec,CancellationToken token)
        {token.ThrowIfCancellationRequested();Opens++;return ValueTask.FromResult<Stream?>(new MemoryStream(bytes,false));}
    }
    private static string PngPixelHash(byte[] png)
    {
        Assert.Equal(1024,BinaryPrimitives.ReadInt32BigEndian(png.AsSpan(16)));Assert.Equal(1024,BinaryPrimitives.ReadInt32BigEndian(png.AsSpan(20)));
        int size=BinaryPrimitives.ReadInt32BigEndian(png.AsSpan(33));Assert.Equal("IDAT",System.Text.Encoding.ASCII.GetString(png,37,4));
        using var z=new ZLibStream(new MemoryStream(png,41,size),CompressionMode.Decompress);var raw=new byte[1024*4097];z.ReadExactly(raw);Assert.Equal(-1,z.ReadByte());
        var pixels=new byte[1024*4096];for(int y=0;y<1024;y++){Assert.Equal(0,raw[y*4097]);raw.AsSpan(y*4097+1,4096).CopyTo(pixels.AsSpan(y*4096));}return SpritePng.Hash(pixels);
    }
    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public async Task Fixed_receipt_factory_pixels_and_png_match_independent_UnityPy(int index)
    {
        var f=Fixture(index);var cache=new Cache(f.Bytes);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",cache,[f.Receipt]);
        var result=await batch.RebuildAsync(10001);Assert.Equal(3,cache.Opens);Assert.Equal(10001,result.Model);Assert.False(result.HasVerifiedProvenance);
        Assert.Equal(Row(index).GetProperty("pixels").GetString(),result.PixelSha256);Assert.Equal(result.PixelSha256,PngPixelHash(result.CopyPng()));
        Assert.Equal(batch.SourceFingerprint,result.SourceFingerprint);var copy=result.CopyPng();copy[0]^=1;Assert.Equal(result.PngSha256,SpritePng.Hash(result.CopyPng()));
        var again=await batch.RebuildAsync(10001);Assert.Equal(result.PngSha256,again.PngSha256);
    }
    [Theory][InlineData(3)][InlineData(4)]
    public async Task Unreviewed_geometry_or_color_never_produces_png(int index)
    {
        var f=Fixture(index);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",new Cache(f.Bytes),[f.Receipt]);
        var error=await Record.ExceptionAsync(()=>batch.RebuildAsync(10001));Assert.True(error is UnityTextAssetException or SpritePixelException);
    }
    [Fact]
    public async Task Unknown_model_cancel_wrong_receipt_and_changed_source_are_rejected()
    {
        var f=Fixture();var cache=new Cache(f.Bytes);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",cache,[f.Receipt]);
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>batch.RebuildAsync(10002));await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>batch.RebuildAsync(10001,new(true)));Assert.Equal(0,cache.Opens);
        Assert.Throws<UnityTextAssetException>(()=>new SmallMapReceiptBatch(f.Manifest,"1.3.24",cache,[f.Receipt]));
        Assert.Throws<UnityTextAssetException>(()=>new SmallMapReceiptBatch(f.Manifest,"1.3.23",cache,[]));
        f.Bytes[^1]^=1;await Assert.ThrowsAsync<BundleSourceException>(()=>batch.RebuildAsync(10001));
    }
    [Fact]
    public async Task Async_texture_binding_requires_exact_source_owner_and_resource_path()
    {
        var f=Fixture();await using var source=await VerifiedBundleBlockSource.OpenAsync(new Cache(f.Bytes),f.Receipt);var archive=await StreamedUnityArchive.CreateAsync(source);
        var owner=new UnityFileIdentity("owned.bundle","CAB-owned");
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadResourceAsync(owner with{BundleName="other.bundle"},"archive:/CAB-owned/CAB-owned.resS",0,1));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadResourceAsync(owner,"CAB-owned.resS",0,1));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>archive.ReadResourceAsync(owner,"archive:/CAB-owned/CAB-owned.resS",long.MaxValue,1));
        await source.DisposeAsync();await Assert.ThrowsAsync<ObjectDisposedException>(()=>archive.ReadResourceAsync(owner,"archive:/CAB-owned/CAB-owned.resS",0,1));
    }
    [Fact]
    public async Task SQLite_roundtrip_streams_all_models_in_one_phase_and_rebuilds_independently()
    {
        var f=Fixture(5);var cache=new Cache(f.Bytes);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",cache,[f.Receipt]);int checks=0;
        var written=await SmallMapPngStore.WriteAsync(Connection(),batch,()=>checks++);Assert.Equal(3,cache.Opens);
        var read=await SmallMapPngStore.ReadAsync(Connection(),batch,()=>checks++);Assert.Equal(6,cache.Opens);
        Assert.Equal(written,read);Assert.Equal(2,read.Count);Assert.Equal(2,checks);Assert.False(read.HasVerifiedProvenance);
    }
    [Theory][InlineData("png")][InlineData("source")][InlineData("path")][InlineData("pixel")][InlineData("missing")][InlineData("extra")][InlineData("type")][InlineData("oversize")]
    public async Task SQLite_changed_rows_cannot_authorize_pixels(string change)
    {
        var f=Fixture(1);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",new Cache(f.Bytes),[f.Receipt]);
        await SmallMapPngStore.WriteAsync(Connection(),batch,()=>{});
        Execute(change switch
        {
            "png"=>"UPDATE smallmap_frames_v1 SET png=zeroblob(length(png))",
            "source"=>"UPDATE smallmap_frames_v1 SET source='bad'",
            "path"=>"UPDATE smallmap_frames_v1 SET asset='bad'",
            "pixel"=>"UPDATE smallmap_frames_v1 SET pixel_sha='bad'",
            "missing"=>"DELETE FROM smallmap_frames_v1",
            "extra"=>"INSERT INTO smallmap_frames_v1 SELECT model+1,source,asset,pixel_sha,png_sha,png FROM smallmap_frames_v1",
            "type"=>"UPDATE smallmap_frames_v1 SET png='text'",
            _=>"UPDATE smallmap_frames_v1 SET png=zeroblob(4194305)"
        });
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>SmallMapPngStore.ReadAsync(Connection(),batch,()=>{}));
    }
    [Theory][InlineData(false)][InlineData(true)]
    public async Task SQLite_failed_final_revalidation_rolls_back_prior_batch(bool cancel)
    {
        var f=Fixture(1);await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",new Cache(f.Bytes),[f.Receipt]);
        var old=await SmallMapPngStore.WriteAsync(Connection(),batch,()=>{});using var stop=new CancellationTokenSource();
        var error=await Record.ExceptionAsync(()=>SmallMapPngStore.WriteAsync(Connection(),batch,()=>{if(cancel)stop.Cancel();else throw new InvalidDataException("owned revoke");},stop.Token));
        Assert.NotNull(error);Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted,error.Data[ResourceInventoryDatabase.OutcomeKey]);Assert.Equal(true,error.Data[ResourceInventoryDatabase.RollbackKey]);
        Assert.Equal(old,await SmallMapPngStore.ReadAsync(Connection(),batch,()=>{}));
    }
    [Fact]
    public async Task Publication_copies_verified_pixels_and_rejects_revocation_before_or_during_copy()
    {
        var f=Fixture();await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",new Cache(f.Bytes),[f.Receipt]);
        await SmallMapPngStore.WriteAsync(Connection(),batch,()=>{});
        var snapshot=await SmallMapPngStore.ReadForPublicationAsync(Connection(),batch,()=>{});
        bool current=true;var request=new SmallMapRenderRequest(snapshot,10001,()=>current);
        Assert.True(request.TryReadPng(out var first));Assert.Equal(request.PngSha256,SpritePng.Hash(first!));
        first![0]^=1;Execute("UPDATE smallmap_frames_v1 SET png=zeroblob(length(png))");
        Assert.True(request.TryReadPng(out var second));Assert.Equal(request.PngSha256,SpritePng.Hash(second!));
        current=false;Assert.False(request.TryReadPng(out var revoked));Assert.Null(revoked);
        int checks=0;var racing=new SmallMapRenderRequest(snapshot,10001,()=>++checks==1);
        Assert.False(racing.TryReadPng(out var late));Assert.Null(late);
    }
    [Fact]
    public async Task Final_revalidation_failure_never_returns_publication_snapshot()
    {
        var f=Fixture();await using var batch=new SmallMapReceiptBatch(f.Manifest,"1.3.23",new Cache(f.Bytes),[f.Receipt]);
        await SmallMapPngStore.WriteAsync(Connection(),batch,()=>{});
        await Assert.ThrowsAsync<InvalidOperationException>(()=>SmallMapPngStore.ReadForPublicationAsync(Connection(),batch,()=>throw new InvalidOperationException("revoked")));
    }

}
