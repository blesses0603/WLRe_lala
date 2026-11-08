using System.Data;
using System.Data.Common;
using System.Runtime.ExceptionServices;
using System.Text;

namespace Lala.Core.Resources;

// A closed, exclusively supplied SQLite-compatible connection is required. This helper never
// selects a path/provider or changes host registration. All SQL is owned by the inventory port.
internal sealed class ResourceInventoryDatabase(DbConnection connection, CancellationToken token)
{
    internal const string OutcomeKey = "ResourceInventoryStore.WriteOutcome";
    internal const string CleanupKey = "ResourceInventoryStore.CleanupFailures";
    internal const string RollbackKey = "ResourceInventoryStore.RollbackSucceeded";
    private Encoding encoding = Encoding.UTF8;
    private bool beginAttempted, commitAttempted, commitExecuted;
    internal int TextByteMultiplier => encoding == Encoding.UTF8 ? 1 : 2;
    internal CancellationToken Token => token;

    internal async Task OpenAsync()
    {
        token.ThrowIfCancellationRequested();
        if (connection.State != ConnectionState.Closed) throw new InvalidOperationException("Inventory requires a closed, exclusively owned SQLite connection");
        await connection.OpenAsync(token).ConfigureAwait(false); token.ThrowIfCancellationRequested();
        if (connection.State != ConnectionState.Open) throw Invalid("Inventory provider did not open the connection");
        beginAttempted = true;
        await ExecuteAsync("BEGIN IMMEDIATE").ConfigureAwait(false);
        var rows = await ReadAsync("PRAGMA main.encoding", 1).ConfigureAwait(false);
        if (rows.Count != 1 || rows[0].Length != 1) throw Invalid("Database encoding is unavailable");
        encoding = Text(rows[0][0]) switch { "UTF-8" => Encoding.UTF8, "UTF-16le" => Encoding.Unicode, "UTF-16be" => Encoding.BigEndianUnicode,
            _ => throw Invalid("Unsupported database encoding") };
    }

    internal async Task CommitAsync(Action? admitCommit = null)
    {
        token.ThrowIfCancellationRequested();
        // Once COMMIT starts, resolve its outcome rather than returning an ordinary late
        // cancellation that could be mistaken for rollback. Provider timeout is not hard realtime.
        var command = Command("COMMIT", []);
        await UseAsync(command, async () =>
        {
            // Command construction/cleanup and provider work are outside the owner's gate.
            // Admission is the final cancellation/generation boundary. After it succeeds
            // COMMIT resolves uncancelled, even if publication is concurrently revoked.
            token.ThrowIfCancellationRequested();
            admitCommit?.Invoke();
            commitAttempted = true;
            await command.ExecuteNonQueryAsync(CancellationToken.None).ConfigureAwait(false);
            commitExecuted = true; // Must precede command disposal, which can separately fail.
            return true;
        }).ConfigureAwait(false);
    }

    internal async Task FinishAsync(Exception? primary)
    {
        var cleanup = new List<Exception>(); bool rolledBack = false;
        if (beginAttempted && !commitExecuted)
        {
            try
            {
                var command = Command("ROLLBACK", []);
                await UseAsync(command, async () =>
                {
                    await command.ExecuteNonQueryAsync(CancellationToken.None).ConfigureAwait(false); rolledBack = true; return true;
                }).ConfigureAwait(false);
            }
            catch (Exception error) { cleanup.Add(error); }
        }
        try { await connection.DisposeAsync().ConfigureAwait(false); }
        catch (Exception error) { cleanup.Add(error); }
        var outcome = commitExecuted ? ResourceInventoryWriteOutcome.Committed : commitAttempted || (beginAttempted && !rolledBack)
            ? ResourceInventoryWriteOutcome.Unknown : ResourceInventoryWriteOutcome.NotCommitted;
        if (primary is null && cleanup.Count != 0) primary = new AggregateException("Inventory cleanup failed", cleanup);
        else if (primary is not null && cleanup.Count != 0) AddCleanup(primary, cleanup);
        if (primary is not null)
        {
            primary.Data[OutcomeKey] = outcome; primary.Data[RollbackKey] = rolledBack;
            ExceptionDispatchInfo.Capture(primary).Throw();
        }
    }

    internal Task<int> ExecuteAsync(string sql, params (string Name, object? Value)[] parameters)
    {
        token.ThrowIfCancellationRequested(); var command = Command(sql, parameters);
        return UseAsync(command, () => command.ExecuteNonQueryAsync(token));
    }

