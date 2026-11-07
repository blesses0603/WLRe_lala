using System.Collections.Immutable;
using System.Data.Common;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Social.Ark;
using Lala.Core.Storage;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Tests.Storage;

internal sealed class ArkQuestionStorageTestDatabase : IDisposable
{
    internal string DirectoryPath { get; } = Path.Combine(Path.GetTempPath(), "lala-ark-tests-" + Guid.NewGuid().ToString("N"));
    internal string PathName => Path.Combine(DirectoryPath, "synthetic.sqlite3");
    internal ArkQuestionStorageTestDatabase() => Directory.CreateDirectory(DirectoryPath);
    internal SqliteConnection Connection() => new(new SqliteConnectionStringBuilder { DataSource = PathName, Pooling = false }.ToString());
    internal ArkQuestionStore Store(TimeProvider? time = null) => new(Connection, time ?? FixedClock.Instance);
    internal void Sql(string sql)
    {
        using var db = Connection(); db.Open();
        using var cmd = db.CreateCommand(); cmd.CommandText = sql; cmd.ExecuteNonQuery();
    }
    internal object? Scalar(string sql)
    {
        using var db = Connection(); db.Open();
        using var cmd = db.CreateCommand(); cmd.CommandText = sql; return cmd.ExecuteScalar();
    }
    internal JsonObject Snapshot()
    {
        using var db = Connection(); db.Open();
        var result = new JsonObject();
        foreach (string table in new[] { "questions", "candidates", "candidate_attempts" })
        {
            using var cmd = db.CreateCommand(); cmd.CommandText = $"SELECT * FROM {table} ORDER BY catalog,role,fingerprint";
            using var reader = cmd.ExecuteReader();
            var rows = new JsonArray();
            while (reader.Read())
            {
                var row = new JsonArray();
                for (int i = 0; i < reader.FieldCount; i++)
                    row.Add(reader.IsDBNull(i) ? null : table == "questions" && i == 3
                        ? JsonNode.Parse(reader.GetString(i)) : JsonSerializer.SerializeToNode(reader.GetValue(i)));
                rows.Add(row);
            }
            result[table] = rows;
        }
        result["version"] = JsonSerializer.SerializeToNode(Scalar("PRAGMA user_version"));
        return result;
    }
    public void Dispose() => Directory.Delete(DirectoryPath, recursive: true);
    internal sealed class FixedClock : TimeProvider
    {
        internal static readonly FixedClock Instance = new();
        public override DateTimeOffset GetUtcNow() => DateTimeOffset.FromUnixTimeSeconds(12345);
    }
    internal static readonly ArkCatalogToken Token = new(true, new string('a', 64));
    internal static readonly ArkQuestionSnapshot Question = new(20, new(0, 0, 0), [21, 22, 23, 24], "題目", ["甲", "乙", "丙", "丁"]);
    internal static ArkQuestionSnapshot QuestionFrom(JsonElement value) => Question with
    {
        Question = value.GetProperty("question").GetUInt32(), Text = value.GetProperty("text").GetString()!,
        Options = value.GetProperty("options").EnumerateArray().Select(e => e.GetUInt32()).ToImmutableArray(),
        Labels = value.GetProperty("labels").EnumerateArray().Select(e => e.GetString()!).ToImmutableArray()
    };
}
