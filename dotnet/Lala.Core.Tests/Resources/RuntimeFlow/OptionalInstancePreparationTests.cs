using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

internal static class InstanceFlowAssertions
{
    internal static void Present(OfflineRuntimeCandidate candidate)
    {
        var instances = Assert.IsType<InstanceCatalogPreview>(candidate.OptionalInstances);
        Assert.Equal(2, instances.Entries.Length);
        Assert.Equal(new[] { "  場景😀  ", "任務" }, instances.Entries.Select(row => row.Name));
        Assert.Equal(new uint[] { 30, 10 }, instances.Entries.Select(row => row.NameId));
        Assert.Equal(new ushort[] { 1, 2 }, instances.Entries.Select(row => row.Data.Id));
        Assert.Equal(new byte[] { 1, 2 }, instances.Entries.Select(row => row.Data.Kind));
        Assert.Equal(new byte[] { 1, 2 }, instances.Entries.Select(row => row.Variant));
        Assert.Equal(new ushort[] { 500 }, instances.DeclaredMainMapIds);
        foreach (var row in instances.Entries)
        {
            Assert.Equal((ushort)500, row.Data.MapId); Assert.Equal((ushort)500, row.Stage.Id);
            Assert.Equal(999u, row.Data.DescriptionId); // No description-text join is invented.
            Assert.Equal((byte)4, row.Data.Picture); Assert.Equal((byte)5, row.Data.ScoreDisplay);
            Assert.Equal((byte)6, row.Data.AwardGroup); Assert.Equal((byte)8, row.Data.QuickId);
            Assert.Equal((ushort)101, row.Data.NpcX); Assert.Equal((ushort)202, row.Data.NpcY);
            Assert.Equal(16, row.Data.Awards.Length);
            Assert.Equal(new byte[] { 1, 16 }, row.Data.DoubleAwardSlots);
            Assert.Equal(new byte[] { 2, 15 }, row.Data.SpecialAwardSlots);
            Assert.Equal(new byte[] { 1, 2, 16 }, row.Awards.Select(award => award.Slot));
            Assert.Equal(new byte[] { 10, 1, 11 }, row.Awards.Select(award => award.Kind));
            Assert.Equal(new uint[] { 123, 0, 99 }, row.Awards.Select(award => award.Id));
            Assert.Equal(new uint[] { 2, 3, 4 }, row.Awards.Select(award => award.Value));
            Assert.Equal((byte)0, row.MinMembers); Assert.Equal((byte)0, row.MaxMembers);
            Assert.Equal((ushort)0, row.MinLevel); Assert.Equal((ushort)0, row.TimeMinutes);
            Assert.Equal((byte)0, row.RoomCount); Assert.Null(row.IsOpen);
            Assert.False(row.CreationSupported); // Existing synthetic scene has zero member bounds.
        }
        Assert.Null(instances.Entries[0].CooperativeEvent);
        var cooperative = Assert.Single(instances.CooperativeEvents);
        Assert.Same(cooperative, instances.Entries[1].CooperativeEvent);
        Assert.Equal((ushort)7, instances.Entries[1].Data.NpcId);
        Assert.Equal((byte)7, cooperative.Id); Assert.Equal(10u, cooperative.TextId);
        Assert.Equal((ushort)303, cooperative.NpcX); Assert.Equal((ushort)404, cooperative.NpcY);
        Assert.Equal((byte)5, cooperative.FightCount);
        Assert.Equal((ushort)601, cooperative.StepMarkId); Assert.Equal((ushort)602, cooperative.FinishMarkId);
        Assert.Equal((ushort)603, cooperative.SellDataId);
        Assert.Equal(new ushort[] { 11, 22, 33, 44 }, cooperative.FollowerIds);
        Assert.Equal(new InstanceAward(11, 20, 6), cooperative.FollowerReward);
        Assert.DoesNotContain("instances", candidate.UnavailableOptionalSources);
        Assert.False(instances.AssetsReady); Assert.False(instances.CanSendPackets);
        Assert.False(candidate.HasVerifiedProvenance); Assert.False(candidate.RuntimeAdmitted);
        Assert.False(candidate.AssetsReady); Assert.False(candidate.CanSendPackets);
        Assert.True(candidate.RequiredTablesStructurallyComplete);
        Assert.Equal(10, candidate.SourceSha256.Count);
    }

