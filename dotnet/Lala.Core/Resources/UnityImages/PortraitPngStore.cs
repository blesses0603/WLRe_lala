using System.Collections.Frozen;
using System.Data.Common;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// Immutable input index; it describes the required offline set, not official provenance.
internal sealed class PortraitCachePlan
{
    internal string SourceFingerprint { get; }
    internal IReadOnlyList<PortraitMaterialKey> Keys { get; }
    internal PortraitCachePlan(string source,IReadOnlyList<PortraitMaterialKey> keys)
    {
        Require(source.Length==64&&source.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f'),"Invalid portrait source fingerprint");
        Require(keys.Count is >0 and <=1024,"Portrait cache count exceeds bound");
        var copy=keys.ToArray();Require(copy.Length is >0 and <=1024&&copy.Distinct().Count()==copy.Length,"Invalid portrait cache index");
        Require(copy.All(k=>k.Kind is "player" or "companion"&&k.Icon.Length<=32&&Regex.IsMatch(k.Icon,@"\A[0-9]{4}(?:_[0-9]+)?\z",RegexOptions.CultureInvariant|RegexOptions.NonBacktracking)),"Invalid portrait cache key");
        SourceFingerprint=source;Keys=Array.AsReadOnly(copy.OrderBy(k=>k.Kind,StringComparer.Ordinal).ThenBy(k=>k.Icon,StringComparer.Ordinal).ToArray());
    }
    internal static PortraitCachePlan FromSources(PortraitSourcePlan.VerifiedPortraitSources sources)=>new(sources.Plan.Fingerprint,sources.Plan.Materials.Keys.ToArray());
}
internal sealed class PortraitCachedImage
{
    private readonly byte[] basis,mask;
    private readonly PortraitRenderSettings settings;
    internal string Fingerprint { get; }
    internal byte[] CopyBasePng()=>basis.ToArray();
    internal byte[] CopyMaskPng()=>mask.ToArray();
    internal PortraitRenderSettings CopyRenderSettings()=>settings with { Colors=settings.Colors.ToDictionary(p=>p.Key,p=>p.Value.ToArray(),StringComparer.Ordinal) };
    internal PortraitCachedImage(PortraitImageCandidate candidate,byte[] basis,byte[] mask)
    {Fingerprint=candidate.Fingerprint;this.basis=basis.ToArray();this.mask=mask.ToArray();settings=candidate.CopyRenderSettings();}
}
internal sealed record PortraitPngReadback(PortraitBatchReceipt Receipt,IReadOnlyDictionary<PortraitMaterialKey,PortraitCachedImage> Images)
{
    internal PortraitMapping? Mapping { get; init; }
    internal PortraitSelection? Select(Lala.Core.Protocol.WorldPlayer? player,
        Lala.Core.Inventory.CompanionReceiveSnapshot companions, bool companion)
    {
        var selected = Mapping?.Select(player, companions, companion);
        return selected is not null && Images.ContainsKey(selected.Key) ? selected : null;
    }
    internal bool HasVerifiedProvenance=>false; // Current owner activation must separately admit each read.
}
internal static class PortraitPngStore
{
    private const string Schema="CREATE TABLE portrait_png_v1 (kind TEXT NOT NULL, icon TEXT NOT NULL, source TEXT NOT NULL, image_sha TEXT NOT NULL, base_sha TEXT NOT NULL, mask_sha TEXT NOT NULL, base_png BLOB NOT NULL, mask_png BLOB NOT NULL, PRIMARY KEY(kind,icon))";
    internal const int MaximumPngBytes=512*1024,MaximumTotalBytes=64*1024*1024;
    internal static async Task<PortraitBatchReceipt> WriteAsync(DbConnection connection,PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>,CancellationToken,PortraitBatchReceipt> rebuild,Action revalidateSources,CancellationToken token=default)
        =>(await RunWorker(connection,plan,rebuild,revalidateSources,true,token).ConfigureAwait(false)).Receipt;
    internal static Task<PortraitPngReadback> ReadAsync(DbConnection connection,PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>,CancellationToken,PortraitBatchReceipt> rebuild,Action revalidateSources,CancellationToken token=default)
        =>RunWorker(connection,plan,rebuild,revalidateSources,false,token);
    // The caller transfers a closed exclusive connection. CPU work/serial callback waits stay
    // on a worker; the returned task drains cleanup even when initially cancelled.
    private static Task<PortraitPngReadback> RunWorker(DbConnection connection,PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>,CancellationToken,PortraitBatchReceipt> rebuild,Action revalidateSources,bool write,CancellationToken token)
        =>Task.Run(()=>RunAsync(connection,plan,rebuild,revalidateSources,write,token),CancellationToken.None);
    private static async Task<PortraitPngReadback> RunAsync(DbConnection connection,PortraitCachePlan plan,
        Func<Action<PortraitImageCandidate>,CancellationToken,PortraitBatchReceipt> rebuild,Action revalidateSources,bool write,CancellationToken token)
    {
        var db=new ResourceInventoryDatabase(connection,token);Exception? primary=null;PortraitBatchReceipt? receipt=null;
        var result=new Dictionary<PortraitMaterialKey,PortraitCachedImage>();
        try
        {
            ArgumentNullException.ThrowIfNull(plan);ArgumentNullException.ThrowIfNull(rebuild);ArgumentNullException.ThrowIfNull(revalidateSources);
            token.ThrowIfCancellationRequested();await db.OpenAsync(write).ConfigureAwait(false);
            var schema=await db.ReadAsync("SELECT "+ResourceInventoryDatabase.BoundedTextSql("sql",4096)+" FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'",1).ConfigureAwait(false);
            if(schema.Count==0&&write)await db.ExecuteAsync(Schema).ConfigureAwait(false);
            else Require(schema.Count==1&&schema[0][0] as string==Schema,"Unexpected portrait cache schema");
            if(write)await db.ExecuteAsync("DELETE FROM portrait_png_v1").ConfigureAwait(false);
            int count=0;long total=0;using var digest=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            async Task Consume(PortraitImageCandidate candidate)
            {
                token.ThrowIfCancellationRequested();Require(count<plan.Keys.Count&&candidate.Key==plan.Keys[count]&&candidate.SourceFingerprint==plan.SourceFingerprint,"Portrait producer index/source mismatch");
                byte[] basis=SpritePng.EncodePortrait(candidate.CopyBase(),token),mask=SpritePng.EncodePortrait(candidate.CopyMask(),token);
                total+=(long)basis.Length+mask.Length;Require(basis.Length<=MaximumPngBytes&&mask.Length<=MaximumPngBytes&&total<=MaximumTotalBytes,"Portrait PNG budget exceeded");
                string baseSha=SpritePng.Hash(basis),maskSha=SpritePng.Hash(mask);
                if(write)await db.ExecuteAsync("INSERT INTO portrait_png_v1 VALUES(CAST(@kind AS TEXT),CAST(@icon AS TEXT),CAST(@source AS TEXT),CAST(@image AS TEXT),CAST(@bs AS TEXT),CAST(@ms AS TEXT),@base,@mask)",
                    ("@kind",candidate.Key.Kind),("@icon",candidate.Key.Icon),("@source",plan.SourceFingerprint),("@image",candidate.Fingerprint),("@bs",baseSha),("@ms",maskSha),("@base",basis),("@mask",mask)).ConfigureAwait(false);
                var rows=await db.ReadAsync("SELECT "+string.Join(',',new[]{"source","image_sha","base_sha","mask_sha"}.Select(c=>ResourceInventoryDatabase.BoundedTextSql(c,64)))+
                    $",CASE WHEN typeof(base_png)='blob' AND length(base_png)<={MaximumPngBytes} THEN base_png ELSE NULL END,CASE WHEN typeof(mask_png)='blob' AND length(mask_png)<={MaximumPngBytes} THEN mask_png ELSE NULL END FROM portrait_png_v1 WHERE kind=CAST(@kind AS TEXT) AND icon=CAST(@icon AS TEXT)",
                    1,("@kind",candidate.Key.Kind),("@icon",candidate.Key.Icon)).ConfigureAwait(false);
                Require(rows.Count==1,"Missing portrait PNG row");var row=rows[0];
                Require(row[0] as string==plan.SourceFingerprint&&row[1] as string==candidate.Fingerprint&&row[2] as string==baseSha&&row[3] as string==maskSha&&
                    row[4] is byte[] bp&&bp.AsSpan().SequenceEqual(basis)&&row[5] is byte[] mp&&mp.AsSpan().SequenceEqual(mask),"Portrait PNG identity or pixels changed");
                if(!write)result.Add(candidate.Key,new(candidate,(byte[])row[4]!, (byte[])row[5]!));
                digest.AppendData(Convert.FromHexString(candidate.Fingerprint));count++;
            }
            // No SynchronizationContext is captured: producer and serial SQLite callbacks
            // run on this worker. No concurrent command or fire-and-forget producer escapes.
            receipt=rebuild(candidate=>Consume(candidate).GetAwaiter().GetResult(),token);
            Require(count==plan.Keys.Count&&receipt.Count==count&&receipt.SourceFingerprint==plan.SourceFingerprint&&
                receipt.Fingerprint==Convert.ToHexStringLower(digest.GetHashAndReset()),"Incomplete or mismatched portrait batch receipt");
            var rowCount=await db.ReadAsync("SELECT count(*) FROM portrait_png_v1",1).ConfigureAwait(false);
            Require(ResourceInventoryDatabase.Number(rowCount[0][0])==count,"Portrait cache index changed");
            await db.CommitAsync(()=>{revalidateSources();token.ThrowIfCancellationRequested();}).ConfigureAwait(false);
        }
        catch(Exception error){primary=error;}
        await db.FinishAsync(primary).ConfigureAwait(false);
        return new(receipt!,result.ToFrozenDictionary());
    }
}
