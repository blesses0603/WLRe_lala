using System.Collections;
using System.Data;
using System.Data.Common;
using System.Diagnostics.CodeAnalysis;

namespace Lala.Core.Tests.Resources;

// Fault-injecting DbConnection seam over the real test-only SQLite provider. No guessed provider.
internal sealed class ScriptedReadConnection(DbConnection inner) : DbConnection
{
    internal readonly List<string> Commands = [];
    internal readonly List<TrackedReadCommand> CreatedCommands = [];
    internal readonly List<TrackedReadDataReader> Readers = [];
    internal Action<TrackedReadCommand, CancellationToken>? BeforeExecute;
    internal Action<TrackedReadCommand>? AfterExecute;
    internal Action<TrackedReadDataReader>? BeforeBlobRead;
    internal Func<TrackedReadDataReader, int, object, object>? TransformValue;
    internal Func<TrackedReadDataReader, int, int>? TransformFieldCount;
    internal string? ExtraResultSql;
    internal Exception? OpenError, DisposeError, CommandDisposeError, ReaderDisposeError;
    internal bool WasDisposed;
    internal int Opens;
    internal DbConnection Inner => inner;
    [AllowNull] public override string ConnectionString { get => inner.ConnectionString; set => inner.ConnectionString = value; }
    public override string Database => inner.Database;
    public override string DataSource => inner.DataSource;
    public override string ServerVersion => inner.ServerVersion;
    public override ConnectionState State => inner.State;
    public override void ChangeDatabase(string databaseName) => throw new NotSupportedException();
    public override void Close() => inner.Close();
    public override void Open() => OpenAsync(CancellationToken.None).GetAwaiter().GetResult();
    public override async Task OpenAsync(CancellationToken cancellationToken)
    { Opens++; if (OpenError is not null) throw OpenError; await inner.OpenAsync(cancellationToken); }
    protected override DbTransaction BeginDbTransaction(IsolationLevel isolationLevel) => throw new InvalidOperationException("Reader must use explicit deferred BEGIN");
    protected override DbCommand CreateDbCommand()
    {
        var command = new TrackedReadCommand(this, inner.CreateCommand()); CreatedCommands.Add(command); return command;
    }
    internal void Before(TrackedReadCommand command, CancellationToken token)
    { Commands.Add(command.CommandText); BeforeExecute?.Invoke(command, token); }
    public override async ValueTask DisposeAsync()
    { WasDisposed = true; await inner.DisposeAsync(); if (DisposeError is not null) throw DisposeError; GC.SuppressFinalize(this); }
}

internal sealed class TrackedReadCommand(ScriptedReadConnection owner, DbCommand inner) : DbCommand
{
    internal bool WasDisposed;
    [AllowNull] public override string CommandText { get => inner.CommandText; set => inner.CommandText = value; }
    public override int CommandTimeout { get => inner.CommandTimeout; set => inner.CommandTimeout = value; }
    public override CommandType CommandType { get => inner.CommandType; set => inner.CommandType = value; }
    public override bool DesignTimeVisible { get => inner.DesignTimeVisible; set => inner.DesignTimeVisible = value; }
    public override UpdateRowSource UpdatedRowSource { get => inner.UpdatedRowSource; set => inner.UpdatedRowSource = value; }
    protected override DbConnection? DbConnection { get => owner; set { if (value != owner) throw new NotSupportedException(); } }
    protected override DbParameterCollection DbParameterCollection => inner.Parameters;
    protected override DbTransaction? DbTransaction { get => inner.Transaction; set => inner.Transaction = value; }
    public override void Cancel() => inner.Cancel();
    public override void Prepare() => throw new NotSupportedException();
    protected override DbParameter CreateDbParameter() => inner.CreateParameter();
    public override int ExecuteNonQuery() => ExecuteNonQueryAsync(CancellationToken.None).GetAwaiter().GetResult();
    public override object? ExecuteScalar() => throw new NotSupportedException();
    protected override DbDataReader ExecuteDbDataReader(CommandBehavior behavior) => ExecuteDbDataReaderAsync(behavior, CancellationToken.None).GetAwaiter().GetResult();
    public override async Task<int> ExecuteNonQueryAsync(CancellationToken cancellationToken)
    { owner.Before(this, cancellationToken); int result = await inner.ExecuteNonQueryAsync(cancellationToken); owner.AfterExecute?.Invoke(this); return result; }
    protected override async Task<DbDataReader> ExecuteDbDataReaderAsync(CommandBehavior behavior, CancellationToken cancellationToken)
    {
        owner.Before(this, cancellationToken);
        var reader = new TrackedReadDataReader(owner, this, await inner.ExecuteReaderAsync(behavior, cancellationToken)); owner.Readers.Add(reader);
        owner.AfterExecute?.Invoke(this); return reader;
    }
    public override async ValueTask DisposeAsync()
    { WasDisposed = true; await inner.DisposeAsync(); if (owner.CommandDisposeError is not null) throw owner.CommandDisposeError; GC.SuppressFinalize(this); }
}

