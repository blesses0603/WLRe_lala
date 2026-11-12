using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Lala.Core.Catalogs;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed partial class OfflineBundleRuntimePreparationTests
{
    private static Script EmojiScript(string mode)
    {
        using var fixture=JsonDocument.Parse(typeof(EmojiSourceTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.mapping.json")!);
        var bundles=new Dictionary<string,byte[]>{{"all-ten.bundle",RuntimeFlowFixtures.Read("all-ten.bundle")},{"emoji.bundle",Convert.FromBase64String(fixture.RootElement.GetProperty("bundle").GetString()!)}};
        var source=new Script(bundles);
        source.Data=RuntimeFlowFixtures.Manifest(bundles,new Dictionary<string,string>{{"EmojiData_C","emoji.bundle"}},version:EmojiSourcePlan.DataPackageVersion,includeEmoji:true);
        var main=BundleSourceFixtures.Index("main-valid");main["header"]!["package_version"]=EmojiSourcePlan.MainVersion;
        if(mode!="missing-path")main["assets"]![0]!["path"]=EmojiSourcePlan.AtlasPath;
        source.Main=BundleSourceFixtures.Encode(main);
        source.Observe=_=>OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new{schema_version=1,origin="official_pc_version_endpoint",data_ver=mode=="unknown-version"?"1.3.24":EmojiSourcePlan.DataVersion,exe_version="1.3.0",packages=new{DataPackage=EmojiSourcePlan.DataPackageVersion,MainPackage=EmojiSourcePlan.MainVersion},checked_at_utc="2026-01-02T03:04:05Z",assets_ready=false}));
        return source;
    }
    [Theory][InlineData("unknown-mapping")][InlineData("unknown-version")][InlineData("missing-path")]
    public async Task Production_emoji_scope_does_not_bypass_required_official_table_pins(string mode)
    {
        var source=EmojiScript(mode);
        await Assert.ThrowsAsync<CatalogDecodeException>(()=>new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.DoesNotContain(source.Requests,p=>p.EndsWith("/emoji.bundle",StringComparison.Ordinal));
        Assert.All(source.Streams,s=>Assert.True(s.Disposed));
    }
}
