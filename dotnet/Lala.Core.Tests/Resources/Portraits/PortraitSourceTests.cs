using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;
namespace Lala.Core.Tests.Resources;

public sealed class PortraitSourceTests
{
    private static readonly (string Name, int Size)[] Bundles = [("mainpackage_material.bundle",1903222), ("mainpackage_texture_a.bundle",21442774), ("mainpackage_unityshaders.bundle",1226061)];
    private static JsonObject Index()
    {
        var index = BundleSourceFixtures.Index("main-valid");
        index["header"]!["package_version"] = PortraitSourcePlan.MainVersion;
        var originalAsset = index["assets"]![0]!.DeepClone(); var originalBundle = index["bundles"]![0]!.DeepClone();
        var assets = new JsonArray();
        for (int i = 1; i <= 778; i++)
        {
            bool player = i <= 15; string id = (player ? i : i-15).ToString("D4");
            var asset = originalAsset.DeepClone(); asset["bundle_id"] = 0;
            asset["path"] = $"Assets/ResourcesBuild/Other/{(player ? "Avatar2DMaterial" : "Avatar2DNPCMaterial")}/{id}/{(player ? "PhotoAvatar_" : "PhotoAvatarNPC_")}{id}.mat";
            assets.Add(asset);
        }
        var bundles = new JsonArray();
        foreach (var (name,size) in Bundles.Append(("unrelated.bundle",8)))
        {
            byte[] raw = new byte[size]; var bundle = originalBundle.DeepClone();
            bundle["name"] = name; bundle["file_size"] = (long)size;
            bundle["file_hash"] = Convert.ToHexStringLower(MD5.HashData(raw)); bundle["file_crc"] = ManifestIdentity.Crc32LittleEndian(raw);
            bundle["dependency_ids"] = new JsonArray(); bundles.Add(bundle);
        }
        bundles[0]!["dependency_ids"] = new JsonArray(1,2,3);
        index["assets"] = assets; index["bundles"] = bundles; return index;
    }
    private static YooAssetManifest Parse(JsonObject index) => YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));
    [Fact]
    public void Exact_source_projection_preserves_paths_sizes_and_separate_dependency_scope()
    {
        var index = Index(); var plan = PortraitSourcePlan.Create(Parse(index), "1.3.23");
        Assert.Equal(778, plan.Materials.Count); Assert.Equal(15, plan.Materials.Keys.Count(k => k.Kind == "player"));
        Assert.Equal(24572057, plan.Specs.Sum(s => s.Size)); Assert.Equal(3, plan.Specs.Count);
        Assert.DoesNotContain(plan.Specs, s => s.Name == "unrelated.bundle");
        Assert.EndsWith("/0001/PhotoAvatar_0001.mat", plan.Materials[new("player","0001")]);
        string old = plan.Fingerprint;
        index["header"]!["package_note"] = "owned manifest change";
        Assert.NotEqual(old, PortraitSourcePlan.Create(Parse(index), "1.3.23").Fingerprint);
        Assert.Equal(old, plan.Fingerprint);
    }
    [Theory, InlineData("version"), InlineData("size"), InlineData("missing"), InlineData("incomplete"), InlineData("directory"), InlineData("wrong-root"), InlineData("extra-player"), InlineData("unicode")]
    public void Unknown_sources_and_material_shapes_fail_closed(string mutation)
    {
        var index = Index();
        switch (mutation)
        {
            case "version": index["header"]!["package_version"] = "1297_2026_11_04_13_36_07_72"; break;
            case "size": index["bundles"]![1]!["file_size"] = 21442775L; break;
            case "missing": index["bundles"]![1]!["name"] = "unknown.bundle"; break;
            case "incomplete": index["assets"]!.AsArray().RemoveAt(0); break;
            case "directory": index["assets"]![0]!["path"] = "Assets/ResourcesBuild/Other/Avatar2DMaterial/0002/PhotoAvatar_0001.mat"; break;
            case "wrong-root": index["assets"]![0]!["bundle_id"] = 1; break;
            case "extra-player": index["assets"]![0]!["path"] = "Assets/ResourcesBuild/Other/Avatar2DMaterial/0016/PhotoAvatar_0016.mat"; break;
            case "unicode": index["assets"]![0]!["path"] = "Assets/ResourcesBuild/Other/Avatar2DMaterial/０００１/PhotoAvatar_０００１.mat"; break;
        }
        Assert.Throws<SpritePixelException>(() => PortraitSourcePlan.Create(Parse(index), "1.3.23"));
    }
    [Fact]
    public void Manifest_consistent_owned_bytes_still_fail_official_sha_pins()
    {
        var plan = PortraitSourcePlan.Create(Parse(Index()), "1.3.23");
        var sources = plan.Specs.Select(s => VerifiedBundleSource.Verify(s, new byte[(int)s.Size], BundleAcquisition.Cache)).ToArray();
        Assert.Throws<SpritePixelException>(() => plan.Verify(sources));
        Assert.Throws<SpritePixelException>(() => PortraitSourcePlan.VerifiedPortraitSources.Capture(plan,sources,default));
        Assert.Throws<SpritePixelException>(() => plan.Verify([]));
        Assert.Throws<SpritePixelException>(() => plan.Verify([sources[0],sources[0],sources[1]]));
        Assert.ThrowsAny<OperationCanceledException>(() => plan.Verify(sources, new(true)));
    }
    [Fact]
    public void Data_version_and_cancelled_plans_do_not_create_candidates()
    {
        var manifest=Parse(Index());
        Assert.Throws<SpritePixelException>(() => PortraitSourcePlan.Create(manifest,"1.3.24"));
        Assert.ThrowsAny<OperationCanceledException>(() => PortraitSourcePlan.Create(manifest,"1.3.23",new(true)));
    }
    private sealed class Source : IResourceSource
    {
        internal readonly byte[] Main = BundleSourceFixtures.Encode(Index());
        internal readonly byte[] Data = BundleSourceFixtures.Bytes("data-valid");
        internal readonly List<string> Requests = [];
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token) => ValueTask.FromResult(OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema_version=1, origin="official_pc_version_endpoint", data_ver="1.3.23", exe_version="1.3.0",
            packages=new { DataPackage=BundleSourceFixtures.Case("data-valid").Text("package_version"), MainPackage=PortraitSourcePlan.MainVersion },
            checked_at_utc="2026-01-02T03:04:05Z", assets_ready=false
        })));
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); string name = url[(url.LastIndexOf('/')+1)..]; Requests.Add(name);
            byte[] raw = name switch
            {
                "DataPackage.bytes" => Data, "MainPackage.bytes" => Main,
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                _ => Bundles.Any(b => b.Name==name) ? new byte[Bundles.Single(b => b.Name==name).Size] : BundleSourceFixtures.Payload(name)
            };
            return ValueTask.FromResult(new ResourceResponse(url,200,raw.Length.ToString(System.Globalization.CultureInfo.InvariantCulture),new MemoryStream(raw,false)));
        }
    }
    [Fact]
    public async Task Acquisition_uses_only_three_exact_sources_and_rejects_synthetic_fingerprints()
    {
        var source = new Source(); var preparation = new BundleSourcePreparation(); var required = await preparation.PrepareAsync(source);
        var totals = new BundleDownloadTotals(required.DownloadCount,required.DownloadBytes);
        await Assert.ThrowsAsync<SpritePixelException>(() => preparation.PreparePortraitSourcesAsync(source,required,null,null,totals));
        Assert.All(Bundles, b => Assert.Equal(1,source.Requests.Count(n => n==b.Name)));
        Assert.DoesNotContain("unrelated.bundle",source.Requests);
        Assert.Equal(required.DownloadCount+3,totals.Count);
        Assert.Equal(required.DownloadBytes+24572057,totals.Bytes);
        int requests=source.Requests.Count;
        await Assert.ThrowsAsync<SpritePixelException>(() => preparation.PreparePortraitSourcesAsync(source,required,null,null,totals));
        Assert.Equal(requests,source.Requests.Count); // No new acquisition on identical owned bytes; still rejects SHA pins.
    }
    [Fact]
    public async Task Shared_budget_stale_attempt_and_cancellation_block_before_download()
    {
        var source=new Source(); var preparation=new BundleSourcePreparation(); var required=await preparation.PrepareAsync(source);
        int requests=source.Requests.Count;
        var error=await Assert.ThrowsAsync<BundleSourceException>(() => preparation.PreparePortraitSourcesAsync(source,required,null,new(required.DownloadCount),new(required.DownloadCount,required.DownloadBytes)));
        Assert.Equal(BundleSourceFailure.Budget,error.Failure); Assert.Equal(requests,source.Requests.Count);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => preparation.PreparePortraitSourcesAsync(source,required,null,null,new(0,0),new(true)));
        preparation.Invalidate();
        error=await Assert.ThrowsAsync<BundleSourceException>(() => preparation.PreparePortraitSourcesAsync(source,required,null,null,new(0,0)));
        Assert.Equal(BundleSourceFailure.StaleAttempt,error.Failure); Assert.Equal(requests,source.Requests.Count);
    }
}
