using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static Source WithDailyCatalog()
    {
        // Keep the existing scripted source's exact request target. The owned bundle
        // contains all required tables plus the pair, so acquisition is shared.
        var source = new Source { Bundle = RuntimeFlowFixtures.Read("all-ten-daily.bundle") };
        source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = source.Bundle }, includeDaily: true);
        return source;
    }

    [Fact]
    public async Task Daily_pair_survives_real_bootstrap_independent_readback_and_read_only_refresh()
    {
        using var fixture = new Fixture(); var source = WithDailyCatalog(); var writes = 0;
        var connections = new List<ScriptedReadConnection>();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            BeforeWrite = () => { writes++; return Task.CompletedTask; },
            WrapConnection = connection => { var wrapped = new ScriptedReadConnection(connection); connections.Add(wrapped); return wrapped; }
        });
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        DailyFlowAssertions.Present(first.Publication!.Candidate);
        Assert.Equal(12L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(2L, fixture.Sql("SELECT count(*) FROM resources WHERE name IN ('DailyTaskData_C.bytes','DailyTaskRewardData_C.bytes')"));
        Assert.Equal(1, source.BundleRequests); Assert.Equal(1, writes);
        Assert.Single(connections.SelectMany(connection => connection.Commands), sql => sql == "COMMIT");
        Assert.All(connections, connection => Assert.True(connection.WasDisposed));
        byte[] before = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Same(refreshed, owner.Current); Assert.True(refreshed.Generation > first.Publication.Generation);
        DailyFlowAssertions.Present(refreshed.Candidate);
        Assert.Equal(before, fixture.Bytes()); Assert.Equal(1, writes);
        Assert.False(refreshed.ResourceAdmitted); Assert.False(refreshed.CanLogin); Assert.False(refreshed.CanSendPackets);
    }

    [Theory]
    [InlineData("DailyTaskData_C.bytes", "blob")]
    [InlineData("DailyTaskRewardData_C.bytes", "blob")]
    [InlineData("DailyTaskData_C.bytes", "hash")]
    [InlineData("DailyTaskRewardData_C.bytes", "hash")]
    [InlineData("DailyTaskData_C.bytes", "missing")]
    [InlineData("DailyTaskRewardData_C.bytes", "missing")]
    public async Task Daily_readback_corruption_drops_pair_without_retrying_storage_or_losing_required_publication(string table, string mode)
    {
        using var fixture = new Fixture(); var writes = 0; var readbacks = 0;
        var connections = new List<ScriptedReadConnection>();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, WithDailyCatalog(), bootstrapHooks: new()
        {
            BeforeWrite = () => { writes++; return Task.CompletedTask; },
            BeforeReadback = () =>
            {
                readbacks++;
                fixture.Sql(mode switch
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
        Assert.Equal(mode == "missing" ? 11L : 12L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Null(result.Publication!.Candidate.OptionalDailyCatalog);
        Assert.Contains("daily", result.Publication.Candidate.UnavailableOptionalSources);
        Assert.Equal(3, result.Publication.Candidate.Items.Count);
        Assert.Equal("任務", result.Publication.Candidate.Expedition.Tasks[1].Name);
        Assert.True(result.Publication.Candidate.RequiredTablesStructurallyComplete);
        Assert.All(connections, connection => Assert.True(connection.WasDisposed));
        // The retained optional mismatch is not repaired by ordinary read-only refresh.
        byte[] before = fixture.Bytes();
        var refreshed = await owner.RefreshAsync();
        Assert.Null(refreshed.Candidate.OptionalDailyCatalog);
        Assert.Equal(before, fixture.Bytes()); Assert.Equal(1, writes); Assert.Equal(1, readbacks);
    }
}
