using System.Data;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseOptionalDailyCatalogTests
{
    private const string TaskTable = "DailyTaskData_C.bytes";
    private const string RewardTable = "DailyTaskRewardData_C.bytes";
    private const string SkillTable = "SkillData_C.bytes";
    private static readonly byte[] TaskBytes = [1, 0, 0, 0, 7, 9];
    private static readonly byte[] RewardBytes = [1, 0, 0, 0, 8, 10, 11];
    private static readonly byte[] SkillBytes = [1, 0, 0, 0, 2];
    private static string TaskSha => DatabaseReadTestDatabase.Sha(TaskBytes);
    private static string RewardSha => DatabaseReadTestDatabase.Sha(RewardBytes);

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Daily_capture_requires_its_own_opt_in_and_does_not_change_required_or_skill_matching(bool includeSkill)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db); AddSkill(db);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: includeSkill);

        AssertRequiredMatch(result);
        Assert.Null(result.Snapshot.Table(41, TaskTable)); Assert.Null(result.Snapshot.Table(41, RewardTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(result.Snapshot, TaskSha, RewardSha));
        Assert.Equal(includeSkill, result.Snapshot.Table(41, SkillTable) is not null);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(result.Snapshot));
        var expected = BundleSourcePlan.RequiredTables.Select(name => name + ".bytes");
        Assert.Equal(includeSkill ? expected.Append(SkillTable) : expected, TableQueries(connection));
        var extraDigests = DatabaseReadTestDatabase.Digests();
        extraDigests.Add("DailyTaskData_C", TaskSha); extraDigests.Add("DailyTaskRewardData_C", RewardSha);
        Assert.False(RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), extraDigests).MatchesSuppliedRuntime);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Explicit_read_owns_exact_daily_slots_in_one_read_only_transaction(bool includeSkill)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db); AddSkill(db);
        db.Execute("INSERT INTO resources VALUES(41,'Other.bytes','unused',x'00')");
        byte[] before = File.ReadAllBytes(db.FileName);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: includeSkill, includeDailyCatalog: true);

        AssertRequiredMatch(result); AssertDailyMatch(result);
        Assert.Equal(before, File.ReadAllBytes(db.FileName));
        var expected = BundleSourcePlan.RequiredTables.Select(name => name + ".bytes");
        if (includeSkill) expected = expected.Append(SkillTable);
        Assert.Equal(expected.Append(TaskTable).Append(RewardTable), TableQueries(connection));
        Assert.Equal("BEGIN", connection.Commands[0]); Assert.Equal("ROLLBACK", connection.Commands[^1]);
        Assert.Single(connection.Commands, sql => sql == "BEGIN");
        Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed)); Assert.True(connection.WasDisposed);
        foreach (var command in connection.CreatedCommands.Where(command => command.CommandText == RuntimeDatabaseSnapshotReader.TableSql))
        {
            Assert.Equal(DbType.Int64, command.Parameters["@version"].DbType); Assert.Equal(41L, command.Parameters["@version"].Value);
            Assert.Equal(DbType.String, command.Parameters["@name"].DbType); Assert.Equal(5, command.CommandTimeout);
        }
        Assert.Equal(TaskBytes, result.Snapshot.Table(41, TaskTable)!.Bytes.ToArray());
        Assert.Equal(RewardBytes, result.Snapshot.Table(41, RewardTable)!.Bytes.ToArray());
        Assert.Null(result.Snapshot.Table(41, "Other.bytes"));
        Assert.Equal(includeSkill, result.Snapshot.Table(41, SkillTable) is not null);
        // Daily claims do not weaken the separately compiled skill fingerprint.
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(result.Snapshot));
        db.Execute("UPDATE resources SET data=x'00',sha256='changed' WHERE name IN (@p0,@p1)", TaskTable, RewardTable);
        AssertDailyMatch(result); AssertRequiredMatch(result);
    }

    public static IEnumerable<object[]> MalformedRows() =>
        from name in new[] { TaskTable, RewardTable }
        from anomaly in new[] { "missing", "empty", "text", "non-text-digest", "long-digest", "oversized", "wrong-version", "wrong-case", "duplicate", "null" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(MalformedRows))]
    public async Task Missing_or_malformed_daily_row_only_disables_daily_matching(string name, string anomaly)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db); AddSkill(db);
        switch (anomaly)
        {
            case "missing": db.Execute("DELETE FROM resources WHERE name=@p0", name); break;
            case "empty": db.Execute("UPDATE resources SET data=x'' WHERE name=@p0", name); break;
            case "text": db.Execute("UPDATE resources SET data='not-a-blob' WHERE name=@p0", name); break;
            case "non-text-digest": db.Execute("UPDATE resources SET sha256=x'00' WHERE name=@p0", name); break;
            case "long-digest": db.Execute("UPDATE resources SET sha256=@p0 WHERE name=@p1", new string('a', 257), name); break;
            case "oversized": db.Execute("UPDATE resources SET data=zeroblob(@p0) WHERE name=@p1", OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1, name); break;
            case "wrong-version": db.Execute("UPDATE resources SET version_id=42 WHERE name=@p0", name); break;
            case "wrong-case": db.Execute("UPDATE resources SET name=@p0 WHERE name=@p1", name.ToLowerInvariant(), name); break;
            case "duplicate":
            case "null":
                db.Execute("ALTER TABLE resources RENAME TO old_resources; CREATE TABLE resources(version_id INTEGER, name TEXT, sha256 TEXT, data BLOB); INSERT INTO resources SELECT * FROM old_resources; DROP TABLE old_resources");
                if (anomaly == "duplicate") db.Execute("INSERT INTO resources SELECT * FROM resources WHERE name=@p0", name);
                else db.Execute("UPDATE resources SET data=NULL WHERE name=@p0", name);
                break;
        }
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true, includeDailyCatalog: true);

        AssertRequiredMatch(result); Assert.Null(result.Snapshot.Table(41, name));
        Assert.NotNull(result.Snapshot.Table(41, name == TaskTable ? RewardTable : TaskTable));
        Assert.Equal(SkillBytes, result.Snapshot.Table(41, SkillTable)!.Bytes.ToArray());
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(result.Snapshot, TaskSha, RewardSha));
        Assert.Equal(13, TableQueries(connection).Count());
        if (anomaly == "oversized")
        {
            int index = name == TaskTable ? 11 : 12;
            Assert.Equal(0, connection.Readers.Where(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).ElementAt(index).BlobReads);
        }
    }

    [Theory]
    [InlineData(false, 0, false, false)]
    [InlineData(false, 5, false, false)]
    [InlineData(false, 6, true, false)]
    [InlineData(false, 12, true, false)]
    [InlineData(false, 13, true, true)]
    [InlineData(true, 5, false, false)]
    [InlineData(true, 10, false, false)]
    [InlineData(true, 11, true, false)]
    [InlineData(true, 17, true, false)]
    [InlineData(true, 18, true, true)]
    public async Task Required_skill_and_both_daily_rows_share_one_budget_before_blob_materialization(
        bool includeSkill, int remaining, bool taskFits, bool rewardFits)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db); AddSkill(db);
        long requiredBytes = RequiredRows().Values.Sum(row => (long)row!.Data!.Value.Length);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, maximumAggregateBytes: requiredBytes + remaining,
            includeSkillData: includeSkill, includeDailyCatalog: true);

        AssertRequiredMatch(result);
        Assert.Equal(includeSkill, result.Snapshot.Table(41, SkillTable) is not null);
        Assert.Equal(taskFits, result.Snapshot.Table(41, TaskTable) is not null);
        Assert.Equal(rewardFits, result.Snapshot.Table(41, RewardTable) is not null);
        Assert.Equal(taskFits && rewardFits, RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(result.Snapshot, TaskSha, RewardSha));
        var dailyReaders = connection.Readers.Where(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).TakeLast(2).ToArray();
        Assert.Equal(taskFits ? 1 : 0, dailyReaders[0].BlobReads); Assert.Equal(rewardFits ? 1 : 0, dailyReaders[1].BlobReads);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Required_row_failure_remains_fatal_before_daily_read(bool malformed)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        db.Execute(malformed ? "UPDATE resources SET data=x'' WHERE name='Eve.bytes'" : "DELETE FROM resources WHERE name='Eve.bytes'");
        var connection = new ScriptedReadConnection(db.Connection());
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true));
        Assert.DoesNotContain(TaskTable, TableQueries(connection)); Assert.DoesNotContain(RewardTable, TableQueries(connection));
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Fact]
    public async Task Both_daily_rows_observe_the_required_rows_wal_snapshot()
    {
        using var db = new DatabaseReadTestDatabase(); db.Execute("PRAGMA journal_mode=WAL"); AddDaily(db);
        var connection = new ScriptedReadConnection(db.Connection()); bool changed = false;
        connection.BeforeExecute = (command, _) =>
        {
            if (!IsTable(command, RewardTable)) return;
            changed = true;
            db.Execute("UPDATE resources SET data=x'00',sha256=@p0 WHERE name IN (@p1,@p2)", DatabaseReadTestDatabase.Sha([0]), TaskTable, RewardTable);
        };
        var first = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true);
        Assert.True(changed); AssertRequiredMatch(first); AssertDailyMatch(first);
        var later = await RuntimeDatabaseSnapshotReader.ReadAsync(db.Connection(), includeDailyCatalog: true);
        AssertRequiredMatch(later);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(later.Snapshot, TaskSha, RewardSha));
        Assert.Equal(new byte[] { 0 }, later.Snapshot.Table(41, TaskTable)!.Bytes.ToArray());
        Assert.Equal(new byte[] { 0 }, later.Snapshot.Table(41, RewardTable)!.Bytes.ToArray());
    }

    public static IEnumerable<object[]> ProviderFailures() =>
        from name in new[] { TaskTable, RewardTable }
        from stage in new[] { "execute", "value", "reader-dispose", "command-dispose" }
        select new object[] { name, stage };

    [Theory]
    [MemberData(nameof(ProviderFailures))]
    public async Task Daily_provider_and_cleanup_failures_cannot_publish_any_observation(string name, string stage)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        var failure = new InvalidDataException("provider failure, not optional validation");
        var connection = new ScriptedReadConnection(db.Connection()); bool target = false;
        connection.BeforeExecute = (command, _) =>
        {
            target = IsTable(command, name);
            connection.ReaderDisposeError = target && stage == "reader-dispose" ? failure : null;
            connection.CommandDisposeError = target && stage == "command-dispose" ? failure : null;
            if (target && stage == "execute") throw failure;
        };
        connection.TransformValue = (_, _, value) => target && stage == "value" ? throw failure : value;
        RuntimeDatabaseReadObservation? result = null;
        Assert.Same(failure, await Assert.ThrowsAsync<InvalidDataException>(async () =>
            result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true)));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    public static IEnumerable<object[]> MalformedProjections() =>
        from name in new[] { TaskTable, RewardTable }
        from anomaly in new[] { "projection", "extra-result", "wrong-clr-type", "truncated", "null", "long-length" }
        select new object[] { name, anomaly };

    [Theory]
    [MemberData(nameof(MalformedProjections))]
    public async Task Malformed_daily_projection_is_absent_without_invalidating_the_other_daily_row(string name, string anomaly)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        var connection = new ScriptedReadConnection(db.Connection()); bool target = false;
        connection.BeforeExecute = (command, _) =>
        {
            target = IsTable(command, name);
            connection.ExtraResultSql = target && anomaly == "extra-result" ? RuntimeDatabaseSnapshotReader.TableSql : null;
        };
        connection.TransformFieldCount = (_, count) => target && anomaly == "projection" ? count + 1 : count;
        connection.TransformValue = (_, ordinal, value) =>
        {
            if (!target) return value;
            if (anomaly == "long-length" && ordinal == 4) return long.MaxValue;
            if (ordinal != 5) return value;
            return anomaly switch
            {
                "wrong-clr-type" => new ReadOnlyMemory<byte>((byte[])value),
                "truncated" => ((byte[])value)[..^1], "null" => DBNull.Value, _ => value
            };
        };
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true);
        AssertRequiredMatch(result); Assert.Null(result.Snapshot.Table(41, name));
        Assert.NotNull(result.Snapshot.Table(41, name == TaskTable ? RewardTable : TaskTable));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(result.Snapshot, TaskSha, RewardSha));
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Theory]
    [InlineData(TaskTable, false)]
    [InlineData(TaskTable, true)]
    [InlineData(RewardTable, false)]
    [InlineData(RewardTable, true)]
    public async Task Cancellation_during_either_daily_read_cannot_publish_a_partial_snapshot(string name, bool materializing)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        using var cts = new CancellationTokenSource();
        var connection = new ScriptedReadConnection(db.Connection()); bool target = false;
        connection.BeforeExecute = (command, _) => { target = IsTable(command, name); if (target && !materializing) cts.Cancel(); };
        connection.BeforeBlobRead = _ => { if (target && materializing) cts.Cancel(); };
        RuntimeDatabaseReadObservation? result = null;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, cts.Token, includeDailyCatalog: true));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Cleanup_after_valid_daily_reads_is_fatal(bool rollback)
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        var failure = new IOException("cleanup failed"); var connection = new ScriptedReadConnection(db.Connection());
        if (rollback) connection.BeforeExecute = (command, _) => { if (command.CommandText == "ROLLBACK") throw failure; };
        else connection.DisposeError = failure;
        RuntimeDatabaseReadObservation? result = null;
        var error = await Assert.ThrowsAsync<AggregateException>(async () =>
            result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true));
        Assert.Same(failure, Assert.Single(error.InnerExceptions));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal(12, TableQueries(connection).Count());
    }

    [Fact]
    public async Task Daily_primary_failure_survives_all_cleanup_failures()
    {
        using var db = new DatabaseReadTestDatabase(); AddDaily(db);
        var failure = new InvalidDataException("daily provider failed"); var cleanup = new IOException("cleanup failed");
        var connection = new ScriptedReadConnection(db.Connection()) { DisposeError = cleanup };
        bool target = false;
        connection.BeforeExecute = (command, _) =>
        {
            target = IsTable(command, RewardTable);
            if (target) { connection.ReaderDisposeError = cleanup; connection.CommandDisposeError = cleanup; }
            if (command.CommandText == "ROLLBACK") throw cleanup;
        };
        connection.TransformValue = (_, _, value) => target ? throw failure : value;
        Assert.Same(failure, await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeDailyCatalog: true)));
        var secondary = Assert.IsAssignableFrom<IEnumerable<Exception>>(failure.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey]);
        Assert.Equal(4, secondary.Count()); Assert.All(secondary, item => Assert.Same(cleanup, item));
        Assert.True(connection.WasDisposed);
    }

    private static bool IsTable(TrackedReadCommand command, string name) =>
        command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && (string)command.Parameters["@name"].Value! == name;
    private static void AddDaily(DatabaseReadTestDatabase db)
    {
        db.Execute("INSERT INTO resources VALUES(41,@p0,@p1,@p2)", TaskTable, TaskSha, TaskBytes);
        db.Execute("INSERT INTO resources VALUES(41,@p0,@p1,@p2)", RewardTable, RewardSha, RewardBytes);
    }
    private static void AddSkill(DatabaseReadTestDatabase db) =>
        db.Execute("INSERT INTO resources VALUES(41,@p0,@p1,@p2)", SkillTable, SkillDataParser.ReviewedSha256, SkillBytes);
    private static IEnumerable<string> TableQueries(ScriptedReadConnection connection) => connection.CreatedCommands
        .Where(command => command.CommandText == RuntimeDatabaseSnapshotReader.TableSql).Select(command => (string)command.Parameters["@name"].Value!);
    private static void AssertDailyMatch(RuntimeDatabaseReadObservation result) =>
        Assert.True(RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(result.Snapshot, TaskSha, RewardSha));
    private static void AssertRequiredMatch(RuntimeDatabaseReadObservation result)
    {
        var match = RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.True(result.CompletedSingleReadTransaction); Assert.True(match.MatchesSuppliedRuntime);
        Assert.Equal(BundleSourcePlan.RequiredTables, match.ExaminedSources);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
        Assert.False(match.HasVerifiedProvenance); Assert.False(match.RuntimeAdmitted); Assert.False(match.ProvesDatabaseTransaction);
    }
    private static Dictionary<string, RuntimeDatabaseTableInput?> RequiredRows() => DatabaseMatchPythonVectors.Case("all-ten-match").GetProperty("rows").EnumerateArray()
        .ToDictionary(row => row.GetProperty("name").GetString()!, row => (RuntimeDatabaseTableInput?)new RuntimeDatabaseTableInput(
            row.GetProperty("active_id").GetInt64(), row.GetProperty("name").GetString(), row.GetProperty("sha256").GetString(),
            Convert.FromBase64String(row.GetProperty("data").GetProperty("value").GetString()!)), StringComparer.Ordinal);
}
