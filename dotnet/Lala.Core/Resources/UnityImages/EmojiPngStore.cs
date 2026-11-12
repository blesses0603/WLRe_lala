using System.Data.Common;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed record EmojiPngReadback(string SourceFingerprint,EmojiPixelBatch Batch)
{
    internal bool HasVerifiedProvenance=>false;
    internal byte[]? CopyPng(int token)=>Batch.Find(token)?.CopyPng();
}
internal static class EmojiPngStore
{
    private const string Frames="CREATE TABLE emoji_frames_v1 (frame TEXT PRIMARY KEY, source TEXT NOT NULL, batch TEXT NOT NULL, input_sha TEXT NOT NULL, pixel_sha TEXT NOT NULL, png_sha TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, png BLOB NOT NULL)";
    private const string Tokens="CREATE TABLE emoji_tokens_v1 (token INTEGER PRIMARY KEY, id INTEGER NOT NULL, mark INTEGER NOT NULL, icon INTEGER NOT NULL, text_id INTEGER NOT NULL, visible INTEGER NOT NULL, frame TEXT NOT NULL)";
    internal static async Task<string> WriteAsync(DbConnection connection,string source,Func<CancellationToken,EmojiPixelBatch> rebuild,Action revalidate,CancellationToken token=default)
        =>(await Task.Run(()=>Run(connection,source,rebuild,revalidate,true,token),CancellationToken.None).ConfigureAwait(false)).Batch.Fingerprint;
    internal static Task<EmojiPngReadback> ReadAsync(DbConnection connection,string source,Func<CancellationToken,EmojiPixelBatch> rebuild,Action revalidate,CancellationToken token=default)
        =>Task.Run(()=>Run(connection,source,rebuild,revalidate,false,token),CancellationToken.None);
    private static async Task<EmojiPngReadback> Run(DbConnection connection,string source,Func<CancellationToken,EmojiPixelBatch> rebuild,Action revalidate,bool write,CancellationToken token)
    {
        var db=new ResourceInventoryDatabase(connection,token);Exception? failure=null;EmojiPixelBatch? batch=null;
        try
        {
            ArgumentNullException.ThrowIfNull(rebuild);ArgumentNullException.ThrowIfNull(revalidate);
            Require(source.Length==64&&source.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f'),"Invalid emoji source fingerprint");
            token.ThrowIfCancellationRequested();await db.OpenAsync(write).ConfigureAwait(false);
            var schema=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("sql",4096)+" FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'",2).ConfigureAwait(false);
            if(schema.Count==0&&write){await db.ExecuteAsync(Frames).ConfigureAwait(false);await db.ExecuteAsync(Tokens).ConfigureAwait(false);}
            else Require(schema.Count==2&&schema.Select(row=>row[0] as string).ToHashSet(StringComparer.Ordinal).SetEquals(new[]{Frames,Tokens}),"Unexpected emoji cache schema");
            // Every write/read independently rebuilds complete mapping and PNGs from its producer.
            batch=rebuild(token);token.ThrowIfCancellationRequested();
            if(write){await db.ExecuteAsync("DELETE FROM emoji_tokens_v1").ConfigureAwait(false);await db.ExecuteAsync("DELETE FROM emoji_frames_v1").ConfigureAwait(false);}
            long total=0;
            foreach(var (frame,image) in batch.Images.OrderBy(p=>p.Key,StringComparer.Ordinal))
            {
                token.ThrowIfCancellationRequested();byte[] png=image.CopyPng();total+=png.Length;
                Require(png.Length is >0 and <=1024*1024&&total<=8*1024*1024,"Emoji stored PNG quota exceeded");
                if(write)await db.ExecuteAsync("INSERT INTO emoji_frames_v1 VALUES(CAST(@f AS TEXT),CAST(@s AS TEXT),CAST(@b AS TEXT),CAST(@i AS TEXT),CAST(@p AS TEXT),CAST(@h AS TEXT),@w,@y,@png)",
                    ("@f",frame),("@s",source),("@b",batch.Fingerprint),("@i",image.InputFingerprint),("@p",image.PixelSha256),("@h",image.PngSha256),("@w",image.Width),("@y",image.Height),("@png",png)).ConfigureAwait(false);
                var rows=await db.ReadAsync("SELECT "+string.Join(',',new[]{"source","batch","input_sha","pixel_sha","png_sha"}.Select(c=>ResourceInventoryDatabase.BoundedTextSql(c,64)))+
                    ",width,height,CASE WHEN typeof(png)='blob' AND length(png)<=1048576 THEN png ELSE NULL END FROM emoji_frames_v1 WHERE frame=CAST(@f AS TEXT)",1,("@f",frame)).ConfigureAwait(false);
                Require(rows.Count==1,"Missing emoji PNG row");var row=rows[0];
                Require(row[0] as string==source&&row[1] as string==batch.Fingerprint&&row[2] as string==image.InputFingerprint&&row[3] as string==image.PixelSha256&&row[4] as string==image.PngSha256&&
                    ResourceInventoryDatabase.Number(row[5])==image.Width&&ResourceInventoryDatabase.Number(row[6])==image.Height&&row[7] is byte[] stored&&stored.AsSpan().SequenceEqual(png),"Emoji PNG identity or pixels changed");
            }
            foreach(var row in batch.Mapping.Rows)
            {
                token.ThrowIfCancellationRequested();
                if(write)await db.ExecuteAsync("INSERT INTO emoji_tokens_v1 VALUES(@t,@i,@m,@c,@x,@v,CAST(@f AS TEXT))",("@t",row.Token),("@i",row.Id),("@m",row.MarkId),("@c",row.Icon),("@x",(long)row.TextId),("@v",row.ShowInList?1:0),("@f",row.FirstFrame)).ConfigureAwait(false);
                var rows=await db.ReadAsync("SELECT id,mark,icon,text_id,visible,"+ResourceInventoryDatabase.BoundedTextSql("frame",32)+" FROM emoji_tokens_v1 WHERE token=@t",1,("@t",row.Token)).ConfigureAwait(false);
                Require(rows.Count==1,"Missing emoji token row");var stored=rows[0];
                Require(ResourceInventoryDatabase.Number(stored[0])==row.Id&&ResourceInventoryDatabase.Number(stored[1])==row.MarkId&&ResourceInventoryDatabase.Number(stored[2])==row.Icon&&ResourceInventoryDatabase.Number(stored[3])==row.TextId&&ResourceInventoryDatabase.Number(stored[4])==(row.ShowInList?1:0)&&stored[5] as string==row.FirstFrame,"Emoji token mapping changed");
            }
            foreach(var (table,count) in new[]{("emoji_frames_v1",batch.Images.Count),("emoji_tokens_v1",batch.Mapping.Rows.Length)})
            {
                var rows=await db.ReadAsync("SELECT count(*) FROM "+table,1).ConfigureAwait(false);
                Require(ResourceInventoryDatabase.Number(rows[0][0])==count,"Emoji cache index changed");
            }
            await db.CommitAsync(()=>{revalidate();token.ThrowIfCancellationRequested();}).ConfigureAwait(false);
        }
        catch(Exception error){failure=error;}
        await db.FinishAsync(failure).ConfigureAwait(false);
        return new(source,batch!);
    }
}
