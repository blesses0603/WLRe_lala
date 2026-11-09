using System.Collections.Immutable;
using System.Data.Common;
using System.Numerics;
using System.Text.Json;
using Lala.Core.Social.Ark;
using Lala.Core.Storage;
using Microsoft.Data.Sqlite;
using Xunit;
using static Lala.Core.Tests.Storage.ArkQuestionStorageTestDatabase;

namespace Lala.Core.Tests.Storage;

public sealed class ArkQuestionStorageContractTests
{
    [Fact]
    public void Invalid_identity_and_answer_do_not_invoke_factory()
    {
        int opens = 0;
        var store = new ArkQuestionStore(() => { opens++; throw new InvalidOperationException(); });
        foreach (var token in new[] { new ArkCatalogToken(false, Token.IdentityKey), new(true, "bad"), new(true, new string('A', 64)), new(true, null) })
            Assert.Throws<ArgumentException>(() => store.Observe(token, 1, Question));
        foreach (var role in new[] { BigInteger.Zero, BigInteger.MinusOne, BigInteger.Pow(10, 4300) })
            Assert.Throws<ArgumentException>(() => store.Observe(Token, role, Question));
        Assert.Throws<ArgumentException>(() => store.Confirm(Token, 1, Question, 99));
        Assert.Throws<ArgumentException>(() => store.ClaimCandidate(Token, 1, Question, 0));
        Assert.Throws<ArgumentException>(() => store.RecordCandidateAttempt(Token, 1, Question, 99, true));
        Assert.Throws<ArgumentException>(() => store.Reject(Token, 1, Question, 99));
        Assert.Equal(0, opens);
    }

    private static IEnumerable<ArkQuestionSnapshot> InvalidQuestions()
    {
        foreach (var question in new[]
        {
            Question with { Question = 0 }, Question with { Options = default }, Question with { Labels = default },
            Question with { Options = [21, 21, 23, 24] }, Question with { Options = [0, 22, 23, 24] },
            Question with { Options = [21, 22, 23] }, Question with { Labels = ["a"] },
            Question with { Text = "" }, Question with { Text = new string('x', 32769) },
            Question with { Text = "\ud800" }, Question with { Labels = ["a", "b", "\udfff", "d"] },
            Question with { Labels = ["a", "b", "", "d"] }, Question with { Text = null! },
            Question with { Text = string.Concat(Enumerable.Repeat("😀", 32769)) }
        }) yield return question;
    }
    public static IEnumerable<object[]> InvalidQuestionIndices => InvalidQuestions().Select((_, i) => new object[] { i });
    [Theory, MemberData(nameof(InvalidQuestionIndices))]
    public void Malformed_or_oversized_question_never_opens_database(int index)
    {
        var question = InvalidQuestions().ElementAt(index);
        var store = new ArkQuestionStore(() => throw new Xunit.Sdk.XunitException("Unexpected factory call"));
        Assert.Throws<ArgumentException>(() => store.Observe(Token, 1, question));
    }

    [Theory]
    [InlineData("")][InlineData(" ")][InlineData(" x")][InlineData("x ")][InlineData("x\n")]
    [InlineData("x\0y")][InlineData("x\u007fy")][InlineData("server_confirmed")]
    public void Invalid_candidate_provenance_fails_before_open(string value)
    {
        var store = new ArkQuestionStore(() => throw new Xunit.Sdk.XunitException("Unexpected factory call"));
        Assert.Throws<ArgumentException>(() => store.RecordCandidate(Token, 1, Question, 22, value, "r1"));
        if (value != "server_confirmed")
            Assert.Throws<ArgumentException>(() => store.RecordCandidate(Token, 1, Question, 22, "reviewed", value));
        Assert.Throws<ArgumentException>(() => store.RecordCandidate(Token, 1, Question, 22, new string('x', 1025), "r1"));
    }

