using System.Text;
using System.Text.Json;
using Lala.Core.Resources;
using Lala.Core.Catalogs;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Small_map_stage_cannot_bypass_required_official_table_pins()
    {
        using var fixture=new Fixture();var map=SmallMapReceiptTests.Fixture();var source=new Source{Main=map.ManifestBytes};
        source.Data=RuntimeFlowFixtures.Manifest(new Dictionary<string,byte[]>{{"all-ten.bundle",source.Bundle}},version:EmojiSourcePlan.DataPackageVersion);
        source.AdditionalBundles["owned.bundle"]=map.Bytes;
        source.Snapshot=_=>OfficialVersionSnapshot.Parse(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new{
            schema_version=1,origin="official_pc_version_endpoint",data_ver=EmojiSourcePlan.DataVersion,exe_version="1.3.0",
            packages=new{DataPackage=EmojiSourcePlan.DataPackageVersion,MainPackage=EmojiSourcePlan.MainVersion},checked_at_utc="2026-01-02T03:04:05Z",assets_ready=false})));
        await using var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,source);
        var result=await owner.BootstrapAndRefreshAsync();
        var failure=Assert.IsType<CatalogDecodeException>(result.Failure);
        Assert.Contains("source digest mismatch",failure.Message);
        Assert.False(result.WasPublished);Assert.Null(owner.Current);Assert.Null(result.SmallMapDownloadCount);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted,result.SmallMapStorageOutcome);
        Assert.Equal(1,source.BundleRequests); // Required table only; no small-map request.
        Assert.False(File.Exists(Path.Combine(fixture.Root,"official_sync","derived_catalogs","core_smallmaps_v1.sqlite3")));
    }
}
