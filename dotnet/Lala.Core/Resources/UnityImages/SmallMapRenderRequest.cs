using System.Collections.Frozen;
namespace Lala.Core.Resources;

// Private verified copies, capped by the store's 96 MiB full-batch limit. Cache
// mutations after readback cannot alter these bytes or supply new images.
internal sealed class SmallMapPngSnapshot
{
    private readonly FrozenDictionary<int,byte[]> images;
    private readonly FrozenDictionary<int,string> hashes;
    internal SmallMapPngReadback Readback {get;}
    internal SmallMapPngSnapshot(SmallMapPngReadback readback,Dictionary<int,byte[]> owned)
    {Readback=readback;images=owned.ToFrozenDictionary();hashes=owned.ToFrozenDictionary(p=>p.Key,p=>SpritePng.Hash(p.Value));}
    internal string Hash(int model)=>hashes[model];
    internal bool Contains(int model)=>images.ContainsKey(model);
    internal byte[]? Copy(int model)=>images.TryGetValue(model,out var png)?png.ToArray():null;
}
/// <summary>Current map artwork only. No position transform, navigation or packet authority.</summary>
public sealed class SmallMapRenderRequest
{
    private readonly SmallMapPngSnapshot snapshot;private readonly Func<bool> current;
    public int Model {get;}
    public string PngSha256 {get;}
    public string Identity {get;}
    public bool IsCurrent=>current();
    internal SmallMapRenderRequest(SmallMapPngSnapshot snapshot,int model,Func<bool> current)
    {this.snapshot=snapshot;Model=model;this.current=current;PngSha256=snapshot.Hash(model);Identity=snapshot.Readback.SourceFingerprint+":"+snapshot.Readback.BatchFingerprint+":"+model;}
    public bool TryReadPng(out byte[]? png)
    {png=null;if(!IsCurrent)return false;var copy=snapshot.Copy(Model);if(copy is null||!IsCurrent)return false;png=copy;return true;}
}
