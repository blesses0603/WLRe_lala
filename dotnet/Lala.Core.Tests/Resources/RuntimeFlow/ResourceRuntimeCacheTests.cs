using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static string BundleCachePath(Fixture fixture, BundleSourceSpec spec)
        => Path.Combine(fixture.Root, "official_sync", "bundles", spec.Package,
            spec.PackageVersion, spec.Md5, spec.Name);

    private static string RequiredBundleCachePath(Fixture fixture, Source source)
    {
        var manifest = YooAssetManifest.Parse(source.Data);
        var spec = BundleSourcePlan.Create(manifest, RuntimeFlowFixtures.Snapshot().DataVersion).Entries.Single().Spec;
        return BundleCachePath(fixture, spec);
    }

    private static string SeedBundleCache(Fixture fixture, Source source, byte[] bytes)
    {
        string path = RequiredBundleCachePath(fixture, source);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
        return path;
    }

    [Fact]
    public async Task Existing_verified_cache_bootstraps_and_refreshes_without_bundle_downloads()
    {
        using var fixture = new Fixture(); var source = new Source();
        string path = SeedBundleCache(fixture, source, source.Bundle);
        File.SetLastWriteTimeUtc(path, new DateTime(2001, 1, 1, 0, 0, 0, DateTimeKind.Utc));
        var writtenAt = File.GetLastWriteTimeUtc(path);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        int observations = source.Observations;
        Assert.NotNull(await owner.RefreshAsync());
        Assert.True(source.Observations > observations);
        Assert.Equal(0, source.BundleRequests);
        Assert.Equal(source.Bundle, File.ReadAllBytes(path));
        Assert.Equal(writtenAt, File.GetLastWriteTimeUtc(path));
        Assert.False(owner.Current!.ResourceAdmitted);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Bootstrap_populates_or_repairs_verified_cache_and_refresh_downloads_no_bundles(bool corrupt)
    {
        using var fixture = new Fixture(); var source = new Source();
        string path = RequiredBundleCachePath(fixture, source);
        if (corrupt) SeedBundleCache(fixture, source, new byte[] { 1, 2, 3 });
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(1, source.BundleRequests);
        Assert.Equal(source.Bundle, File.ReadAllBytes(path));
        int observations = source.Observations;
        byte[] database = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Equal(1, source.BundleRequests); Assert.True(source.Observations > observations);
        Assert.Equal(database, fixture.Bytes()); Assert.False(refreshed.ResourceAdmitted);
        Assert.Equal(source.Bundle, File.ReadAllBytes(path));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Read_only_refresh_missing_or_corrupt_cache_downloads_without_cache_writes(bool corrupt)
    {
        using var fixture = new Fixture(); var source = new Source(); int cacheWrites = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeCacheWrite = () => { cacheWrites++; return Task.CompletedTask; } });
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        string path = RequiredBundleCachePath(fixture, source);
        if (corrupt) File.WriteAllBytes(path, [1, 2, 3]);
        else Directory.Delete(Path.Combine(fixture.Root, "official_sync", "bundles"), true);
        byte[] database = fixture.Bytes();
        var result = await owner.RefreshWithResultAsync();
        Assert.Null(result.Failure); Assert.True(result.WasPublished); Assert.False(result.StorageAttempted);
        Assert.Equal(2, source.BundleRequests); Assert.Equal(1, cacheWrites);
        Assert.Equal(database, fixture.Bytes());
        if (corrupt) Assert.Equal(new byte[] { 1, 2, 3 }, File.ReadAllBytes(path));
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

    [Fact]
    public async Task Cache_write_failure_preserves_committed_database_receipt_but_never_publishes()
    {
        using var fixture = new Fixture(); var source = new Source();
        string path = RequiredBundleCachePath(fixture, source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            BeforeCacheWrite = () =>
            {
                Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
                Directory.CreateDirectory(path); // Occupy the destination with a directory only after readback.
                return Task.CompletedTask;
            }
        });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.True(result.StorageAttempted); Assert.True(result.CommitAdmitted);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.NotNull(result.Receipt);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback); Assert.False(result.SourcesRechecked);
        Assert.NotNull(result.Failure); Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Empty(Directory.GetFiles(Path.Combine(fixture.Root, "official_sync", "bundles"), "*", SearchOption.AllDirectories));
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public async Task Cache_boundary_cancellation_or_invalidation_retains_storage_without_publication(bool invalidate, bool afterWrite)
    {
        using var fixture = new Fixture(); var source = new Source(); using var cancellation = new CancellationTokenSource();
        ResourceRuntimeOwner? owner = null;
        Task Stop()
        {
            if (invalidate) owner!.Invalidate(); else cancellation.Cancel();
            return Task.CompletedTask;
        }
        owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeCacheWrite = afterWrite ? null : Stop, AfterCacheWrite = afterWrite ? Stop : null });
        await using var lifetime = owner;
        var result = await owner.BootstrapAndRefreshAsync(cancellation.Token);
        Assert.True(result.StorageAttempted); Assert.True(result.CommitAdmitted); Assert.NotNull(result.Receipt);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback); Assert.False(result.SourcesRechecked);
        Assert.IsAssignableFrom<OperationCanceledException>(result.Failure);
        Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(afterWrite, File.Exists(RequiredBundleCachePath(fixture, source)));
        if (afterWrite) Assert.Equal(source.Bundle, File.ReadAllBytes(RequiredBundleCachePath(fixture, source)));
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Disposal_joins_cache_phase_before_retiring_source_without_late_publication(bool afterWrite)
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        async Task Pause() { entered.SetResult(); await release.Task.WaitAsync(Timeout); }
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeCacheWrite = afterWrite ? null : Pause, AfterCacheWrite = afterWrite ? Pause : null });
        var operation = owner.BootstrapAndRefreshAsync();
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(Timeout);
            disposal = owner.DisposeAsync().AsTask();
            Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals); Assert.Null(owner.Current);
            await Assert.ThrowsAnyAsync<InvalidOperationException>(() => owner.BootstrapAndRefreshAsync());
        }
        finally { release.TrySetResult(); }
        var result = await operation.WaitAsync(Timeout);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.NotNull(result.Receipt);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback);
        Assert.NotNull(result.Failure); Assert.False(result.WasPublished); Assert.False(result.SourcesRechecked);
        Assert.Equal(afterWrite, File.Exists(RequiredBundleCachePath(fixture, source)));
        await disposal!.WaitAsync(Timeout); Assert.Equal(1, source.Disposals);
    }

    [Fact]
    public async Task Later_cache_file_failure_does_not_claim_rollback_of_an_already_published_file()
    {
        using var fixture = new Fixture(); var source = new Source();
        const string optionalName = "optional-daily.bundle";
        source.AdditionalBundles.Add(optionalName, RuntimeFlowFixtures.Read(optionalName));
        source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]>
        {
            ["all-ten.bundle"] = source.Bundle, [optionalName] = source.AdditionalBundles[optionalName]
        }, new Dictionary<string, string> { ["DailyTaskData_C"] = optionalName, ["DailyTaskRewardData_C"] = optionalName }, includeDaily: true);
        string optionalPath = BundleCachePath(fixture,
            BundleSourcePlan.CreateDaily(YooAssetManifest.Parse(source.Data), RuntimeFlowFixtures.Snapshot().DataVersion, CancellationToken.None).Entries.Single().Spec);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeCacheWrite = () => { Directory.CreateDirectory(optionalPath); return Task.CompletedTask; } });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.IsAssignableFrom<IOException>(result.Failure);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.NotNull(result.Receipt);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback);
        Assert.False(result.SourcesRechecked); Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(source.Bundle, File.ReadAllBytes(RequiredBundleCachePath(fixture, source)));
        Assert.Equal(12L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Single(Directory.GetFiles(Path.Combine(fixture.Root, "official_sync", "bundles"), "*", SearchOption.AllDirectories));
    }

    [Fact]
    public async Task Post_cache_source_drift_leaves_version_keyed_bytes_without_admission()
    {
        using var fixture = new Fixture(); var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { AfterCacheWrite = () => { source.Snapshot = _ => RuntimeFlowFixtures.Snapshot("1.3.22"); return Task.CompletedTask; } });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Equal(BundleSourceFailure.VersionsChanged, Assert.IsType<BundleSourceException>(result.Failure).Failure);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.NotNull(result.Receipt);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback); Assert.False(result.SourcesRechecked);
        Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(source.Bundle, File.ReadAllBytes(RequiredBundleCachePath(fixture, source)));
    }

    [Fact]
    public async Task Cache_population_uses_owned_snapshot_instead_of_reopening_source_bytes()
    {
        using var fixture = new Fixture(); var source = new Source(); byte[] expected = source.Bundle.ToArray();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeCacheWrite = () => { Array.Fill(source.Bundle, (byte)0xff); return Task.CompletedTask; } });
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(expected, File.ReadAllBytes(RequiredBundleCachePath(fixture, source)));
        Assert.Equal(1, source.BundleRequests);
        Assert.NotNull(await owner.RefreshAsync());
        Assert.Equal(1, source.BundleRequests);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Accepted_optional_bundle_closures_are_cached_but_cannot_override_readback(bool rejectDailyReadback)
    {
        using var fixture = new Fixture(); var source = new Source();
        source.AdditionalBundles.Add("optional-daily.bundle", RuntimeFlowFixtures.Read("optional-daily.bundle"));
        source.AdditionalBundles.Add("optional-instances.bundle", RuntimeFlowFixtures.Read("optional-instances.bundle"));
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal) { ["all-ten.bundle"] = source.Bundle };
        foreach (var pair in source.AdditionalBundles) bundles.Add(pair.Key, pair.Value);
        var roots = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["DailyTaskData_C"] = "optional-daily.bundle", ["DailyTaskRewardData_C"] = "optional-daily.bundle",
            ["DungeonData_C"] = "optional-instances.bundle", ["CooperateEventData_C"] = "optional-instances.bundle"
        };
        source.Data = RuntimeFlowFixtures.Manifest(bundles, roots,
            new Dictionary<string, string[]>
            {
                ["optional-daily.bundle"] = ["all-ten.bundle"],
                ["optional-instances.bundle"] = ["all-ten.bundle"]
            }, includeDaily: true, includeInstances: true);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            BeforeReadback = () =>
            {
                if (rejectDailyReadback) fixture.Sql("UPDATE resources SET sha256=printf('%064d',0) WHERE name='DailyTaskData_C.bytes'");
                return Task.CompletedTask;
            }
        });
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        InstanceFlowAssertions.Present(first.Publication!.Candidate);
        if (rejectDailyReadback) Assert.Null(first.Publication.Candidate.OptionalDailyCatalog);
        else DailyFlowAssertions.Present(first.Publication.Candidate);
        var files = Directory.GetFiles(Path.Combine(fixture.Root, "official_sync", "bundles"), "*", SearchOption.AllDirectories);
        Assert.Equal(3, files.Length);
        foreach (var pair in bundles) Assert.Equal(pair.Value, File.ReadAllBytes(Assert.Single(files,
            path => Path.GetFileName(path) == pair.Key)));
        Assert.Equal(3, source.BundleRequests);
        byte[] database = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Equal(3, source.BundleRequests); Assert.Equal(database, fixture.Bytes());
        InstanceFlowAssertions.Present(refreshed.Candidate);
        if (rejectDailyReadback) Assert.Null(refreshed.Candidate.OptionalDailyCatalog);
        else DailyFlowAssertions.Present(refreshed.Candidate);
        Assert.False(refreshed.ResourceAdmitted); Assert.False(refreshed.CanSendPackets);
    }

    [Theory]
    [InlineData("optional-skill.bundle", "skill")]
    [InlineData("optional-daily-malformed-task.bundle", "daily")]
    [InlineData("optional-instances-malformed-dungeon.bundle", "instances")]
    public async Task Rejected_optional_only_bundles_are_not_retained_just_for_cache(string name, string feature)
    {
        using var fixture = new Fixture(); var source = new Source();
        source.AdditionalBundles.Add(name, RuntimeFlowFixtures.Read(name));
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal) { ["all-ten.bundle"] = source.Bundle };
        foreach (var pair in source.AdditionalBundles) bundles.Add(pair.Key, pair.Value);
        var roots = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string table in feature switch
        {
            "skill" => new[] { "SkillData_C" },
            "daily" => new[] { "DailyTaskData_C", "DailyTaskRewardData_C" },
            _ => new[] { "DungeonData_C", "CooperateEventData_C" }
        }) roots.Add(table, name);
        source.Data = RuntimeFlowFixtures.Manifest(bundles, roots,
            includeSkill: feature == "skill", includeDaily: feature == "daily", includeInstances: feature == "instances");
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync(); Published(result, owner);
        Assert.Null(result.Publication!.Candidate.OptionalSkills);
        Assert.Null(result.Publication.Candidate.OptionalDailyCatalog);
        Assert.Null(result.Publication.Candidate.OptionalInstances);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        string path = Assert.Single(Directory.GetFiles(Path.Combine(fixture.Root, "official_sync", "bundles"), "*", SearchOption.AllDirectories));
        Assert.Equal("all-ten.bundle", Path.GetFileName(path));
        Assert.Equal(2, source.BundleRequests);
        Assert.NotNull(await owner.RefreshAsync());
        Assert.Equal(3, source.BundleRequests); // Only the uncached, still-unavailable optional bundle is retried.
        Assert.Single(Directory.GetFiles(Path.Combine(fixture.Root, "official_sync", "bundles"), "*", SearchOption.AllDirectories));
    }
}