    internal Task<List<object?[]>> ReadAsync(string sql, int maximumRows, params (string Name, object? Value)[] parameters)
    {
        token.ThrowIfCancellationRequested(); var command = Command(sql, parameters);
        return UseAsync(command, async () =>
        {
            var reader = await command.ExecuteReaderAsync(CommandBehavior.Default, token).ConfigureAwait(false);
            return await UseAsync(reader, async () =>
            {
                var result = new List<object?[]>(); long bytes = 0;
                if (reader.FieldCount > 16) throw Invalid("Unexpected inventory result shape");
                while (await reader.ReadAsync(token).ConfigureAwait(false))
                {
                    token.ThrowIfCancellationRequested();
                    if (result.Count == maximumRows) throw Invalid("Inventory database row quota exceeded");
                    var row = new object?[reader.FieldCount];
                    for (int column = 0; column < row.Length; column++)
                    {
                        token.ThrowIfCancellationRequested(); object? value = reader.GetValue(column);
                        if (value is DBNull) value = null;
                        if (value is byte[] blob)
                        {
                            if (blob.Length > ResourceInventoryInput.MaximumTableBytes) throw Invalid("Inventory database blob quota exceeded");
                            bytes += blob.Length; value = blob.ToArray(); // Detach before provider row advancement.
                        }
                        else if (value is string text)
                        {
                            if (text.Length > 512 * 1024) throw Invalid("Inventory database text quota exceeded");
                            bytes += (long)text.Length * sizeof(char);
                        }
                        if (bytes > 256L * 1024 * 1024) throw Invalid("Inventory database result quota exceeded");
                        row[column] = value;
                    }
                    result.Add(row);
                }
                if (await reader.NextResultAsync(token).ConfigureAwait(false)) throw Invalid("Unexpected inventory result set");
                token.ThrowIfCancellationRequested(); return result;
            }).ConfigureAwait(false);
        });
    }

    private DbCommand Command(string sql, (string Name, object? Value)[] values)
    {
        var command = connection.CreateCommand();
        try
        {
            command.CommandText = sql; command.CommandType = CommandType.Text; command.CommandTimeout = 5;
            foreach (var (name, value) in values)
            {
                var parameter = command.CreateParameter(); parameter.ParameterName = name;
                // Every string parameter is used inside CAST(@name AS TEXT). This preserves
                // embedded NULs and exact Unicode even in providers with NUL-terminated bindings.
                if (value is string text) { parameter.DbType = DbType.Binary; parameter.Value = encoding.GetBytes(text); }
                else if (value is byte[] bytes) { parameter.DbType = DbType.Binary; parameter.Value = bytes; }
                else { parameter.DbType = DbType.Int64; parameter.Value = value ?? DBNull.Value; }
                command.Parameters.Add(parameter);
            }
            return command;
        }
        catch (Exception error)
        {
            try { command.Dispose(); } catch (Exception cleanup) { AddCleanup(error, [cleanup]); }
            throw;
        }
    }

    private static async Task<T> UseAsync<T>(IAsyncDisposable resource, Func<Task<T>> operation)
    {
        Exception? primary = null; T result = default!;
        try { result = await operation().ConfigureAwait(false); }
        catch (Exception error) { primary = error; }
        try { await resource.DisposeAsync().ConfigureAwait(false); }
        catch (Exception error) { if (primary is null) primary = error; else AddCleanup(primary, [error]); }
        if (primary is not null) ExceptionDispatchInfo.Capture(primary).Throw();
        return result;
    }
    private static void AddCleanup(Exception error, IEnumerable<Exception> additions)
    {
        var failures = error.Data[CleanupKey] is IEnumerable<Exception> prior ? prior.ToList() : [];
        failures.AddRange(additions); error.Data[CleanupKey] = failures.AsReadOnly();
    }
    internal static string BoundedTextSql(string expression, int maximumBytes) =>
        $"CASE WHEN typeof({expression})='text' AND length(CAST({expression} AS BLOB))<={maximumBytes} THEN {expression} ELSE NULL END";
    internal static string Text(object? value) => value as string ?? throw Invalid("Invalid inventory text storage type");
    internal static long Number(object? value) => value is long number ? number : throw Invalid("Invalid inventory integer storage type");
    internal static InvalidDataException Invalid(string message) => new(message);
}
