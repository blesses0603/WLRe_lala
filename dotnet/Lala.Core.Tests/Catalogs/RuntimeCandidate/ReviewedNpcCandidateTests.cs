using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Text;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Tests.Catalogs.ReviewedNpcs;
using Xunit;

namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;

public sealed class ReviewedNpcCandidateTests
{
    private const string Version = "1286_2026_10_29_13_42_37_94";

    [Fact]
    public void Unknown_required_npc_digest_does_not_fail_candidate_or_accept_supplied_metadata_claims()
    {
        var sources = Sources();
        sources["ReviewedNpcs"] = Encoding.UTF8.GetBytes("trusted");
        sources["NpcDataSha256"] = Encoding.ASCII.GetBytes(NormalAttackCatalogParser.ReviewedNpcSha256);
        var candidate = OfflineRuntimeCandidateDecoder.Decode(sources, Version);
        Assert.NotEmpty(candidate.Npcs);
        Assert.Null(candidate.ReviewedNpcs);
        Assert.NotEqual(NormalAttackCatalogParser.ReviewedNpcSha256, candidate.SourceSha256["NpcData_C"]);
        Assert.Equal(10, candidate.SourceSha256.Count);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources, candidate.SourceSha256.Keys);
        Assert.True(candidate.RequiredTablesStructurallyComplete);
        Assert.False(candidate.HasVerifiedProvenance); Assert.False(candidate.RuntimeAdmitted);
        Assert.False(candidate.AssetsReady); Assert.False(candidate.CanSendPackets);
        Assert.Empty(typeof(OfflineRuntimeCandidate).GetConstructors());
        Assert.Null(typeof(OfflineRuntimeCandidate).GetProperty(nameof(OfflineRuntimeCandidate.ReviewedNpcs))!.SetMethod);
    }

    [Fact]
    public void Every_optional_copy_preserves_owned_reviewed_npcs_and_other_required_observations()
    {
        var original = OfflineRuntimeCandidateDecoder.Decode(Sources(), Version);
        var npcs = ReviewedNpcCatalogParser.ParseLayout(ReviewedNpcCatalogTests.Table(
            ReviewedNpcCatalogTests.Record(1, "NPC", [101, 0, 65535, 101, 5])));
        // Internal synthetic construction tests cloning only. It cannot bypass the public decoder's pin.
        var seeded = new OfflineRuntimeCandidate(original.EveIndexes, original.Items, original.Talks,
            original.Texts, original.Recipes, original.Stages, original.Doors, original.SceneNames,
            original.Expedition, original.Npcs, original.SourceSha256, original.PortalObservations,
            reviewedNpcs: npcs);
        var (tasks, rewards) = DailyTables(original.Texts.Keys.First());
        byte[] dungeons = DungeonTable(original.Stages.Keys.First());
        var daily = seeded.WithOptionalDailyCatalog(tasks, rewards, default);
        var instances = daily.WithOptionalInstances(dungeons, new byte[4], default);
        Assert.NotNull(daily.OptionalDailyCatalog); Assert.NotNull(instances.OptionalInstances);
        foreach (var copy in new[]
        {
            seeded.WithoutOptionalSkills(), seeded.WithoutOptionalDailyCatalog(), seeded.WithoutOptionalInstances(),
            daily, instances, instances.WithoutOptionalSkills(), instances.WithoutOptionalDailyCatalog(),
            instances.WithoutOptionalInstances(), instances.WithoutOptionalInstances().WithoutOptionalDailyCatalog().WithoutOptionalSkills()
        })
        {
            Assert.Same(npcs, copy.ReviewedNpcs);
            Assert.Same(original.SourceSha256, copy.SourceSha256);
            Assert.Same(original.Npcs, copy.Npcs);
            Assert.Same(original.PortalObservations, copy.PortalObservations);
            Assert.False(copy.HasVerifiedProvenance); Assert.False(copy.CanSendPackets);
        }
        Assert.Throws<NotSupportedException>(() => ((IDictionary<uint, CombatResourceNpc>)seeded.ReviewedNpcs!).Clear());
        Assert.Equal(new uint[] { 101, 0, 65535, 101, 5 }, seeded.ReviewedNpcs![1].Skills);
        Assert.Null(original.ReviewedNpcs);
    }

    [Fact]
    public void Missing_reviewed_npcs_stays_unknown_through_optional_copy_operations()
    {
        var candidate = OfflineRuntimeCandidateDecoder.Decode(Sources(), Version);
        var (tasks, rewards) = DailyTables(candidate.Texts.Keys.First());
        Assert.Null(candidate.WithOptionalDailyCatalog(tasks, rewards, default).ReviewedNpcs);
        Assert.Null(candidate.WithOptionalInstances(DungeonTable(candidate.Stages.Keys.First()), new byte[4], default).ReviewedNpcs);
        Assert.Null(candidate.WithoutOptionalSkills().WithoutOptionalDailyCatalog().WithoutOptionalInstances().ReviewedNpcs);
    }

    [Fact]
    public void Optional_failures_and_cancellation_never_mutate_prior_candidate()
    {
        var candidate = OfflineRuntimeCandidateDecoder.Decode(Sources(), Version);
        Assert.Throws<CatalogDecodeException>(() => candidate.WithOptionalSkills([], default));
        Assert.Throws<CatalogDecodeException>(() => candidate.WithOptionalDailyCatalog([], [], default));
        Assert.Throws<CatalogDecodeException>(() => candidate.WithOptionalInstances([], [], default));
        using var stop = new CancellationTokenSource(); stop.Cancel();
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeCandidateDecoder.Decode(Sources(), Version, stop.Token));
        Assert.Throws<OperationCanceledException>(() => candidate.WithOptionalSkills([], stop.Token));
        Assert.Throws<OperationCanceledException>(() => candidate.WithOptionalDailyCatalog([], [], stop.Token));
        Assert.Throws<OperationCanceledException>(() => candidate.WithOptionalInstances([], [], stop.Token));
        Assert.Null(candidate.ReviewedNpcs);
        Assert.True(candidate.RequiredTablesStructurallyComplete);
    }

    private static Dictionary<string, ReadOnlyMemory<byte>> Sources() => RuntimeCandidateOracleCases.Case(0)
        .GetProperty("inputs").EnumerateObject().ToDictionary(pair => pair.Name,
            pair => (ReadOnlyMemory<byte>)Convert.FromBase64String(pair.Value.GetString()!), StringComparer.Ordinal);

    private static (byte[] Tasks, byte[] Rewards) DailyTables(uint nameId)
    {
        byte[] tasks = new byte[11 + DailyTaskDataParser.TaskRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(tasks, 1);
        tasks[4] = 1; tasks[5] = 1; tasks[6] = 1;
        BinaryPrimitives.WriteInt32LittleEndian(tasks.AsSpan(7), 1);
        BinaryPrimitives.WriteUInt16LittleEndian(tasks.AsSpan(11), 1);
        tasks[13] = 1; tasks[14] = 1;
        BinaryPrimitives.WriteUInt32LittleEndian(tasks.AsSpan(15), nameId);
        tasks[19] = 1;
        byte[] rewards = new byte[4 + DailyTaskDataParser.RewardRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(rewards, 1);
        BinaryPrimitives.WriteUInt16LittleEndian(rewards.AsSpan(4), 1); rewards[6] = 1;
        BinaryPrimitives.WriteUInt32LittleEndian(rewards.AsSpan(7), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(rewards.AsSpan(11), 1);
        return (tasks, rewards);
    }

    private static byte[] DungeonTable(ushort map)
    {
        byte[] raw = new byte[4 + InstanceCatalogParser.DungeonRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(raw, 1);
        BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(4), 1);
        raw[6] = 1; raw[7] = 1;
        BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(8), map);
        return raw;
    }
}
