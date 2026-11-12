using System.Text;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public void Inventory_inspection_cleanup_failure_precedes_invalid_or_missing_but_preserves_cancellation()
    {
        var invalid = new InvalidDataException("synthetic primary failure");
        Assert.Equal(ResourceInventoryInspectionStatus.Invalid, ResourceInventoryInspector.ClassifyFailure(invalid));
        invalid.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey] = new[] { new IOException("synthetic cleanup failure") };
        Assert.Equal(ResourceInventoryInspectionStatus.Unavailable, ResourceInventoryInspector.ClassifyFailure(invalid));
        var missing = new FileNotFoundException("synthetic missing");
        missing.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey] = new[] { new IOException("synthetic cleanup failure") };
        Assert.Equal(ResourceInventoryInspectionStatus.Unavailable, ResourceInventoryInspector.ClassifyFailure(missing));
        var cancelled = new OperationCanceledException();
        cancelled.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey] = new[] { new IOException("synthetic cleanup failure") };
        Assert.Null(ResourceInventoryInspector.ClassifyFailure(cancelled));
        Assert.Equal(ResourceInventoryInspectionStatus.Unavailable, ResourceInventoryInspector.ClassifyFailure(new SqliteException("synthetic busy", 5)));
        Assert.Equal(ResourceInventoryInspectionStatus.Unavailable, ResourceInventoryInspector.ClassifyFailure(new UnauthorizedAccessException()));
        Assert.Null(ResourceInventoryInspector.ClassifyFailure(new InvalidOperationException("unexpected")));
    }

    [Fact]
    public async Task Inventory_inspection_reads_real_snapshot_without_source_or_inventory_mutation()
    {
        using var fixture = new Fixture(); var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var written = await owner.BootstrapAndRefreshAsync();
        byte[] before = fixture.Bytes(); int observations = source.Observations;
        var result = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.SelfConsistent, result.Status);
        Assert.Equal(written.Publication!.Identity.Key, result.CatalogIdentity);
        Assert.Equal(written.Publication.Identity.DataVersion, result.DataVersion);
        Assert.Equal(written.Publication.Identity.ExeVersion, result.ExeVersion);
        Assert.Equal(10, result.RequiredTables); Assert.True(result.RequiredTableBytes > 0);
        Assert.Equal(observations, source.Observations); Assert.Equal(before, fixture.Bytes());
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted);
        Assert.False(result.CanLogin); Assert.False(result.CanSendPackets);
    }

    [Fact]
    public async Task Inventory_inspection_missing_and_precancelled_never_create_storage()
    {
        using var fixture = new Fixture();
        var missing = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.Missing, missing.Status);
        Assert.Null(missing.CatalogIdentity); Assert.Equal(0, missing.RequiredTables);
        using var cancel = new CancellationTokenSource(); cancel.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => ResourceInventoryInspector.InspectAsync(fixture.Root, cancel.Token));
        await Assert.ThrowsAsync<ArgumentException>(() => ResourceInventoryInspector.InspectAsync("relative"));
        Assert.False(Directory.Exists(fixture.Root));
    }

    [Theory]
    [InlineData("blob")]
    [InlineData("digest")]
    [InlineData("missing-row")]
    [InlineData("identity-key")]
    [InlineData("duplicate-identity-key")]
    [InlineData("noncanonical-identity")]
    [InlineData("identity-schema")]
    [InlineData("extra-identity-field")]
    public async Task Inventory_inspection_rejects_inconsistent_or_noncanonical_storage(string mode)
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await owner.BootstrapAndRefreshAsync();
        if (mode == "blob") fixture.Sql("UPDATE resources SET data=x'00' WHERE name='Eve.bytes'");
        else if (mode == "digest") fixture.Sql("UPDATE resources SET sha256='invalid' WHERE name='Eve.bytes'");
        else if (mode == "missing-row") fixture.Sql("DELETE FROM resources WHERE name='Eve.bytes'");
        else if (mode == "identity-key") fixture.Sql("UPDATE versions SET catalog_key='invalid'");
        else
        {
            string identity = (string)fixture.Sql("SELECT identity FROM version_identities")!;
            identity = mode switch
            {
                "duplicate-identity-key" => identity.Replace("\"schema_version\":1", "\"schema_version\":1,\"schema_version\":1", StringComparison.Ordinal),
                "noncanonical-identity" => " " + identity,
                "identity-schema" => identity.Replace("\"schema_version\":1", "\"schema_version\":2", StringComparison.Ordinal),
                _ => identity[..^1] + ",\"extra\":true}"
            };
            RewriteLocalIdentity(fixture, identity); // Rehash too: schema/canonical validation must still reject.
        }
        byte[] before = fixture.Bytes();
        var result = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.Invalid, result.Status);
        Assert.Null(result.CatalogIdentity); Assert.Null(result.DataVersion); Assert.Equal(0, result.RequiredTables);
        Assert.Equal(before, fixture.Bytes());
    }

    private static void RewriteLocalIdentity(Fixture fixture, string identity)
    {
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = fixture.Inventory, Pooling = false }.ToString());
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "UPDATE version_identities SET identity=@identity; UPDATE versions SET catalog_key=@key";
        command.Parameters.AddWithValue("@identity", identity);
        command.Parameters.AddWithValue("@key", ResourceValidation.Digest(Encoding.ASCII.GetBytes(identity)));
        command.ExecuteNonQuery();
    }

    [Fact]
    public async Task Inventory_inspection_self_consistency_does_not_authenticate_forged_raw_bytes()
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await owner.BootstrapAndRefreshAsync();
        string forgedHash = ResourceValidation.Digest(new byte[] { 0 });
        fixture.Sql("UPDATE resources SET data=x'00',sha256='" + forgedHash + "' WHERE name='Eve.bytes'");
        var result = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.SelfConsistent, result.Status);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted); Assert.False(result.CanSendPackets);
        // Fresh source/database matching remains mandatory and rejects the forged local pair.
        await Assert.ThrowsAsync<ResourceValidationException>(() => owner.RefreshAsync());
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Inventory_inspection_after_unknown_commit_observes_storage_without_retry(bool committed)
    {
        using var fixture = new Fixture(); int commitExecutions = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                var writer = new ScriptedReadConnection(c);
                writer.BeforeExecute = (command, _) =>
                {
                    if (command.CommandText != "COMMIT") return;
                    commitExecutions++;
                    if (!committed) throw new IOException("synthetic unacknowledged commit");
                };
                writer.AfterExecute = command => { if (committed && command.CommandText == "COMMIT") throw new IOException("synthetic lost acknowledgment"); };
                return writer;
            }
        });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Equal(ResourceInventoryWriteOutcome.Unknown, result.StorageOutcome);
        var inspection = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(committed ? ResourceInventoryInspectionStatus.SelfConsistent : ResourceInventoryInspectionStatus.Invalid, inspection.Status);
        Assert.Equal(1, commitExecutions); Assert.Equal(ResourceInventoryWriteOutcome.Unknown, result.StorageOutcome);
        Assert.False(inspection.RuntimeAdmitted); Assert.Null(owner.Current);
    }

    [Fact]
    public async Task Inventory_inspection_rejects_non_database_file_without_repair()
    {
        using var fixture = new Fixture(); Directory.CreateDirectory(Path.GetDirectoryName(fixture.Inventory)!);
        byte[] bytes = Encoding.ASCII.GetBytes("synthetic invalid database");
        await File.WriteAllBytesAsync(fixture.Inventory, bytes);
        var result = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.Invalid, result.Status);
        Assert.Equal(bytes, fixture.Bytes());
    }

    [Fact]
    public async Task Inventory_inspection_enforces_32_MiB_aggregate_before_detaching_snapshot()
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await owner.BootstrapAndRefreshAsync();
        fixture.Sql("UPDATE resources SET data=zeroblob(16777216) WHERE name IN ('Eve.bytes','ItemData_C.bytes','TalkData_C.bytes')");
        var result = await ResourceInventoryInspector.InspectAsync(fixture.Root);
        Assert.Equal(ResourceInventoryInspectionStatus.Invalid, result.Status); Assert.Equal(0, result.RequiredTableBytes);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(167772161)]
    public async Task Snapshot_aggregate_budget_failure_still_disposes_read_scope(long budget)
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await owner.BootstrapAndRefreshAsync();
        var connection = new ScriptedReadConnection(new SqliteConnection(new SqliteConnectionStringBuilder
        { DataSource = fixture.Inventory, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString()));
        if (budget == 1)
        {
            await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, maximumAggregateBytes: budget));
            Assert.Contains("ROLLBACK", connection.Commands);
        }
        else await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, maximumAggregateBytes: budget));
        Assert.True(connection.WasDisposed);
    }
}
