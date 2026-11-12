using System.Data.Common;
using System.Security.Cryptography;
using System.Text.Json;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed record SmallMapPngReadback(string SourceFingerprint,string BatchFingerprint,int Count)
{ internal bool HasVerifiedProvenance=>false; }
// Entire cache is atomically verified against freshly rebuilt pixels, one PNG at
// a time. No stored PNG is decoded or returned as publication authority.
internal static class SmallMapPngStore
{
    private const string Schema="CREATE TABLE smallmap_frames_v1 (model INTEGER PRIMARY KEY, source TEXT NOT NULL, asset TEXT NOT NULL, pixel_sha TEXT NOT NULL, png_sha TEXT NOT NULL, png BLOB NOT NULL)";
    internal static Task<SmallMapPngReadback> WriteAsync(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,CancellationToken token=default)
        =>Task.Run(async()=>(await Run(connection,batch,revalidate,true,false,token).ConfigureAwait(false)).Readback,CancellationToken.None);
    internal static Task<SmallMapPngReadback> ReadAsync(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,CancellationToken token=default)
        =>Task.Run(async()=>(await Run(connection,batch,revalidate,false,false,token).ConfigureAwait(false)).Readback,CancellationToken.None);
    internal static Task<SmallMapPngSnapshot> ReadForPublicationAsync(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,CancellationToken token=default)
        =>Task.Run(()=>Run(connection,batch,revalidate,false,true,token),CancellationToken.None);
    // Retain the same bounded source-derived PNG set needed for publication. A
    // separate reopened read below verifies the database without decoding it twice.
    internal static Task<SmallMapPngSnapshot> WriteForReadbackAsync(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,CancellationToken token=default,Action<int,int>? report=null)
        =>Task.Run(()=>Run(connection,batch,revalidate,true,true,token,report),CancellationToken.None);
    internal static Task<SmallMapPngSnapshot> ReadCapturedAsync(DbConnection connection,SmallMapPngSnapshot expected,Action revalidate,CancellationToken token=default,Action<int,int>? report=null)
        =>Task.Run(()=>ReadCapturedCoreAsync(connection,expected,revalidate,token,report),CancellationToken.None);
    internal static Task<SmallMapPngSnapshot> ReadWithProgressAsync(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,CancellationToken token,Action<int,int> report)
        =>Task.Run(()=>Run(connection,batch,revalidate,false,true,token,report),CancellationToken.None);
    private static async Task<SmallMapPngSnapshot> Run(DbConnection connection,SmallMapReceiptBatch batch,Action revalidate,bool write,bool capture,CancellationToken token,Action<int,int>? report=null)
    {
        var db=new ResourceInventoryDatabase(connection,token);Exception? failure=null;SmallMapPngReadback? result=null;var images=new Dictionary<int,byte[]>();
        try
        {
            ArgumentNullException.ThrowIfNull(batch);ArgumentNullException.ThrowIfNull(revalidate);token.ThrowIfCancellationRequested();
            await db.OpenAsync(write).ConfigureAwait(false);
            var schema=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("sql",4096)+" FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'",1).ConfigureAwait(false);
            if(schema.Count==0&&write)await db.ExecuteAsync(Schema).ConfigureAwait(false);
            else Require(schema.Count==1&&schema[0][0] as string==Schema,"Unexpected small map cache schema");
            if(write)await db.ExecuteAsync("DELETE FROM smallmap_frames_v1").ConfigureAwait(false);
            long total=0;int count=0;using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            hash.AppendData(JsonSerializer.SerializeToUtf8Bytes(new{Schema=1,batch.SourceFingerprint}));
            await batch.ConsumeAsync(async(image,ct)=>
            {
                ct.ThrowIfCancellationRequested();byte[] png=image.CopyPng();total=checked(total+png.Length);count++;
                Require(png.Length is >0 and <=4*1024*1024&&total<=96L*1024*1024&&count<=2048,"Small map PNG batch quota exceeded");
                if(write)await db.ExecuteAsync("INSERT INTO smallmap_frames_v1 VALUES(@m,CAST(@s AS TEXT),CAST(@a AS TEXT),CAST(@p AS TEXT),CAST(@h AS TEXT),@png)",
                    ("@m",image.Model),("@s",batch.SourceFingerprint),("@a",image.AssetPath),("@p",image.PixelSha256),("@h",image.PngSha256),("@png",png)).ConfigureAwait(false);
                var rows=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("source",64)+","+ResourceInventoryDatabase.BoundedTextSql("asset",1024)+","+ResourceInventoryDatabase.BoundedTextSql("pixel_sha",64)+","+ResourceInventoryDatabase.BoundedTextSql("png_sha",64)+",CASE WHEN typeof(png)='blob' AND length(png)<=4194304 THEN png ELSE NULL END FROM smallmap_frames_v1 WHERE model=@m",1,("@m",image.Model)).ConfigureAwait(false);
                Require(rows.Count==1,"Missing small map PNG row");var row=rows[0];
                Require(row[0] as string==batch.SourceFingerprint&&row[1] as string==image.AssetPath&&row[2] as string==image.PixelSha256&&row[3] as string==image.PngSha256&&row[4] is byte[] stored&&stored.AsSpan().SequenceEqual(png),"Small map PNG identity or bytes changed");
                if(capture)images.Add(image.Model,png);
                hash.AppendData(JsonSerializer.SerializeToUtf8Bytes(new{image.Model,image.AssetPath,image.PixelSha256,image.PngSha256}));
                report?.Invoke(count,batch.Paths.Count);
            },token).ConfigureAwait(false);
            var rows=await db.ReadAsync("SELECT count(*) FROM smallmap_frames_v1",1).ConfigureAwait(false);
            Require(count==batch.Paths.Count&&ResourceInventoryDatabase.Number(rows[0][0])==count,"Small map cache coverage changed");
            result=new(batch.SourceFingerprint,Convert.ToHexStringLower(hash.GetHashAndReset()),count);
            await db.CommitAsync(()=>{revalidate();token.ThrowIfCancellationRequested();}).ConfigureAwait(false);
        }
        catch(Exception error){failure=error;images.Clear();}
        await db.FinishAsync(failure).ConfigureAwait(false);return new(result!,images);
    }

    private static async Task<SmallMapPngSnapshot> ReadCapturedCoreAsync(DbConnection connection,SmallMapPngSnapshot expected,Action revalidate,CancellationToken token,Action<int,int>? report)
    {
        var db=new ResourceInventoryDatabase(connection,token);Exception? failure=null;
        try
        {
            ArgumentNullException.ThrowIfNull(expected);ArgumentNullException.ThrowIfNull(revalidate);token.ThrowIfCancellationRequested();
            await db.OpenAsync(false).ConfigureAwait(false);
            var schema=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("sql",4096)+" FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'",1).ConfigureAwait(false);
            Require(schema.Count==1&&schema[0][0] as string==Schema,"Unexpected small map cache schema");
            using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);long total=0;int count=0;
            hash.AppendData(JsonSerializer.SerializeToUtf8Bytes(new{Schema=1,expected.Readback.SourceFingerprint}));
            foreach(int model in expected.Models)
            {
                token.ThrowIfCancellationRequested();
                var rows=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("source",64)+","+ResourceInventoryDatabase.BoundedTextSql("asset",1024)+","+ResourceInventoryDatabase.BoundedTextSql("pixel_sha",64)+","+ResourceInventoryDatabase.BoundedTextSql("png_sha",64)+",CASE WHEN typeof(png)='blob' AND length(png)<=4194304 THEN png ELSE NULL END FROM smallmap_frames_v1 WHERE model=@m",1,("@m",model)).ConfigureAwait(false);
                Require(rows.Count==1,"Missing small map PNG row");var row=rows[0];
                Require(row[4] is byte[],"Small map PNG type or bound changed");var png=(byte[])row[4]!;
                total=checked(total+png.Length);count++;
                Require(png.Length>0&&total<=96L*1024*1024&&count<=2048&&row[0] as string==expected.Readback.SourceFingerprint&&row[3] as string==expected.Hash(model)&&expected.Matches(model,png),"Small map PNG identity or bytes changed");
                hash.AppendData(JsonSerializer.SerializeToUtf8Bytes(new{Model=model,AssetPath=row[1] as string,PixelSha256=row[2] as string,PngSha256=row[3] as string}));
                report?.Invoke(count,expected.Readback.Count);
            }
            var coverage=await db.ReadAsync("SELECT count(*) FROM smallmap_frames_v1",1).ConfigureAwait(false);
            Require(count==expected.Readback.Count&&ResourceInventoryDatabase.Number(coverage[0][0])==count&&Convert.ToHexStringLower(hash.GetHashAndReset())==expected.Readback.BatchFingerprint,"Small map cache metadata or coverage changed");
            await db.CommitAsync(()=>{revalidate();token.ThrowIfCancellationRequested();}).ConfigureAwait(false);
        }
        catch(Exception error){failure=error;}
        await db.FinishAsync(failure).ConfigureAwait(false);return expected;
    }
}
