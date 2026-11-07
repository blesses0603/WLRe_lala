using System.Data.Common;
using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Tests.Resources;

internal sealed class DatabaseReadTestDatabase : IDisposable
{
    internal string FileName { get; } = Path.Combine(Path.GetTempPath(), "lala-resource-reader-" + Guid.NewGuid().ToString("N") + ".sqlite");
    internal DatabaseReadTestDatabase(string? encoding = null)
    {
        if (encoding is not null)
        {
            if (encoding is not ("UTF-8" or "UTF-16le" or "UTF-16be")) throw new ArgumentException("Unsupported test encoding", nameof(encoding));
            Execute("PRAGMA encoding='" + encoding + "'; CREATE TABLE encoding_fixture_marker (id INTEGER)");
        }
        Execute("CREATE TABLE versions (id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL);" +
            "CREATE TABLE version_identities (version_id INTEGER PRIMARY KEY, identity TEXT NOT NULL);" +
            "CREATE TABLE resources (version_id INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(version_id,name));" +
            "CREATE TABLE sync_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL)");
        var fixture = DatabaseMatchPythonVectors.Case("all-ten-match"); var active = fixture.GetProperty("active");
        Execute("INSERT INTO versions VALUES(@p0,@p1)", active[0].GetInt64(), active[1].GetString()!);
        Execute("INSERT INTO version_identities VALUES(@p0,@p1)", active[0].GetInt64(), active[2].GetString()!);
        Execute("INSERT INTO sync_state VALUES(1,@p0)", active[0].GetInt64());
        foreach (var row in fixture.GetProperty("rows").EnumerateArray())
            Execute("INSERT INTO resources VALUES(@p0,@p1,@p2,@p3)", row.GetProperty("active_id").GetInt64(),
                row.GetProperty("name").GetString()!, row.GetProperty("sha256").GetString()!,
                Convert.FromBase64String(row.GetProperty("data").GetProperty("value").GetString()!));
    }
    internal SqliteConnection Connection(bool readOnly = true) => new(new SqliteConnectionStringBuilder
    { DataSource = FileName, Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate, Pooling = false, DefaultTimeout = 1 }.ToString());
    internal void Execute(string sql, params object?[] values)
        => ExecuteParameters(sql, "@p", values);
    internal void ExecuteParameters(string sql, string prefix, params object?[] values)
    {
        using var connection = Connection(false); connection.Open(); using var command = connection.CreateCommand(); command.CommandText = sql;
        for (int i = 0; i < values.Length; i++) command.Parameters.AddWithValue(prefix + i, values[i] ?? DBNull.Value);
        command.ExecuteNonQuery();
    }
    internal static ManifestIdentity Identity()
    {
        var input = DatabaseMatchPythonVectors.Root.GetProperty("identity_inputs");
        var snapshot = OfficialVersionSnapshot.Parse(input.GetProperty("snapshot"));
        var manifests = new Dictionary<string, ManifestIdentityInput>(StringComparer.Ordinal);
        foreach (var row in input.GetProperty("manifests").EnumerateArray())
        {
            string name = row.GetProperty("package").GetString()!, version = row.GetProperty("package_version").GetString()!;
            manifests.Add(name, new(snapshot.DataVersion, name, version, name, version, "2.2.5", row.GetProperty("crc32_le").GetString()!, Convert.FromBase64String(row.GetProperty("bytes_base64").GetString()!)));
        }
        return ManifestIdentity.Derive(snapshot, manifests);
    }
    internal static Dictionary<string, string?> Digests() => DatabaseMatchPythonVectors.Case("all-ten-match").GetProperty("expected_digests").EnumerateArray()
        .ToDictionary(row => row.GetProperty("name").GetString()!, row => row.GetProperty("sha256").GetString(), StringComparer.Ordinal);
    internal static string Sha(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    public void Dispose()
    {
        foreach (string suffix in new[] { "", "-wal", "-shm", "-journal" }) File.Delete(FileName + suffix);
    }
}
