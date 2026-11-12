using System.Security.Cryptography;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static Source WithInstanceCatalog(bool includeDaily = false)
    {
        // Reuse the established source's exact request target. Required and optional
        // arrays are genuine TextAssets in the same owned, independently read bundle.
        var source = new Source { Bundle = RuntimeFlowFixtures.Read(includeDaily
            ? "all-ten-daily-instances.bundle" : "all-ten-instances.bundle") };
        source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = source.Bundle },
            includeDaily: includeDaily, includeInstances: true);
        return source;
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Instance_pair_survives_bootstrap_independent_readback_and_read_only_refresh(bool includeDaily)
    {
        using var fixture = new Fixture(); var source = WithInstanceCatalog(includeDaily); var writes = 0;
        var connections = new List<ScriptedReadConnection>();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            BeforeWrite = () => { writes++; return Task.CompletedTask; },
            WrapConnection = connection => { var wrapped = new ScriptedReadConnection(connection); connections.Add(wrapped); return wrapped; }
        });
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        InstanceFlowAssertions.Present(first.Publication!.Candidate);
        if (includeDaily) DailyFlowAssertions.Present(first.Publication.Candidate);
        Assert.Equal(includeDaily ? 14L : 12L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(2L, fixture.Sql("SELECT count(*) FROM resources WHERE name IN ('DungeonData_C.bytes','CooperateEventData_C.bytes')"));
        Assert.Equal(1, source.BundleRequests); Assert.Equal(1, writes);
        Assert.Single(connections.SelectMany(connection => connection.Commands), sql => sql == "COMMIT");
        Assert.All(connections, connection => Assert.True(connection.WasDisposed));
        byte[] before = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Same(refreshed, owner.Current); Assert.True(refreshed.Generation > first.Publication.Generation);
        InstanceFlowAssertions.Present(refreshed.Candidate);
        if (includeDaily) DailyFlowAssertions.Present(refreshed.Candidate);
        Assert.Equal(before, fixture.Bytes()); Assert.Equal(1, writes);
        Assert.False(refreshed.ResourceAdmitted); Assert.False(refreshed.CanLogin); Assert.False(refreshed.CanSendPackets);
    }

    [Theory]
    [InlineData("DungeonData_C.bytes", "blob")]
    [InlineData("CooperateEventData_C.bytes", "blob")]
    [InlineData("DungeonData_C.bytes", "hash")]
    [InlineData("CooperateEventData_C.bytes", "hash")]
    [InlineData("DungeonData_C.bytes", "missing")]
    [InlineData("CooperateEventData_C.bytes", "missing")]
    [InlineData("DungeonData_C.bytes", "valid-changed")]
    [InlineData("CooperateEventData_C.bytes", "valid-changed")]
    public async Task Instance_readback_mismatch_drops_only_instances_preserving_daily_without_repair_or_retry(string table, string mode)
    {
        using var fixture = new Fixture(); var writes = 0; var readbacks = 0;
        var connections = new List<ScriptedReadConnection>();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, WithInstanceCatalog(includeDaily: true), bootstrapHooks: new()
        {
            BeforeWrite = () => { writes++; return Task.CompletedTask; },
            BeforeReadback = () =>
            {
                readbacks++;
                if (mode == "valid-changed")
                {
                    // Keep the altered table parseable and make its stored hash honest.
                    // Only comparison with the freshly acquired optional source can reject it.
                    var bytes = Assert.IsType<byte[]>(fixture.Sql($"SELECT data FROM resources WHERE name='{table}'"));
                    bytes[table == "DungeonData_C.bytes" ? 4 : 5] = table == "DungeonData_C.bytes" ? (byte)9 : (byte)20;
                    string hash = Convert.ToHexStringLower(SHA256.HashData(bytes));
                    fixture.Sql($"UPDATE resources SET data=x'{Convert.ToHexString(bytes)}',sha256='{hash}' WHERE name='{table}'");
                }
                else fixture.Sql(mode switch
                {
                    "missing" => $"DELETE FROM resources WHERE name='{table}'",
                    "hash" => $"UPDATE resources SET sha256=printf('%064d',0) WHERE name='{table}'",
                    _ => $"UPDATE resources SET data=x'0000' WHERE name='{table}'"
                });
                return Task.CompletedTask;
            },
            WrapConnection = connection => { var wrapped = new ScriptedReadConnection(connection); connections.Add(wrapped); return wrapped; }
        });
        var result = await owner.BootstrapAndRefreshAsync(); Published(result, owner);
        Assert.Equal(1, writes); Assert.Equal(1, readbacks);
        Assert.Single(connections.SelectMany(connection => connection.Commands), sql => sql == "COMMIT");
        Assert.Equal(mode == "missing" ? 13L : 14L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Null(result.Publication!.Candidate.OptionalInstances);
        Assert.Contains("instances", result.Publication.Candidate.UnavailableOptionalSources);
        DailyFlowAssertions.Present(result.Publication.Candidate);
        Assert.Equal(3, result.Publication.Candidate.Items.Count);
        Assert.Equal("任務", result.Publication.Candidate.Expedition.Tasks[1].Name);
        Assert.True(result.Publication.Candidate.RequiredTablesStructurallyComplete);
        Assert.All(connections, connection => Assert.True(connection.WasDisposed));
        // Ordinary refresh is read-only and cannot repair the retained mismatch.
        byte[] before = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Null(refreshed.Candidate.OptionalInstances);
        Assert.Contains("instances", refreshed.Candidate.UnavailableOptionalSources);
        DailyFlowAssertions.Present(refreshed.Candidate);
        Assert.Equal(before, fixture.Bytes()); Assert.Equal(1, writes); Assert.Equal(1, readbacks);
        Assert.False(refreshed.ResourceAdmitted); Assert.False(refreshed.CanLogin); Assert.False(refreshed.CanSendPackets);
    }

    [Theory]
    [InlineData("DailyTaskData_C.bytes")]
    [InlineData("DailyTaskRewardData_C.bytes")]
    public async Task Dropping_corrupt_daily_readback_preserves_independently_valid_instances(string table)
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, WithInstanceCatalog(includeDaily: true), bootstrapHooks: new()
        {
            BeforeReadback = () =>
            {
                fixture.Sql($"UPDATE resources SET sha256=printf('%064d',0) WHERE name='{table}'");
                return Task.CompletedTask;
            }
        });
        var result = await owner.BootstrapAndRefreshAsync(); Published(result, owner);
        InstanceFlowAssertions.Present(result.Publication!.Candidate);
        Assert.Null(result.Publication.Candidate.OptionalDailyCatalog);
        Assert.Contains("daily", result.Publication.Candidate.UnavailableOptionalSources);
        Assert.Equal(14L, fixture.Sql("SELECT count(*) FROM resources"));
        byte[] before = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        InstanceFlowAssertions.Present(refreshed.Candidate);
        Assert.Null(refreshed.Candidate.OptionalDailyCatalog); Assert.Equal(before, fixture.Bytes());
    }
}
