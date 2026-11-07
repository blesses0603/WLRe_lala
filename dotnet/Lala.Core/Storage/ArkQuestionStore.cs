using System.Data;
using System.Data.Common;
using System.Numerics;
using Lala.Core.Social.Ark;

namespace Lala.Core.Storage;

public enum ArkQuestionEvidenceStatus { Unknown, Candidate, Pending, Confirmed, Conflict }
public sealed record ArkQuestionObservation(uint? Answer, ArkQuestionEvidenceStatus Status);

/// <summary>Explicit SQLite evidence boundary. The factory must return a NEW CLOSED SQLite
/// connection, owned/disposed by each operation, with the caller's chosen location/provider.
/// No default path, provider initialization, receive-intent execution, solver or sending occurs.
/// Operations are synchronous I/O and must not run on a host UI thread.
/// A confirmation records the caller's server evidence; this class cannot authenticate it.
/// DbException, invalid schema/evidence (InvalidDataException), invalid input (ArgumentException),
/// and cancellation propagate. A failed write is never reported as a successful observation.</summary>
public sealed partial class ArkQuestionStore(Func<DbConnection> connectionFactory, TimeProvider? timeProvider = null)
{
    private readonly Func<DbConnection> factory = connectionFactory ?? throw new ArgumentNullException(nameof(connectionFactory));
    private readonly TimeProvider clock = timeProvider ?? TimeProvider.System;

    public ArkQuestionObservation Observe(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question,
        CancellationToken cancellationToken = default) => Execute<ArkQuestionObservation>(token, role, question, null, cancellationToken, (db, key, state) =>
    {
        EnsureObserved(db, key, state);
        return state.Question is { Conflict: true }
            ? new(null, ArkQuestionEvidenceStatus.Conflict)
            : state.Question is { Source: "server_confirmed", Answer: { } answer }
                ? new(answer, ArkQuestionEvidenceStatus.Confirmed) : new(null, ArkQuestionEvidenceStatus.Unknown);
    });

    public ArkQuestionEvidenceStatus RecordCandidate(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question,
        uint answer, string source, string revision, CancellationToken cancellationToken = default)
    {
        if (!ArkQuestionIdentity.ValidMetadata(source) || source == "server_confirmed" || !ArkQuestionIdentity.ValidMetadata(revision))
            throw new ArgumentException("Candidate source and revision must be bounded, nonempty provenance.");
        return Execute(token, role, question, answer, cancellationToken, (db, key, state) =>
        {
            EnsureObserved(db, key, state);
            bool conflict = state.Question?.Conflict == true ||
                state.Candidate is { } c && (c.Answer != answer || c.Rejected) ||
                state.Attempt is { } pending && pending != answer ||
                state.Question is { Source: "server_confirmed" } q && q.Answer != answer;
            if (state.Candidate is null)
                db.Run("INSERT INTO candidates (catalog,role,fingerprint,answer,source,revision,updated) VALUES ($catalog,$role,$fingerprint,$answer,$source,$revision,$updated)",
                    key, ("answer", (long)answer), ("source", source), ("revision", revision), ("updated", Now()));
            else if (!conflict)
                db.Run("UPDATE candidates SET source=$source,revision=$revision,updated=$updated WHERE " + Match,
                    key, ("source", source), ("revision", revision), ("updated", Now()));
            if (conflict) { QuarantineRow(db, key); return ArkQuestionEvidenceStatus.Conflict; }
            return state.Attempt is not null ? ArkQuestionEvidenceStatus.Pending :
                state.Question?.Source == "server_confirmed" ? ArkQuestionEvidenceStatus.Confirmed : ArkQuestionEvidenceStatus.Candidate;
        });
    }

    /// <summary>Durable once-only claim of matching reviewed evidence, NOT authorization to send.</summary>
    public bool ClaimCandidate(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question, uint answer,
        CancellationToken cancellationToken = default) => Execute(token, role, question, answer, cancellationToken, (db, key, state) =>
    {
        if (state.Question is null or { Conflict: true } || state.Candidate is not { Rejected: false } c || c.Answer != answer)
            return false;
        return InsertAttempt(db, key, answer) == 1;
    });

    /// <summary>Records an explicit selection, including under quarantine; never clears safety flags.
    /// allowUnregistered records caller-matched external evidence, not a new reviewed candidate.</summary>
    public bool RecordCandidateAttempt(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question, uint answer,
        bool allowUnregistered = false, CancellationToken cancellationToken = default) =>
        Execute(token, role, question, answer, cancellationToken, (db, key, state) =>
        {
            if ((state.Candidate is null || state.Candidate.Answer != answer) && !allowUnregistered) return false;
            EnsureObserved(db, key, state);
            if (state.Candidate is { } c && c.Answer != answer || state.Attempt is { } pending && pending != answer)
                QuarantineRow(db, key);
            InsertAttempt(db, key, answer);
            return true;
        });

    public ArkQuestionEvidenceStatus Confirm(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question,
        uint answer, CancellationToken cancellationToken = default) => Execute(token, role, question, answer, cancellationToken, (db, key, state) =>
    {
        EnsureObserved(db, key, state);
        bool conflict = state.Question?.Conflict == true ||
            state.Question?.Answer is { } old && old != answer ||
            state.Candidate is { } c && (c.Answer != answer || c.Rejected);
        if (conflict) { QuarantineRow(db, key); return ArkQuestionEvidenceStatus.Conflict; }
        db.Run("UPDATE questions SET answer=$answer,source='server_confirmed',updated=$updated WHERE " + Match,
            key, ("answer", (long)answer), ("updated", Now()));
        db.Run("DELETE FROM candidate_attempts WHERE " + Match, key);
        return ArkQuestionEvidenceStatus.Confirmed;
    });

