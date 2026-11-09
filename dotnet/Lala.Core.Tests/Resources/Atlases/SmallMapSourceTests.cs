using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SmallMapSourceTests
{
    private static JsonObject Index(params string[] names)
    {
        var index=BundleSourceFixtures.Index("main-valid");index["header"]!["package_version"]=EmojiSourcePlan.MainVersion;
        var sample=index["assets"]![0]!.DeepClone();var assets=new JsonArray();
        foreach(var name in names){var a=sample.DeepClone();a["path"]=SmallMapSourcePlan.Prefix+name;assets.Add(a);}
        index["assets"]=assets;return index;
    }
    private static YooAssetManifest Parse(JsonObject index)=>YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));
    [Fact]
    public void Exact_models_preserve_manifest_closure_without_pixel_or_navigation_claims()
    {
        var m=Parse(Index("SmallMap2D_10001.png","SmallMap2D_60015.png"));var paths=SmallMapSourcePlan.Paths(m);
        Assert.Equal(new[]{10001,60015},paths.Keys.Order());
        var plan=SmallMapSourcePlan.Create(m,EmojiSourcePlan.DataVersion);Assert.Equal(3,plan.Entries.Count);
        Assert.Equal(new[]{"dep-a.bundle","dep-b.bundle","root-a.bundle"},plan.AssetSourceNames[paths[10001]]);
        Assert.Throws<OperationCanceledException>(()=>SmallMapSourcePlan.Paths(m,new(true)));
        Assert.Throws<UnityTextAssetException>(()=>SmallMapSourcePlan.Create(m,"1.3.24"));
    }
    [Theory][InlineData("SmallMap2D_0.png")][InlineData("SmallMap2D_65536.png")][InlineData("SmallMap2D_1.PNG")][InlineData("SmallMap2D_x.png")][InlineData("../SmallMap2D_1.png")][InlineData("SmallMap2D_.png")]
    public void Unreviewed_names_fail(string name)=>Assert.Throws<UnityTextAssetException>(()=>SmallMapSourcePlan.Paths(Parse(Index(name))));
    [Fact]
    public void Aliases_missing_assets_and_observed_official_size_remain_blocked()
    {
        Assert.Throws<UnityTextAssetException>(()=>SmallMapSourcePlan.Paths(Parse(Index("SmallMap2D_1.png","SmallMap2D_01.png"))));
        Assert.Throws<UnityTextAssetException>(()=>SmallMapSourcePlan.Paths(Parse(Index())));
        var index=Index("SmallMap2D_10001.png");index["bundles"]![0]!["file_size"]=43187027L;
        Assert.Equal(BundleSourceFailure.Budget,Assert.Throws<BundleSourceException>(()=>SmallMapSourcePlan.Create(Parse(index),EmojiSourcePlan.DataVersion)).Failure);
    }
}
