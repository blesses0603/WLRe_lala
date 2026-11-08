using System.Data;
using System.Data.Common;
using System.Runtime.ExceptionServices;
using System.Text;

namespace Lala.Core.Resources;

/// <summary>A completed read scope under the documented SQLite provider contract, not official
/// authority. The detached snapshot remains suitable only for non-authorizing structural matching.</summary>
internal sealed class RuntimeDatabaseReadObservation(OwnedRuntimeDatabaseSnapshot snapshot)
{
    internal OwnedRuntimeDatabaseSnapshot Snapshot { get; } = snapshot;
    internal bool CompletedSingleReadTransaction => true;
    internal bool HasVerifiedProvenance => false;
    internal bool RuntimeAdmitted => false;
    internal bool AssetsReady => false;
    internal bool CanSendPackets => false;
}

/// <summary>Owns and disposes a closed, exclusively supplied, read-only SQLite-compatible
/// DbConnection. No provider discovery, filesystem access, schema writes or admission. Generic
/// DbConnection cannot verify read-only configuration or a dishonest provider's transaction claims.</summary>
internal static class RuntimeDatabaseSnapshotReader
{
    internal const int CommandTimeoutSeconds = 5;
    internal const string CleanupFailuresKey = "RuntimeDatabaseSnapshotReader.CleanupFailures";
    // CASE prevents an oversized value from entering the managed provider projection at all.
    // CAST-to-BLOB length also bounds text containing embedded NUL (SQLite text length stops there).
    internal const string EncodingSql = "PRAGMA main.encoding";
    internal const string SchemaSql = "SELECT name,type,rootpage FROM main.sqlite_schema " +
        "WHERE name IN ('sync_state','versions','version_identities','resources') LIMIT 5";
    internal const string ActiveSql = "SELECT typeof(s.active_id),CASE WHEN typeof(s.active_id)='integer' THEN s.active_id ELSE NULL END," +
        "typeof(v.catalog_key),length(CAST(v.catalog_key AS BLOB))," +
        "CASE WHEN typeof(v.catalog_key)='text' AND length(CAST(v.catalog_key AS BLOB))<=256 THEN v.catalog_key ELSE NULL END," +
        "typeof(i.identity),length(CAST(i.identity AS BLOB))," +
        "CASE WHEN typeof(i.identity)='text' AND length(CAST(i.identity AS BLOB))<=16384 THEN i.identity ELSE NULL END " +
        "FROM main.sync_state s JOIN main.versions v ON v.id=s.active_id " +
        "JOIN main.version_identities i ON i.version_id=v.id WHERE s.singleton=1 LIMIT 2";
    internal const string TableSql = "SELECT typeof(sha256),length(CAST(sha256 AS BLOB))," +
        "CASE WHEN typeof(sha256)='text' AND length(CAST(sha256 AS BLOB))<=256 THEN sha256 ELSE NULL END," +
        "typeof(data),length(data)," +
        "CASE WHEN typeof(data)='blob' AND length(data)>0 AND length(data)<=16777216 THEN data ELSE NULL END " +
        "FROM main.resources WHERE version_id=@version AND name=@name LIMIT 2";

