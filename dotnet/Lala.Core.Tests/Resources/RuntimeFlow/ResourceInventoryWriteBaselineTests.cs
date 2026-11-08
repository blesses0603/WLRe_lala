using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Theory]
    [InlineData(false, "1.3.22", false)]
    [InlineData(false, "1.3.22", true)]
    [InlineData(true, "1.3.22", false)]
    [InlineData(false, "1.3.21", false)]
    public async Task Older_preparation_cannot_overwrite_another_owners_committed_active_inventory(bool existing, string newerVersion, bool failRollback)
    {
        using var fixture = new Fixture();
        if (existing)
        {
            var seedSource = new Source { Snapshot = _ => RuntimeFlowFixtures.Snapshot(dataVersion: "1.3.20") };
            await using var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, seedSource);
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        }
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var staleSource = new Source { BeforeObserve = n =>
        {
            if (n != 1) return Task.CompletedTask;
            entered.TrySetResult(); return release.Task;
        } };
        ScriptedReadConnection? staleWriter = null;
        await using var staleOwner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, staleSource, bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                staleWriter = new ScriptedReadConnection(c);
                if (failRollback) staleWriter.BeforeExecute = (command, _) => { if (command.CommandText == "ROLLBACK") throw new IOException("synthetic rollback failure"); };
                return staleWriter;
            }
        });
        var stale = staleOwner.BootstrapAndRefreshAsync();
        try
        {
            await entered.Task.WaitAsync(Timeout); // Baseline capture has completed before this source call.
            var newSource = new Source { Snapshot = _ => RuntimeFlowFixtures.Snapshot(dataVersion: newerVersion) };
            await using var newer = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, newSource);
            var committed = await newer.BootstrapAndRefreshAsync(); Published(committed, newer);
            byte[] preserved = fixture.Bytes();
            release.TrySetResult();
            var rejected = await stale.WaitAsync(Timeout);
            Assert.True(rejected.StorageAttempted); Assert.Equal(failRollback ? ResourceInventoryWriteOutcome.Unknown : ResourceInventoryWriteOutcome.NotCommitted, rejected.StorageOutcome);
            Assert.False(rejected.CommitAdmitted); Assert.False(rejected.WasPublished); Assert.Null(staleOwner.Current);
            Assert.IsType<InvalidDataException>(rejected.Failure);
            Assert.Equal(committed.Publication!.Identity.Key, fixture.Sql("SELECT catalog_key FROM versions WHERE id=(SELECT active_id FROM sync_state WHERE singleton=1)"));
            Assert.Equal(preserved, fixture.Bytes());
            Assert.NotNull(staleWriter); Assert.Contains("BEGIN IMMEDIATE", staleWriter.Commands);
            Assert.DoesNotContain(staleWriter.Commands, sql => sql.StartsWith("INSERT", StringComparison.Ordinal));
            Assert.DoesNotContain("COMMIT", staleWriter.Commands); Assert.Contains("ROLLBACK", staleWriter.Commands);
            Assert.True(staleWriter.WasDisposed);
            Assert.Equal(existing ? 2L : 1L, fixture.Sql("SELECT count(*) FROM versions"));
        }
        finally { release.TrySetResult(); }
    }

    [Theory]
    [InlineData("raw")]
    [InlineData("derived")]
    [InlineData("identity")]
    [InlineData("identity-bytes")]
    [InlineData("unrelated")]
    public async Task Same_key_concurrent_rows_keep_existing_integrity_and_unrelated_table_contracts(string change)
    {
        using var fixture = new Fixture();
        await using (var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()))
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        fixture.Sql("CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES('original')");
        if (change == "identity-bytes") fixture.Sql("UPDATE version_identities SET identity=CAST(x'80' AS TEXT)");
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var source = new Source { BeforeObserve = n =>
        {
            if (n != 1) return Task.CompletedTask;
            entered.TrySetResult(); return release.Task;
        } };
        ScriptedReadConnection? writer = null;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = c => ReadOnly(c) ? c : writer = new ScriptedReadConnection(c)
        });
        var operation = owner.BootstrapAndRefreshAsync();
        try
        {
            await entered.Task.WaitAsync(Timeout);
            fixture.Sql(change switch
            {
                "raw" => "UPDATE resources SET data=x'00' WHERE name='Eve.bytes'",
                "derived" => "UPDATE parsed_resource_rows SET data='{}' WHERE rowid=(SELECT min(rowid) FROM parsed_resource_rows)",
                "identity" => "UPDATE version_identities SET identity='{}'",
                "identity-bytes" => "UPDATE version_identities SET identity=CAST(x'81' AS TEXT)",
                _ => "UPDATE retained SET value='concurrent'"
            });
            byte[] concurrent = fixture.Bytes();
            release.TrySetResult();
            var result = await operation.WaitAsync(Timeout);
            if (change == "unrelated")
            {
                Published(result, owner);
                Assert.Equal("concurrent", fixture.Sql("SELECT value FROM retained"));
            }
            else
            {
                Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, result.StorageOutcome);
                Assert.False(result.WasPublished); Assert.NotNull(result.Failure); Assert.Equal(concurrent, fixture.Bytes());
                if (change.StartsWith("identity", StringComparison.Ordinal))
                {
                    Assert.NotNull(writer);
                    Assert.DoesNotContain(writer.Commands, sql => sql.StartsWith("INSERT", StringComparison.Ordinal));
                }
            }
        }
        finally { release.TrySetResult(); }
    }

    [Theory]
    [InlineData("UTF-8")]
    [InlineData("UTF-16le")]
    [InlineData("UTF-16be")]
    public async Task Baseline_exact_bytes_support_existing_database_encodings(string encoding)
    {
        using var fixture = new Fixture(); Directory.CreateDirectory(Path.GetDirectoryName(fixture.Inventory)!);
        using (var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = fixture.Inventory, Pooling = false }.ToString()))
        {
            db.Open(); using var command = db.CreateCommand();
            command.CommandText = "PRAGMA encoding='" + encoding + "'; CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES('untouched')";
            command.ExecuteNonQuery();
        }
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(encoding, fixture.Sql("PRAGMA encoding")); Assert.Equal("untouched", fixture.Sql("SELECT value FROM retained"));
    }

    [Theory]
    [InlineData("identity")]
    [InlineData("selector")]
    [InlineData("empty-selector")]
    public async Task Baseline_preserves_supported_additive_legacy_schema_creation(string missing)
    {
        using var fixture = new Fixture(); Directory.CreateDirectory(Path.GetDirectoryName(fixture.Inventory)!);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        using (var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = fixture.Inventory, Pooling = false }.ToString()))
        {
            db.Open(); using var command = db.CreateCommand();
            command.CommandText = missing switch
            {
                "selector" => "CREATE TABLE versions(id INTEGER PRIMARY KEY,catalog_key TEXT UNIQUE NOT NULL); INSERT INTO versions VALUES(7,@key)",
                "empty-selector" => "CREATE TABLE sync_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),active_id INTEGER NOT NULL)",
                _ => "CREATE TABLE versions(id INTEGER PRIMARY KEY,catalog_key TEXT UNIQUE NOT NULL); INSERT INTO versions VALUES(7,@key); " +
                    "CREATE TABLE sync_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),active_id INTEGER NOT NULL); INSERT INTO sync_state VALUES(1,7)"
            };
            command.Parameters.AddWithValue("@key", prepared.Identity.Key); command.ExecuteNonQuery();
        }
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(prepared.Identity.CanonicalJson, fixture.Sql("SELECT identity FROM version_identities"));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Baseline_read_cleanup_or_cancellation_prevents_source_acquisition_and_writer(bool cancel)
    {
        using var fixture = new Fixture();
        await using (var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()))
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        using var caller = new CancellationTokenSource(); var source = new Source(); ScriptedReadConnection? baseline = null;
        var modes = new List<SqliteOpenMode>();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                modes.Add(new SqliteConnectionStringBuilder(c.ConnectionString).Mode);
                baseline = new ScriptedReadConnection(c);
                if (cancel) baseline.BeforeExecute = (command, _) => { if (command.CommandText.StartsWith("SELECT name,type,rootpage", StringComparison.Ordinal)) caller.Cancel(); };
                else baseline.DisposeError = new IOException("synthetic baseline cleanup failure");
                return baseline;
            }
        });
        byte[] before = fixture.Bytes();
        var result = await owner.BootstrapAndRefreshAsync(caller.Token);
        Assert.False(result.StorageAttempted); Assert.False(result.CommitAdmitted); Assert.False(result.WasPublished);
        Assert.NotNull(result.Failure); Assert.Equal(0, source.Observations);
        Assert.Equal(new[] { SqliteOpenMode.ReadOnly }, modes); Assert.NotNull(baseline); Assert.True(baseline.WasDisposed);
        Assert.Contains("BEGIN", baseline.Commands); Assert.DoesNotContain("BEGIN IMMEDIATE", baseline.Commands);
        Assert.Contains("ROLLBACK", baseline.Commands); Assert.Equal(before, fixture.Bytes());
    }

    [Fact]
    public async Task Baseline_identity_bounds_fail_before_source_or_mutation()
    {
        using var fixture = new Fixture();
        await using (var seed = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()))
            Published(await seed.BootstrapAndRefreshAsync(), seed);
        fixture.Sql("UPDATE version_identities SET identity=printf('%05000d',0)");
        byte[] before = fixture.Bytes(); var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.False(result.StorageAttempted); Assert.NotNull(result.Failure); Assert.Equal(0, source.Observations);
        Assert.Equal(before, fixture.Bytes());
    }

    [Fact]
    public async Task Unreadable_active_baseline_is_not_treated_as_empty_or_repaired()
    {
        using var fixture = new Fixture(); Directory.CreateDirectory(Path.GetDirectoryName(fixture.Inventory)!);
        using (var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = fixture.Inventory, Pooling = false }.ToString()))
        {
            db.Open(); using var command = db.CreateCommand();
            command.CommandText = "CREATE TABLE sync_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),active_id INTEGER NOT NULL); INSERT INTO sync_state VALUES(1,7)";
            command.ExecuteNonQuery();
        }
        byte[] before = fixture.Bytes(); var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.False(result.StorageAttempted); Assert.NotNull(result.Failure); Assert.Equal(0, source.Observations);
        Assert.Equal(before, fixture.Bytes());
    }
}
