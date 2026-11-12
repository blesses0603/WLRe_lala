using System.Security.Cryptography;
using System.Text.Json;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Tests.Resources;

internal sealed class InventoryTestDatabase : IDisposable
{
    private readonly string file = Path.Combine(Path.GetTempPath(), "lala-inventory-" + Guid.NewGuid().ToString("N") + ".sqlite");
    internal SqliteConnection Connection() => new(new SqliteConnectionStringBuilder
        { DataSource = file, Mode = SqliteOpenMode.ReadWriteCreate, Pooling = false, DefaultTimeout = 1 }.ToString());
    internal void Execute(string sql, params object?[] values)
    {
        using var db = Connection(); db.Open(); using var command = db.CreateCommand();
        for (int i = 0; i < values.Length; i++)
        {
            int marker = sql.IndexOf('?');
            if (marker >= 0) sql = sql[..marker] + "@p" + i + sql[(marker + 1)..];
            command.Parameters.AddWithValue("@p" + i, values[i] ?? DBNull.Value);
        }
        command.CommandText = sql; command.ExecuteNonQuery();
    }
    internal void Operations(JsonElement operations)
    {
        foreach (var op in operations.EnumerateArray())
            Execute(op.GetProperty("sql").GetString()!, op.GetProperty("parameters").EnumerateArray().Select(value => value.ValueKind switch
            {
                JsonValueKind.Null => null,
                JsonValueKind.String => (object?)value.GetString(),
                JsonValueKind.Number => value.GetInt64(),
                JsonValueKind.Object => Blob(value.GetProperty("blob_ref").GetString()!),
                _ => throw new InvalidOperationException("Unsupported retained SQL value")
            }).ToArray());
    }
    internal JsonElement Snapshot()
    {
        using var db = Connection(); db.Open();
        var tables = new Dictionary<string, object?>();
        foreach (var (table, order) in new[] { ("versions", "id"), ("version_identities", "version_id"),
            ("resources", "version_id,name"), ("parsed_resource_rows", "version_id,source,row_key"),
            ("sync_state", "singleton"), ("version_parents", "version_id") })
        {
            using var exists = db.CreateCommand(); exists.CommandText = "SELECT count(*) FROM sqlite_schema WHERE type='table' AND name=@name";
            exists.Parameters.AddWithValue("@name", table);
            if ((long)exists.ExecuteScalar()! == 0) { tables[table] = null; continue; }
            using var query = db.CreateCommand(); query.CommandText = $"SELECT * FROM {table} ORDER BY {order}";
            using var reader = query.ExecuteReader(); var rows = new List<Dictionary<string, object?>>();
            while (reader.Read())
            {
                var row = new Dictionary<string, object?>();
                for (int i = 0; i < reader.FieldCount; i++)
                {
                    object value = reader.GetValue(i); string name = reader.GetName(i);
                    if (table == "resources" && name == "data")
                    {
                        var bytes = (byte[])value; row["data_sha256"] = Sha(bytes); row["data_length"] = bytes.Length;
                    }
                    else row[name] = value is DBNull ? null : value;
                }
                rows.Add(row);
            }
            tables[table] = rows;
        }
        using var columnsCommand = db.CreateCommand(); columnsCommand.CommandText = "PRAGMA table_info(sync_state)";
        using var columnsReader = columnsCommand.ExecuteReader(); var columns = new List<string>();
        while (columnsReader.Read()) columns.Add(columnsReader.GetString(1));
        return JsonSerializer.SerializeToElement(new { tables, sync_state_columns = columns });
    }
    internal static byte[] Blob(string id)
    {
        var data = InventoryPythonVectors.Root.GetProperty("blobs").GetProperty(id); byte[] result;
        if (data.GetProperty("kind").GetString() == "base64") result = Convert.FromBase64String(data.GetProperty("value").GetString()!);
        else { result = new byte[data.GetProperty("length").GetInt32()]; Array.Fill(result, data.GetProperty("byte").GetByte()); }
        if (result.Length != data.GetProperty("size").GetInt32() || Sha(result) != data.GetProperty("sha256").GetString())
            throw new InvalidOperationException("Retained inventory blob recipe mismatch");
        return result;
    }
    internal static ManifestIdentity Identity(string id)
    {
        var input = InventoryPythonVectors.Root.GetProperty("identities").GetProperty(id);
        var snapshot = OfficialVersionSnapshot.Parse(input.GetProperty("snapshot"));
        var manifests = new Dictionary<string, ManifestIdentityInput>(StringComparer.Ordinal);
        foreach (var row in input.GetProperty("manifests").EnumerateArray())
        {
            string name = row.GetProperty("package").GetString()!, version = row.GetProperty("package_version").GetString()!;
            manifests.Add(name, new(snapshot.DataVersion, name, version, name, version, "2.2.5", row.GetProperty("crc32_le").GetString()!,
                Convert.FromBase64String(row.GetProperty("bytes_base64").GetString()!)));
        }
        return ManifestIdentity.Derive(snapshot, manifests);
    }
    internal static ResourceInventoryInput Input(JsonElement call)
    {
        var members = call.GetProperty("members").EnumerateArray().Select(member =>
            new ResourceInventoryMember(member.GetProperty("name").GetString()!,
                member.TryGetProperty("data_kind", out _) ? (ReadOnlyMemory<byte>?)null : Blob(member.GetProperty("blob_ref").GetString()!))).ToArray();
        string? identity = call.GetProperty("identity_ref").GetString();
        return ResourceInventoryInput.Capture(call.GetProperty("catalog_key").GetString()!, members, identity is null ? null : Identity(identity));
    }
    internal static ResourceInventoryInput Simple(string key = "synthetic", byte[]? bytes = null) =>
        ResourceInventoryInput.Capture(key, [new("tables/Opaque.bytes", bytes ?? [1, 2, 3])]);
    internal static string Sha(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
    public void Dispose()
    {
        foreach (string suffix in new[] { "", "-wal", "-shm", "-journal" }) File.Delete(file + suffix);
    }
}
