using System.Collections.Frozen;
using System.Globalization;
using static Lala.Core.Resources.UnityReadCursor;
namespace Lala.Core.Resources;

// Source preflight only. No pixels, scene geometry, publication or navigation authority.
internal static class SmallMapSourcePlan
{
    internal const string Prefix="Assets/ResourcesBuild/Texture/SmallMap2D/";
    internal static IReadOnlyDictionary<int,string> Paths(YooAssetManifest manifest,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(manifest.Header.PackageName=="MainPackage","Small maps require MainPackage");
        var paths=new Dictionary<int,string>();
        foreach(var asset in manifest.Assets)
        {
            token.ThrowIfCancellationRequested();if(!asset.Path.StartsWith(Prefix,StringComparison.Ordinal))continue;
            var name=asset.Path[Prefix.Length..];
            Require(name.StartsWith("SmallMap2D_",StringComparison.Ordinal)&&name.EndsWith(".png",StringComparison.Ordinal),"Invalid small map path");
            int length=name.Length-15;Require(length is >=1 and <=5,"Invalid small map model length");
            var digits=name.AsSpan(11,length);
            foreach(char c in digits)Require(c is >= '0' and <= '9',"Invalid small map model");
            int model=int.Parse(digits,NumberStyles.None,CultureInfo.InvariantCulture);
            Require(model is >0 and <=65535&&paths.TryAdd(model,asset.Path),"Invalid or duplicate small map model");
            Require(paths.Count<=2048,"Small map count exceeds bound");
        }
        Require(paths.Count>0,"Missing small map assets");return paths.ToFrozenDictionary();
    }
    internal static BundleSourcePlan CreateStaged(YooAssetManifest manifest,string version,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(version==EmojiSourcePlan.DataVersion&&manifest.Header.PackageVersion==EmojiSourcePlan.MainVersion,"Unreviewed staged small map source version");
        return BundleSourcePlan.CreateStagedSmallMaps(manifest,version,Paths(manifest,token).Values.ToArray(),token);
    }
    internal static BundleSourcePlan Create(YooAssetManifest manifest,string version,CancellationToken token=default)
    {
        token.ThrowIfCancellationRequested();Require(version==EmojiSourcePlan.DataVersion&&manifest.Header.PackageVersion==EmojiSourcePlan.MainVersion,"Unreviewed small map source version");
        return BundleSourcePlan.CreateSmallMaps(manifest,version,Paths(manifest,token).Values.ToArray(),token);
    }
}
