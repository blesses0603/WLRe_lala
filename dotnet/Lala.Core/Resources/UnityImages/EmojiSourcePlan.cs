using System.Text.Json;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// Fixed reviewed version and exact manifests. Checksums are source observations;
// preparation is not official admission, current publication or permission to send.
internal sealed class EmojiSourcePlan
{
    internal const string DataVersion="1.3.23",DataPackageVersion="1296_2026_11_04_13_34_19_13",MainVersion="1296_2026_11_04_13_36_07_72";
    internal const string DataPath="Assets/ResourcesBuild/Data/EmojiData_C.bytes";
    internal const string AtlasPath="Assets/ResourcesBuild/Sprite/Atlas/SpriteAtlas_Emoji/SpriteAtlas_Emoji.spriteatlasv2";
    internal BundleSourcePlan Data {get;}
    internal BundleSourcePlan Images {get;}
    internal string Fingerprint {get;}
    private EmojiSourcePlan(YooAssetManifest data,YooAssetManifest main,BundleSourcePlan dp,BundleSourcePlan mp)
    {
        Data=dp;Images=mp;
        Fingerprint=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new{DataVersion,DataPackageVersion,MainVersion,DataManifest=data.Sha256,MainManifest=main.Sha256,
            DataSources=dp.Entries.Select(e=>new{e.Spec.DataVersion,e.Spec.Package,e.Spec.PackageVersion,e.Spec.Name,e.Spec.Size,e.Spec.Md5,e.Spec.Crc32Le}),ImageSources=mp.Entries.Select(e=>new{e.Spec.DataVersion,e.Spec.Package,e.Spec.PackageVersion,e.Spec.Name,e.Spec.Size,e.Spec.Md5,e.Spec.Crc32Le}),
            DataClosure=dp.AssetSourceNames[DataPath],ImageClosure=mp.AssetSourceNames[AtlasPath]}));
    }
    internal static EmojiSourcePlan Create(YooAssetManifest data,YooAssetManifest main,string version,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(version==DataVersion&&data.Header.PackageName=="DataPackage"&&data.Header.PackageVersion==DataPackageVersion&&main.Header.PackageName=="MainPackage"&&main.Header.PackageVersion==MainVersion,"Emoji source version is not reviewed");
        var dp=BundleSourcePlan.CreateEmojiData(data,version,token);var mp=BundleSourcePlan.CreateEmojiAtlas(main,version,token);
        Require(dp.Entries.Count is >0 and <=24&&dp.Entries.Sum(e=>e.Spec.Size)<=32L*1024*1024,"Emoji data source quota exceeded");
        return new(data,main,dp,mp);
    }
    internal EmojiMapping ValidateCapture(EmojiMapping mapping,IReadOnlyList<VerifiedBundleSource> data,IReadOnlyList<VerifiedBundleSource> images,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(mapping.Reviewed&&mapping.SourceSha256==EmojiMapping.KnownSha256,"Unreviewed EmojiData mapping cannot prepare sources");
        var d=data.ToArray();var m=images.ToArray();
        static void Validate(BundleSourcePlan plan,VerifiedBundleSource[] sources,CancellationToken token)
        {
            Require(sources.Length==plan.Entries.Count&&sources.Select(s=>s.Spec.Name).Distinct(StringComparer.Ordinal).Count()==sources.Length,"Emoji source set mismatch");
            foreach(var entry in plan.Entries){token.ThrowIfCancellationRequested();Require(sources.SingleOrDefault(s=>s.Spec.Name==entry.Spec.Name)?.Spec==entry.Spec,"Emoji source differs from exact manifest");}
        }
        Validate(Data,d,token);Validate(Images,m,token);
        // Independently derive the mapping from the captured source bytes, not a caller's claim.
        var raw=UnityTextAssetExtractor.Extract(DataPath,Data.AssetSourceNames[DataPath].Select(n=>d.Single(s=>s.Spec.Name==n)).ToArray(),cancellationToken:token);
        var rebuilt=EmojiMapping.Create(raw,token);Require(rebuilt.Rows.SequenceEqual(mapping.Rows),"Emoji mapping differs from captured sources");
        return rebuilt;
    }
}
internal sealed class PreparedEmojiSources
{
    internal EmojiSourcePlan Plan {get;}
    internal EmojiMapping Mapping {get;}
    internal IReadOnlyList<VerifiedBundleSource> Data {get;}
    internal IReadOnlyList<VerifiedBundleSource> Images {get;}
    internal string Fingerprint {get;}
    internal static PreparedEmojiSources Capture(EmojiSourcePlan plan,EmojiMapping mapping,IReadOnlyList<VerifiedBundleSource> data,IReadOnlyList<VerifiedBundleSource> images,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();
        Require(mapping.Reviewed&&mapping.SourceSha256==EmojiMapping.KnownSha256,"Unreviewed EmojiData mapping cannot prepare sources");
        Require(data.Count==plan.Data.Entries.Count&&images.Count==plan.Images.Entries.Count,"Emoji source set mismatch");
        var d=data.ToArray();var m=images.ToArray();var rebuilt=plan.ValidateCapture(mapping,d,m,token);
        token.ThrowIfCancellationRequested();return new(plan,rebuilt,d,m);
    }
    private PreparedEmojiSources(EmojiSourcePlan plan,EmojiMapping mapping,VerifiedBundleSource[] data,VerifiedBundleSource[] images)
    {
        Plan=plan;Mapping=mapping;Data=Array.AsReadOnly(data.ToArray());Images=Array.AsReadOnly(images.ToArray());
        Fingerprint=SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new{plan.Fingerprint,mapping.SourceSha256,Sources=data.Concat(images).OrderBy(s=>s.Spec.Package,StringComparer.Ordinal).ThenBy(s=>s.Spec.Name,StringComparer.Ordinal).Select(s=>new{s.Spec.Package,s.Spec.Name,s.Sha256})}));
    }
}