internal sealed class TrackedReadDataReader(ScriptedReadConnection owner, TrackedReadCommand command, DbDataReader inner) : DbDataReader
{
    internal bool WasDisposed;
    internal string Sql => command.CommandText;
    internal int BlobReads;
    public override int FieldCount => owner.TransformFieldCount?.Invoke(this, inner.FieldCount) ?? inner.FieldCount;
    public override int Depth => inner.Depth;
    public override bool HasRows => inner.HasRows;
    public override bool IsClosed => inner.IsClosed;
    public override int RecordsAffected => inner.RecordsAffected;
    public override object this[int ordinal] => GetValue(ordinal);
    public override object this[string name] => GetValue(GetOrdinal(name));
    public override object GetValue(int ordinal)
    {
        if (Sql == Lala.Core.Resources.RuntimeDatabaseSnapshotReader.TableSql && ordinal == 5)
        { BlobReads++; owner.BeforeBlobRead?.Invoke(this); }
        object value = inner.GetValue(ordinal); return owner.TransformValue?.Invoke(this, ordinal, value) ?? value;
    }
    public override Type GetFieldType(int ordinal) => inner.GetFieldType(ordinal);
    public override long GetBytes(int ordinal, long dataOffset, byte[]? buffer, int bufferOffset, int length) =>
        throw new InvalidOperationException("Expression projection must not use provider blob-origin streaming");
    public override Stream GetStream(int ordinal) =>
        throw new InvalidOperationException("Expression projection must not use provider blob-origin streaming");
    public override bool Read() => inner.Read();
    public override Task<bool> ReadAsync(CancellationToken cancellationToken) => inner.ReadAsync(cancellationToken);
    public override bool NextResult() => inner.NextResult();
    public override Task<bool> NextResultAsync(CancellationToken cancellationToken) => owner.ExtraResultSql == Sql ? Task.FromResult(true) : inner.NextResultAsync(cancellationToken);
    public override string GetName(int ordinal) => inner.GetName(ordinal);
    public override string GetDataTypeName(int ordinal) => inner.GetDataTypeName(ordinal);
    public override int GetOrdinal(string name) => inner.GetOrdinal(name);
    public override int GetValues(object[] values) => inner.GetValues(values);
    public override bool IsDBNull(int ordinal) => inner.IsDBNull(ordinal);
    public override bool GetBoolean(int ordinal) => inner.GetBoolean(ordinal);
    public override byte GetByte(int ordinal) => inner.GetByte(ordinal);
    public override char GetChar(int ordinal) => inner.GetChar(ordinal);
    public override DateTime GetDateTime(int ordinal) => inner.GetDateTime(ordinal);
    public override decimal GetDecimal(int ordinal) => inner.GetDecimal(ordinal);
    public override double GetDouble(int ordinal) => inner.GetDouble(ordinal);
    public override float GetFloat(int ordinal) => inner.GetFloat(ordinal);
    public override Guid GetGuid(int ordinal) => inner.GetGuid(ordinal);
    public override short GetInt16(int ordinal) => inner.GetInt16(ordinal);
    public override int GetInt32(int ordinal) => inner.GetInt32(ordinal);
    public override long GetInt64(int ordinal) => inner.GetInt64(ordinal);
    public override string GetString(int ordinal) => inner.GetString(ordinal);
    public override long GetChars(int ordinal, long dataOffset, char[]? buffer, int bufferOffset, int length) => inner.GetChars(ordinal, dataOffset, buffer, bufferOffset, length);
    public override IEnumerator GetEnumerator() => ((IEnumerable)inner).GetEnumerator();
    public override async ValueTask DisposeAsync()
    { WasDisposed = true; await inner.DisposeAsync(); if (owner.ReaderDisposeError is not null) throw owner.ReaderDisposeError; GC.SuppressFinalize(this); }
}