    public ArkQuestionEvidenceStatus Quarantine(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question,
        CancellationToken cancellationToken = default) => Execute(token, role, question, null, cancellationToken, (db, key, state) =>
    {
        EnsureObserved(db, key, state);
        QuarantineRow(db, key);
        return ArkQuestionEvidenceStatus.Conflict;
    });

    public void Reject(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question, uint answer,
        bool candidate = false, CancellationToken cancellationToken = default) =>
        Execute(token, role, question, answer, cancellationToken, (db, key, state) =>
        {
            if (candidate)
            {
                EnsureObserved(db, key, state);
                QuarantineRow(db, key);
                db.Run("DELETE FROM candidate_attempts WHERE " + Match, key);
                db.Run("UPDATE candidates SET rejected=1,updated=$updated WHERE " + Match, key, ("updated", Now()));
            }
            else
                db.Run("UPDATE questions SET answer=NULL,conflict=1,updated=$updated WHERE " + Match + " AND answer=$answer",
                    key, ("updated", Now()), ("answer", (long)answer));
            return true;
        });

    // Column collation can differ from the validated primary-key index collation.
    // Bind every read/update/delete to the exact catalog, role hash and fingerprint bytes.
    private const string Match = "catalog COLLATE BINARY=$catalog AND role COLLATE BINARY=$role AND fingerprint COLLATE BINARY=$fingerprint";
    private long Now() => clock.GetUtcNow().ToUnixTimeSeconds();
    private void EnsureObserved(Database db, ArkQuestionIdentity key, Evidence state)
    {
        if (state.Question is null)
            db.Run("INSERT INTO questions (catalog,role,fingerprint,payload,updated) VALUES ($catalog,$role,$fingerprint,$payload,$updated)",
                key, ("payload", key.CanonicalPayload), ("updated", Now()));
    }
    private void QuarantineRow(Database db, ArkQuestionIdentity key) =>
        db.Run("UPDATE questions SET answer=NULL,conflict=1,updated=$updated WHERE " + Match, key, ("updated", Now()));
    private int InsertAttempt(Database db, ArkQuestionIdentity key, uint answer) =>
        db.Run("INSERT OR IGNORE INTO candidate_attempts (catalog,role,fingerprint,answer,updated) VALUES ($catalog,$role,$fingerprint,$answer,$updated)",
            key, ("answer", (long)answer), ("updated", Now()));

    private T Execute<T>(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question, uint? answer,
        CancellationToken cancellationToken, Func<Database, ArkQuestionIdentity, Evidence, T> action)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var key = ArkQuestionIdentity.Create(token, role, question);
        if (answer is { } selected && !question.Options.Contains(selected))
            throw new ArgumentException("Answer is not an option in the exact current question.");
        using var connection = factory() ?? throw new InvalidOperationException("Connection factory returned null.");
        if (connection.State != ConnectionState.Closed) throw new InvalidOperationException("Connection factory must return a new closed connection.");
        cancellationToken.ThrowIfCancellationRequested();
        connection.Open();
        var db = new Database(connection, cancellationToken);
        db.Run("PRAGMA busy_timeout=250");
        // SQLite reserves the writer before schema/evidence reads. A provider command timeout
        // of one second bounds lock retry (Microsoft.Data.Sqlite rounds to whole seconds).
        db.Run("BEGIN IMMEDIATE");
        try
        {
            ValidateSchema(db);
            var state = ReadEvidence(db, key, question);
            T result = action(db, key, state);
            cancellationToken.ThrowIfCancellationRequested();
            db.Run("COMMIT");
            return result;
        }
        catch (Exception error)
        {
            try { new Database(connection, CancellationToken.None).Run("ROLLBACK"); }
            catch (Exception rollbackError) { error.Data["ArkQuestionRollbackError"] = rollbackError; }
            throw;
        }
    }

    private sealed class Database(DbConnection connection, CancellationToken cancellationToken)
    {
        private DbCommand Command(string sql, ArkQuestionIdentity? key, (string Name, object Value)[] parameters)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var command = connection.CreateCommand();
            command.CommandText = sql;
            command.CommandTimeout = 1;
            if (key is not null)
                foreach (var pair in new[] { ("catalog", key.Catalog), ("role", key.Role), ("fingerprint", key.Fingerprint) })
                { var p = command.CreateParameter(); p.ParameterName = "$" + pair.Item1; p.Value = pair.Item2; command.Parameters.Add(p); }
            foreach (var (name, value) in parameters)
            { var p = command.CreateParameter(); p.ParameterName = "$" + name; p.Value = value; command.Parameters.Add(p); }
            return command;
        }
        internal int Run(string sql, ArkQuestionIdentity? key = null, params (string Name, object Value)[] parameters)
        {
            using var command = Command(sql, key, parameters);
            return command.ExecuteNonQuery();
        }
        internal List<object?[]> Read(string sql, ArkQuestionIdentity? key = null, int maximumRows = 32)
        {
            using var command = Command(sql, key, []);
            using var reader = command.ExecuteReader();
            var rows = new List<object?[]>();
            while (reader.Read())
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (rows.Count >= maximumRows) throw new InvalidDataException("Ark evidence query exceeds its bounded row count.");
                var values = new object[reader.FieldCount];
                reader.GetValues(values);
                rows.Add(values.Select(v => v is DBNull ? null : v).ToArray());
            }
            return rows;
        }
    }
}
