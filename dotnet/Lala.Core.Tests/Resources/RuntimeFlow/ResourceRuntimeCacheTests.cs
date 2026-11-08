using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static string SeedBundleCache(Fixture fixture, Source source, byte[] bytes)
    {
        var manifest = YooAssetManifest.Parse(source.Data);
        var spec = BundleSourcePlan.Create(manifest, RuntimeFlowFixtures.Snapshot().DataVersion).Entries.Single().Spec;
        string path = Path.Combine(fixture.Root, "official_sync", "bundles", spec.Package,
            spec.PackageVersion, spec.Md5, spec.Name);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
        return path;
    }

    [Fact]
    public async Task Existing_verified_cache_bootstraps_and_refreshes_without_bundle_downloads()
    {
        using var fixture = new Fixture(); var source = new Source();
        string path = SeedBundleCache(fixture, source, source.Bundle);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        int observations = source.Observations;
        Assert.NotNull(await owner.RefreshAsync());
        Assert.True(source.Observations > observations);
        Assert.Equal(0, source.BundleRequests);
        Assert.Equal(source.Bundle, File.ReadAllBytes(path));
        Assert.False(owner.Current!.ResourceAdmitted);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Missing_or_corrupt_cache_downloads_without_creating_or_repairing_cache(bool corrupt)
    {
        using var fixture = new Fixture(); var source = new Source();
        string? path = corrupt ? SeedBundleCache(fixture, source, new byte[] { 1, 2, 3 }) : null;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(1, source.BundleRequests);
        if (path is not null) Assert.Equal(new byte[] { 1, 2, 3 }, File.ReadAllBytes(path));
        else Assert.False(Directory.Exists(Path.Combine(fixture.Root, "official_sync", "bundles")));
    }

    [Fact]
    public async Task Cache_disappearing_after_planning_fails_before_storage_without_download_fallback()
    {
        using var fixture = new Fixture(); var source = new Source();
        string path = SeedBundleCache(fixture, source, source.Bundle);
        source.BeforeObserve = count => { if (count == 2) File.Delete(path); return Task.CompletedTask; };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.IsType<BundleSourceException>(result.Failure);
        Assert.False(result.StorageAttempted); Assert.False(result.WasPublished);
        Assert.Equal(0, source.BundleRequests); Assert.False(File.Exists(fixture.Inventory));
    }
}
