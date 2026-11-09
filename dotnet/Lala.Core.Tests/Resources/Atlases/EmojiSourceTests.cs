using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class EmojiSourceTests
{
    private static byte[] Bundle(){using var d=JsonDocument.Parse(typeof(EmojiSourceTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.Atlases.mapping.json")!);return Convert.FromBase64String(d.RootElement.GetProperty("bundle").GetString()!);}
    private static JsonObject DataIndex()
    {
        var i=BundleSourceFixtures.Index();i["header"]!["package_version"]=EmojiSourcePlan.DataPackageVersion;
        var b=i["bundles"]![0]!.DeepClone();byte[] raw=Bundle();b["name"]="emoji.bundle";b["file_size"]=(long)raw.Length;b["file_hash"]=Convert.ToHexStringLower(MD5.HashData(raw));b["file_crc"]=ManifestIdentity.Crc32LittleEndian(raw);b["dependency_ids"]=new JsonArray();
        int id=i["bundles"]!.AsArray().Count;i["bundles"]!.AsArray().Add(b);
        var a=i["assets"]![0]!.DeepClone();a["path"]=EmojiSourcePlan.DataPath;a["bundle_id"]=id;i["assets"]!.AsArray().Add(a);return i;
    }
    private static JsonObject MainIndex()
    {
        var i=BundleSourceFixtures.Index("main-valid");i["header"]!["package_version"]=EmojiSourcePlan.MainVersion;i["assets"]![0]!["path"]=EmojiSourcePlan.AtlasPath;
        foreach(var b in i["bundles"]!.AsArray())b!["name"]="image-"+b["name"]!.GetValue<string>();return i;
    }
    private static YooAssetManifest Parse(JsonObject i)=>YooAssetManifest.Parse(BundleSourceFixtures.Encode(i));
    private static EmojiSourcePlan Plan()=>EmojiSourcePlan.Create(Parse(DataIndex()),Parse(MainIndex()),EmojiSourcePlan.DataVersion);
    [Fact]
    public void Exact_paths_complete_dependency_sets_and_manifest_fingerprints_are_retained()
    {
        var p=Plan();Assert.Single(p.Data.Entries);Assert.Equal("emoji.bundle",p.Data.Entries[0].Spec.Name);
        Assert.Equal(3,p.Images.Entries.Count);Assert.Equal(new[]{"image-dep-a.bundle","image-dep-b.bundle","image-root-a.bundle"},p.Images.AssetSourceNames[EmojiSourcePlan.AtlasPath]);
        Assert.DoesNotContain(p.Images.Entries,e=>e.Spec.Name=="image-unrelated.bundle"); // Do not recursively follow a dependency's own set.
        var m=MainIndex();m["header"]!["package_note"]="changed same-version bytes";
        Assert.NotEqual(p.Fingerprint,EmojiSourcePlan.Create(Parse(DataIndex()),Parse(m),EmojiSourcePlan.DataVersion).Fingerprint);
        var d=DataIndex();d["header"]!["package_note"]="changed data bytes";
        Assert.NotEqual(p.Fingerprint,EmojiSourcePlan.Create(Parse(d),Parse(MainIndex()),EmojiSourcePlan.DataVersion).Fingerprint);
    }
    [Theory][InlineData("data-version")][InlineData("main-version")][InlineData("data-path")][InlineData("atlas-path")][InlineData("files")][InlineData("bytes")]
    public void Unsupported_versions_paths_and_source_budgets_fail_before_acquisition(string change)
    {
        var d=DataIndex();var m=MainIndex();
        switch(change)
        {
            case "data-version":d["header"]!["package_version"]="1297_2026_11_04_13_34_19_13";break;
            case "main-version":m["header"]!["package_version"]="1297_2026_11_04_13_36_07_72";break;
            case "data-path":d["assets"]!.AsArray().RemoveAt(d["assets"]!.AsArray().Count-1);break;
            case "atlas-path":m["assets"]![0]!["path"]=EmojiSourcePlan.AtlasPath+".unknown";break;
            case "files":
                while(m["bundles"]!.AsArray().Count<9){var b=m["bundles"]![4]!.DeepClone();b["name"]="extra"+m["bundles"]!.AsArray().Count+".bundle";m["bundles"]!.AsArray().Add(b);}
                m["bundles"]![0]!["dependency_ids"]=new JsonArray(1,2,3,4,5,6,7,8);break;
            case "bytes":m["bundles"]![0]!["file_size"]=32L*1024*1024;break;
        }
        if(change is "data-version" or "main-version")
            Assert.Throws<UnityTextAssetException>(()=>EmojiSourcePlan.Create(Parse(d),Parse(m),EmojiSourcePlan.DataVersion));
        else
        {
            var error=Assert.Throws<BundleSourceException>(()=>EmojiSourcePlan.Create(Parse(d),Parse(m),EmojiSourcePlan.DataVersion));
            Assert.Equal(change is "files" or "bytes"?BundleSourceFailure.Budget:BundleSourceFailure.MissingRequiredAsset,error.Failure);
        }
    }
    [Fact]
    public void Six_source_official_closure_shape_fits_Python_budget_without_expanding_decode_scope()
    {
        var m=MainIndex();var list=m["bundles"]!.AsArray();var extra=list[4]!.DeepClone();extra["name"]="sixth.bundle";list.Add(extra);
        long[] sizes=[241598,787748,686253,616676,493351,23715415];
        for(int i=0;i<6;i++){list[i]!["file_size"]=sizes[i];list[i]!["dependency_ids"]=new JsonArray();}
        list[5]!["dependency_ids"]=new JsonArray(0,1,2,3,4);m["assets"]![0]!["bundle_id"]=5;
        var plan=EmojiSourcePlan.Create(Parse(DataIndex()),Parse(m),EmojiSourcePlan.DataVersion);
        Assert.Equal(6,plan.Images.Entries.Count);Assert.Equal(26541041,plan.Images.Entries.Sum(e=>e.Spec.Size));
        // Owned metadata with observed counts/sizes is not official Bundle bytes.
        Assert.Throws<UnityTextAssetException>(()=>PreparedEmojiSources.Capture(plan,EmojiMapping.ParseLayoutForOfflineTests(EmojiMappingTests.Owned()),[],[]));
    }
    [Fact]
    public void Offline_mapping_cannot_mint_prepared_sources_and_cancellation_is_preserved()
    {
        var p=Plan();var m=EmojiMapping.ParseLayoutForOfflineTests(EmojiMappingTests.Owned());
        Assert.Throws<UnityTextAssetException>(()=>PreparedEmojiSources.Capture(p,m,[],[]));
        Assert.Throws<UnityTextAssetException>(()=>EmojiSourcePlan.Create(Parse(DataIndex()),Parse(MainIndex()),"1.3.24"));
        Assert.Throws<OperationCanceledException>(()=>EmojiSourcePlan.Create(Parse(DataIndex()),Parse(MainIndex()),EmojiSourcePlan.DataVersion,new(true)));
    }
    private sealed class Source:IResourceSource
    {
        internal readonly byte[] Data=BundleSourceFixtures.Encode(DataIndex()),Main=BundleSourceFixtures.Encode(MainIndex());
        internal readonly List<string> Requests=[];
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken t)=>ValueTask.FromResult(OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new{schema_version=1,origin="official_pc_version_endpoint",data_ver=EmojiSourcePlan.DataVersion,exe_version="1.3.0",packages=new{DataPackage=EmojiSourcePlan.DataPackageVersion,MainPackage=EmojiSourcePlan.MainVersion},checked_at_utc="2026-01-02T03:04:05Z",assets_ready=false})));
        public ValueTask<ResourceResponse> OpenAsync(string url,CancellationToken t)
        {
            t.ThrowIfCancellationRequested();string name=url[(url.LastIndexOf('/')+1)..];Requests.Add(name);
            byte[] raw=name switch{"DataPackage.bytes"=>Data,"MainPackage.bytes"=>Main,"DataPackage.hash"=>Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),"MainPackage.hash"=>Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),"emoji.bundle"=>Bundle(),_=>BundleSourceFixtures.Payload(name.StartsWith("image-",StringComparison.Ordinal)?name[6..]:name)};
            return ValueTask.FromResult(new ResourceResponse(url,200,raw.Length.ToString(System.Globalization.CultureInfo.InvariantCulture),new MemoryStream(raw,false)));
        }
    }
    [Fact]
    public async Task Unknown_raw_pin_blocks_atlas_download_after_real_TextAsset_extraction()
    {
        var s=new Source();var prep=new BundleSourcePreparation();var required=await prep.PrepareAsync(s);var totals=new BundleDownloadTotals(required.DownloadCount,required.DownloadBytes);
        var error=await Assert.ThrowsAsync<UnityTextAssetException>(()=>prep.PrepareEmojiSourcesAsync(s,required,null,null,totals));
        Assert.Contains("fingerprint",error.Message);Assert.Equal(1,s.Requests.Count(n=>n=="emoji.bundle"));Assert.DoesNotContain(s.Requests,n=>n.StartsWith("image-",StringComparison.Ordinal));
        Assert.Equal(required.DownloadCount+1,totals.Count);Assert.Equal(required.DownloadBytes+Bundle().Length,totals.Bytes);
        int count=s.Requests.Count;await Assert.ThrowsAsync<UnityTextAssetException>(()=>prep.PrepareEmojiSourcesAsync(s,required,null,null,totals));Assert.Equal(count,s.Requests.Count);
    }
    [Fact]
    public async Task Shared_quota_cancellation_and_retirement_prevent_optional_requests()
    {
        var s=new Source();var prep=new BundleSourcePreparation();var required=await prep.PrepareAsync(s);int count=s.Requests.Count;
        var error=await Assert.ThrowsAsync<BundleSourceException>(()=>prep.PrepareEmojiSourcesAsync(s,required,null,new(required.DownloadCount),new(required.DownloadCount,required.DownloadBytes)));
        Assert.Equal(BundleSourceFailure.Budget,error.Failure);Assert.Equal(count,s.Requests.Count);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>prep.PrepareEmojiSourcesAsync(s,required,null,null,new(0,0),new(true)));
        prep.Invalidate();error=await Assert.ThrowsAsync<BundleSourceException>(()=>prep.PrepareEmojiSourcesAsync(s,required,null,null,new(0,0)));Assert.Equal(BundleSourceFailure.StaleAttempt,error.Failure);Assert.Equal(count,s.Requests.Count);
    }
}
