namespace Lala.Core.Resources;

internal static class ResourceInventorySchema
{
    private sealed record Table(string Name, string Definition, string? IndexOrigin, string[] IndexedColumns);
    private static readonly Table[] Tables =
    [
        new("versions", "id INTEGER PRIMARY KEY, catalog_key TEXT UNIQUE NOT NULL", "u", ["catalog_key"]),
        new("version_identities", "version_id INTEGER PRIMARY KEY, identity TEXT NOT NULL", null, []),
        new("resources", "version_id INTEGER NOT NULL, name TEXT NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(version_id,name)", "pk", ["version_id", "name"]),
        new("parsed_resource_rows", "version_id INTEGER NOT NULL, source TEXT NOT NULL, row_key TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(version_id,source,row_key)", "pk", ["version_id", "source", "row_key"]),
        new("sync_state", "singleton INTEGER PRIMARY KEY CHECK(singleton=1), active_id INTEGER NOT NULL", null, []),
        new("version_parents", "version_id INTEGER PRIMARY KEY, parent_id INTEGER", null, [])
    ];
    internal static async Task EnsureAsync(ResourceInventoryDatabase db)
    {
        foreach (var table in Tables)
        {
            var rows = await db.ReadAsync("SELECT type,rootpage," + ResourceInventoryDatabase.BoundedTextSql("sql", 32768) +
                " FROM main.sqlite_schema WHERE name=CAST(@name AS TEXT) LIMIT 2", 1, ("@name", table.Name)).ConfigureAwait(false);
            if (rows.Count == 0)
            {
                await db.ExecuteAsync($"CREATE TABLE main.{table.Name} ({table.Definition})").ConfigureAwait(false);
            }
            else
            {
                var row = rows[0];
                if (row.Length != 3 || ResourceInventoryDatabase.Text(row[0]) != "table" || ResourceInventoryDatabase.Number(row[1]) <= 0)
                    throw Invalid();
                string definition = Normalize(ResourceInventoryDatabase.Text(row[2]));
                string expected = Normalize($"CREATE TABLE {table.Name} ({table.Definition})");
                bool currentSync = table.Name == "sync_state" && definition == Normalize($"CREATE TABLE {table.Name} ({table.Definition}, previous_id INTEGER)");
                if (definition != expected && !currentSync) throw Invalid();
            }
            await ValidateObjectsAsync(db, table).ConfigureAwait(false);
        }
        var columns = await db.ReadAsync("PRAGMA main.table_xinfo('sync_state')", 4).ConfigureAwait(false);
        if (columns.Count == 2)
            await db.ExecuteAsync("ALTER TABLE main.sync_state ADD COLUMN previous_id INTEGER").ConfigureAwait(false);
        else if (columns.Count != 3 || ResourceInventoryDatabase.Text(columns[2][1]) != "previous_id") throw Invalid();
        // This is the source's only supported schema evolution. No user_version or invented
        // format marker is written; unrelated tables and schema versions remain untouched.
    }

    private static async Task ValidateObjectsAsync(ResourceInventoryDatabase db, Table table)
    {
        foreach (string schema in new[] { "main", "temp" })
        {
            var triggers = await db.ReadAsync($"SELECT 1 FROM {schema}.sqlite_schema WHERE type='trigger' AND tbl_name COLLATE NOCASE=CAST(@name AS TEXT) LIMIT 1", 1,
                ("@name", table.Name)).ConfigureAwait(false);
            if (triggers.Count != 0) throw Invalid();
        }
        if ((await db.ReadAsync($"SELECT 1 FROM pragma_foreign_key_list('{table.Name}','main') LIMIT 1", 1).ConfigureAwait(false)).Count != 0) throw Invalid();
        var indexes = await db.ReadAsync($"SELECT seq," + ResourceInventoryDatabase.BoundedTextSql("name", 512) + $",[unique],origin,partial FROM pragma_index_list('{table.Name}','main') LIMIT 3", 2).ConfigureAwait(false);
        if (indexes.Count != (table.IndexOrigin is null ? 0 : 1)) throw Invalid();
        if (indexes.Count == 1)
        {
            var index = indexes[0];
            if (index.Length != 5 || ResourceInventoryDatabase.Number(index[2]) != 1 ||
                ResourceInventoryDatabase.Text(index[3]) != table.IndexOrigin || ResourceInventoryDatabase.Number(index[4]) != 0) throw Invalid();
            string name = ResourceInventoryDatabase.Text(index[1]);
            ResourceInventoryInput.ValidateText(name, 128);
            var columns = await db.ReadAsync("SELECT seqno,cid," + ResourceInventoryDatabase.BoundedTextSql("name", 512) + ",desc," + ResourceInventoryDatabase.BoundedTextSql("coll", 512) + ",key FROM pragma_index_xinfo(CAST(@name AS TEXT),'main') LIMIT 6", 5,
                ("@name", name)).ConfigureAwait(false);
            if (columns.Count != table.IndexedColumns.Length + 1) throw Invalid();
            for (int i = 0; i < table.IndexedColumns.Length; i++)
            {
                var column = columns[i];
                if (column.Length != 6 || ResourceInventoryDatabase.Number(column[0]) != i ||
                    ResourceInventoryDatabase.Text(column[2]) != table.IndexedColumns[i] || ResourceInventoryDatabase.Number(column[3]) != 0 ||
                    ResourceInventoryDatabase.Text(column[4]) != "BINARY" || ResourceInventoryDatabase.Number(column[5]) != 1) throw Invalid();
            }
            if (ResourceInventoryDatabase.Number(columns[^1][1]) != -1 || ResourceInventoryDatabase.Number(columns[^1][5]) != 0) throw Invalid();
        }
    }
    private static string Normalize(string sql) => string.Concat(sql.Where(character => !char.IsWhiteSpace(character))).ToUpperInvariant();
    private static InvalidDataException Invalid() => new("Unknown or unsafe resource inventory schema; no reset or unsupported migration performed");
}
