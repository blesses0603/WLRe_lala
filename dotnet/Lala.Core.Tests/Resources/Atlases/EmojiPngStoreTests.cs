using System.Text.Json;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;
namespace Lala.Core.Tests.Resources;
internal static class EmojiRuntimeFixtures
{
    internal static readonly string Source=new('a',64);
    internal static EmojiPixelBatch Pixels(int seed=0,CancellationToken token=default)
    {
        using var d=JsonDocument.Parse(typeof(EmojiRuntimeFixtures).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.batch.json")!);
        var mapping=EmojiMapping.ParseLayoutForOfflineTests(Convert.FromBase64String(d.RootElement.GetProperty("raw").GetString()!));
        var images=d.RootElement.GetProperty("images").EnumerateObject().Select(p=>
        {
            var pixels=Convert.FromBase64String(p.Value.GetProperty("pixels").GetString()!);pixels[0]^=(byte)seed;
            return new AtlasPixelCandidate(p.Name,3,5,pixels,Source);
        });
        return EmojiPixelBatch.Create(mapping,images,token);
    }
    internal static EmojiRuntimeBatch Batch(Func<int>? seed=null)=>EmojiRuntimeBatch.ForOfflineTests(Source,t=>Pixels(seed?.Invoke()??0,t));
}
public sealed class EmojiPngStoreTests:IDisposable
{
    private readonly string path=Path.Combine(Path.GetTempPath(),"lala-emoji-"+Guid.NewGuid()+".sqlite");
    private SqliteConnection Connection()=>new(new SqliteConnectionStringBuilder{DataSource=path,Pooling=false}.ToString());
    public void Dispose(){File.Delete(path);File.Delete(path+"-journal");}
    private static EmojiPixelBatch Rebuild(CancellationToken t)=>EmojiRuntimeFixtures.Pixels(token:t);
    private Task<string> Write(Action? check=null,CancellationToken token=default)=>EmojiPngStore.WriteAsync(Connection(),EmojiRuntimeFixtures.Source,Rebuild,check??(()=>{}),token);
    private Task<EmojiPngReadback> Read()=>EmojiPngStore.ReadAsync(Connection(),EmojiRuntimeFixtures.Source,Rebuild,()=>{});
    private void Execute(string sql,params(string,object)[] parameters)
    {using var c=Connection();c.Open();using var cmd=c.CreateCommand();cmd.CommandText=sql;foreach(var(k,v)in parameters)cmd.Parameters.AddWithValue(k,v);cmd.ExecuteNonQuery();}
    [Fact]
    public async Task Complete_mapping_round_trips_with_fresh_pixels_and_private_copies()
    {
        int builds=0,checks=0;EmojiPixelBatch Build(CancellationToken t){builds++;return Rebuild(t);}
        var hash=await EmojiPngStore.WriteAsync(Connection(),EmojiRuntimeFixtures.Source,Build,()=>checks++);
        var read=await EmojiPngStore.ReadAsync(Connection(),EmojiRuntimeFixtures.Source,Build,()=>checks++);
        Assert.Equal(hash,read.Batch.Fingerprint);Assert.Equal(2,builds);Assert.Equal(2,checks);Assert.False(read.HasVerifiedProvenance);
        Assert.Equal(3,read.Batch.Mapping.Rows.Length);Assert.Equal(2,read.Batch.Images.Count);
        Assert.Equal(read.CopyPng(1),read.CopyPng(3));Assert.Null(read.CopyPng(0));
        var copy=read.CopyPng(1)!;copy[0]=0;Assert.Equal(137,read.CopyPng(1)![0]);
    }
    [Theory,InlineData("png"),InlineData("source"),InlineData("batch"),InlineData("input"),InlineData("pixel"),InlineData("width"),InlineData("token"),InlineData("visible"),InlineData("frame"),InlineData("missing-frame"),InlineData("missing-token"),InlineData("extra-frame"),InlineData("extra-token"),InlineData("type"),InlineData("oversize"),InlineData("forged")]
    public async Task Cache_metadata_or_self_consistent_png_replacement_never_authorizes_pixels(string change)
    {
        await Write();
        switch(change)
        {
            case "png":Execute("UPDATE emoji_frames_v1 SET png=zeroblob(length(png))");break;
            case "source":Execute("UPDATE emoji_frames_v1 SET source='bad'");break;
            case "batch":Execute("UPDATE emoji_frames_v1 SET batch='bad'");break;
            case "input":Execute("UPDATE emoji_frames_v1 SET input_sha='bad'");break;
            case "pixel":Execute("UPDATE emoji_frames_v1 SET pixel_sha='bad'");break;
            case "width":Execute("UPDATE emoji_frames_v1 SET width=4");break;
            case "token":Execute("UPDATE emoji_tokens_v1 SET mark=99");break;
            case "visible":Execute("UPDATE emoji_tokens_v1 SET visible=1-visible");break;
            case "frame":Execute("UPDATE emoji_tokens_v1 SET frame='missing'");break;
            case "missing-frame":Execute("DELETE FROM emoji_frames_v1");break;
            case "missing-token":Execute("DELETE FROM emoji_tokens_v1");break;
            case "extra-frame":Execute("INSERT INTO emoji_frames_v1 SELECT frame||'extra',source,batch,input_sha,pixel_sha,png_sha,width,height,png FROM emoji_frames_v1");break;
            case "extra-token":Execute("INSERT INTO emoji_tokens_v1 SELECT token+100,id,mark,icon,text_id,visible,frame FROM emoji_tokens_v1");break;
            case "type":Execute("UPDATE emoji_frames_v1 SET png='text'");break;
            case "oversize":Execute("UPDATE emoji_frames_v1 SET png=zeroblob(1048577)");break;
            case "forged":var image=EmojiRuntimeFixtures.Pixels(1).Find(1)!;Execute("UPDATE emoji_frames_v1 SET png=@p,png_sha=@h,pixel_sha=@s",("@p",image.CopyPng()),("@h",image.PngSha256),("@s",image.PixelSha256));break;
        }
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>Read());
    }
    [Theory,InlineData("cancel"),InlineData("source"),InlineData("producer")]
    public async Task Failed_write_retains_prior_batch_and_drains_transaction(string mode)
    {
        var old=await Write();using var stop=new CancellationTokenSource();
        EmojiPixelBatch Next(CancellationToken t)=>mode=="producer"?throw new IOException("owned failure"):EmojiRuntimeFixtures.Pixels(1,t);
        void Check(){if(mode=="cancel")stop.Cancel();else throw new InvalidDataException("owned source changed");}
        var error=await Assert.ThrowsAnyAsync<Exception>(()=>EmojiPngStore.WriteAsync(Connection(),new string('b',64),Next,Check,stop.Token));
        Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted,error.Data[ResourceInventoryDatabase.OutcomeKey]);Assert.Equal(true,error.Data[ResourceInventoryDatabase.RollbackKey]);
        Assert.Equal(old,(await Read()).Batch.Fingerprint);
    }
    [Fact]
    public async Task Read_rechecks_source_and_pixels_and_initial_cancel_creates_nothing()
    {
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>Write(token:new(true)));Assert.False(File.Exists(path));await Write();
        await Assert.ThrowsAsync<InvalidDataException>(()=>EmojiPngStore.ReadAsync(Connection(),EmojiRuntimeFixtures.Source,Rebuild,()=>throw new InvalidDataException("changed")));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>EmojiPngStore.ReadAsync(Connection(),EmojiRuntimeFixtures.Source,t=>EmojiRuntimeFixtures.Pixels(1,t),()=>{}));
        await Assert.ThrowsAsync<UnityTextAssetException>(()=>EmojiPngStore.ReadAsync(Connection(),new string('b',64),Rebuild,()=>{}));
    }
    [Fact]
    public async Task Foreign_schema_is_not_repaired_or_executed()
    {
        await Write();Execute("CREATE TRIGGER extra BEFORE DELETE ON emoji_frames_v1 BEGIN SELECT RAISE(FAIL,'unexpected'); END");
        await Assert.ThrowsAnyAsync<InvalidDataException>(()=>Write());Execute("DROP TRIGGER extra");Assert.NotNull(await Read());
    }
}
