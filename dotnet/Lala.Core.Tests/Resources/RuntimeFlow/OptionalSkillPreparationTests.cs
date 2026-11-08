using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class OfflineBundleRuntimePreparationTests
{
    private static Script WithOptionalSkill()
    {
        var source = new Script(new Dictionary<string, byte[]>
        {
            ["all-ten.bundle"] = RuntimeFlowFixtures.Read("all-ten.bundle"),
            ["optional-skill.bundle"] = RuntimeFlowFixtures.Read("optional-skill.bundle")
        });
        source.Data = RuntimeFlowFixtures.Manifest(source.Bundles,
            new Dictionary<string, string> { ["SkillData_C"] = "optional-skill.bundle" }, includeSkill: true);
        return source;
    }

    [Fact]
    public async Task Native_optional_extraction_preserves_valid_synthetic_layout_without_bypassing_review_pin()
    {
        var source = WithOptionalSkill(); var preparation = new BundleSourcePreparation();
        var required = await preparation.PrepareAsync(source);
        var handles = await preparation.PrepareSkillAsync(source, required, null, null,
            new BundleDownloadTotals(required.DownloadCount, required.DownloadBytes), CancellationToken.None);
        byte[] raw = UnityTextAssetExtractor.Extract(BundleSourcePlan.SkillAssetPath, handles);
        Assert.Single(SkillDataParser.ParseLayout(raw));
        Assert.Throws<CatalogDecodeException>(() => SkillDataParser.Parse(raw));
    }

    [Fact]
    public async Task Optional_synthetic_skill_is_acquired_and_extracted_but_unreviewed_digest_stays_unavailable()
    {
        var source = WithOptionalSkill();
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Single(source.Requests, x => x.EndsWith("optional-skill.bundle", StringComparison.Ordinal));
        Assert.Null(result.Candidate.OptionalSkills);
        Assert.Contains("SkillData", result.Candidate.UnavailableOptionalSources);
        Assert.Equal(10, result.InventoryInput.Tables.Length);
        Assert.Equal(10, result.ExtractedTables.Length);
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles.Values.Sum(raw => (long)raw.Length), result.DownloadBytes);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Fact]
    public async Task Optional_download_cannot_reset_required_download_quota()
    {
        var source = WithOptionalSkill();
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source,
            budget: new BundleSourceBudget(1, source.Bundles["all-ten.bundle"].Length));
        Assert.Null(result.Candidate.OptionalSkills);
        Assert.DoesNotContain(source.Requests, x => x.EndsWith("optional-skill.bundle", StringComparison.Ordinal));
        Assert.Equal(10, result.InventoryInput.Tables.Length);
    }

    [Fact]
    public async Task Optional_download_failure_keeps_required_tables_but_source_drift_still_fails()
    {
        var source = WithOptionalSkill();
        source.BeforeOpen = (name, _) => { if (name == "optional-skill.bundle") throw new IOException("Synthetic optional read failure"); };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Null(result.Candidate.OptionalSkills); Assert.Equal(10, result.InventoryInput.Tables.Length);
        source = WithOptionalSkill();
        source.BeforeOpen = (name, _) => { if (name == "optional-skill.bundle") source.Observe = _ => RuntimeFlowFixtures.Snapshot("1.3.22"); };
        await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
    }

    [Fact]
    public async Task Cancellation_during_optional_acquisition_is_not_optional_unavailability()
    {
        var source = WithOptionalSkill(); using var stop = new CancellationTokenSource();
        source.BeforeOpen = (name, _) => { if (name == "optional-skill.bundle") stop.Cancel(); };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source,
            cancellationToken: stop.Token));
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }
    [Fact]
    public async Task Optional_cleanup_failure_is_not_hidden_as_unavailability()
    {
        var source = WithOptionalSkill();
        source.BeforeOpen = (name, _) =>
        {
            if (name == "optional-skill.bundle") throw new ResourceTransportException(ResourceTransportFailure.Cleanup);
        };
        var error = await Assert.ThrowsAsync<ResourceTransportException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(ResourceTransportFailure.Cleanup, error.Failure);
    }

    private sealed class CleanupCache(byte[] raw) : IBundleSourceCacheReader
    {
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken token)
            => ValueTask.FromResult<Stream?>(spec.Name == "optional-skill.bundle" ? new BrokenCleanupStream(raw) : null);
    }
    private sealed class BrokenCleanupStream(byte[] raw) : MemoryStream(raw, false)
    {
        protected override void Dispose(bool disposing)
        { base.Dispose(disposing); throw new IOException("Synthetic cache cleanup failure"); }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Optional_cache_cleanup_failure_preserves_primary_and_never_degrades(bool corrupt)
    {
        var source = WithOptionalSkill();
        var cache = new CleanupCache(corrupt ? new byte[] { 1 } : source.Bundles["optional-skill.bundle"]);
        var error = await Record.ExceptionAsync(() => new OfflineBundleRuntimePreparation().PrepareAsync(source, cache));
        if (corrupt)
        {
            Assert.IsType<BundleSourceException>(error);
            Assert.True(error!.Data.Contains(ResourceCleanup.FailureMarker));
        }
        else Assert.Equal(ResourceTransportFailure.Cleanup, Assert.IsType<ResourceTransportException>(error).Failure);
    }

    [Fact]
    public async Task Optional_primary_transport_failure_with_cleanup_marker_is_not_hidden()
    {
        var source = WithOptionalSkill();
        source.BeforeOpen = (name, _) =>
        {
            if (name != "optional-skill.bundle") return;
            var error = new IOException("Synthetic primary failure");
            error.Data[ResourceCleanup.FailureMarker] = "Cleanup";
            throw error;
        };
        var error = await Assert.ThrowsAsync<IOException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.True(error.Data.Contains(ResourceCleanup.FailureMarker));
    }

}
