using System.Collections.Immutable;
using System.Globalization;
using System.Text.Json;
using Lala.Core.Social.Ark;

namespace Lala.Core.Storage;

public sealed partial class ArkQuestionStore
{
    private static readonly (string Name, string Columns)[] Tables =
    [
        ("questions", "catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, answer INTEGER, conflict INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'observed', updated INTEGER NOT NULL, PRIMARY KEY (catalog, role, fingerprint)"),
        ("candidates", "catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL, answer INTEGER NOT NULL, source TEXT NOT NULL, revision TEXT NOT NULL, rejected INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL, PRIMARY KEY (catalog, role, fingerprint)"),
        ("candidate_attempts", "catalog TEXT NOT NULL, role TEXT NOT NULL, fingerprint TEXT NOT NULL, answer INTEGER NOT NULL, updated INTEGER NOT NULL, PRIMARY KEY (catalog, role, fingerprint)")
    ];

    private static void ValidateSchema(Database db)
    {
        var version = Number(db.Read("PRAGMA user_version").Single()[0]);
        if (version is < 0 or > 2) throw new InvalidDataException("Unsupported Ark question schema version.");
        foreach (var (name, definition) in Tables)
        {
            var existing = db.Read($"SELECT type FROM sqlite_master WHERE name='{name}'");
            if (existing.Count == 0) db.Run($"CREATE TABLE {name} ({definition})");
            else if (existing.Count != 1 || !Equals(existing[0][0], "table")) throw Invalid();
            // Validate existing tables instead of trusting CREATE IF NOT EXISTS or user_version.
            // This includes hidden/generated columns and defaults used by INSERT operations.
            string[] columns = definition.Split(", PRIMARY KEY", StringSplitOptions.None)[0].Split(", ");
            var rows = db.Read($"PRAGMA table_xinfo('{name}')");
            if (rows.Count != columns.Length) throw Invalid();
            for (int i = 0; i < columns.Length; i++)
            {
                string[] expected = columns[i].Split(' ');
                var row = rows[i];
                string? defaultValue = columns[i].Contains(" DEFAULT ", StringComparison.Ordinal) ? expected[^1] : null;
                if (Number(row[0]) != i || !Equals(row[1], expected[0]) || !Equals(row[2], expected[1]) ||
                    Number(row[3]) != (columns[i].Contains("NOT NULL", StringComparison.Ordinal) ? 1 : 0) ||
                    !Equals(row[4], defaultValue) || Number(row[5]) != (i < 3 ? i + 1 : 0) || Number(row[6]) != 0)
                    throw Invalid();
            }
            var indexes = db.Read($"PRAGMA index_list('{name}')");
            if (indexes.Count != 1 || Number(indexes[0][2]) != 1 || !Equals(indexes[0][3], "pk") || Number(indexes[0][4]) != 0)
                throw Invalid();
            string indexName = Text(indexes[0][1]);
            // The name is read from disk, not trusted SQL. Quote any apostrophes.
            var index = db.Read($"PRAGMA index_xinfo('{indexName.Replace("'", "''", StringComparison.Ordinal)}')");
            if (index.Count != 4) throw Invalid();
            for (int i = 0; i < 3; i++)
                if (Number(index[i][1]) != i || !Equals(index[i][2], new[] { "catalog", "role", "fingerprint" }[i]) ||
                    Number(index[i][3]) != 0 || !Equals(index[i][4], "BINARY") || Number(index[i][5]) != 1) throw Invalid();
            // SQLite identifiers are case-insensitive, including sqlite_master trigger
            // owners recorded with the spelling used by CREATE TRIGGER ... ON.
            if (Number(index[3][1]) != -1 || Number(index[3][5]) != 0 ||
                db.Read($"PRAGMA foreign_key_list('{name}')").Count != 0 ||
                db.Read($"SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name COLLATE NOCASE='{name}'").Count != 0)
                throw Invalid();
        }
        if (version < 2) db.Run("PRAGMA user_version=2");
    }

