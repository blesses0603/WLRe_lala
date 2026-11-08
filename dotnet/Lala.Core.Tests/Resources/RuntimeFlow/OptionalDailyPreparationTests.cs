using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

internal static class DailyFlowAssertions
{
    internal static void Present(OfflineRuntimeCandidate candidate)
    {
        var daily = Assert.IsType<DailyTaskCatalogPreview>(candidate.OptionalDailyCatalog);
        Assert.Equal(2, daily.Tasks.Length); Assert.Equal(2, daily.Rewards.Length);
        Assert.Equal(new[] { "任務", "  場景😀  " }, daily.Tasks.Select(row => row.Name));
        Assert.Equal(new byte[] { 1, 2 }, daily.Tasks.Select(row => row.Cycle));
        Assert.Equal(new int?[] { 3, 7 }, daily.Tasks.Select(row => row.Goal));
        Assert.Equal(new ushort[] { 1, 2 }, daily.Tasks.Select(row => row.Data.Index));
        Assert.Equal(new byte[] { 1, 12 }, daily.Tasks.Select(row => row.Data.Id));
        Assert.Equal(new uint[] { 10, 30 }, daily.Tasks.Select(row => row.Data.MissionNameTextId));
        Assert.Equal(new ushort[] { 2, 3, 7 }, daily.Tasks[1].Data.ConditionParams);
        Assert.Equal((byte)2, daily.Tasks[0].Data.FunctionKind);
        Assert.Equal((byte)3, daily.Tasks[0].Data.FunctionArg1);
        Assert.Equal((byte)4, daily.Tasks[0].Data.FunctionArg2);
        Assert.Equal(123u, daily.Tasks[0].Data.Awards[0].Id);
        Assert.Equal(2u, daily.Tasks[0].Data.Awards[0].Value);
        Assert.Equal((byte)11, daily.Tasks[1].Data.Awards[0].Kind);
        Assert.Equal(new uint[] { 10, 50 }, daily.Rewards.Select(row => row.Value));
        Assert.Equal(new uint[] { 1, 8 }, daily.Rewards.Select(row => row.Mark));
        Assert.Equal(99u, daily.Rewards[0].Awards[0].Id);
        Assert.Equal(20u, daily.Rewards[1].Awards[0].Id);
        Assert.DoesNotContain("daily", candidate.UnavailableOptionalSources);
        Assert.False(daily.AssetsReady); Assert.False(daily.CanSendPackets);
        Assert.False(candidate.HasVerifiedProvenance); Assert.False(candidate.RuntimeAdmitted);
        Assert.False(candidate.AssetsReady); Assert.False(candidate.CanSendPackets);
        Assert.Equal(10, candidate.SourceSha256.Count); // Required-table matching remains exactly ten.
    }

    internal static void Absent(OfflinePreparedRuntimeCandidate result)
    {
        Assert.Null(result.Candidate.OptionalDailyCatalog);
        Assert.Contains("daily", result.Candidate.UnavailableOptionalSources);
        Assert.True(result.Candidate.RequiredTablesStructurallyComplete);
        Assert.Equal(10, result.InventoryInput.Tables.Length);
        Assert.Equal<string>(OfflineRuntimeCandidateDecoder.Sources, result.ExtractedTables);
        Assert.Equal("任務", result.Candidate.Expedition.Tasks[1].Name);
    }
}

