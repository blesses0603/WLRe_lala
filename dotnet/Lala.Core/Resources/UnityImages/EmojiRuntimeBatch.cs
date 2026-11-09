namespace Lala.Core.Resources;

// Immutable verified source closure; publication still requires currentness and readback.
// No production factory accepts caller-provided pixels or a claimed source fingerprint.
internal sealed class EmojiRuntimeBatch
{
    internal string SourceFingerprint {get;}
    private readonly Func<CancellationToken,EmojiPixelBatch> rebuild;
    private readonly string expected;
    private EmojiRuntimeBatch(string source,Func<CancellationToken,EmojiPixelBatch> rebuild,CancellationToken token=default)
    {UnityReadCursor.Require(source.Length==64&&source.All(c=>c is >= '0' and <= '9' or >= 'a' and <= 'f'),"Invalid emoji source fingerprint");ArgumentNullException.ThrowIfNull(rebuild);SourceFingerprint=source;this.rebuild=rebuild;expected=rebuild(token).Fingerprint;}
    internal static EmojiRuntimeBatch Create(PreparedEmojiSources sources,CancellationToken token=default)
    {
        ArgumentNullException.ThrowIfNull(sources);token.ThrowIfCancellationRequested();
        return new(sources.Fingerprint,ct=>Build(sources,ct),token);
    }
    private static EmojiPixelBatch Build(PreparedEmojiSources sources,CancellationToken token)
    {
        var mapping=sources.Plan.ValidateCapture(sources.Mapping,sources.Data,sources.Images,token);
        // Manifest closure order is dependencies followed by the exact asset root.
        string root=sources.Plan.Images.AssetSourceNames[EmojiSourcePlan.AtlasPath][^1];
        var source=sources.Images.Single(s=>s.Spec.Name==root);
        UnityReadCursor.Require(source.Spec.Size<=BoundedUnityBundle.MaximumBundleBytes,"Emoji root exceeds archive bound");
        using var stream=source.OpenRead();var bytes=new byte[checked((int)source.Spec.Size)];
        for(int offset=0;offset<bytes.Length;)
        {
            token.ThrowIfCancellationRequested();int count=stream.Read(bytes,offset,Math.Min(65536,bytes.Length-offset));
            UnityReadCursor.Require(count>0,"Truncated emoji root");offset+=count;
        }
        UnityReadCursor.Require(stream.ReadByte()==-1,"Emoji root size changed");
        var budget=new UnityExtractionBudget();var archive=UnityImageArchive.Read(root,bytes,budget,token);
        UnityReadCursor.Require(archive.SourceSha256==source.Sha256,"Emoji root digest changed");
        var owners=archive.SerializedOwners;
        UnityReadCursor.Require(owners.Count==1,"Unreviewed emoji serialized owner set");
        var owner=owners[0];
        var file=BoundedSerializedFile.ReadEmojiAtlasProjection(owner,archive.CopySerialized(owner,token),budget,token,archive);
        var pointer=file.Container.Single().Pointer;
        return EmojiPixelBatch.FromAtlas(mapping,new([file],[]),owner,pointer.PathId,archive,token);
    }
    internal static EmojiRuntimeBatch ForOfflineTests(string source,Func<CancellationToken,EmojiPixelBatch> rebuild)=>new(source,rebuild);
    internal EmojiPixelBatch Rebuild(CancellationToken token)
    {
        var batch=rebuild(token);UnityReadCursor.Require(batch.Fingerprint==expected,"Emoji batch changed since preparation");return batch;
    }
}
