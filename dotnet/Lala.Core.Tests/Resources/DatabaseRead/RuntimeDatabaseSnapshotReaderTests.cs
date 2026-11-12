using System.Data;
using System.Data.Common;
using System.Reflection;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseSnapshotReaderTests
{
    [Fact]
    public async Task Real_read_only_sqlite_returns_owned_ten_table_observation_without_modifying_file()
    {
        using var db = new DatabaseReadTestDatabase(); byte[] before = File.ReadAllBytes(db.FileName);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection);
        Assert.True(result.CompletedSingleReadTransaction); AssertNonAuthorizing(result);
        var match = RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.True(match.MatchesSuppliedRuntime); Assert.False(match.ProvesDatabaseTransaction); Assert.False(match.RuntimeAdmitted);
        Assert.Equal(before, File.ReadAllBytes(db.FileName));
        Assert.Equal(new[] { "BEGIN", RuntimeDatabaseSnapshotReader.SchemaSql }
            .Concat(ResourceInventoryReadShape.SnapshotTables.Select(ResourceInventoryReadShape.ColumnsSql))
            .Concat(new[] { RuntimeDatabaseSnapshotReader.EncodingSql, RuntimeDatabaseSnapshotReader.ActiveSql })
            .Concat(Enumerable.Repeat(RuntimeDatabaseSnapshotReader.TableSql, 10)).Append("ROLLBACK"), connection.Commands);
        Assert.All(connection.CreatedCommands, command => { Assert.True(command.WasDisposed); Assert.Equal(5, command.CommandTimeout); });
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed)); Assert.True(connection.WasDisposed);
        var tableCommands = connection.CreatedCommands.Where(command => command.CommandText == RuntimeDatabaseSnapshotReader.TableSql).ToArray();
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes"), tableCommands.Select(command => (string)command.Parameters["@name"].Value!));
        Assert.All(tableCommands, command => { Assert.Equal(DbType.Int64, command.Parameters["@version"].DbType); Assert.Equal(41L, command.Parameters["@version"].Value); });
        db.Execute("UPDATE resources SET data=x'00',sha256='changed'");
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
    }

    [Fact]
    public async Task Wal_writer_between_active_and_payload_queries_cannot_mix_database_generations()
    {
        using var db = new DatabaseReadTestDatabase(); db.Execute("PRAGMA journal_mode=WAL");
        var connection = new ScriptedReadConnection(db.Connection()); bool changed = false;
        connection.BeforeExecute = (command, _) =>
        {
            if (command.CommandText != RuntimeDatabaseSnapshotReader.TableSql || changed) return;
            changed = true;
            db.Execute("BEGIN; INSERT INTO versions VALUES(42,'new-generation');" +
                "INSERT INTO version_identities VALUES(42,'{}'); UPDATE sync_state SET active_id=42;" +
                "UPDATE resources SET data=x'01',sha256='tampered' WHERE version_id=41; COMMIT");
        };
        var old = await RuntimeDatabaseSnapshotReader.ReadAsync(connection);
        Assert.True(changed); Assert.Equal(41, old.Snapshot.Active!.VersionId);
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(old.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
        // A later attempt sees the new active version and must not reuse the prior owned rows.
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(db.Connection()));
    }

    [Fact]
    public async Task Read_only_provider_configuration_is_real_but_not_inferred_by_the_generic_seam()
    {
        using var db = new DatabaseReadTestDatabase();
        using (var connection = db.Connection())
        {
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = "DELETE FROM resources";
            var error = Assert.Throws<SqliteException>(() => command.ExecuteNonQuery()); Assert.Equal(8, error.SqliteErrorCode);
        }
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(db.Connection()); AssertNonAuthorizing(result);
    }

    [Theory]
    [InlineData("before-open")]
    [InlineData("after-begin")]
    [InlineData("during-first-blob")]
    [InlineData("before-last-table")]
    [InlineData("during-rollback")]
    public async Task Cancellation_never_publishes_a_partial_observation_and_cleanup_ignores_cancelled_token(string stage)
    {
        using var db = new DatabaseReadTestDatabase(); using var cts = new CancellationTokenSource();
        var connection = new ScriptedReadConnection(db.Connection()); bool rollback = false;
        connection.BeforeExecute = (command, token) =>
        {
            if (command.CommandText == "ROLLBACK") { rollback = true; Assert.False(token.CanBeCanceled); if (stage == "during-rollback") cts.Cancel(); }
            if (command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && stage == "before-last-table" &&
                (string)command.Parameters["@name"].Value! == "NpcCareerData_C.bytes") cts.Cancel();
        };
        connection.AfterExecute = command => { if (command.CommandText == "BEGIN" && stage == "after-begin") cts.Cancel(); };
        connection.BeforeBlobRead = reader => { if (stage == "during-first-blob" && reader.BlobReads == 1) cts.Cancel(); };
        if (stage == "before-open") cts.Cancel();
        RuntimeDatabaseReadObservation? result = null;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, cts.Token));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal(stage != "before-open", rollback);
        Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
    }

    [Fact]
    public async Task Open_failure_disposes_connection_without_begin_or_rollback()
    {
        using var db = new DatabaseReadTestDatabase(); var primary = new InvalidOperationException("open failure");
        var connection = new ScriptedReadConnection(db.Connection()) { OpenError = primary };
        Assert.Same(primary, await Assert.ThrowsAsync<InvalidOperationException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection)));
        Assert.Empty(connection.Commands); Assert.True(connection.WasDisposed);
    }

    [Fact]
    public async Task Already_open_connection_is_rejected_and_disposed_under_exclusive_ownership_contract()
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection()); connection.Open();
        await Assert.ThrowsAsync<InvalidOperationException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        Assert.Empty(connection.Commands); Assert.True(connection.WasDisposed);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Failed_or_uncertain_begin_still_attempts_rollback_and_preserves_primary(bool executed)
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        var primary = new InvalidOperationException("begin failed");
        connection.BeforeExecute = (command, _) => { if (!executed && command.CommandText == "BEGIN") throw primary; };
        connection.AfterExecute = command => { if (executed && command.CommandText == "BEGIN") throw primary; };
        Assert.Same(primary, await Assert.ThrowsAsync<InvalidOperationException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection)));
        Assert.Equal(new[] { "BEGIN", "ROLLBACK" }, connection.Commands); Assert.True(connection.WasDisposed);
        if (!executed) Assert.True(primary.Data.Contains(RuntimeDatabaseSnapshotReader.CleanupFailuresKey));
    }

    [Fact]
    public async Task Primary_read_failure_survives_reader_command_rollback_and_connection_cleanup_failures()
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        var primary = new InvalidDataException("primary read failure");
        var readerFailure = new IOException("reader dispose"); var commandFailure = new IOException("command dispose");
        var rollbackFailure = new IOException("rollback"); var connectionFailure = new IOException("connection dispose");
        connection.DisposeError = connectionFailure;
        connection.BeforeExecute = (command, _) =>
        {
            if (command.CommandText == RuntimeDatabaseSnapshotReader.TableSql)
            { connection.CommandDisposeError = commandFailure; connection.ReaderDisposeError = readerFailure; }
            if (command.CommandText == "ROLLBACK") { connection.CommandDisposeError = null; throw rollbackFailure; }
        };
        connection.TransformValue = (reader, _, value) => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql ? throw primary : value;
        Assert.Same(primary, await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection)));
        var cleanup = Assert.IsAssignableFrom<IReadOnlyList<Exception>>(primary.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey]);
        Assert.Equal(new Exception[] { readerFailure, commandFailure, rollbackFailure, connectionFailure }, cleanup);
        Assert.True(connection.WasDisposed); Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
    }

    [Theory]
    [InlineData("rollback")]
    [InlineData("dispose")]
    public async Task Successful_reads_do_not_publish_if_scope_cleanup_is_uncertain(string stage)
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        var failure = new IOException(stage);
        if (stage == "dispose") connection.DisposeError = failure;
        else connection.BeforeExecute = (command, _) => { if (command.CommandText == "ROLLBACK") throw failure; };
        RuntimeDatabaseReadObservation? result = null;
        var error = await Assert.ThrowsAsync<AggregateException>(async () => result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        Assert.Null(result); Assert.Same(failure, Assert.Single(error.InnerExceptions)); Assert.True(connection.WasDisposed);
    }

    [Theory]
    [InlineData("long-length")]
    [InlineData("wrong-storage-type")]
    [InlineData("wrong-clr-type")]
    [InlineData("truncated")]
    [InlineData("trailing")]
    [InlineData("null")]
    public async Task Scripted_provider_type_and_materialized_length_anomalies_fail_closed(string anomaly)
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        connection.TransformValue = (reader, ordinal, value) =>
        {
            if (reader.Sql != RuntimeDatabaseSnapshotReader.TableSql) return value;
            if (anomaly == "long-length" && ordinal == 4) return long.MaxValue;
            if (anomaly == "wrong-storage-type" && ordinal == 3) return "text";
            if (ordinal == 5) return anomaly switch {
                "wrong-clr-type" => new ReadOnlyMemory<byte>((byte[])value),
                "truncated" => ((byte[])value)[..^1],
                "trailing" => ((byte[])value).Concat(new byte[] { 0 }).ToArray(),
                "null" => DBNull.Value,
                _ => value };
            return value;
        };
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        if (anomaly is "long-length" or "wrong-storage-type")
            Assert.Equal(0, connection.Readers.Single(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).BlobReads);
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Fact]
    public async Task Large_blob_materialization_followed_by_cancellation_cannot_publish_a_snapshot()
    {
        using var db = new DatabaseReadTestDatabase(); byte[] blob = new byte[256 * 1024]; Array.Fill(blob, (byte)0xa7);
        db.Execute("UPDATE resources SET data=@p0,sha256=@p1 WHERE name='Eve.bytes'", blob, DatabaseReadTestDatabase.Sha(blob));
        using var cts = new CancellationTokenSource(); var connection = new ScriptedReadConnection(db.Connection());
        connection.TransformValue = (reader, ordinal, value) =>
        { if (reader.Sql == RuntimeDatabaseSnapshotReader.TableSql && ordinal == 5) cts.Cancel(); return value; };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, cts.Token));
        Assert.Equal(1, connection.Readers.Single(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).BlobReads);
        Assert.True(connection.WasDisposed);
    }

    [Fact]
    public async Task Provider_arrays_are_copied_before_the_next_row_can_reuse_or_mutate_them()
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        byte[]? prior = null;
        connection.BeforeExecute = (command, _) => { if (prior is not null) Array.Fill(prior, (byte)0); };
        connection.TransformValue = (reader, ordinal, value) =>
        { if (reader.Sql == RuntimeDatabaseSnapshotReader.TableSql && ordinal == 5) prior = (byte[])value; return value; };
        var observation = await RuntimeDatabaseSnapshotReader.ReadAsync(connection);
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(observation.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
    }

    [Theory]
    [InlineData("schema", false)]
    [InlineData("schema", true)]
    [InlineData("encoding", false)]
    [InlineData("encoding", true)]
    [InlineData("active", false)]
    [InlineData("active", true)]
    [InlineData("table", false)]
    [InlineData("table", true)]
    public async Task Unexpected_projection_columns_or_result_sets_are_rejected(string stage, bool extraResult)
    {
        using var db = new DatabaseReadTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        string sql = stage switch { "schema" => RuntimeDatabaseSnapshotReader.SchemaSql, "encoding" => RuntimeDatabaseSnapshotReader.EncodingSql,
            "active" => RuntimeDatabaseSnapshotReader.ActiveSql, _ => RuntimeDatabaseSnapshotReader.TableSql };
        if (extraResult) connection.ExtraResultSql = sql;
        else connection.TransformFieldCount = (reader, count) => reader.Sql == sql ? count + 1 : count;
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Fact]
    public async Task Cancellation_remains_primary_when_rollback_and_disposal_also_fail()
    {
        using var db = new DatabaseReadTestDatabase(); using var cts = new CancellationTokenSource();
        var connection = new ScriptedReadConnection(db.Connection()) { DisposeError = new IOException("dispose") };
        connection.AfterExecute = command => { if (command.CommandText == "BEGIN") cts.Cancel(); };
        connection.BeforeExecute = (command, _) => { if (command.CommandText == "ROLLBACK") throw new IOException("rollback"); };
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, cts.Token));
        Assert.Equal(cts.Token, error.CancellationToken);
        Assert.Equal(2, Assert.IsAssignableFrom<IReadOnlyList<Exception>>(error.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey]).Count);
        Assert.True(connection.WasDisposed);
    }

    [Fact]
    public void Reader_remains_provider_neutral_and_internal_with_concrete_owner_isolated()
    {
        Assert.False(typeof(RuntimeDatabaseSnapshotReader).IsPublic); Assert.False(typeof(RuntimeDatabaseReadObservation).IsPublic);
        // Core now deliberately owns a concrete SQLite connection in ResourceRuntimeOwner.
        // The reusable reader must still accept provider-neutral connections and expose no
        // concrete provider types, so scripted providers exercise the identical reader path.
        var reader = typeof(RuntimeDatabaseSnapshotReader);
        foreach (var member in reader.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.DeclaredOnly))
        {
            Assert.DoesNotContain("Sqlite", member.ReturnType.ToString(), StringComparison.OrdinalIgnoreCase);
            foreach (var parameter in member.GetParameters())
                Assert.DoesNotContain("Sqlite", parameter.ParameterType.ToString(), StringComparison.OrdinalIgnoreCase);
        }
        Assert.False(typeof(ResourceRuntimeOwner).IsPublic);
        var factory = typeof(ResourceRuntimeOwner).GetMethod("Create", BindingFlags.NonPublic | BindingFlags.Static)!;
        Assert.Equal(typeof(string), Assert.Single(factory.GetParameters()).ParameterType);
        Assert.DoesNotContain(reader.Assembly.GetReferencedAssemblies(), name =>
            name.Name!.StartsWith("Avalonia", StringComparison.Ordinal) ||
            name.Name.StartsWith("Mono.Android", StringComparison.Ordinal) ||
            name.Name is "PresentationFramework" or "WindowsBase");
        MethodInfo method = typeof(RuntimeDatabaseSnapshotReader).GetMethod("ReadAsync", BindingFlags.NonPublic | BindingFlags.Static)!;
        Assert.Equal(typeof(DbConnection), method.GetParameters()[0].ParameterType);
        Assert.DoesNotContain(method.GetCustomAttributesData(), attribute => attribute.AttributeType.Name == "SupportedOSPlatformAttribute");
    }

    private static void AssertNonAuthorizing(RuntimeDatabaseReadObservation result)
    { Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets); }
}