    internal static void Absent(OfflinePreparedRuntimeCandidate result)
    {
        Assert.Null(result.Candidate.OptionalInstances);
        Assert.Contains("instances", result.Candidate.UnavailableOptionalSources);
        Assert.True(result.Candidate.RequiredTablesStructurallyComplete);
        Assert.Equal(10, result.InventoryInput.Tables.Length);
        Assert.Equal<string>(OfflineRuntimeCandidateDecoder.Sources, result.ExtractedTables);
        Assert.Equal("任務", result.Candidate.Expedition.Tasks[1].Name);
        Assert.False(result.Candidate.AssetsReady); Assert.False(result.Candidate.CanSendPackets);
    }
}

public sealed partial class OfflineBundleRuntimePreparationTests
{
    private static Script WithOptionalInstances(string fixture = "optional-instances.bundle", string? missingTable = null,
        bool includeSkill = false, bool includeDaily = false, bool shareInstancesWithSkill = false)
    {
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["all-ten.bundle"] = RuntimeFlowFixtures.Read("all-ten.bundle"),
            [fixture] = RuntimeFlowFixtures.Read(fixture)
        };
        var roots = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["DungeonData_C"] = fixture, ["CooperateEventData_C"] = fixture
        };
        if (includeSkill)
        {
            bundles.Add("optional-skill.bundle", RuntimeFlowFixtures.Read("optional-skill.bundle"));
            roots.Add("SkillData_C", "optional-skill.bundle");
        }
        if (includeDaily)
        {
            bundles.Add("optional-daily.bundle", RuntimeFlowFixtures.Read("optional-daily.bundle"));
            roots.Add("DailyTaskData_C", "optional-daily.bundle");
            roots.Add("DailyTaskRewardData_C", "optional-daily.bundle");
        }
        var dependencies = shareInstancesWithSkill
            ? new Dictionary<string, string[]> { ["optional-skill.bundle"] = [fixture] } : null;
        var source = new Script(bundles);
        source.Data = RuntimeFlowFixtures.Manifest(bundles, roots, dependencies,
            includeSkill: includeSkill, includeDaily: includeDaily, includeInstances: true,
            omittedTables: missingTable is null ? null : new HashSet<string> { missingTable });
        return source;
    }

    [Fact]
    public async Task Instance_pair_binds_original_scene_text_item_payloads_and_retains_exact_extracted_bytes()
    {
        var source = WithOptionalInstances();
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        InstanceFlowAssertions.Present(result.Candidate);
        Assert.Equal(12, result.InventoryInput.Tables.Length);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources.Concat(new[] { "DungeonData_C", "CooperateEventData_C" }), result.ExtractedTables);
        Assert.Single(source.Requests, url => url.EndsWith("optional-instances.bundle", StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles.Values.Sum(raw => (long)raw.Length), result.DownloadBytes);
        Assert.Equal(6, source.Observations);
        using var evidence = JsonDocument.Parse(RuntimeFlowFixtures.Read("evidence.json"));
        foreach (var table in evidence.RootElement.GetProperty("instances").GetProperty("tables").EnumerateArray())
        {
            var stored = Assert.Single(result.InventoryInput.Tables, row => row.Name == table.GetProperty("table").GetString() + ".bytes");
            Assert.Equal(table.GetProperty("sha256").GetString(), stored.Sha256);
            Assert.Equal(table.GetProperty("bytes").GetInt32(), stored.CopyBytes().Length);
            Assert.Equal(stored.Sha256, Convert.ToHexStringLower(SHA256.HashData(stored.CopyBytes())));
        }
        Array.Fill(source.Bundles["optional-instances.bundle"], (byte)0);
        Array.Fill(source.Data, (byte)0);
        InstanceFlowAssertions.Present(result.Candidate);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Theory]
    [InlineData("DungeonData_C")]
    [InlineData("CooperateEventData_C")]
    public async Task Partial_instance_manifest_pair_is_unavailable_without_downloading_the_other_member(string missingTable)
    {
        var source = WithOptionalInstances(missingTable: missingTable);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        InstanceFlowAssertions.Absent(result);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-instances.bundle", StringComparison.Ordinal));
        Assert.Equal(1, result.DownloadCount);
    }

    [Theory]
    [InlineData("optional-instances-missing-text.bundle")]
    [InlineData("optional-instances-missing-map.bundle")]
    [InlineData("optional-instances-missing-item.bundle")]
    [InlineData("optional-instances-missing-kind11-item.bundle")]
    [InlineData("optional-instances-missing-event.bundle")]
    [InlineData("optional-instances-duplicate-key.bundle")]
    [InlineData("optional-instances-duplicate-main-map.bundle")]
    [InlineData("optional-instances-duplicate-event.bundle")]
    [InlineData("optional-instances-zero-event.bundle")]
    [InlineData("optional-instances-invalid-empty-award.bundle")]
    [InlineData("optional-instances-malformed-dungeon.bundle")]
    [InlineData("optional-instances-malformed-event.bundle")]
    [InlineData("optional-instances-missing-dungeon-path.bundle")]
    [InlineData("optional-instances-missing-event-path.bundle")]
    public async Task Invalid_instance_bindings_layout_duplicates_or_partial_extraction_drop_both_tables(string fixture)
    {
        var source = WithOptionalInstances(fixture);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        InstanceFlowAssertions.Absent(result);
        Assert.Single(source.Requests, url => url.EndsWith(fixture, StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Instances_cannot_reset_required_file_or_byte_download_quota(bool byteLimit)
    {
        var source = WithOptionalInstances();
        var budget = byteLimit ? new BundleSourceBudget(24, source.Bundles["all-ten.bundle"].Length)
            : new BundleSourceBudget(1);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, budget: budget);
        InstanceFlowAssertions.Absent(result);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-instances.bundle", StringComparison.Ordinal));
        Assert.Equal(1, result.DownloadCount);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Skills_keep_successful_or_failed_reservations_before_instance_and_daily_acquisition(bool failSkillRead)
    {
        var source = WithOptionalInstances(includeSkill: true, includeDaily: true);
        source.BeforeOpen = (name, _) =>
        {
            if (failSkillRead && name == "optional-skill.bundle") throw new IOException("Owned optional read failure");
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, budget: new BundleSourceBudget(2));
        InstanceFlowAssertions.Absent(result);
        Assert.Null(result.Candidate.OptionalSkills); Assert.Null(result.Candidate.OptionalDailyCatalog);
        Assert.Single(source.Requests, url => url.EndsWith("optional-skill.bundle", StringComparison.Ordinal));
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-instances.bundle", StringComparison.Ordinal));
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles["all-ten.bundle"].Length + (long)source.Bundles["optional-skill.bundle"].Length, result.DownloadBytes);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Instance_reservations_precede_daily_and_are_not_refunded_on_failure(bool failInstanceRead)
    {
        var source = WithOptionalInstances(includeDaily: true);
        source.BeforeOpen = (name, _) =>
        {
            if (failInstanceRead && name == "optional-instances.bundle") throw new IOException("Owned instance read failure");
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, budget: new BundleSourceBudget(2));
        if (failInstanceRead) InstanceFlowAssertions.Absent(result);
        else { InstanceFlowAssertions.Present(result.Candidate); Assert.Equal(12, result.InventoryInput.Tables.Length); }
        Assert.Null(result.Candidate.OptionalDailyCatalog);
        Assert.Single(source.Requests, url => url.EndsWith("optional-instances.bundle", StringComparison.Ordinal));
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles["all-ten.bundle"].Length + (long)source.Bundles["optional-instances.bundle"].Length, result.DownloadBytes);
    }

    [Fact]
    public async Task Instances_acquired_as_a_skill_dependency_are_reused_without_spending_daily_quota()
    {
        var source = WithOptionalInstances(includeSkill: true, includeDaily: true, shareInstancesWithSkill: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source,
            budget: new BundleSourceBudget(4, source.Bundles.Values.Sum(raw => (long)raw.Length)));
        InstanceFlowAssertions.Present(result.Candidate); DailyFlowAssertions.Present(result.Candidate);
        Assert.Null(result.Candidate.OptionalSkills);
        Assert.Equal(14, result.InventoryInput.Tables.Length); Assert.Equal(4, result.DownloadCount);
        foreach (string name in source.Bundles.Keys)
            Assert.Single(source.Requests, url => url.EndsWith(name, StringComparison.Ordinal));
        Assert.Equal(source.Bundles.Values.Sum(raw => (long)raw.Length), result.DownloadBytes);
    }

    [Fact]
    public async Task Invalid_instances_do_not_discard_independent_daily_tables()
    {
        var source = WithOptionalInstances("optional-instances-missing-event.bundle", includeDaily: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Null(result.Candidate.OptionalInstances);
        Assert.Contains("instances", result.Candidate.UnavailableOptionalSources);
        DailyFlowAssertions.Present(result.Candidate);
        Assert.Equal(12, result.InventoryInput.Tables.Length);
        Assert.DoesNotContain(result.InventoryInput.Tables, row => row.Name is "DungeonData_C.bytes" or "CooperateEventData_C.bytes");
        Assert.Equal(3, result.DownloadCount);
    }

    [Fact]
    public async Task Instances_use_reverified_owned_cache_bytes_without_network_or_download_quota()
    {
        var source = WithOptionalInstances(); var cache = new Cache(source.Bundles);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, cache, new BundleSourceBudget(0, 0));
        InstanceFlowAssertions.Present(result.Candidate);
        Assert.Equal(4, cache.Reads); Assert.Equal(0, result.DownloadCount); Assert.Equal(0, result.DownloadBytes);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith(".bundle", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Instance_download_failure_is_optional_but_following_source_drift_is_not()
    {
        var source = WithOptionalInstances();
        source.BeforeOpen = (name, _) => { if (name == "optional-instances.bundle") throw new IOException("Owned instance read failure"); };
        InstanceFlowAssertions.Absent(await new OfflineBundleRuntimePreparation().PrepareAsync(source));
        source = WithOptionalInstances();
        source.BeforeOpen = (name, _) =>
        {
            if (name != "optional-instances.bundle") return;
            source.Observe = _ => RuntimeFlowFixtures.Snapshot("1.3.22");
            throw new IOException("Owned instance read failure after source drift");
        };
        var failure = await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(BundleSourceFailure.VersionsChanged, failure.Failure);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Cancellation_or_invalidation_during_instances_cannot_return_required_only_result(bool invalidate)
    {
        var source = WithOptionalInstances(); var pipeline = new OfflineBundleRuntimePreparation();
        using var cancellation = new CancellationTokenSource();
        source.BeforeOpen = (name, _) =>
        {
            if (name != "optional-instances.bundle") return;
            if (invalidate) pipeline.Invalidate(); else cancellation.Cancel();
        };
        if (invalidate)
            Assert.Equal(BundleSourceFailure.StaleAttempt, (await Assert.ThrowsAsync<BundleSourceException>(() => pipeline.PrepareAsync(source))).Failure);
        else
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pipeline.PrepareAsync(source, cancellationToken: cancellation.Token));
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Instance_transport_cleanup_failures_cannot_degrade_to_optional_unavailability(bool primaryFailure)
    {
        var source = WithOptionalInstances();
        Exception failure = primaryFailure ? new IOException("Owned primary failure")
            : new ResourceTransportException(ResourceTransportFailure.Cleanup);
        if (primaryFailure) failure.Data[ResourceCleanup.FailureMarker] = "Cleanup";
        source.BeforeOpen = (name, _) => { if (name == "optional-instances.bundle") throw failure; };
        Assert.Same(failure, await Record.ExceptionAsync(() => new OfflineBundleRuntimePreparation().PrepareAsync(source)));
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }
}