    private sealed record QuestionRow(uint? Answer, bool Conflict, string Source);
    private sealed record CandidateRow(uint Answer, bool Rejected);
    private sealed record Evidence(QuestionRow? Question, CandidateRow? Candidate, uint? Attempt);
    private static Evidence ReadEvidence(Database db, ArkQuestionIdentity key, ArkQuestionSnapshot question)
    {
        // Bound string materialization at the SQL boundary, including corrupt preexisting data.
        var qs = db.Read("SELECT " + BoundedText("payload", 1_000_000) + ",answer,conflict," + BoundedText("source", 128) +
            ",updated FROM questions WHERE " + Match, key, 1);
        QuestionRow? q = null;
        if (qs.Count != 0)
        {
            var row = qs[0];
            ValidatePayload(Text(row[0]), question, key);
            uint? answer = row[1] is null ? null : Answer(row[1], question);
            bool conflict = Flag(row[2]);
            string source = Text(row[3]);
            _ = Number(row[4]);
            if (source is not ("observed" or "server_confirmed") ||
                conflict && answer is not null || !conflict && (source == "server_confirmed") != (answer is not null)) throw Invalid();
            q = new(answer, conflict, source);
        }
        var cs = db.Read("SELECT answer," + BoundedText("source", 8192) + "," + BoundedText("revision", 8192) +
            ",rejected,updated FROM candidates WHERE " + Match, key, 1);
        CandidateRow? c = null;
        if (cs.Count != 0)
        {
            var row = cs[0];
            uint answer = Answer(row[0], question);
            string source = Text(row[1]);
            if (!ArkQuestionIdentity.ValidMetadata(source) || source == "server_confirmed" ||
                !ArkQuestionIdentity.ValidMetadata(Text(row[2]))) throw Invalid();
            bool rejected = Flag(row[3]);
            _ = Number(row[4]);
            if (q is null || rejected && !q.Conflict || !q.Conflict && q.Answer is { } known && answer != known) throw Invalid();
            c = new(answer, rejected);
        }
        var attempts = db.Read("SELECT answer,updated FROM candidate_attempts WHERE " + Match, key, 1);
        uint? attempt = null;
        if (attempts.Count != 0)
        {
            if (q is null) throw Invalid();
            attempt = Answer(attempts[0][0], question);
            _ = Number(attempts[0][1]);
            // A reviewed candidate and a different durable attempt must already be
            // quarantined. Do not let Confirm erase this unreachable, corrupt state.
            // An unregistered attempt alone remains non-authoritative Python evidence.
            if (!q.Conflict && c is not null && c.Answer != attempt) throw Invalid();
        }
        return new(q, c, attempt);
    }

    private static string BoundedText(string column, int bytes) =>
        $"CASE WHEN typeof({column})='text' AND length(CAST({column} AS BLOB))<={bytes.ToString(CultureInfo.InvariantCulture)} THEN {column} ELSE NULL END";
    private static long Number(object? value) => value is long number ? number : throw Invalid();
    private static string Text(object? value) => value as string ?? throw Invalid();
    private static bool Flag(object? value) => Number(value) switch { 0 => false, 1 => true, _ => throw Invalid() };
    private static uint Answer(object? value, ArkQuestionSnapshot question)
    {
        long answer = Number(value);
        return answer is > 0 and <= uint.MaxValue && question.Options.Contains((uint)answer) ? (uint)answer : throw Invalid();
    }
    private static InvalidDataException Invalid() => new("Invalid Ark question schema or persisted evidence; storage was not reset.");

    private static void ValidatePayload(string payload, ArkQuestionSnapshot question, ArkQuestionIdentity key)
    {
        try
        {
            using var document = JsonDocument.Parse(payload, new JsonDocumentOptions { MaxDepth = 5 });
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || root.EnumerateObject().Count() != 3 ||
                root.EnumerateObject().Select(p => p.Name).Distinct().Count() != 3) throw Invalid();
            var options = root.GetProperty("options");
            if (options.GetArrayLength() != 4) throw Invalid();
            var ids = ImmutableArray.CreateBuilder<uint>(4);
            var labels = ImmutableArray.CreateBuilder<string>(4);
            foreach (var option in options.EnumerateArray())
            {
                if (option.GetArrayLength() != 2) throw Invalid();
                ids.Add(option[0].GetUInt32());
                labels.Add(option[1].GetString() ?? throw Invalid());
            }
            var persisted = question with { Question = root.GetProperty("question").GetUInt32(),
                Text = root.GetProperty("text").GetString() ?? throw Invalid(), Options = ids.ToImmutable(), Labels = labels.ToImmutable() };
            if (ArkQuestionIdentity.Payload(persisted) != key.CanonicalPayload) throw Invalid();
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or ArgumentException or OverflowException)
        { throw new InvalidDataException("Persisted question payload does not match the complete supplied identity.", e); }
    }
}
