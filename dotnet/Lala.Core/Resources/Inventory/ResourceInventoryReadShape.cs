using System.Collections.Immutable;
using System.Data.Common;

namespace Lala.Core.Resources;

/// <summary>Only the columns actually read by the resource pipeline must be ordinary stored
/// columns. Reject generated/hidden expressions before selecting values; unrelated columns
/// remain outside this read contract. This is not full schema compatibility or provenance.</summary>
internal static class ResourceInventoryReadShape
{
    internal static ImmutableArray<string> SnapshotTables { get; } = ["sync_state", "versions", "version_identities", "resources"];
    private static ImmutableArray<string> Columns(string table) => table switch
    {
        "sync_state" => ["singleton", "active_id"],
        "versions" => ["id", "catalog_key"],
        "version_identities" => ["version_id", "identity"],
        "resources" => ["version_id", "name", "sha256", "data"],
        _ => throw new ArgumentOutOfRangeException(nameof(table))
    };
    internal static string ColumnsSql(string table)
    {
        var columns = Columns(table); // Only fixed, owned identifiers enter this SQL.
        return $"SELECT name,cid,hidden FROM pragma_table_xinfo('{table}','main') WHERE name IN (" +
            string.Join(',', columns.Select(column => "'" + column + "'")) + $") LIMIT {columns.Length + 1}";
    }
    internal static async Task ValidateAsync(ResourceInventoryDatabase db, string table)
        => Validate(table, await db.ReadAsync(ColumnsSql(table), Columns(table).Length).ConfigureAwait(false));

    internal static async Task<bool> ValidateReaderAsync(DbDataReader reader, string table, CancellationToken token)
    {
        if (reader.FieldCount != 3) throw Invalid();
        var rows = new List<object?[]>();
        int maximum = Columns(table).Length;
        while (await reader.ReadAsync(token).ConfigureAwait(false))
        {
            token.ThrowIfCancellationRequested();
            if (rows.Count == maximum) throw Invalid();
            rows.Add([reader.GetValue(0), reader.GetValue(1), reader.GetValue(2)]);
        }
        if (await reader.NextResultAsync(token).ConfigureAwait(false)) throw Invalid();
        token.ThrowIfCancellationRequested(); Validate(table, rows); return true;
    }
    private static void Validate(string table, IReadOnlyList<object?[]> rows)
    {
        var expected = Columns(table).ToHashSet(StringComparer.Ordinal);
        if (rows.Count != expected.Count) throw Invalid();
        foreach (var row in rows)
            if (row.Length != 3 || row[0] is not string name || !expected.Remove(name) ||
                row[1] is not long ordinal || ordinal < 0 || row[2] is not long hidden || hidden != 0)
                throw Invalid();
        if (expected.Count != 0) throw Invalid();
    }
    private static InvalidDataException Invalid() => new("Resource reads require ordinary stored identity and payload columns");
}
