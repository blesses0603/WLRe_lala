using System.Data.Common;

namespace Lala.Core.Resources;

/// <summary>Opaque local compare-and-swap state, never official provenance or authority.
/// Captured before source preparation and compared inside the writer's IMMEDIATE transaction.
/// This detects a changed active selector/identity, not every intervening same-state write.</summary>
internal sealed record ResourceInventoryWriteBaseline(long? ActiveId, string? CatalogKeyHex, string? IdentityHex)
{
    internal static ResourceInventoryWriteBaseline Empty { get; } = new(null, null, null);

    internal static async Task<ResourceInventoryWriteBaseline> CaptureAsync(DbConnection connection, CancellationToken token)
    {
        ArgumentNullException.ThrowIfNull(connection);
        var db = new ResourceInventoryDatabase(connection, token);
        Exception? failure = null; ResourceInventoryWriteBaseline? result = null;
        try
        {
            await db.OpenAsync(write: false).ConfigureAwait(false);
            result = await ReadAsync(db).ConfigureAwait(false);
        }
        catch (Exception error) { failure = error; }
        // No COMMIT or DML: the shared cleanup primitive rolls back the read scope and owns
        // every connection/command/reader. No token or snapshot escapes cleanup failure.
        await db.FinishAsync(failure).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        return result!;
    }

    internal async Task EnsureUnchangedAsync(ResourceInventoryDatabase db)
    {
        if (this != await ReadAsync(db).ConfigureAwait(false))
            throw new InvalidDataException("Active inventory changed during source preparation; fresh explicit preparation is required");
    }

    private static async Task<ResourceInventoryWriteBaseline> ReadAsync(ResourceInventoryDatabase db)
    {
        var schema = await db.ReadAsync("SELECT name,type,rootpage FROM main.sqlite_schema " +
            "WHERE name IN ('versions','version_identities','sync_state') LIMIT 4", 3).ConfigureAwait(false);
        var present = new HashSet<string>(StringComparer.Ordinal);
        foreach (var row in schema)
            if (row.Length != 3 || !present.Add(ResourceInventoryDatabase.Text(row[0])) ||
                ResourceInventoryDatabase.Text(row[1]) != "table" || ResourceInventoryDatabase.Number(row[2]) <= 0)
                throw new InvalidDataException("Invalid inventory baseline schema");
        foreach (string table in present)
            await ResourceInventoryReadShape.ValidateAsync(db, table).ConfigureAwait(false);
        // Preserve the store's supported additive schema creation: no selector is Empty,
        // and an absent identity table is equivalent to a missing identity row. An existing
        // active selector without its versions table is malformed, not an empty inventory.
        if (!present.Contains("sync_state")) return Empty;
        if (!present.Contains("versions"))
        {
            if ((await db.ReadAsync("SELECT 1 FROM main.sync_state WHERE singleton=1 LIMIT 1", 1).ConfigureAwait(false)).Count != 0)
                throw new InvalidDataException("Active inventory baseline has no versions table");
            return Empty;
        }
        bool hasIdentities = present.Contains("version_identities");
        string identityColumns = hasIdentities ? "i.version_id,typeof(i.identity)," +
            HexText("i.identity", ResourceInventoryInput.MaximumIdentityCharacters * db.TextByteMultiplier) : "NULL,'null',NULL";
        var rows = await db.ReadAsync("SELECT CASE WHEN typeof(s.active_id)='integer' THEN s.active_id ELSE NULL END," +
            HexText("v.catalog_key", ResourceInventoryInput.MaximumCatalogKeyCharacters * 4) + "," + identityColumns +
            " FROM main.sync_state s LEFT JOIN main.versions v ON v.id=s.active_id" +
            (hasIdentities ? " LEFT JOIN main.version_identities i ON i.version_id=v.id" : "") +
            " WHERE s.singleton=1 LIMIT 2", 1).ConfigureAwait(false);
        if (rows.Count == 0) return Empty;
        var active = rows[0];
        if (active.Length != 5) throw new InvalidDataException("Invalid inventory baseline projection");
        long id = ResourceInventoryDatabase.Number(active[0]);
        string key = ResourceInventoryDatabase.Text(active[1]);
        string? identity = null;
        if (active[2] is not null)
        {
            if (ResourceInventoryDatabase.Number(active[2]) != id || ResourceInventoryDatabase.Text(active[3]) != "text")
                throw new InvalidDataException("Invalid inventory identity baseline");
            identity = ResourceInventoryDatabase.Text(active[4]);
        }
        if (key.Length > ResourceInventoryInput.MaximumCatalogKeyCharacters * 8 ||
            identity?.Length > ResourceInventoryInput.MaximumIdentityCharacters * db.TextByteMultiplier * 2)
            throw new InvalidDataException("Inventory baseline exceeds metadata bounds");
        return new(id, key, identity);
    }
    // Compare exact stored text bytes, not provider-decoded strings. This also avoids
    // malformed UTF-8 replacement characters aliasing different local baseline values.
    private static string HexText(string expression, int maximumBytes) =>
        $"CASE WHEN typeof({expression})='text' AND length(CAST({expression} AS BLOB))<={maximumBytes} " +
        $"THEN hex(CAST({expression} AS BLOB)) ELSE NULL END";

}
