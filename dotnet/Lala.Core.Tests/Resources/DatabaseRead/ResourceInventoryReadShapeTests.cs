using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class ResourceInventoryReadShapeTests
{
    private static (string Name, string Type)[] Columns(string table) => table switch
    {
        "sync_state" => [("singleton", "INTEGER"), ("active_id", "INTEGER")],
        "versions" => [("id", "INTEGER"), ("catalog_key", "TEXT")],
        "version_identities" => [("version_id", "INTEGER"), ("identity", "TEXT")],
        "resources" => [("version_id", "INTEGER"), ("name", "TEXT"), ("sha256", "TEXT"), ("data", "BLOB")],
        _ => throw new ArgumentOutOfRangeException(nameof(table))
    };
    public static IEnumerable<object[]> RequiredColumns()
    {
        foreach (string table in ResourceInventoryReadShape.SnapshotTables)
            foreach (var column in Columns(table))
                foreach (bool stored in new[] { false, true }) yield return [table, column.Name, stored];
    }
    public static IEnumerable<object[]> BaselineColumns() => RequiredColumns().Where(row => (string)row[0] != "resources");

    internal static void RegisterProbes(SqliteConnection connection, Action observed)
    {
        Assert.Equal(System.Data.ConnectionState.Open, connection.State);
        connection.CreateFunction<long, long>("shape_probe_integer", value => { observed(); return value; }, isDeterministic: true);
        connection.CreateFunction<string, string>("shape_probe_text", value => { observed(); return value; }, isDeterministic: true);
        connection.CreateFunction<byte[], byte[]>("shape_probe_blob", value => { observed(); return value; }, isDeterministic: true);
    }
    internal static ScriptedReadConnection WithReadProbes(SqliteConnection connection, Action observed)
    {
        var wrapped = new ScriptedReadConnection(connection);
        // Register on the opened native connection before BEGIN/value queries, so the
        // synthetic schema sees the deterministic function registrations on this handle.
        wrapped.BeforeExecute = (command, _) => { if (command.CommandText == "BEGIN") RegisterProbes(connection, observed); };
        return wrapped;
    }
    internal static void ReplaceWithGeneratedColumn(string file, string table, string column, bool stored = false, bool useProbe = true)
    {
        var columns = Columns(table); var selected = columns.Single(item => item.Name == column);
        string function = "shape_probe_" + selected.Type.ToLowerInvariant();
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = file, Pooling = false }.ToString());
        connection.Open(); RegisterProbes(connection, () => { });
        using var command = connection.CreateCommand();
        string expression = useProbe ? $"{function}(stored_{column})" : $"stored_{column}";
        string definition = string.Join(',', columns.Select(item => item.Name == column
            ? $"{item.Name} {item.Type} GENERATED ALWAYS AS ({expression}) " + (stored ? "STORED" : "VIRTUAL")
            : $"{item.Name} {item.Type}"));
        string targets = string.Join(',', columns.Select(item => item.Name == column ? "stored_" + column : item.Name));
        command.CommandText = $"ALTER TABLE main.{table} RENAME TO shape_original; " +
            $"CREATE TABLE main.{table} ({definition},stored_{column} {selected.Type}); " +
            $"INSERT INTO main.{table} ({targets}) SELECT {string.Join(',', columns.Select(item => item.Name))} FROM shape_original; " +
            "DROP TABLE shape_original";
        command.ExecuteNonQuery();
    }

    [Theory]
    [MemberData(nameof(RequiredColumns))]
    public async Task Snapshot_rejects_every_generated_required_column_before_reading_values(string table, string column, bool stored)
    {
        using var db = new DatabaseReadTestDatabase(); ReplaceWithGeneratedColumn(db.FileName, table, column, stored);
        byte[] before = File.ReadAllBytes(db.FileName); int probes = 0;
        var connection = WithReadProbes(db.Connection(), () => probes++);
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        Assert.Equal(0, probes); Assert.True(connection.WasDisposed);
        Assert.DoesNotContain(RuntimeDatabaseSnapshotReader.ActiveSql, connection.Commands);
        Assert.DoesNotContain(RuntimeDatabaseSnapshotReader.TableSql, connection.Commands);
        Assert.Contains("ROLLBACK", connection.Commands); Assert.Equal(before, File.ReadAllBytes(db.FileName));
    }

    [Theory]
    [MemberData(nameof(BaselineColumns))]
    public async Task Write_baseline_rejects_generated_identity_columns_before_values(string table, string column, bool stored)
    {
        using var db = new DatabaseReadTestDatabase(); ReplaceWithGeneratedColumn(db.FileName, table, column, stored);
        int probes = 0; var connection = WithReadProbes(db.Connection(), () => probes++);
        await Assert.ThrowsAsync<InvalidDataException>(() => ResourceInventoryWriteBaseline.CaptureAsync(connection, CancellationToken.None));
        Assert.Equal(0, probes); Assert.True(connection.WasDisposed);
        Assert.DoesNotContain(connection.Commands, sql => sql.StartsWith("SELECT CASE WHEN typeof(s.active_id)", StringComparison.Ordinal));
        Assert.Contains("ROLLBACK", connection.Commands); Assert.DoesNotContain("COMMIT", connection.Commands);
    }

    [Fact]
    public async Task Unread_extra_generated_column_does_not_change_required_stored_column_contract()
    {
        using var db = new DatabaseReadTestDatabase();
        using (var writer = db.Connection(false))
        {
            writer.Open(); RegisterProbes(writer, () => { }); using var command = writer.CreateCommand();
            command.CommandText = "ALTER TABLE resources ADD COLUMN ignored TEXT GENERATED ALWAYS AS (shape_probe_text('unused')) VIRTUAL";
            command.ExecuteNonQuery();
        }
        int probes = 0; var connection = WithReadProbes(db.Connection(), () => probes++);
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection);
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
        Assert.Equal(0, probes); Assert.False(result.RuntimeAdmitted);
    }

    [Theory]
    [InlineData("shape")]
    [InlineData("extra-result")]
    [InlineData("hidden")]
    [InlineData("cancel")]
    public async Task Column_metadata_failure_or_cancellation_disposes_without_value_query(string failure)
    {
        using var db = new DatabaseReadTestDatabase(); using var cancel = new CancellationTokenSource();
        string target = ResourceInventoryReadShape.ColumnsSql("resources");
        var connection = new ScriptedReadConnection(db.Connection());
        if (failure == "shape") connection.TransformFieldCount = (reader, count) => reader.Sql == target ? count + 1 : count;
        if (failure == "hidden") connection.TransformValue = (reader, ordinal, value) => reader.Sql == target && ordinal == 2 ? 2L : value;
        connection.BeforeExecute = (command, _) =>
        {
            if (command.CommandText != target) return;
            if (failure == "extra-result") connection.ExtraResultSql = target;
            if (failure == "cancel") cancel.Cancel();
        };
        if (failure == "cancel") await Assert.ThrowsAnyAsync<OperationCanceledException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, cancel.Token));
        else await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection));
        Assert.True(connection.WasDisposed); Assert.Contains("ROLLBACK", connection.Commands);
        Assert.DoesNotContain(RuntimeDatabaseSnapshotReader.ActiveSql, connection.Commands);
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
    }
}
