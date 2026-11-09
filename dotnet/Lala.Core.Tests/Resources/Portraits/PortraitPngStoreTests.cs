using System.Buffers.Binary;
using System.IO.Compression;
using System.Security.Cryptography;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class PortraitPngStoreTests:IDisposable
{
    private readonly string path=Path.Combine(Path.GetTempPath(),"lala-owned-portrait-"+Guid.NewGuid()+".sqlite");
    private static readonly string Source=new('a',64);
    private static readonly PortraitMaterialKey[] Keys=[new("player","0001"),new("companion","0001")];
    private SqliteConnection Connection()=>new(new SqliteConnectionStringBuilder{DataSource=path,Pooling=false}.ToString());
    public void Dispose(){File.Delete(path);File.Delete(path+"-journal");}
    private static PortraitCachePlan Plan(string? source=null)=>new(source??Source,Keys);
    private static PortraitImageCandidate Candidate(PortraitMaterialKey key,string source,int seed=11,byte[]? random=null)
    {
        var colors=PortraitRenderer.Parts.ToDictionary(k=>k,k=>new UnityMaterialColor(4,4,4,1));
        var material=new PortraitMaterialCandidate("owned",new(2,1),new(1,2),new(0,0),.06f,colors);
        var row=new PortraitLinkedRow(key,"Assets/owned.mat",3,material,2,"Assets/owned.png",null);
        byte[] basis=random??Enumerable.Range(0,256*256*4).Select(i=>(byte)((i*37+seed)%256)).ToArray();
        return new(row,source,basis,random??Enumerable.Repeat((byte)255,basis.Length).ToArray());
    }
    private static Func<Action<PortraitImageCandidate>,CancellationToken,PortraitBatchReceipt> Producer(PortraitCachePlan plan,int seed=11,byte[]? random=null)=>
        (consume,token)=>
        {
            using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);int count=0;
            foreach(var key in plan.Keys){token.ThrowIfCancellationRequested();var c=Candidate(key,plan.SourceFingerprint,seed,random);consume(c);hash.AppendData(Convert.FromHexString(c.Fingerprint));count++;}
            return new(plan.SourceFingerprint,Convert.ToHexStringLower(hash.GetHashAndReset()),count);
        };
    private static void CheckSource(){}
    private void Execute(string sql,params(string,object)[] parameters)
    {
        using var c=Connection();c.Open();using var cmd=c.CreateCommand();cmd.CommandText=sql;
        foreach(var(k,v)in parameters)cmd.Parameters.AddWithValue(k,v);cmd.ExecuteNonQuery();
    }
    private static byte[] DecodeOwnedPng(byte[] png)
    {
        Assert.Equal(new byte[]{137,80,78,71,13,10,26,10},png[..8]);using var idat=new MemoryStream();int offset=8;
        while(offset<png.Length)
        {
            int size=checked((int)BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset)));string type=System.Text.Encoding.ASCII.GetString(png,offset+4,4);
            var data=png.AsSpan(offset+8,size);string crc=ManifestIdentity.Crc32LittleEndian(png.AsSpan(offset+4,size+4));
            Assert.Equal(BinaryPrimitives.ReadUInt32LittleEndian(Convert.FromHexString(crc)),BinaryPrimitives.ReadUInt32BigEndian(png.AsSpan(offset+8+size)));
            if(type=="IHDR"){Assert.Equal(256u,BinaryPrimitives.ReadUInt32BigEndian(data));Assert.Equal(256u,BinaryPrimitives.ReadUInt32BigEndian(data[4..]));Assert.Equal(8,data[8]);Assert.Equal(6,data[9]);}
            if(type=="IDAT")idat.Write(data);offset+=size+12;
        }
        idat.Position=0;using var z=new ZLibStream(idat,CompressionMode.Decompress);using var result=new MemoryStream();z.CopyTo(result);
        byte[] raw=result.ToArray();Assert.Equal(256*(256*4+1),raw.Length);var pixels=new byte[256*256*4];
        for(int y=0;y<256;y++){Assert.Equal(0,raw[y*1025]);raw.AsSpan(y*1025+1,1024).CopyTo(pixels.AsSpan(y*1024));}return pixels;
    }
    [Fact]
    public async Task Complete_owned_batch_round_trips_with_fresh_candidates_and_private_copies()
    {
        var plan=Plan();int sourceChecks=0,builds=0;var producer=Producer(plan);
        PortraitBatchReceipt Rebuild(Action<PortraitImageCandidate> consume,CancellationToken token){builds++;return producer(consume,token);}
        var written=await PortraitPngStore.WriteAsync(Connection(),plan,Rebuild,()=>sourceChecks++);
        var read=await PortraitPngStore.ReadAsync(Connection(),plan,Rebuild,()=>sourceChecks++);
        Assert.Equal(written,read.Receipt);Assert.Equal(2,builds);Assert.Equal(2,sourceChecks);Assert.False(read.HasVerifiedProvenance);
        foreach(var key in plan.Keys)
        {
            var expected=Candidate(key,Source);var image=read.Images[key];Assert.Equal(expected.CopyBase(),DecodeOwnedPng(image.CopyBasePng()));
            Assert.Equal(expected.CopyMask(),DecodeOwnedPng(image.CopyMaskPng()));Assert.True(image.CopyBasePng().Length<8192);
            byte[] copy=image.CopyBasePng();Array.Fill(copy,(byte)0);Assert.NotEqual(copy,image.CopyBasePng());
            var settings=image.CopyRenderSettings();settings.Colors.First().Value[0]=99;Assert.Equal(4,image.CopyRenderSettings().Colors.First().Value[0]);
        }
    }
    [Theory,InlineData("base"),InlineData("mask"),InlineData("hash"),InlineData("identity"),InlineData("source"),InlineData("missing"),InlineData("extra"),InlineData("type"),InlineData("oversize"),InlineData("forged-png")]
    public async Task Corruption_and_self_consistent_replacement_cannot_authorize_pixels(string change)
    {
        var plan=Plan();await PortraitPngStore.WriteAsync(Connection(),plan,Producer(plan),CheckSource);
        switch(change)
        {
            case "base":Execute("UPDATE portrait_png_v1 SET base_png=zeroblob(length(base_png))");break;
            case "mask":Execute("UPDATE portrait_png_v1 SET mask_png=zeroblob(length(mask_png))");break;
            case "hash":Execute("UPDATE portrait_png_v1 SET base_sha='bad'");break;
            case "identity":Execute("UPDATE portrait_png_v1 SET image_sha='bad'");break;
            case "source":Execute("UPDATE portrait_png_v1 SET source='bad'");break;
            case "missing":Execute("DELETE FROM portrait_png_v1");break;
            case "extra":Execute("INSERT INTO portrait_png_v1 SELECT kind, '9999',source,image_sha,base_sha,mask_sha,base_png,mask_png FROM portrait_png_v1");break;
            case "type":Execute("UPDATE portrait_png_v1 SET base_png='text'");break;
            case "oversize":Execute("UPDATE portrait_png_v1 SET base_png=zeroblob(524289)");break;
            case "forged-png":var png=SpritePng.EncodePortrait(Candidate(plan.Keys[0],Source,12).CopyBase());Execute("UPDATE portrait_png_v1 SET base_png=@png,base_sha=@sha",("@png",png),("@sha",SpritePng.Hash(png)));break;
        }
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>PortraitPngStore.ReadAsync(Connection(),plan,Producer(plan),CheckSource));
    }
    [Theory,InlineData("partial"),InlineData("receipt"),InlineData("cancel"),InlineData("source")]
    public async Task Failed_batch_rolls_back_prior_rows_and_drains_connection(string failure)
    {
        var old=Plan();await PortraitPngStore.WriteAsync(Connection(),old,Producer(old),CheckSource);var next=Plan(new string('b',64));using var cts=new CancellationTokenSource();
        var producer=Producer(next);
        PortraitBatchReceipt Rebuild(Action<PortraitImageCandidate> consume,CancellationToken token)
        {
            if(failure=="partial"){consume(Candidate(next.Keys[0],next.SourceFingerprint));throw new InvalidDataException("owned partial failure");}
            var receipt=producer(consume,token);return failure=="receipt"?receipt with{Count=1}:receipt;
        }
        void Recheck(){if(failure=="cancel")cts.Cancel();if(failure=="source")throw new InvalidDataException("owned source changed");}
        var error=await Assert.ThrowsAnyAsync<Exception>(()=>PortraitPngStore.WriteAsync(Connection(),next,Rebuild,Recheck,cts.Token));
        Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted,error.Data[ResourceInventoryDatabase.OutcomeKey]);Assert.Equal(true,error.Data[ResourceInventoryDatabase.RollbackKey]);
        Assert.Equal(2,(await PortraitPngStore.ReadAsync(Connection(),old,Producer(old),CheckSource)).Images.Count);
    }
    [Fact]
    public async Task Read_rechecks_source_and_rejects_wrong_pixels_or_version()
    {
        var plan=Plan();await PortraitPngStore.WriteAsync(Connection(),plan,Producer(plan),CheckSource);
        await Assert.ThrowsAsync<InvalidDataException>(()=>PortraitPngStore.ReadAsync(Connection(),plan,Producer(plan),()=>throw new InvalidDataException("changed")));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>PortraitPngStore.ReadAsync(Connection(),plan,Producer(plan,12),CheckSource));
        var other=Plan(new string('b',64));await Assert.ThrowsAsync<UnityTextAssetException>(()=>PortraitPngStore.ReadAsync(Connection(),other,Producer(other),CheckSource));
    }
    [Fact]
    public async Task Aggregate_png_budget_is_enforced_without_replacing_old_catalog()
    {
        var old=Plan();await PortraitPngStore.WriteAsync(Connection(),old,Producer(old),CheckSource);
        var large=new PortraitCachePlan(Source,Enumerable.Range(1,129).Select(i=>new PortraitMaterialKey("companion",i.ToString("D4"))).ToArray());
        byte[] random=new byte[256*256*4];new Random(731).NextBytes(random);
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>PortraitPngStore.WriteAsync(Connection(),large,Producer(large,random:random),CheckSource));
        Assert.Equal(2,(await PortraitPngStore.ReadAsync(Connection(),old,Producer(old),CheckSource)).Images.Count);
    }
    [Fact]
    public async Task Invalid_index_foreign_schema_and_initial_cancel_are_rejected()
    {
        Assert.Throws<UnityTextAssetException>(()=>new PortraitCachePlan(Source,[Keys[0],Keys[0]]));
        Assert.Throws<UnityTextAssetException>(()=>new PortraitCachePlan(Source,Enumerable.Repeat(Keys[0],1025).ToArray()));
        var plan=Plan();await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>PortraitPngStore.WriteAsync(Connection(),plan,Producer(plan),CheckSource,new(true)));Assert.False(File.Exists(path));
        await PortraitPngStore.WriteAsync(Connection(),plan,Producer(plan),CheckSource);Execute("CREATE TRIGGER extra BEFORE DELETE ON portrait_png_v1 BEGIN SELECT RAISE(FAIL,'unexpected'); END");
        await Assert.ThrowsAsync<InvalidDataException>(()=>PortraitPngStore.WriteAsync(Connection(),plan,Producer(plan),CheckSource));
        Execute("DROP TRIGGER extra");Assert.Equal(2,(await PortraitPngStore.ReadAsync(Connection(),plan,Producer(plan),CheckSource)).Images.Count);
    }
}
