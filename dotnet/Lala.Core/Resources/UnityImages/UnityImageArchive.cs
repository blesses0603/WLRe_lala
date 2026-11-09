using System.Collections.Frozen;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// Owns one bounded decompression, never opens a path or searches other bundles.
// This is a byte observation, not official admission or a current publication.
internal sealed class UnityImageArchive
{
    private readonly FrozenDictionary<string, BoundedUnityBundle.Entry> entries;
    internal string BundleName { get; }
    internal string SourceSha256 { get; }
    private UnityImageArchive(string name, string hash, List<BoundedUnityBundle.Entry> values)
    { BundleName=name; SourceSha256=hash; entries=values.ToFrozenDictionary(e=>e.Name,StringComparer.Ordinal); }
    internal static UnityImageArchive Read(string bundleName, ReadOnlyMemory<byte> input, UnityExtractionBudget budget, CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require(bundleName.Length is >0 and <=255 && bundleName.All(c=>char.IsAsciiLetterOrDigit(c)||c is '-' or '_' or '.'),"Invalid image bundle identity");
        Require(input.Length is >0 and <=BoundedUnityBundle.MaximumBundleBytes,"Image bundle input exceeds bound");
        var snapshot=input.ToArray();
        var values=BoundedUnityBundle.ReadImageArchive(snapshot,budget,token);
        var result=new UnityImageArchive(bundleName,SpritePng.Hash(snapshot),values);
        token.ThrowIfCancellationRequested();return result;
    }
    internal byte[] CopySerialized(UnityFileIdentity owner, CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require(owner.BundleName==BundleName && entries.TryGetValue(owner.EntryName,out var entry) && !entry.IsResource,"Serialized owner outside exact bundle");
        var bytes=entries[owner.EntryName].Bytes;
        Require(bytes.Length<=16*1024*1024,"Serialized image file exceeds bound");
        var copy=bytes.ToArray();token.ThrowIfCancellationRequested();return copy;
    }
    internal byte[] CopyResource(UnityFileIdentity owner, string archivePath, long offset, uint size, CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require(owner.BundleName==BundleName && entries.TryGetValue(owner.EntryName,out var file) && !file.IsResource,"Resource owner outside exact bundle");
        string resource=owner.EntryName+".resS";
        Require(archivePath=="archive:/"+owner.EntryName+"/"+resource && entries.TryGetValue(resource,out var entry) && entry.IsResource,"Resource path is not the exact paired archive identity");
        var bytes=entries[resource].Bytes;
        Require(offset>=0 && size is >0 and <=16*1024*1024 && offset<=bytes.Length && size<=bytes.Length-offset,"Image resource slice exceeds bound");
        var owned=bytes.Slice((int)offset,(int)size).ToArray();token.ThrowIfCancellationRequested();return owned;
    }
}