    [Fact]
    public void Python_unicode_scalar_limits_and_unbounded_positive_role_are_preserved()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        var question = Question with { Text = string.Concat(Enumerable.Repeat("😀", 32768)) };
        var role = BigInteger.Pow(10, 4299);
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().Confirm(Token, role, question, 22));
        Assert.Equal(new ArkQuestionObservation(22, ArkQuestionEvidenceStatus.Confirmed), db.Store().Observe(Token, role, question));
        Assert.Equal(ArkQuestionEvidenceStatus.Unknown, db.Store().Observe(Token, role + 1, question).Status);
    }

    [Theory][InlineData("😀")][InlineData("\0")]
    public void Maximum_scalar_and_json_escape_lengths_fit_bounded_persistence(string scalar)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        string maximum = string.Concat(Enumerable.Repeat(scalar, 32768));
        string provenance = string.Concat(Enumerable.Repeat("😀", 1024));
        var question = Question with { Text = maximum, Labels = [maximum, maximum, maximum, maximum] };
        Assert.Equal(ArkQuestionEvidenceStatus.Candidate, db.Store().RecordCandidate(Token, 1, question, 22, provenance, provenance));
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().Confirm(Token, 1, question, 22));
        Assert.Equal(new ArkQuestionObservation(22, ArkQuestionEvidenceStatus.Confirmed), db.Store().Observe(Token, 1, question));
        Assert.InRange((long)db.Scalar("SELECT length(CAST(payload AS BLOB)) FROM questions")!, 1L, 1_000_000L);
    }

    [Fact]
    public void Caller_carried_answer_and_candidate_flags_do_not_create_authority()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        var carried = Question with { KnownAnswer = 22, AnswerSource = "server_confirmed", AnswerKind = "confirmed",
            Selected = 1, SelectedCandidate = false, CandidateSource = "server_confirmed", CandidateRevision = "trusted-looking" };
        Assert.Equal(new ArkQuestionObservation(null, ArkQuestionEvidenceStatus.Unknown), db.Store().Observe(Token, 1, carried));
        Assert.Equal("observed", db.Scalar("SELECT source FROM questions"));
        Assert.Equal(DBNull.Value, db.Scalar("SELECT answer FROM questions"));
        db.Store().RecordCandidate(Token, 1, carried, 22, "reviewed", "r1");
        Assert.Equal(new ArkQuestionObservation(null, ArkQuestionEvidenceStatus.Unknown), db.Store().Observe(Token, 1, carried));
    }

    [Fact]
    public void Incompatible_factory_is_explicit_and_never_falls_back_to_a_path()
    {
        Assert.Throws<ArgumentNullException>(() => new ArkQuestionStore(null!));
        Assert.Throws<InvalidOperationException>(() => new ArkQuestionStore(() => null!).Observe(Token, 1, Question));
        using var db = new ArkQuestionStorageTestDatabase();
        var connection = db.Connection(); connection.Open();
        Assert.Throws<InvalidOperationException>(() => new ArkQuestionStore(() => connection).Observe(Token, 1, Question));
        Assert.Equal(System.Data.ConnectionState.Closed, connection.State);
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM sqlite_master WHERE type='table'"));
    }

    [Fact]
    public void Corrupt_file_is_not_reset_or_overwritten()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        byte[] original = "not a sqlite database"u8.ToArray();
        File.WriteAllBytes(db.PathName, original);
        Assert.Throws<SqliteException>(() => db.Store().Observe(Token, 1, Question));
        Assert.Equal(original, File.ReadAllBytes(db.PathName));
    }

    [Theory][InlineData(3)][InlineData(99)][InlineData(-1)]
    public void Future_or_invalid_schema_is_not_migrated(int version)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Sql($"PRAGMA user_version={version}");
        Assert.Throws<InvalidDataException>(() => db.Store().Observe(Token, 1, Question));
        Assert.Equal((long)version, db.Scalar("PRAGMA user_version"));
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM sqlite_master WHERE type='table'"));
    }

    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public void Legacy_schema_and_additive_attempt_table_preserve_evidence(int version)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().Confirm(Token, 1, Question, 22);
        db.Sql($"DROP TABLE candidates; DROP TABLE candidate_attempts; PRAGMA user_version={version}");
        Assert.Equal(new ArkQuestionObservation(22, ArkQuestionEvidenceStatus.Confirmed), db.Store().Observe(Token, 1, Question));
        Assert.Equal(2L, db.Scalar("PRAGMA user_version"));
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r1"));
        Assert.True(db.Store().ClaimCandidate(Token, 1, Question, 22));
    }

    [Theory]
    [InlineData("ALTER TABLE questions ADD COLUMN surprise INTEGER")]
    [InlineData("CREATE INDEX unexpected ON questions(answer)")]
    [InlineData("CREATE TRIGGER unexpected AFTER INSERT ON questions BEGIN DELETE FROM candidates; END")]
    [InlineData("CREATE TRIGGER unexpected AFTER INSERT ON QUESTIONS BEGIN DELETE FROM candidates; END")]
    [InlineData("CREATE TRIGGER unexpected AFTER INSERT ON CANDIDATES BEGIN DELETE FROM questions; END")]
    [InlineData("CREATE TRIGGER unexpected AFTER INSERT ON CANDIDATE_ATTEMPTS BEGIN DELETE FROM questions; END")]
    [InlineData("DROP TABLE candidate_attempts; CREATE VIEW candidate_attempts AS SELECT 1")]
    [InlineData("DROP TABLE candidate_attempts; CREATE TABLE candidate_attempts(catalog TEXT NOT NULL COLLATE NOCASE,role TEXT NOT NULL,fingerprint TEXT NOT NULL,answer INTEGER NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(catalog,role,fingerprint))")]
    [InlineData("DROP TABLE candidate_attempts; CREATE TABLE candidate_attempts(catalog TEXT NOT NULL,role TEXT NOT NULL,fingerprint TEXT NOT NULL,answer TEXT NOT NULL,updated INTEGER NOT NULL,PRIMARY KEY(catalog,role,fingerprint))")]
    public void Incompatible_schema_fails_closed_without_new_observation(string sql)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().Observe(Token, 1, Question); db.Sql(sql);
        Assert.Throws<InvalidDataException>(() => db.Store().Observe(Token, 2, Question));
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM questions"));
    }

    [Theory]
    [InlineData("UPDATE questions SET payload='{}'")]
    [InlineData("UPDATE questions SET payload=zeroblob(1000001)")]
    [InlineData("UPDATE questions SET payload=replace(payload,'題目','另一題')")]
    [InlineData("UPDATE questions SET payload=replace(payload,'\"question\":20','\"question\":20,\"question\":20')")]
    [InlineData("UPDATE questions SET source='candidate'")]
    [InlineData("UPDATE questions SET source=zeroblob(200)")]
    [InlineData("UPDATE questions SET answer=99,source='server_confirmed'")]
    [InlineData("UPDATE questions SET answer=22,source='observed'")]
    [InlineData("UPDATE questions SET answer=22.5,source='server_confirmed'")]
    [InlineData("UPDATE questions SET source='server_confirmed'")]
    [InlineData("UPDATE questions SET conflict=2")]
    [InlineData("UPDATE questions SET updated='invalid'")]
    [InlineData("UPDATE candidates SET source='server_confirmed'")]
    [InlineData("UPDATE candidates SET revision=' '")]
    [InlineData("UPDATE candidates SET revision=zeroblob(9000)")]
    [InlineData("UPDATE candidates SET answer=99")]
    [InlineData("UPDATE candidates SET rejected=1")]
    [InlineData("UPDATE candidate_attempts SET answer=99")]
    [InlineData("UPDATE candidate_attempts SET answer=23")]
    [InlineData("DELETE FROM questions")]
    public void Complete_persisted_evidence_is_revalidated_before_any_authority_or_mutation(string sql)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r1");
        db.Store().ClaimCandidate(Token, 1, Question, 22); db.Sql(sql);
        var before = RawRows(db);
        foreach (Action operation in new Action[]
        {
            () => db.Store().Observe(Token, 1, Question), () => db.Store().Confirm(Token, 1, Question, 22),
            () => db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r2"),
            () => db.Store().ClaimCandidate(Token, 1, Question, 22),
            () => db.Store().RecordCandidateAttempt(Token, 1, Question, 22, true),
            () => db.Store().Reject(Token, 1, Question, 22, true), () => db.Store().Quarantine(Token, 1, Question)
        }) Assert.Throws<InvalidDataException>(operation);
        Assert.Equal(before, RawRows(db));
    }

    [Fact]
    public void Quarantined_reviewed_candidate_and_different_valid_attempt_stay_quarantined()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r1");
        Assert.True(db.Store().RecordCandidateAttempt(Token, 1, Question, 23, allowUnregistered: true));
        Assert.Equal(new ArkQuestionObservation(null, ArkQuestionEvidenceStatus.Conflict), db.Store().Observe(Token, 1, Question));
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().Confirm(Token, 1, Question, 22));
        Assert.Equal(22L, db.Scalar("SELECT answer FROM candidates"));
        Assert.Equal(23L, db.Scalar("SELECT answer FROM candidate_attempts"));
    }

    [Fact]
    public void Unregistered_attempt_alone_does_not_contradict_server_confirmation()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        Assert.True(db.Store().RecordCandidateAttempt(Token, 1, Question, 23, allowUnregistered: true));
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().Confirm(Token, 1, Question, 22));
        Assert.Equal(new ArkQuestionObservation(22, ArkQuestionEvidenceStatus.Confirmed), db.Store().Observe(Token, 1, Question));
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM candidates"));
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM candidate_attempts"));
    }

    [Theory][InlineData("catalog")][InlineData("role")][InlineData("fingerprint")]
    public void Column_collation_cannot_alias_exact_identity_reads_or_mutations(string identityColumn)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        const string keyColumns = "catalog TEXT COLLATE NOCASE NOT NULL,role TEXT COLLATE NOCASE NOT NULL,fingerprint TEXT COLLATE NOCASE NOT NULL,";
        const string binaryPrimaryKey = "PRIMARY KEY(catalog COLLATE BINARY,role COLLATE BINARY,fingerprint COLLATE BINARY)";
        db.Sql("CREATE TABLE questions(" + keyColumns + "payload TEXT NOT NULL,answer INTEGER,conflict INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL DEFAULT 'observed',updated INTEGER NOT NULL," + binaryPrimaryKey + ");" +
            "CREATE TABLE candidates(" + keyColumns + "answer INTEGER NOT NULL,source TEXT NOT NULL,revision TEXT NOT NULL,rejected INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL," + binaryPrimaryKey + ");" +
            "CREATE TABLE candidate_attempts(" + keyColumns + "answer INTEGER NOT NULL,updated INTEGER NOT NULL," + binaryPrimaryKey + ")");
        db.Store().Confirm(Token, 1, Question, 22);
        db.Store().RecordCandidate(Token, 1, Question, 22, "original", "r1");
        Assert.True(db.Store().ClaimCandidate(Token, 1, Question, 22));
        foreach (string table in new[] { "questions", "candidates", "candidate_attempts" })
            db.Sql($"UPDATE {table} SET {identityColumn}=upper({identityColumn})");
        var key = ArkQuestionIdentity.Create(Token, 1, Question);
        string expected = identityColumn switch { "catalog" => key.Catalog, "role" => key.Role, _ => key.Fingerprint };
        string foreign = expected.ToUpperInvariant();
        Assert.NotEqual(expected, foreign);
        // Metadata permits NOCASE columns with an explicitly BINARY primary key. Every
        // lookup/mutation must nevertheless distinguish the malformed uppercase row.
        Assert.Equal(new ArkQuestionObservation(null, ArkQuestionEvidenceStatus.Unknown), db.Store().Observe(Token, 1, Question));
        Assert.False(db.Store().ClaimCandidate(Token, 1, Question, 22));
        Assert.False(db.Store().RecordCandidateAttempt(Token, 1, Question, 22));
        Assert.Equal(ArkQuestionEvidenceStatus.Candidate, db.Store().RecordCandidate(Token, 1, Question, 23, "new", "r2"));
        Assert.True(db.Store().ClaimCandidate(Token, 1, Question, 23));
        Assert.Equal(ArkQuestionEvidenceStatus.Confirmed, db.Store().Confirm(Token, 1, Question, 23));
        db.Store().Reject(Token, 1, Question, 23, candidate: true);
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().Quarantine(Token, 1, Question));
        string foreignMatch = $"{identityColumn} COLLATE BINARY='{foreign}'";
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM questions WHERE " + foreignMatch + " AND answer=22 AND source='server_confirmed' AND conflict=0"));
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM candidates WHERE " + foreignMatch + " AND answer=22 AND source='original' AND revision='r1' AND rejected=0"));
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM candidate_attempts WHERE " + foreignMatch + " AND answer=22"));
        Assert.Equal(2L, db.Scalar("SELECT count(*) FROM questions"));
        Assert.Equal(2L, db.Scalar("SELECT count(*) FROM candidates"));
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM candidate_attempts"));
    }

    // Capture all fields without parsing intentionally damaged payload/metadata.
    private static string RawRows(ArkQuestionStorageTestDatabase db)
    {
        using var connection = db.Connection(); connection.Open();
        var rows = new List<object[]>();
        foreach (string table in new[] { "questions", "candidates", "candidate_attempts" })
        {
            using var command = connection.CreateCommand(); command.CommandText = $"SELECT * FROM {table} ORDER BY catalog,role,fingerprint";
            using var reader = command.ExecuteReader();
            while (reader.Read())
            {
                var row = new object[reader.FieldCount]; reader.GetValues(row); rows.Add(row);
            }
        }
        return JsonSerializer.Serialize(rows);
    }

    [Fact]
    public void Failed_second_write_rolls_back_observation_and_candidate_atomically()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().Observe(Token, 2, Question);
        db.Sql("DROP TABLE candidates; CREATE TABLE candidates(catalog TEXT NOT NULL,role TEXT NOT NULL,fingerprint TEXT NOT NULL,answer INTEGER NOT NULL,source TEXT NOT NULL CHECK(source != 'reviewed'),revision TEXT NOT NULL,rejected INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL,PRIMARY KEY(catalog,role,fingerprint))");
        Assert.Throws<SqliteException>(() => db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r1"));
        Assert.Equal(1L, db.Scalar("SELECT count(*) FROM questions"));
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM candidates"));
        Assert.Equal(ArkQuestionEvidenceStatus.Unknown, db.Store().Observe(Token, 1, Question).Status);
    }

    [Fact]
    public void Cancellation_before_open_has_no_side_effects()
    {
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        var store = new ArkQuestionStore(() => throw new Xunit.Sdk.XunitException("Unexpected factory call"));
        Assert.Throws<OperationCanceledException>(() => store.Observe(Token, 1, Question, cancellation.Token));
    }

    private sealed class CallbackClock(Action action) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() { action(); return FixedClock.Instance.GetUtcNow(); }
    }
    [Theory][InlineData(false)][InlineData(true)]
    public void Cancellation_or_exception_after_first_write_rolls_back_schema_and_evidence(bool cancel)
    {
        using var db = new ArkQuestionStorageTestDatabase();
        using var cancellation = new CancellationTokenSource();
        int reads = 0;
        var clock = new CallbackClock(() =>
        {
            if (++reads != 2) return;
            if (cancel) cancellation.Cancel(); else throw new InvalidOperationException("Synthetic clock failure");
        });
        if (cancel)
            Assert.Throws<OperationCanceledException>(() => db.Store(clock).Confirm(Token, 1, Question, 22, cancellation.Token));
        else
            Assert.Throws<InvalidOperationException>(() => db.Store(clock).Confirm(Token, 1, Question, 22));
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM sqlite_master WHERE type='table'"));
        Assert.Equal(0L, db.Scalar("PRAGMA user_version"));
        Assert.Equal(ArkQuestionEvidenceStatus.Unknown, db.Store().Observe(Token, 1, Question).Status);
    }

    private sealed class TrackedConnection(string connectionString, List<DbCommand> commands) : SqliteConnection(connectionString)
    {
        protected override DbCommand CreateDbCommand()
        {
            var command = base.CreateDbCommand(); commands.Add(command); return command;
        }
    }

    [Fact]
    public void Busy_database_error_is_bounded_and_never_reports_success()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().Observe(Token, 1, Question);
        using var blocking = db.Connection(); blocking.Open();
        using var cmd = blocking.CreateCommand(); cmd.CommandText = "BEGIN IMMEDIATE"; cmd.ExecuteNonQuery();
        var commands = new List<DbCommand>();
        using var settings = db.Connection();
        var store = new ArkQuestionStore(() => new TrackedConnection(settings.ConnectionString, commands));
        var started = System.Diagnostics.Stopwatch.StartNew();
        var error = Assert.Throws<SqliteException>(() => store.RecordCandidate(Token, 1, Question, 22, "reviewed", "r1"));
        Assert.Equal(5, error.SqliteErrorCode);
        Assert.All(commands, command => Assert.Equal(1, command.CommandTimeout));
        Assert.Contains(commands, command => command.CommandText == "PRAGMA busy_timeout=250");
        Assert.Single(commands, command => command.CommandText == "BEGIN IMMEDIATE");
        // This is a CI safety ceiling, not an assertion of Python's 250-ms timing parity.
        Assert.InRange(started.Elapsed.TotalSeconds, 0, 15);
        cmd.CommandText = "ROLLBACK"; cmd.ExecuteNonQuery();
        Assert.Equal(ArkQuestionEvidenceStatus.Unknown, db.Store().Observe(Token, 1, Question).Status);
        Assert.Equal(0L, db.Scalar("SELECT count(*) FROM candidates"));
    }

    [Theory][InlineData(0)][InlineData(1)][InlineData(2)]
    public async Task Competing_writers_preserve_contradiction(int mode)
    {
        using var db = new ArkQuestionStorageTestDatabase(); db.Store().Observe(Token, 1, Question);
        using var gate = new Barrier(2);
        ArkQuestionEvidenceStatus Write(int i) => mode == 0 || mode == 2 && i == 1
            ? db.Store().Confirm(Token, 1, Question, (uint)(22 + i))
            : db.Store().RecordCandidate(Token, 1, Question, (uint)(22 + i), "reviewed", "r1");
        // The store deliberately bounds lock waiting to one second. Under runner
        // contention a competing call may fail BUSY rather than both succeeding.
        // Drain both attempts first; only then explicitly resubmit the rejected
        // observation. No production retry or timeout change is implied.
        var results = await Task.WhenAll(Enumerable.Range(0, 2).Select(i => Task.Run(() =>
        {
            gate.SignalAndWait();
            try { return (ArkQuestionEvidenceStatus?)Write(i); }
            catch (SqliteException error) when (error.SqliteErrorCode == 5)
            { Assert.False(error.Data.Contains("ArkQuestionRollbackError")); return null; }
        })));
        Assert.Contains(results, result => result is not null);
        for (int i = 0; i < results.Length; i++)
            if (results[i] is null) results[i] = Write(i);
        Assert.Contains(ArkQuestionEvidenceStatus.Conflict, results);
        Assert.Equal(new ArkQuestionObservation(null, ArkQuestionEvidenceStatus.Conflict), db.Store().Observe(Token, 1, Question));
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().Confirm(Token, 1, Question, 22));
    }

    [Fact]
    public async Task Candidate_claim_is_once_only_across_independent_connections()
    {
        using var db = new ArkQuestionStorageTestDatabase(); db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r1");
        using var gate = new Barrier(4);
        var results = await Task.WhenAll(Enumerable.Range(0, 4).Select(_ => Task.Run(() =>
        { gate.SignalAndWait(); return db.Store().ClaimCandidate(Token, 1, Question, 22); })));
        Assert.Single(results, x => x);
        Assert.Equal(ArkQuestionEvidenceStatus.Pending, db.Store().RecordCandidate(Token, 1, Question, 22, "reviewed", "r2"));
        Assert.False(db.Store().ClaimCandidate(Token, 1, Question, 22));
    }

    [Fact]
    public void Contradictory_candidate_keeps_first_provenance_and_never_lifts_quarantine()
    {
        using var db = new ArkQuestionStorageTestDatabase();
        db.Store().RecordCandidate(Token, 1, Question, 22, "first", "r1");
        db.Store().ClaimCandidate(Token, 1, Question, 22);
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().RecordCandidate(Token, 1, Question, 23, "second", "r2"));
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().RecordCandidate(Token, 1, Question, 22, "third", "r3"));
        Assert.True(db.Store().RecordCandidateAttempt(Token, 1, Question, 23, true));
        Assert.Equal(22L, db.Scalar("SELECT answer FROM candidates"));
        Assert.Equal("first", db.Scalar("SELECT source FROM candidates"));
        Assert.Equal("r1", db.Scalar("SELECT revision FROM candidates"));
        Assert.Equal(22L, db.Scalar("SELECT answer FROM candidate_attempts"));
        Assert.Equal(ArkQuestionEvidenceStatus.Conflict, db.Store().Confirm(Token, 1, Question, 22));
    }
}
