using System.Text.Json;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

internal sealed class SmallMapPngCandidate
{
    private readonly byte[] png;
    internal int Model {get;}
    internal string AssetPath {get;}
    internal string SourceFingerprint {get;}
    internal string PixelSha256 {get;}
    internal string PngSha256 {get;}
    internal bool HasVerifiedProvenance=>false;
    internal byte[] CopyPng()=>png.ToArray();
    internal SmallMapPngCandidate(int model,string path,string source,TexturePixelCandidate pixels,CancellationToken token)
    {Model=model;AssetPath=path;SourceFingerprint=source;PixelSha256=pixels.PixelSha256;png=SpritePng.EncodeSmallMap(pixels,token);PngSha256=SpritePng.Hash(png);}
}
// Fixed cache-backed factory. It accepts manifest-derived receipts, never pixels,
// serialized object claims, arbitrary decoders or caller-selected source hashes.
// Current manifest checks, SQLite readback and revocable UI publication remain external.
internal sealed class SmallMapReceiptBatch:IAsyncDisposable
{
    private readonly BundleReceiptPhase phase;private readonly BundleSourcePlan plan;
    private readonly IReadOnlyDictionary<int,string> paths;
    internal IReadOnlyDictionary<int,string> Paths=>paths;
    internal string SourceFingerprint {get;}
    internal SmallMapReceiptBatch(YooAssetManifest manifest,string version,IBundleSourceCacheReader cache,IReadOnlyList<BundleStreamReceipt> receipts,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();plan=SmallMapSourcePlan.CreateStaged(manifest,version,token);paths=SmallMapSourcePlan.Paths(manifest,token);
        var captured=receipts.ToArray();
        Require(captured.Length==plan.Entries.Count&&captured.Select(r=>r.Spec.Name).Distinct(StringComparer.Ordinal).Count()==captured.Length,"Small map receipt set mismatch");
        foreach(var entry in plan.Entries)Require(captured.SingleOrDefault(r=>r.Spec.Name==entry.Spec.Name)?.Spec==entry.Spec,"Small map receipt differs from exact manifest");
        phase=new(cache,captured);
        SourceFingerprint=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new{Schema=1,version,manifest.Sha256,Sources=captured.OrderBy(r=>r.Spec.Name,StringComparer.Ordinal).Select(r=>new{r.Spec.Name,r.Spec.Size,r.Spec.Md5,r.Spec.Crc32Le,r.Sha256}),Assets=paths.OrderBy(p=>p.Key).Select(p=>new{Model=p.Key,Path=p.Value,Closure=plan.AssetSourceNames[p.Value]})}));
    }
    internal async Task<SmallMapPngCandidate> RebuildAsync(int model,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(paths.TryGetValue(model,out var path),"Small map model outside exact manifest");
        SmallMapPngCandidate? result=null;
        await ConsumeRootAsync(plan.AssetSourceNames[path!][^1],[new(model,path!)],(image,ct)=>{result=image;return Task.CompletedTask;},token).ConfigureAwait(false);
        return result!;
    }
    internal async Task ConsumeAsync(Func<SmallMapPngCandidate,CancellationToken,Task> consume,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(consume);token.ThrowIfCancellationRequested();
        foreach(var group in paths.GroupBy(p=>plan.AssetSourceNames[p.Value][^1]).OrderBy(g=>g.Key,StringComparer.Ordinal))
            await ConsumeRootAsync(group.Key,group.OrderBy(p=>p.Key).ToArray(),consume,token).ConfigureAwait(false);
    }
    private Task<int> ConsumeRootAsync(string root,IReadOnlyList<KeyValuePair<int,string>> selected,Func<SmallMapPngCandidate,CancellationToken,Task> consume,CancellationToken token)
        =>phase.ReadAsync("MainPackage",root,async(source,ct)=>
        {
            var archive=await StreamedUnityArchive.CreateAsync(source,ct).ConfigureAwait(false);
            var owners=archive.Entries.Where(e=>!e.IsResource).ToArray();Require(owners.Length==1,"Unreviewed small map serialized owner set");
            var entry=owners[0];Require(entry.Size<=StreamedUnityArchive.MaximumSliceBytes,"Small map serialized file exceeds bound");
            var owner=new UnityFileIdentity(root,entry.Name);
            var bytes=await archive.ReadAsync(entry.Name,0,(int)entry.Size,ct).ConfigureAwait(false);
            var required=paths.Values.Where(p=>plan.AssetSourceNames[p][^1]==root).ToArray();
            var file=BoundedSerializedFile.ReadSmallMapProjection(owner,bytes,required,new(),ct);
            foreach(var pair in selected)
            {
                ct.ThrowIfCancellationRequested();var pointer=file.Container.Single(e=>e.Path==pair.Value).Pointer;
                var texture=await UnityImageObjects.TextureAsync(file.Objects[pointer.PathId].Bytes,archive,owner,ct).ConfigureAwait(false);
                Require(texture.Layout.Width==1024&&texture.Layout.Height==1024,"Small map texture geometry mismatch");
                var pixels=BoundedTexturePixels.Decode(new(SourceFingerprint,source.Receipt.Sha256,entry.Name,pair.Value,pointer.PathId),texture,ct);
                await consume(new(pair.Key,pair.Value,SourceFingerprint,pixels,ct),ct).ConfigureAwait(false);
            }
            return selected.Count;
        },token);
    public ValueTask DisposeAsync()=>phase.DisposeAsync();
}