public sealed partial class OfflineBundleRuntimePreparationTests
{
    private static Script WithOptionalDaily(string fixture = "optional-daily.bundle", string? missingTable = null,
        bool includeSkill = false, bool shareDailyWithSkill = false)
    {
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["all-ten.bundle"] = RuntimeFlowFixtures.Read("all-ten.bundle"),
            [fixture] = RuntimeFlowFixtures.Read(fixture)
        };
        var roots = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["DailyTaskData_C"] = fixture,
            ["DailyTaskRewardData_C"] = fixture
        };
        if (includeSkill)
        {
            bundles.Add("optional-skill.bundle", RuntimeFlowFixtures.Read("optional-skill.bundle"));
            roots.Add("SkillData_C", "optional-skill.bundle");
        }
        var dependencies = shareDailyWithSkill
            ? new Dictionary<string, string[]> { ["optional-skill.bundle"] = [fixture] } : null;
        var source = new Script(bundles);
        source.Data = RuntimeFlowFixtures.Manifest(bundles, roots, dependencies,
            includeSkill: includeSkill, includeDaily: true,
            omittedTables: missingTable is null ? null : new HashSet<string> { missingTable });
        return source;
    }

    [Fact]
    public async Task Daily_pair_binds_owned_text_and_items_and_persists_exact_native_payloads()
    {
        var source = WithOptionalDaily();
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        DailyFlowAssertions.Present(result.Candidate);
        Assert.Equal(12, result.InventoryInput.Tables.Length);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources.Concat(new[] { "DailyTaskData_C", "DailyTaskRewardData_C" }), result.ExtractedTables);
        Assert.Single(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles.Values.Sum(raw => (long)raw.Length), result.DownloadBytes);
        Assert.Equal(6, source.Observations);
        using var evidence = JsonDocument.Parse(RuntimeFlowFixtures.Read("evidence.json"));
        foreach (var table in evidence.RootElement.GetProperty("daily").GetProperty("tables").EnumerateArray())
        {
            var stored = Assert.Single(result.InventoryInput.Tables, row => row.Name == table.GetProperty("table").GetString() + ".bytes");
            Assert.Equal(table.GetProperty("sha256").GetString(), stored.Sha256);
            Assert.Equal(table.GetProperty("bytes").GetInt32(), stored.CopyBytes().Length);
            Assert.Equal(stored.Sha256, Convert.ToHexStringLower(SHA256.HashData(stored.CopyBytes())));
        }
        Array.Fill(source.Bundles["optional-daily.bundle"], (byte)0);
        Array.Fill(source.Data, (byte)0);
        DailyFlowAssertions.Present(result.Candidate);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Theory]
    [InlineData("DailyTaskData_C")]
    [InlineData("DailyTaskRewardData_C")]
    public async Task A_partial_manifest_pair_is_unavailable_without_downloading_the_other_table(string missingTable)
    {
        var source = WithOptionalDaily(missingTable: missingTable);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        DailyFlowAssertions.Absent(result);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(1, result.DownloadCount);
    }

    [Theory]
    [InlineData("optional-daily-missing-text.bundle")]
    [InlineData("optional-daily-missing-task-item.bundle")]
    [InlineData("optional-daily-missing-reward-item.bundle")]
    [InlineData("optional-daily-malformed-task.bundle")]
    [InlineData("optional-daily-malformed-reward.bundle")]
    [InlineData("optional-daily-missing-task-path.bundle")]
    [InlineData("optional-daily-missing-reward-path.bundle")]
    public async Task Invalid_cross_references_layout_or_partial_extraction_drop_both_daily_tables(string fixture)
    {
        var source = WithOptionalDaily(fixture);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        DailyFlowAssertions.Absent(result);
        Assert.Single(source.Requests, url => url.EndsWith(fixture, StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Daily_pair_cannot_reset_required_file_or_byte_download_quota(bool byteLimit)
    {
        var source = WithOptionalDaily();
        var budget = byteLimit ? new BundleSourceBudget(24, source.Bundles["all-ten.bundle"].Length)
            : new BundleSourceBudget(1);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, budget: budget);
        DailyFlowAssertions.Absent(result);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(1, result.DownloadCount);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Skill_download_or_failed_reservation_keeps_its_quota_before_daily(bool failSkillRead)
    {
        var source = WithOptionalDaily(includeSkill: true);
        source.BeforeOpen = (name, _) =>
        {
            if (failSkillRead && name == "optional-skill.bundle") throw new IOException("Owned optional read failure");
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, budget: new BundleSourceBudget(2));
        DailyFlowAssertions.Absent(result); Assert.Null(result.Candidate.OptionalSkills);
        Assert.Single(source.Requests, url => url.EndsWith("optional-skill.bundle", StringComparison.Ordinal));
        Assert.DoesNotContain(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Equal(2, result.DownloadCount);
        Assert.Equal(source.Bundles["all-ten.bundle"].Length + (long)source.Bundles["optional-skill.bundle"].Length, result.DownloadBytes);
    }

    [Fact]
    public async Task Daily_dependency_acquired_for_unreviewed_skill_is_reused_once_without_extra_quota()
    {
        var source = WithOptionalDaily(includeSkill: true, shareDailyWithSkill: true);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source,
            budget: new BundleSourceBudget(3, source.Bundles.Values.Sum(raw => (long)raw.Length)));
        DailyFlowAssertions.Present(result.Candidate); Assert.Null(result.Candidate.OptionalSkills);
        Assert.Equal(3, result.DownloadCount); Assert.Equal(12, result.InventoryInput.Tables.Length);
        Assert.Single(source.Requests, url => url.EndsWith("optional-daily.bundle", StringComparison.Ordinal));
        Assert.Single(source.Requests, url => url.EndsWith("optional-skill.bundle", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Daily_uses_reverified_owned_cache_bytes_without_network_or_quota()
    {
        var source = WithOptionalDaily(); var cache = new Cache(source.Bundles);
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, cache, new BundleSourceBudget(0, 0));
        DailyFlowAssertions.Present(result.Candidate);
        Assert.Equal(4, cache.Reads); Assert.Equal(0, result.DownloadCount); Assert.Equal(0, result.DownloadBytes);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith(".bundle", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Daily_download_failure_is_optional_but_source_drift_after_it_is_not()
    {
        var source = WithOptionalDaily();
        source.BeforeOpen = (name, _) => { if (name == "optional-daily.bundle") throw new IOException("Owned daily read failure"); };
        DailyFlowAssertions.Absent(await new OfflineBundleRuntimePreparation().PrepareAsync(source));
        source = WithOptionalDaily();
        source.BeforeOpen = (name, _) =>
        {
            if (name != "optional-daily.bundle") return;
            source.Observe = _ => RuntimeFlowFixtures.Snapshot("1.3.22");
            throw new IOException("Owned daily read failure after source drift");
        };
        var failure = await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(BundleSourceFailure.VersionsChanged, failure.Failure);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Cancellation_or_invalidation_during_daily_cannot_return_required_only_result(bool invalidate)
    {
        var source = WithOptionalDaily(); var pipeline = new OfflineBundleRuntimePreparation();
        using var cancellation = new CancellationTokenSource();
        source.BeforeOpen = (name, _) =>
        {
            if (name != "optional-daily.bundle") return;
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
    public async Task Daily_transport_cleanup_failures_are_not_hidden_as_optional_unavailability(bool primaryFailure)
    {
        var source = WithOptionalDaily();
        Exception failure = primaryFailure ? new IOException("Owned primary failure")
            : new ResourceTransportException(ResourceTransportFailure.Cleanup);
        if (primaryFailure) failure.Data[ResourceCleanup.FailureMarker] = "Cleanup";
        source.BeforeOpen = (name, _) => { if (name == "optional-daily.bundle") throw failure; };
        Assert.Same(failure, await Record.ExceptionAsync(() => new OfflineBundleRuntimePreparation().PrepareAsync(source)));
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }
}
