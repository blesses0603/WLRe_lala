using Lala.Core.Resources.Inventory;
using System.Data.Common;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.Resources;

/// <summary>Complete bounded record_inventory persistence. active_id selects stored inventory;
/// it is never runtime activation, official provenance or permission to connect/send packets.
/// The caller supplies a closed exclusive SQLite write connection; no production registration.</summary>
internal static class ResourceInventoryStore
{
    private sealed record RawMetadata(string Digest, long Length);
    private static readonly (string File, string Source)[] OtherViews =
    [
        ("TalkData_C.bytes", "talk_v1"), ("TextData_C.bytes", "text_v1"), ("ScenesData_C.bytes", "scenes_v1"),
        ("Eve.bytes", "eve_npc_v1"), ("Eve.bytes", "eve_interact_v1")
    ];

    internal static async Task<ResourceInventoryReceipt> RecordAsync(DbConnection connection, ResourceInventoryInput input,
        CancellationToken cancellationToken = default, Action? admitCommit = null)
    {
        ArgumentNullException.ThrowIfNull(connection);
        var db = new ResourceInventoryDatabase(connection, cancellationToken);
        Exception? primary = null; ResourceInventoryReceipt? receipt = null;
        try
        {
            ArgumentNullException.ThrowIfNull(input);
            await db.OpenAsync().ConfigureAwait(false);
            await ResourceInventorySchema.EnsureAsync(db).ConfigureAwait(false);
            receipt = await RecordBodyAsync(db, input).ConfigureAwait(false);
            await db.CommitAsync(admitCommit).ConfigureAwait(false);
        }
        catch (Exception error) { primary = error; }
        await db.FinishAsync(primary).ConfigureAwait(false);
        // Cancellation after a confirmed COMMIT is not reported as rollback or ordinary
        // cancellation. If cleanup failed, FinishAsync throws with the committed outcome.
        return receipt!;
    }

    private static async Task<ResourceInventoryReceipt> RecordBodyAsync(ResourceInventoryDatabase db, ResourceInventoryInput input)
    {
        await db.ExecuteAsync("INSERT OR IGNORE INTO main.versions(catalog_key) VALUES (CAST(@key AS TEXT))", ("@key", input.CatalogKey)).ConfigureAwait(false);
        var versionRows = await db.ReadAsync("SELECT id FROM main.versions WHERE catalog_key=CAST(@key AS TEXT) LIMIT 2", 1, ("@key", input.CatalogKey)).ConfigureAwait(false);
        if (versionRows.Count != 1 || versionRows[0].Length != 1) throw Invalid("Inventory catalog version is missing or ambiguous");
        long current = ResourceInventoryDatabase.Number(versionRows[0][0]);
        if (input.IdentityJson is not null)
        {
            var identities = await db.ReadAsync("SELECT " + Text("identity", 16384) + " FROM main.version_identities WHERE version_id=@id LIMIT 2", 1, ("@id", current)).ConfigureAwait(false);
            if (identities.Count != 0 && ResourceInventoryDatabase.Text(identities[0][0]) != input.IdentityJson)
                throw Invalid("Catalog identity changed for the same catalog key");
            await db.ExecuteAsync("INSERT OR IGNORE INTO main.version_identities VALUES (@id,CAST(@identity AS TEXT))", ("@id", current), ("@identity", input.IdentityJson)).ConfigureAwait(false);
        }
        var activeRows = await db.ReadAsync("SELECT CASE WHEN typeof(active_id)='integer' THEN active_id ELSE 'invalid' END,CASE WHEN typeof(previous_id) IN ('integer','null') THEN previous_id ELSE 'invalid' END FROM main.sync_state WHERE singleton=1 LIMIT 2", 1).ConfigureAwait(false);
        var parentRows = await db.ReadAsync("SELECT CASE WHEN typeof(parent_id) IN ('integer','null') THEN parent_id ELSE 'invalid' END FROM main.version_parents WHERE version_id=@id LIMIT 2", 1, ("@id", current)).ConfigureAwait(false);
        long? active = activeRows.Count == 0 ? null : ResourceInventoryDatabase.Number(activeRows[0][0]);
        long? previous;
        if (active.HasValue && active.Value != current)
        {
            previous = active.Value;
            await db.ExecuteAsync("INSERT OR IGNORE INTO main.version_parents VALUES (@id,@parent)", ("@id", current), ("@parent", previous)).ConfigureAwait(false);
        }
        else
        {
            object? prior = activeRows.Count != 0 && activeRows[0][1] is not null ? activeRows[0][1] : parentRows.Count == 0 ? null : parentRows[0][0];
            long? value = prior is null ? null : ResourceInventoryDatabase.Number(prior);
            previous = value.HasValue && value.Value != current ? value : null;
        }
        await db.ExecuteAsync("INSERT OR REPLACE INTO main.sync_state(singleton,active_id,previous_id) VALUES (1,@id,@previous)", ("@id", current), ("@previous", previous)).ConfigureAwait(false);
        var priorMetadata = previous.HasValue ? await ReadRawMetadataAsync(db, previous.Value).ConfigureAwait(false) : new Dictionary<string, RawMetadata>(StringComparer.Ordinal);
        var existing = await ReadRawMetadataAsync(db, current).ConfigureAwait(false);
        var digests = input.Tables.ToDictionary(table => table.Name, table => table.Sha256, StringComparer.Ordinal);
        long finalBytes = existing.Values.Sum(row => row.Length);
        int finalCount = existing.Count;
        foreach (var table in input.Tables)
        {
            db.Token.ThrowIfCancellationRequested();
            if (existing.TryGetValue(table.Name, out var stored))
            {
                if (stored.Digest != table.Sha256) throw Invalid("Resource changed for the same catalog identity");
                byte[] actual = await ReadRawAsync(db, current, table.Name, stored.Digest).ConfigureAwait(false);
                if (!table.Bytes.SequenceEqual(actual)) throw Invalid("Stored raw resource bytes differ from the immutable input");
                continue;
            }
            if (++finalCount > ResourceInventoryInput.MaximumTables || (finalBytes += table.Length) > ResourceInventoryInput.MaximumRawBytes)
                throw Invalid("Accumulated inventory raw quota exceeded");
            await db.ExecuteAsync("INSERT INTO main.resources VALUES (@id,CAST(@name AS TEXT),CAST(@sha AS TEXT),@data) " +
                "ON CONFLICT(version_id,name) DO UPDATE SET sha256=excluded.sha256,data=excluded.data", ("@id", current),
                ("@name", table.Name), ("@sha", table.Sha256), ("@data", table.CopyBytes())).ConfigureAwait(false);
            byte[] persisted = await ReadRawAsync(db, current, table.Name, table.Sha256).ConfigureAwait(false);
            if (!table.Bytes.SequenceEqual(persisted)) throw Invalid("Stored raw resource bytes differ after insertion");
        }
        var tables = input.Tables.ToDictionary(table => table.Name, StringComparer.Ordinal);
        InventoryRowChanges? items = tables.TryGetValue("ItemData_C.bytes", out var itemRaw)
            ? await PersistViewAsync(db, current, previous, priorMetadata, itemRaw, "items_v1").ConfigureAwait(false) : null;
        InventoryRowChanges? smith = tables.TryGetValue("SmithData_C.bytes", out var smithRaw)
            ? await PersistViewAsync(db, current, previous, priorMetadata, smithRaw, "smith_v1").ConfigureAwait(false) : null;
        var others = new Dictionary<string, InventoryRowChanges>(StringComparer.Ordinal);
        foreach (var (file, source) in OtherViews)
            if (tables.TryGetValue(file, out var raw)) others.Add(source, await PersistViewAsync(db, current, previous, priorMetadata, raw, source).ConfigureAwait(false));
        await CheckDerivedQuotaAsync(db, current).ConfigureAwait(false);
        var priorDigests = priorMetadata.ToDictionary(pair => pair.Key, pair => pair.Value.Digest, StringComparer.Ordinal);
        return new(new(others, items, smith, previous.HasValue, digests, priorDigests), current);
    }