    internal static async Task<RuntimeDatabaseReadObservation> ReadAsync(DbConnection connection,
        CancellationToken cancellationToken = default,
        long maximumAggregateBytes = OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes,
        bool includeSkillData = false, bool includeDailyCatalog = false)
    {
        ArgumentNullException.ThrowIfNull(connection);
        Exception? primary = null;
        List<Exception>? cleanup = null;
        OwnedRuntimeDatabaseSnapshot? snapshot = null;
        bool beginAttempted = false;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (maximumAggregateBytes is <= 0 or > OwnedRuntimeDatabaseSnapshot.MaximumOwnedTableBytes)
                throw new ArgumentOutOfRangeException(nameof(maximumAggregateBytes));
            if (connection.State != ConnectionState.Closed)
                throw new InvalidOperationException("A closed, exclusively owned read-only SQLite connection is required");
            await connection.OpenAsync(cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            if (connection.State != ConnectionState.Open) throw new InvalidOperationException("Provider did not open the connection");
            // Explicit deferred BEGIN matches Python. Generic BeginTransaction may instead
            // issue BEGIN IMMEDIATE on SQLite providers and acquire an unnecessary write lock.
            beginAttempted = true;
            await ExecuteScopeAsync(connection, "BEGIN", cancellationToken).ConfigureAwait(false);
            await CheckSchemaAsync(connection, cancellationToken).ConfigureAwait(false);
            var encoding = await ReadEncodingAsync(connection, cancellationToken).ConfigureAwait(false);
            var active = await ReadActiveAsync(connection, encoding, cancellationToken).ConfigureAwait(false);
            var rows = new Dictionary<string, RuntimeDatabaseTableInput?>(StringComparer.Ordinal);
            long aggregateBytes = 0;
            foreach (string source in BundleSourcePlan.RequiredTables)
            {
                cancellationToken.ThrowIfCancellationRequested();
                string name = source + ".bytes";
                var row = await ReadTableAsync(connection, active.VersionId, name, encoding, cancellationToken).ConfigureAwait(false);
                aggregateBytes = checked(aggregateBytes + row!.Data!.Value.Length);
                if (aggregateBytes > maximumAggregateBytes) throw Invalid("Resource snapshot exceeds aggregate payload limit");
                rows.Add(name, row);
            }
            if (includeSkillData)
            {
                cancellationToken.ThrowIfCancellationRequested();
                // Optional malformed/missing rows are represented by absence, not a failed
                // required snapshot. Provider calls, cancellation and disposal still throw.
                var skill = await ReadTableAsync(connection, active.VersionId, OwnedRuntimeDatabaseSnapshot.SkillTableName,
                    encoding, cancellationToken, optional: true,
                    maximumBytes: (int)Math.Min(OwnedRuntimeDatabaseSnapshot.MaximumTableBytes, maximumAggregateBytes - aggregateBytes)).ConfigureAwait(false);
                if (skill is not null)
                {
                    rows.Add(OwnedRuntimeDatabaseSnapshot.SkillTableName, skill);
                    aggregateBytes += skill.Data!.Value.Length;
                }
            }
            if (includeDailyCatalog)
            {
                foreach (string name in new[] { OwnedRuntimeDatabaseSnapshot.DailyTaskTableName, OwnedRuntimeDatabaseSnapshot.DailyRewardTableName })
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    var daily = await ReadTableAsync(connection, active.VersionId, name, encoding, cancellationToken, optional: true,
                        maximumBytes: (int)Math.Min(OwnedRuntimeDatabaseSnapshot.MaximumTableBytes, maximumAggregateBytes - aggregateBytes)).ConfigureAwait(false);
                    if (daily is not null)
                    {
                        rows.Add(name, daily);
                        aggregateBytes += daily.Data!.Value.Length;
                    }
                }
            }
            // Capture owns a second, detached copy before the transaction ends. At most 160 MiB
            // of temporary payloads plus 160 MiB retained payloads and a current provider value
            // of at most 16 MiB. Provider-internal caches/native buffers are external.
            snapshot = OwnedRuntimeDatabaseSnapshot.Capture(active, rows, cancellationToken, includeSkillData, includeDailyCatalog);
            cancellationToken.ThrowIfCancellationRequested();
        }
        catch (Exception error) { primary = error; }
        finally
        {
            // BEGIN can have executed even when a provider reports cancellation/failure. Always
            // attempt rollback after an attempted BEGIN, and never use the cancelled token here.
            if (beginAttempted)
            {
                try { await ExecuteScopeAsync(connection, "ROLLBACK", CancellationToken.None).ConfigureAwait(false); }
                catch (Exception error) { (cleanup ??= []).Add(error); }
            }
            try { await connection.DisposeAsync().ConfigureAwait(false); }
            catch (Exception error) { (cleanup ??= []).Add(error); }
        }
        if (primary is not null)
        {
            // Keep the original exception type and stack (especially cancellation), while
            // preserving secondary cleanup failures. No observation escapes either failure.
            if (cleanup is not null) RecordCleanup(primary, cleanup);
            ExceptionDispatchInfo.Capture(primary).Throw();
        }
        if (cleanup is not null) throw new AggregateException("Resource database read cleanup failed", cleanup);
        cancellationToken.ThrowIfCancellationRequested();
        return new(snapshot!);
    }

    private static Task<int> ExecuteScopeAsync(DbConnection connection, string sql, CancellationToken token)
    {
        var command = CreateCommand(connection, sql);
        return WithResourceAsync(command, () => command.ExecuteNonQueryAsync(token));
    }

    private static async Task CheckSchemaAsync(DbConnection connection, CancellationToken token)
    {
        await QueryAsync(connection, SchemaSql, null, async reader =>
        {
            var required = new HashSet<string>(["sync_state", "versions", "version_identities", "resources"], StringComparer.Ordinal);
            if (reader.FieldCount != 3) throw Invalid("Unexpected resource schema projection");
            int count = 0;
            while (await reader.ReadAsync(token).ConfigureAwait(false))
            {
                token.ThrowIfCancellationRequested();
                if (++count > 4 || !required.Remove(Text(reader, 0)) || Text(reader, 1) != "table" ||
                    reader.GetValue(2) is not long root || root <= 0)
                    throw Invalid("Resource schema requires unique ordinary main-database tables");
            }
            if (required.Count != 0 || await reader.NextResultAsync(token).ConfigureAwait(false))
                throw Invalid("Required resource schema is missing or ambiguous");
            return true;
        }, token).ConfigureAwait(false);
        foreach (string table in ResourceInventoryReadShape.SnapshotTables)
            await QueryAsync(connection, ResourceInventoryReadShape.ColumnsSql(table), null,
                reader => ResourceInventoryReadShape.ValidateReaderAsync(reader, table, token), token).ConfigureAwait(false);
    }

    private static Task<Encoding> ReadEncodingAsync(DbConnection connection, CancellationToken token) =>
        QueryAsync(connection, EncodingSql, null, async reader =>
        {
            if (reader.FieldCount != 1 || !await reader.ReadAsync(token).ConfigureAwait(false)) throw Invalid("Database encoding is missing");
            Encoding encoding = Text(reader, 0) switch
            {
                "UTF-8" => Encoding.UTF8, "UTF-16le" => Encoding.Unicode, "UTF-16be" => Encoding.BigEndianUnicode,
                _ => throw Invalid("Unsupported SQLite database encoding")
            };
            if (await reader.ReadAsync(token).ConfigureAwait(false) || await reader.NextResultAsync(token).ConfigureAwait(false))
                throw Invalid("Database encoding is ambiguous");
            token.ThrowIfCancellationRequested(); return encoding;
        }, token);

    private static Task<RuntimeDatabaseActiveInput> ReadActiveAsync(DbConnection connection, Encoding encoding, CancellationToken token) =>
        QueryAsync(connection, ActiveSql, null, async reader =>
        {
            token.ThrowIfCancellationRequested();
            if (reader.FieldCount != 8 || !await reader.ReadAsync(token).ConfigureAwait(false)) throw Invalid("Active identity is missing or malformed");
            if (Text(reader, 0) != "integer" || reader.GetValue(1) is not long version) throw Invalid("Active version must be an SQLite integer");
            string key = BoundedText(reader, 2, 3, 4, 256, 64, encoding);
            string identity = BoundedText(reader, 5, 6, 7, 16384, OwnedRuntimeDatabaseSnapshot.MaximumIdentityCharacters, encoding);
            if (await reader.ReadAsync(token).ConfigureAwait(false)) throw Invalid("Active identity is ambiguous");
            if (await reader.NextResultAsync(token).ConfigureAwait(false)) throw Invalid("Unexpected active result set");
            token.ThrowIfCancellationRequested();
            return new RuntimeDatabaseActiveInput(version, key, identity);
        }, token);

    private static Task<RuntimeDatabaseTableInput?> ReadTableAsync(DbConnection connection, long version, string name, Encoding encoding,
        CancellationToken token, bool optional = false, int maximumBytes = OwnedRuntimeDatabaseSnapshot.MaximumTableBytes) =>
        QueryAsync(connection, TableSql, command =>
        {
            AddParameter(command, "@version", DbType.Int64, version);
            AddParameter(command, "@name", DbType.String, name);
        }, async reader =>
        {
            token.ThrowIfCancellationRequested();
            if (reader.FieldCount != 6 || !await reader.ReadAsync(token).ConfigureAwait(false))
                return RejectTable(optional, "A required resource row is missing or malformed");
            if (!TryBoundedText(reader, 0, 1, 2, 256, 64, encoding, out string? digest))
                return RejectTable(optional, "Resource digest differs from the bounded SQLite projection");
            if (reader.GetValue(3) is not string storageType || storageType != "blob" || reader.GetValue(4) is not long length ||
                length <= 0 || length > maximumBytes)
                return RejectTable(optional, "Resource payload must be a nonempty bounded SQLite blob");
            token.ThrowIfCancellationRequested();
            // Use the documented bounded value API, not GetBytes/GetStream. Some SQLite
            // providers probe origin metadata in those streaming APIs; CASE-derived columns
            // have no table/column origin. The SQL guard already bounds this materialization.
            if (reader.GetValue(5) is not byte[] supplied || supplied.LongLength != length)
                return RejectTable(optional, "Provider blob type or length differs from the SQLite projection");
            byte[] bytes = new byte[(int)length];
            for (int position = 0; position < bytes.Length;)
            {
                token.ThrowIfCancellationRequested();
                int count = Math.Min(64 * 1024, bytes.Length - position);
                supplied.AsSpan(position, count).CopyTo(bytes.AsSpan(position, count));
                position += count;
            }
            token.ThrowIfCancellationRequested();
            if (await reader.ReadAsync(token).ConfigureAwait(false)) return RejectTable(optional, "Required resource row is ambiguous");
            if (await reader.NextResultAsync(token).ConfigureAwait(false)) return RejectTable(optional, "Unexpected resource result set");
            token.ThrowIfCancellationRequested();
            return new RuntimeDatabaseTableInput(version, name, digest, bytes);
        }, token);

    private static RuntimeDatabaseTableInput? RejectTable(bool optional, string message) => optional ? null : throw Invalid(message);

    private static Task<T> QueryAsync<T>(DbConnection connection, string sql, Action<DbCommand>? configure,
        Func<DbDataReader, Task<T>> action, CancellationToken token)
    {
        var command = CreateCommand(connection, sql);
        return WithResourceAsync(command, async () =>
        {
            configure?.Invoke(command);
            var reader = await command.ExecuteReaderAsync(CommandBehavior.SequentialAccess, token).ConfigureAwait(false);
            return await WithResourceAsync(reader, () => action(reader)).ConfigureAwait(false);
        });
    }

    private static async Task<T> WithResourceAsync<T>(IAsyncDisposable resource, Func<Task<T>> action)
    {
        Exception? primary = null; T result = default!;
        try { result = await action().ConfigureAwait(false); }
        catch (Exception error) { primary = error; }
        try { await resource.DisposeAsync().ConfigureAwait(false); }
        catch (Exception error)
        {
            if (primary is null) primary = error;
            else RecordCleanup(primary, [error]);
        }
        if (primary is not null) ExceptionDispatchInfo.Capture(primary).Throw();
        return result;
    }

    private static void RecordCleanup(Exception primary, IEnumerable<Exception> failures)
    {
        var combined = primary.Data[CleanupFailuresKey] is IEnumerable<Exception> prior ? prior.ToList() : [];
        combined.AddRange(failures); primary.Data[CleanupFailuresKey] = combined.AsReadOnly();
    }

    private static DbCommand CreateCommand(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        try { command.CommandText = sql; command.CommandTimeout = CommandTimeoutSeconds; return command; }
        catch (Exception error)
        {
            try { command.Dispose(); } catch (Exception cleanup) { RecordCleanup(error, [cleanup]); }
            throw;
        }
    }
    private static void AddParameter(DbCommand command, string name, DbType type, object value)
    {
        var parameter = command.CreateParameter(); parameter.ParameterName = name; parameter.DbType = type; parameter.Value = value;
        if (value is string text) parameter.Size = text.Length;
        command.Parameters.Add(parameter);
    }
    private static string BoundedText(DbDataReader reader, int type, int length, int data, int maximumBytes, int maximumCharacters, Encoding encoding)
    {
        if (Text(reader, type) != "text" || reader.GetValue(length) is not long size || size < 0 || size > maximumBytes)
            throw Invalid("SQLite text type or byte limit is invalid");
        if (reader.GetValue(data) is not string value || value.Length > maximumCharacters ||
            encoding.GetByteCount(value) != size) throw Invalid("Provider text differs from the bounded SQLite projection");
        return value;
    }
    private static bool TryBoundedText(DbDataReader reader, int type, int length, int data, int maximumBytes,
        int maximumCharacters, Encoding encoding, out string? value)
    {
        value = null;
        if (reader.GetValue(type) is not string storageType || storageType != "text" ||
            reader.GetValue(length) is not long size || size < 0 || size > maximumBytes ||
            reader.GetValue(data) is not string text || text.Length > maximumCharacters || encoding.GetByteCount(text) != size)
            return false;
        value = text;
        return true;
    }
    private static string Text(DbDataReader reader, int ordinal) => reader.GetValue(ordinal) is string value ? value : throw Invalid("Provider storage type is not text");
    private static InvalidDataException Invalid(string message) => new(message);
}
