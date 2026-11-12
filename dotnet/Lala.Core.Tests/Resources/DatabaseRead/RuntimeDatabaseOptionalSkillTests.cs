using System.Collections;
using System.Data;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class RuntimeDatabaseOptionalSkillTests
{
    private const string Skill = "SkillData_C.bytes";
    private static readonly byte[] SyntheticSkill = [1, 0, 0, 0, 7, 9];

    [Fact]
    public async Task Default_reader_ignores_optional_rows_and_preserves_exact_ten_table_matching()
    {
        using var db = new DatabaseReadTestDatabase();
        AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection);

        AssertRequiredMatch(result);
        Assert.Null(result.Snapshot.Table(41, Skill));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(result.Snapshot));
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes"), TableQueries(connection));
        var elevenDigests = DatabaseReadTestDatabase.Digests();
        elevenDigests.Add("SkillData_C", SkillDataParser.ReviewedSha256);
        Assert.False(RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), elevenDigests).MatchesSuppliedRuntime);
    }

    [Fact]
    public async Task Explicit_read_captures_only_one_extra_exact_slot_in_the_same_transaction()
    {
        using var db = new DatabaseReadTestDatabase();
        AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        db.Execute("INSERT INTO resources VALUES(41,'Other.bytes','unused',x'00')");
        var connection = new ScriptedReadConnection(db.Connection());
        byte[] before = File.ReadAllBytes(db.FileName);
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true);

        AssertRequiredMatch(result);
        Assert.Equal(before, File.ReadAllBytes(db.FileName));
        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes").Append(Skill), TableQueries(connection));
        Assert.Equal("BEGIN", connection.Commands[0]); Assert.Equal("ROLLBACK", connection.Commands[^1]);
        Assert.Equal(1, connection.Commands.Count(sql => sql == "BEGIN"));
        Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
        Assert.True(connection.WasDisposed);
        var skillCommand = connection.CreatedCommands.Single(command => command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && (string)command.Parameters["@name"].Value! == Skill);
        Assert.Equal(DbType.Int64, skillCommand.Parameters["@version"].DbType);
        Assert.Equal(41L, skillCommand.Parameters["@version"].Value);
        Assert.Equal(SyntheticSkill, result.Snapshot.Table(41, Skill)!.Bytes.ToArray());
        Assert.Null(result.Snapshot.Table(41, "Other.bytes"));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(result.Snapshot));
        db.Execute("UPDATE resources SET data=x'00',sha256='changed' WHERE name=@p0", Skill);
        Assert.Equal(SyntheticSkill, result.Snapshot.Table(41, Skill)!.Bytes.ToArray());
        AssertRequiredMatch(result);
    }

    [Theory]
    [InlineData("missing")]
    [InlineData("empty")]
    [InlineData("text")]
    [InlineData("non-text-digest")]
    [InlineData("long-digest")]
    [InlineData("oversized")]
    [InlineData("wrong-version")]
    [InlineData("wrong-case")]
    [InlineData("duplicate")]
    [InlineData("null")]
    public async Task Missing_or_malformed_optional_rows_do_not_invalidate_required_resources(string anomaly)
    {
        using var db = new DatabaseReadTestDatabase();
        if (anomaly != "missing") AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        switch (anomaly)
        {
            case "empty": db.Execute("UPDATE resources SET data=x'' WHERE name=@p0", Skill); break;
            case "text": db.Execute("UPDATE resources SET data='not-a-blob' WHERE name=@p0", Skill); break;
            case "non-text-digest": db.Execute("UPDATE resources SET sha256=x'00' WHERE name=@p0", Skill); break;
            case "long-digest": db.Execute("UPDATE resources SET sha256=@p0 WHERE name=@p1", new string('a', 257), Skill); break;
            case "oversized": db.Execute("UPDATE resources SET data=zeroblob(@p0) WHERE name=@p1", OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1, Skill); break;
            case "wrong-version": db.Execute("UPDATE resources SET version_id=42 WHERE name=@p0", Skill); break;
            case "wrong-case": db.Execute("UPDATE resources SET name='skilldata_c.bytes' WHERE name=@p0", Skill); break;
            case "duplicate":
            case "null":
                db.Execute("ALTER TABLE resources RENAME TO old_resources; CREATE TABLE resources(version_id INTEGER, name TEXT, sha256 TEXT, data BLOB); INSERT INTO resources SELECT * FROM old_resources; DROP TABLE old_resources");
                if (anomaly == "duplicate") db.Execute("INSERT INTO resources SELECT * FROM resources WHERE name=@p0", Skill);
                else db.Execute("UPDATE resources SET data=NULL WHERE name=@p0", Skill);
                break;
        }
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true);

        AssertRequiredMatch(result);
        Assert.Null(result.Snapshot.Table(41, Skill));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(result.Snapshot));
        Assert.Equal(11, TableQueries(connection).Count());
        if (anomaly == "oversized") Assert.Equal(0, connection.Readers.Last(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).BlobReads);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task A_missing_required_row_still_fails_with_optional_read_enabled(bool malformed)
    {
        using var db = new DatabaseReadTestDatabase(); AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        db.Execute(malformed ? "UPDATE resources SET data=x'' WHERE name='Eve.bytes'" : "DELETE FROM resources WHERE name='Eve.bytes'");
        var connection = new ScriptedReadConnection(db.Connection());
        await Assert.ThrowsAsync<InvalidDataException>(() => RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true));
        Assert.DoesNotContain(Skill, TableQueries(connection));
        Assert.True(connection.WasDisposed);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(5)]
    [InlineData(6)]
    public async Task Optional_read_shares_the_existing_aggregate_budget_and_rejects_before_blob_materialization(int remaining)
    {
        using var db = new DatabaseReadTestDatabase(); AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        long requiredBytes = RequiredRows().Values.Sum(row => (long)row!.Data!.Value.Length);
        var connection = new ScriptedReadConnection(db.Connection());
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, maximumAggregateBytes: requiredBytes + remaining, includeSkillData: true);

        AssertRequiredMatch(result);
        var optional = result.Snapshot.Table(41, Skill);
        Assert.Equal(remaining == SyntheticSkill.Length, optional is not null);
        Assert.Equal(remaining == SyntheticSkill.Length ? 1 : 0, connection.Readers.Last(reader => reader.Sql == RuntimeDatabaseSnapshotReader.TableSql).BlobReads);
    }

    [Fact]
    public async Task Optional_row_observes_the_same_wal_snapshot_as_required_rows()
    {
        using var db = new DatabaseReadTestDatabase(); db.Execute("PRAGMA journal_mode=WAL");
        AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        var connection = new ScriptedReadConnection(db.Connection()); bool changed = false;
        connection.BeforeExecute = (command, _) =>
        {
            if (command.CommandText != RuntimeDatabaseSnapshotReader.TableSql || (string)command.Parameters["@name"].Value! != Skill) return;
            changed = true;
            db.Execute("UPDATE resources SET data=x'00',sha256='changed' WHERE name=@p0", Skill);
        };
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true);

        Assert.True(changed); AssertRequiredMatch(result);
        Assert.Equal(SyntheticSkill, result.Snapshot.Table(41, Skill)!.Bytes.ToArray());
    }

    [Theory]
    [InlineData("execute")]
    [InlineData("value")]
    [InlineData("reader-dispose")]
    [InlineData("command-dispose")]
    public async Task Optional_provider_and_cleanup_failures_are_never_suppressed(string stage)
    {
        using var db = new DatabaseReadTestDatabase(); AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        var failure = new InvalidDataException("provider failure, not optional validation");
        var connection = new ScriptedReadConnection(db.Connection()); bool optional = false;
        connection.BeforeExecute = (command, _) =>
        {
            optional = command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && (string)command.Parameters["@name"].Value! == Skill;
            connection.ReaderDisposeError = optional && stage == "reader-dispose" ? failure : null;
            connection.CommandDisposeError = optional && stage == "command-dispose" ? failure : null;
            if (optional && stage == "execute") throw failure;
        };
        connection.TransformValue = (_, _, value) => optional && stage == "value" ? throw failure : value;
        RuntimeDatabaseReadObservation? result = null;
        Assert.Same(failure, await Assert.ThrowsAsync<InvalidDataException>(async () =>
            result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true)));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Theory]
    [InlineData("projection")]
    [InlineData("extra-result")]
    [InlineData("wrong-clr-type")]
    [InlineData("truncated")]
    [InlineData("null")]
    [InlineData("long-length")]
    public async Task Malformed_optional_projection_values_are_absent_without_hiding_provider_exceptions(string anomaly)
    {
        using var db = new DatabaseReadTestDatabase(); AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        var connection = new ScriptedReadConnection(db.Connection()); bool optional = false;
        connection.BeforeExecute = (command, _) =>
        {
            optional = command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && (string)command.Parameters["@name"].Value! == Skill;
            if (optional && anomaly == "extra-result") connection.ExtraResultSql = RuntimeDatabaseSnapshotReader.TableSql;
        };
        connection.TransformFieldCount = (_, count) => optional && anomaly == "projection" ? count + 1 : count;
        connection.TransformValue = (_, ordinal, value) =>
        {
            if (!optional) return value;
            if (anomaly == "long-length" && ordinal == 4) return long.MaxValue;
            if (ordinal != 5) return value;
            return anomaly switch
            {
                "wrong-clr-type" => new ReadOnlyMemory<byte>((byte[])value),
                "truncated" => ((byte[])value)[..^1],
                "null" => DBNull.Value,
                _ => value
            };
        };
        var result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, includeSkillData: true);
        AssertRequiredMatch(result); Assert.Null(result.Snapshot.Table(41, Skill));
        Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Cancellation_during_optional_read_cannot_publish_required_or_optional_snapshot(bool materializing)
    {
        using var db = new DatabaseReadTestDatabase(); AddSkill(db, SyntheticSkill, SkillDataParser.ReviewedSha256);
        using var cts = new CancellationTokenSource(); var connection = new ScriptedReadConnection(db.Connection()); bool optional = false;
        connection.BeforeExecute = (command, _) =>
        {
            optional = command.CommandText == RuntimeDatabaseSnapshotReader.TableSql && (string)command.Parameters["@name"].Value! == Skill;
            if (optional && !materializing) cts.Cancel();
        };
        connection.BeforeBlobRead = _ => { if (optional && materializing) cts.Cancel(); };
        RuntimeDatabaseReadObservation? result = null;
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            result = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, cts.Token, includeSkillData: true));
        Assert.Null(result); Assert.True(connection.WasDisposed); Assert.Equal("ROLLBACK", connection.Commands[^1]);
    }

    [Fact]
    public void Explicit_capture_performs_exactly_eleven_lookups_and_owns_the_optional_slice()
    {
        var rows = RequiredRows(); byte[] bytes = [255, 1, 0, 0, 0, 7, 9, 255];
        rows.Add(Skill, new(41, Skill, SkillDataParser.ReviewedSha256, bytes.AsMemory(1, 6)));
        rows.Add("Other.bytes", new(41, "Other.bytes", "unused", new byte[100]));
        var lookup = new LookupOnlyRows(rows);
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), lookup, includeSkillData: true);

        Assert.Equal(BundleSourcePlan.RequiredTables.Select(name => name + ".bytes").Append(Skill), lookup.Lookups);
        Array.Fill(bytes, (byte)0); rows.Clear();
        Assert.Equal(SyntheticSkill, snapshot.Table(41, Skill)!.Bytes.ToArray());
        Assert.Null(snapshot.Table(41, "Other.bytes"));
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(snapshot));
    }

    [Theory]
    [InlineData("recorded-pin")]
    [InlineData("self-consistent-hash")]
    [InlineData("wrong-version")]
    [InlineData("wrong-case")]
    [InlineData("null")]
    [InlineData("oversized")]
    public void Supplied_optional_rows_cannot_replace_the_compiled_reviewed_fingerprint(string anomaly)
    {
        var rows = RequiredRows();
        var row = new RuntimeDatabaseTableInput(41, Skill, SkillDataParser.ReviewedSha256, SyntheticSkill);
        row = anomaly switch
        {
            "self-consistent-hash" => row with { RecordedSha256 = DatabaseReadTestDatabase.Sha(SyntheticSkill) },
            "wrong-version" => row with { VersionId = 42 },
            "wrong-case" => row with { Name = "skilldata_c.bytes" },
            "null" => row with { Data = null },
            "oversized" => row with { Data = new byte[OwnedRuntimeDatabaseSnapshot.MaximumTableBytes + 1] },
            _ => row
        };
        rows.Add(Skill, row);
        long before = GC.GetAllocatedBytesForCurrentThread();
        var snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, includeSkillData: true);
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 1024 * 1024);
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(snapshot));
        Assert.True(RuntimeDatabaseStructuralMatcher.Match(snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests()).MatchesSuppliedRuntime);
        if (anomaly is "wrong-version" or "wrong-case" or "null" or "oversized") Assert.Null(snapshot.Table(41, Skill));
    }

    [Fact]
    public void Optional_capture_and_match_preserve_cancellation_even_when_the_row_is_absent()
    {
        using var cts = new CancellationTokenSource();
        var rows = new LookupOnlyRows(RequiredRows(), name => { if (name == Skill) cts.Cancel(); });
        OwnedRuntimeDatabaseSnapshot? snapshot = null;
        Assert.Throws<OperationCanceledException>(() => snapshot = OwnedRuntimeDatabaseSnapshot.Capture(Active(), rows, cts.Token, includeSkillData: true));
        Assert.Null(snapshot); Assert.Equal(11, rows.Lookups.Count);
        Assert.Throws<OperationCanceledException>(() => RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(null, cts.Token));
        Assert.False(RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(null));
    }

    private static RuntimeDatabaseActiveInput Active() => new(41, DatabaseReadTestDatabase.Identity().Key, DatabaseReadTestDatabase.Identity().CanonicalJson);
    private static Dictionary<string, RuntimeDatabaseTableInput?> RequiredRows() => DatabaseMatchPythonVectors.Case("all-ten-match").GetProperty("rows").EnumerateArray()
        .ToDictionary(row => row.GetProperty("name").GetString()!, row => (RuntimeDatabaseTableInput?)new RuntimeDatabaseTableInput(
            row.GetProperty("active_id").GetInt64(), row.GetProperty("name").GetString(), row.GetProperty("sha256").GetString(),
            Convert.FromBase64String(row.GetProperty("data").GetProperty("value").GetString()!)), StringComparer.Ordinal);
    private static void AddSkill(DatabaseReadTestDatabase db, byte[] bytes, string digest) =>
        db.Execute("INSERT INTO resources VALUES(41,@p0,@p1,@p2)", Skill, digest, bytes);
    private static IEnumerable<string> TableQueries(ScriptedReadConnection connection) => connection.CreatedCommands
        .Where(command => command.CommandText == RuntimeDatabaseSnapshotReader.TableSql).Select(command => (string)command.Parameters["@name"].Value!);
    private static void AssertRequiredMatch(RuntimeDatabaseReadObservation result)
    {
        var match = RuntimeDatabaseStructuralMatcher.Match(result.Snapshot, DatabaseReadTestDatabase.Identity(), DatabaseReadTestDatabase.Digests());
        Assert.True(result.CompletedSingleReadTransaction); Assert.True(match.MatchesSuppliedRuntime);
        Assert.Equal(BundleSourcePlan.RequiredTables, match.ExaminedSources);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
        Assert.False(match.HasVerifiedProvenance); Assert.False(match.RuntimeAdmitted); Assert.False(match.ProvesDatabaseTransaction);
    }
    private sealed class LookupOnlyRows(Dictionary<string, RuntimeDatabaseTableInput?> rows, Action<string>? lookup = null)
        : IReadOnlyDictionary<string, RuntimeDatabaseTableInput?>
    {
        internal List<string> Lookups { get; } = [];
        public bool TryGetValue(string key, out RuntimeDatabaseTableInput? value) { Lookups.Add(key); lookup?.Invoke(key); return rows.TryGetValue(key, out value); }
        public int Count => throw new InvalidOperationException("Unneeded row count");
        public IEnumerable<string> Keys => throw new InvalidOperationException("Unbounded row enumeration");
        public IEnumerable<RuntimeDatabaseTableInput?> Values => throw new InvalidOperationException("Unbounded row enumeration");
        public RuntimeDatabaseTableInput? this[string key] => throw new InvalidOperationException("Unneeded lookup");
        public bool ContainsKey(string key) => throw new InvalidOperationException("Unneeded lookup");
        public IEnumerator<KeyValuePair<string, RuntimeDatabaseTableInput?>> GetEnumerator() => throw new InvalidOperationException("Unbounded row enumeration");
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