    private static async Task<InventoryRowChanges> PersistViewAsync(ResourceInventoryDatabase db, long current, long? previous,
        Dictionary<string, RawMetadata> priorMetadata, InventoryRawTable raw, string source)
    {
        Dictionary<string, string> rows;
        try { rows = Parse(raw.Bytes, source, db.Token); }
        catch (Exception error) when (ParseFailure(error)) { return InventoryRowChanges.ParseFailed(); }
        var old = new Dictionary<string, string>(StringComparer.Ordinal); string previousStatus = "unavailable";
        if (previous.HasValue && priorMetadata.TryGetValue(raw.Name, out var prior))
        {
            // Preserve source ordering: a failed current parse never requests/parses prior bytes.
            byte[] bytes = await ReadRawAsync(db, previous.Value, raw.Name, prior.Digest).ConfigureAwait(false);
            try { old = Parse(bytes, source, db.Token); previousStatus = "parsed"; }
            catch (Exception error) when (ParseFailure(error)) { previousStatus = "parse_failed"; }
        }
        var saved = await ReadDerivedRowsAsync(db, current, source).ConfigureAwait(false);
        if (saved.Count != 0 && (saved.Count != rows.Count || rows.Any(pair => !saved.TryGetValue(pair.Key, out string? value) || value != pair.Value)))
            throw Invalid(source == "items_v1" ? "Item rows changed for the same catalog identity" :
                source == "smith_v1" ? "Smith rows changed for the same catalog identity" : "Parsed rows changed for the same catalog identity");
        if (saved.Count == 0)
            foreach (var (key, value) in rows)
                await db.ExecuteAsync("INSERT INTO main.parsed_resource_rows VALUES (@id,CAST(@source AS TEXT),CAST(@key AS TEXT),CAST(@data AS TEXT))",
                    ("@id", current), ("@source", source), ("@key", key), ("@data", value)).ConfigureAwait(false);
        return InventoryRowChanges.Parsed(rows, old, previousStatus);
    }

    private static Dictionary<string, string> Parse(ReadOnlySpan<byte> bytes, string source, CancellationToken token) =>
        InventoryDerivedRows.Parse(source, bytes, token).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
    private static bool ParseFailure(Exception error) => error is CatalogDecodeException or EveDecodeException;

