using System.Data;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class InventoryPersistenceFailureTests
{
    [Theory]
    [InlineData("before-write")]
    [InlineData("late-insert")]
    [InlineData("reader-dispose")]
    [InlineData("read-wrong-type")]
    [InlineData("extra-result")]
    [InlineData("cancel-before-commit")]
    public async Task Failure_before_commit_rolls_back_ddl_and_every_row(string mode)
    {
        using var db = new InventoryTestDatabase(); var before = db.Snapshot();
        using var cancellation = new CancellationTokenSource(); var connection = new ScriptedReadConnection(db.Connection());
        var sentinel = new InvalidOperationException("scripted primary");
        connection.BeforeExecute = (command, _) =>
        {
            if (mode == "before-write" && command.CommandText.StartsWith("INSERT OR IGNORE INTO main.versions", StringComparison.Ordinal)) throw sentinel;
            if (mode == "late-insert" && command.CommandText.StartsWith("SELECT count(*)", StringComparison.Ordinal)) throw sentinel;
            if (mode == "extra-result" && command.CommandText == "PRAGMA main.encoding") connection.ExtraResultSql = command.CommandText;
        };
        connection.AfterExecute = command =>
        {
            if (command.CommandText == "PRAGMA main.encoding" && mode == "reader-dispose") connection.ReaderDisposeError = sentinel;
            if (command.CommandText.StartsWith("SELECT count(*)", StringComparison.Ordinal) && mode == "cancel-before-commit") cancellation.Cancel();
        };
        if (mode == "read-wrong-type") connection.TransformValue = (reader, _, value) => reader.Sql == "PRAGMA main.encoding" ? 42L : value;
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple(), cancellation.Token));
        Assert.NotNull(error); Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        Assert.Equal(true, error.Data[ResourceInventoryDatabase.RollbackKey]);
        if (mode is "before-write" or "late-insert" or "reader-dispose") Assert.Same(sentinel, error);
        if (mode == "cancel-before-commit") Assert.IsAssignableFrom<OperationCanceledException>(error);
        InventoryPersistenceParityTests.Equal(before, db.Snapshot(), mode + " rolled back schema/data");
        AssertDisposed(connection); Assert.Equal("ROLLBACK", connection.Commands[^1]); Assert.DoesNotContain("COMMIT", connection.Commands);
    }

    [Theory]
    [InlineData("commit-before", 2, false)]
    [InlineData("commit-after", 2, true)]
    [InlineData("commit-dispose", 1, true)]
    [InlineData("connection-dispose", 1, true)]
    public async Task Commit_errors_distinguish_confirmed_from_uncertain_outcomes(string mode, int expected, bool stored)
    {
        using var db = new InventoryTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        var sentinel = new InvalidOperationException("scripted commit/cleanup");
        connection.BeforeExecute = (command, token) =>
        {
            if (command.CommandText == "COMMIT")
            {
                Assert.False(token.CanBeCanceled);
                if (mode == "commit-before") throw sentinel;
            }
        };
        connection.AfterExecute = command =>
        {
            if (command.CommandText != "COMMIT") return;
            if (mode == "commit-after") throw sentinel;
            if (mode == "commit-dispose") connection.CommandDisposeError = sentinel;
            if (mode == "connection-dispose") connection.DisposeError = sentinel;
        };
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple()));
        Assert.NotNull(error); Assert.Equal((ResourceInventoryWriteOutcome)expected, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        if (mode != "connection-dispose") Assert.Same(sentinel, error);
        Assert.Equal(stored, db.Snapshot().GetProperty("tables").GetProperty("versions").ValueKind != System.Text.Json.JsonValueKind.Null);
        Assert.Single(connection.Commands, command => command == "COMMIT"); AssertDisposed(connection);
    }

    [Fact]
    public async Task Rollback_and_disposal_failures_do_not_mask_the_primary_or_certify_rollback()
    {
        using var db = new InventoryTestDatabase(); var connection = new ScriptedReadConnection(db.Connection());
        var primary = new InvalidOperationException("primary"); var rollback = new InvalidOperationException("rollback"); var disposal = new InvalidOperationException("dispose");
        connection.DisposeError = disposal;
        connection.BeforeExecute = (command, _) =>
        {
            if (command.CommandText == "ROLLBACK") throw rollback;
            if (command.CommandText.StartsWith("INSERT OR IGNORE INTO main.versions", StringComparison.Ordinal)) throw primary;
        };
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple()));
        Assert.Same(primary, error); Assert.Equal(ResourceInventoryWriteOutcome.Unknown, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        Assert.Equal(false, error.Data[ResourceInventoryDatabase.RollbackKey]);
        Assert.Equal(new[] { rollback, disposal }, Assert.IsAssignableFrom<IEnumerable<Exception>>(error.Data[ResourceInventoryDatabase.CleanupKey]));
        AssertDisposed(connection);
    }

    [Fact]
    public async Task Cancellation_after_commit_started_is_not_reported_as_rollback()
    {
        using var db = new InventoryTestDatabase(); using var source = new CancellationTokenSource();
        var connection = new ScriptedReadConnection(db.Connection());
        connection.BeforeExecute = (command, token) => { if (command.CommandText == "COMMIT") { Assert.False(token.CanBeCanceled); source.Cancel(); } };
        var receipt = await ResourceInventoryStore.RecordAsync(connection, InventoryTestDatabase.Simple(), source.Token);
        Assert.True(source.IsCancellationRequested); Assert.Equal(ResourceInventoryWriteOutcome.Committed, receipt.Outcome);
        Assert.Equal("COMMIT", connection.Commands[^1]); AssertDisposed(connection);
    }

    [Fact]
    public async Task Already_open_or_pre_cancelled_connection_never_begins_writes_and_is_disposed()
    {
        using var db = new InventoryTestDatabase(); var open = new ScriptedReadConnection(db.Connection()); await open.OpenAsync(default);
        var error = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(open, InventoryTestDatabase.Simple()));
        Assert.IsType<InvalidOperationException>(error); Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        Assert.Empty(open.Commands); AssertDisposed(open);
        var cancelled = new ScriptedReadConnection(db.Connection());
        var cancellation = await Record.ExceptionAsync(() => ResourceInventoryStore.RecordAsync(cancelled, InventoryTestDatabase.Simple(), new CancellationToken(true)));
        Assert.IsAssignableFrom<OperationCanceledException>(cancellation); Assert.Equal(0, cancelled.Opens); Assert.Empty(cancelled.Commands); AssertDisposed(cancelled);
    }

    private static void AssertDisposed(ScriptedReadConnection connection)
    {
        Assert.True(connection.WasDisposed); Assert.All(connection.CreatedCommands, command => Assert.True(command.WasDisposed));
        Assert.All(connection.Readers, reader => Assert.True(reader.WasDisposed));
    }
}