    private static async Task<Dictionary<string, RawMetadata>> ReadRawMetadataAsync(ResourceInventoryDatabase db, long version)
    {
        var rows = await db.ReadAsync("SELECT " + Text("name", 480) + "," + Text("sha256", 256) +
            ",length(CAST(data AS BLOB)) FROM main.resources WHERE version_id=@id LIMIT 257", ResourceInventoryInput.MaximumTables,
            ("@id", version)).ConfigureAwait(false);
        var result = new Dictionary<string, RawMetadata>(StringComparer.Ordinal); long total = 0;
        foreach (var row in rows)
        {
            if (row.Length != 3) throw Invalid("Invalid inventory raw metadata projection");
            string name = ResourceInventoryDatabase.Text(row[0]), digest = ResourceInventoryDatabase.Text(row[1]);
            ResourceInventoryInput.ValidateText(name, ResourceInventoryInput.MaximumNameCharacters);
            if (digest.Length > 64) throw Invalid("Invalid stored raw digest length");
            long length = ResourceInventoryDatabase.Number(row[2]);
            if (length < 0 || length > ResourceInventoryInput.MaximumTableBytes || (total += length) > ResourceInventoryInput.MaximumRawBytes ||
                !result.TryAdd(name, new(digest, length))) throw Invalid("Stored raw inventory is ambiguous or exceeds quota");
        }
        return result;
    }

    private static async Task<byte[]> ReadRawAsync(ResourceInventoryDatabase db, long version, string name, string expectedDigest)
    {
        var rows = await db.ReadAsync("SELECT " + Text("sha256", 256) + ",typeof(data),length(data)," +
            "CASE WHEN typeof(data)='blob' AND length(data)<=16777216 THEN data ELSE NULL END " +
            "FROM main.resources WHERE version_id=@id AND name=CAST(@name AS TEXT) LIMIT 2", 1, ("@id", version), ("@name", name)).ConfigureAwait(false);
        if (rows.Count != 1 || rows[0].Length != 4) throw Invalid("Stored raw resource is missing or ambiguous");
        var row = rows[0];
        if (ResourceInventoryDatabase.Text(row[0]) != expectedDigest || ResourceInventoryDatabase.Text(row[1]) != "blob" ||
            row[3] is not byte[] bytes || bytes.LongLength != ResourceInventoryDatabase.Number(row[2]) ||
            ResourceValidation.Digest(bytes, db.Token) != expectedDigest) throw Invalid("Stored raw resource integrity failure");
        return bytes;
    }

    private static async Task<Dictionary<string, string>> ReadDerivedRowsAsync(ResourceInventoryDatabase db, long version, string source)
    {
        var rows = await db.ReadAsync("SELECT " + Text("row_key", 512) + "," + Text("data", InventoryDerivedRows.MaximumRowJsonBytes * 4) +
            " FROM main.parsed_resource_rows WHERE version_id=@id AND source=CAST(@source AS TEXT) LIMIT 1000001", InventoryDerivedRows.MaximumRows,
            ("@id", version), ("@source", source)).ConfigureAwait(false);
        var result = new Dictionary<string, string>(StringComparer.Ordinal); long size = 2;
        foreach (var row in rows)
        {
            if (row.Length != 2) throw Invalid("Invalid derived row projection");
            string key = ResourceInventoryDatabase.Text(row[0]), data = ResourceInventoryDatabase.Text(row[1]);
            ResourceInventoryInput.ValidateText(key, 128);
            if (data.Length > InventoryDerivedRows.MaximumRowJsonBytes || data.Any(character => character > 127)) throw Invalid("Invalid derived JSON storage or quota");
            size += ResourceValidation.Quote(key).Length + 1L + data.Length + (result.Count == 0 ? 0 : 1);
            if (size > InventoryDerivedRows.MaximumViewJsonBytes || !result.TryAdd(key, data)) throw Invalid("Stored derived view is ambiguous or exceeds quota");
        }
        return result;
    }

    private static async Task CheckDerivedQuotaAsync(ResourceInventoryDatabase db, long version)
    {
        // Bound the accumulated version, not merely this request, so repeated partial imports
        // cannot evade the aggregate quota. Canonical derived JSON is ASCII; UTF-16 uses 2 bytes.
        var rows = await db.ReadAsync("SELECT count(*),coalesce(sum(length(CAST(data AS BLOB))),0) FROM main.parsed_resource_rows WHERE version_id=@id", 1,
            ("@id", version)).ConfigureAwait(false);
        if (rows.Count != 1 || rows[0].Length != 2 || ResourceInventoryDatabase.Number(rows[0][0]) > 2_000_000 ||
            ResourceInventoryDatabase.Number(rows[0][1]) > 128L * 1024 * 1024 * db.TextByteMultiplier)
            throw Invalid("Accumulated derived inventory quota exceeded");
    }
    private static string Text(string expression, int bytes) => ResourceInventoryDatabase.BoundedTextSql(expression, bytes);
    private static InvalidDataException Invalid(string message) => new(message);
}
