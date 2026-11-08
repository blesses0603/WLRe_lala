using System.Globalization;
using System.Text;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static readonly TimeSpan Timeout = TimeSpan.FromSeconds(15);
    private sealed class Source : IResourceSource, IDisposable
    {
        internal byte[] Bundle = RuntimeFlowFixtures.Read("all-ten.bundle");
        internal byte[] Main = BundleSourceFixtures.Bytes("main-valid");
        internal byte[] Data;
        internal int Observations, Disposals;
        internal Func<int, Task>? BeforeObserve;
        internal Action<CancellationToken>? OnToken;
        internal Func<int, OfficialVersionSnapshot> Snapshot = _ => RuntimeFlowFixtures.Snapshot();
        internal string? BundleLength;
        internal Source() => Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = Bundle });
        public void Dispose() => Disposals++;
        public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
        {
            int n = ++Observations; OnToken?.Invoke(token);
            if (BeforeObserve is not null) await BeforeObserve(n);
            token.ThrowIfCancellationRequested(); return Snapshot(n);
        }
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            string name = url[(url.LastIndexOf('/') + 1)..];
            byte[] bytes = name switch
            {
                "DataPackage.bytes" => Data, "MainPackage.bytes" => Main,
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                "all-ten.bundle" => Bundle, _ => throw new InvalidDataException("Unexpected owned fixture request")
            };
            return ValueTask.FromResult(new ResourceResponse(url, 200,
                name == "all-ten.bundle" && BundleLength is not null ? BundleLength : bytes.Length.ToString(CultureInfo.InvariantCulture), new MemoryStream(bytes, false)));
        }
    }
    private sealed class Fixture : IDisposable
    {
        internal readonly string Root = Path.Combine(Path.GetTempPath(), "lala-bootstrap-" + Guid.NewGuid().ToString("N"));
        internal string Inventory => Path.Combine(Root, "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        internal object? Sql(string sql)
        {
            using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = Inventory, Pooling = false }.ToString());
            connection.Open(); using var command = connection.CreateCommand(); command.CommandText = sql;
            return command.ExecuteScalar();
        }
        internal byte[] Bytes() => File.ReadAllBytes(Inventory);
        public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }
    private static bool ReadOnly(SqliteConnection c) => new SqliteConnectionStringBuilder(c.ConnectionString).Mode == SqliteOpenMode.ReadOnly;
    private static void Published(ResourceRuntimeBootstrapResult result, ResourceRuntimeOwner owner)
    {
        Assert.True(result.StorageAttempted); Assert.True(result.CommitAdmitted);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome);
        Assert.NotNull(result.Receipt); Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback);
        Assert.True(result.SourcesRechecked); Assert.True(result.WasPublished); Assert.Null(result.Failure);
        Assert.Same(result.Publication, owner.Current);
        Assert.False(result.Publication!.ResourceAdmitted); Assert.False(result.Publication.TlsOriginObserved);
        Assert.False(result.Publication.CanLogin); Assert.False(result.Publication.CanSendPackets);
        Assert.False(result.Publication.Candidate.RuntimeAdmitted);
    }
    [Fact]
    public async Task Missing_inventory_bootstraps_exactly_six_tables_then_independently_reads_only()
    {
        using var fixture = new Fixture(); var modes = new List<SqliteOpenMode>(); ScriptedReadConnection? writer = null; ScriptedReadConnection? reader = null;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                modes.Add(new SqliteConnectionStringBuilder(c.ConnectionString).Mode);
                if (!ReadOnly(c)) return writer = new ScriptedReadConnection(c);
                Assert.NotNull(writer); Assert.True(writer.WasDisposed);
                return reader = new ScriptedReadConnection(c);
            }
        });
        Assert.False(Directory.Exists(fixture.Root));
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        Assert.Equal(new[] { SqliteOpenMode.ReadWriteCreate, SqliteOpenMode.ReadOnly }, modes);
        Assert.NotNull(writer); Assert.NotNull(reader); Assert.True(reader.WasDisposed);
        Assert.Single(writer.Commands, sql => sql == "COMMIT");
        Assert.DoesNotContain(reader.Commands, sql => sql.StartsWith("INSERT", StringComparison.Ordinal) || sql.StartsWith("CREATE", StringComparison.Ordinal) || sql.StartsWith("UPDATE", StringComparison.Ordinal));
        Assert.Equal(6L, fixture.Sql("SELECT count(*) FROM sqlite_schema WHERE type='table'"));
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(new[] { fixture.Inventory }, Directory.GetFiles(fixture.Root, "*", SearchOption.AllDirectories));
    }
    [Fact]
    public async Task Repeat_bootstrap_is_idempotent_and_preserves_unrelated_user_table()
    {
        using var fixture = new Fixture(); await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        fixture.Sql("CREATE TABLE retained(value TEXT); INSERT INTO retained VALUES('untouched');");
        var second = await owner.BootstrapAndRefreshAsync(); Published(second, owner);
        Assert.True(second.Publication!.Generation > first.Publication!.Generation);
        Assert.Equal("untouched", fixture.Sql("SELECT value FROM retained"));
        Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }
    [Theory]
    [InlineData("blob")]
    [InlineData("forged-hash")]
    [InlineData("identity")]
    [InlineData("trigger")]
    [InlineData("schema")]
    [InlineData("derived")]
    public async Task Existing_unsafe_or_immutable_collision_is_not_reset(string mode)
    {
        using var fixture = new Fixture(); await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        Published(await owner.BootstrapAndRefreshAsync(), owner);
        fixture.Sql(mode switch
        {
            "blob" => "UPDATE resources SET data=x'00000000' WHERE name='Eve.bytes'",
            "forged-hash" => "UPDATE resources SET sha256=printf('%064d',0) WHERE name='Eve.bytes'",
            "identity" => "UPDATE version_identities SET identity='{}'",
            "trigger" => "CREATE TRIGGER hostile AFTER INSERT ON resources BEGIN SELECT 1; END",
            "schema" => "ALTER TABLE resources ADD COLUMN unsupported TEXT",
            _ => "UPDATE parsed_resource_rows SET data='{}' WHERE rowid=(SELECT min(rowid) FROM parsed_resource_rows)"
        });
        byte[] before = fixture.Bytes();
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.True(result.StorageAttempted); Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, result.StorageOutcome);
        Assert.False(result.CommitAdmitted); Assert.False(result.WasPublished); Assert.NotNull(result.Failure);
        Assert.Null(owner.Current); Assert.Equal(before, fixture.Bytes());
    }
    [Theory]
    [InlineData("malformed")]
    [InlineData("missing")]
    [InlineData("oversize")]
    [InlineData("missing-path.bundle")]
    [InlineData("late-invalid.bundle")]
    [InlineData("aggregate-overflow.bundle")]
    public async Task Invalid_bundle_never_creates_inventory(string mode)
    {
        using var fixture = new Fixture(); var source = new Source();
        if (mode == "malformed") { source.Bundle = new byte[128]; source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = source.Bundle }); }
        if (mode.EndsWith(".bundle", StringComparison.Ordinal)) { source.Bundle = RuntimeFlowFixtures.Read(mode); source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = source.Bundle }); }
        if (mode == "missing") source.Bundle = [];
        if (mode == "oversize") source.BundleLength = long.MaxValue.ToString(CultureInfo.InvariantCulture);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.False(result.StorageAttempted); Assert.False(result.CommitAdmitted); Assert.False(result.WasPublished);
        Assert.NotNull(result.Failure); Assert.False(File.Exists(fixture.Inventory)); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData("before-write")]
    [InlineData("dml")]
    [InlineData("before-admission")]
    [InlineData("commit")]
    [InlineData("after-commit")]
    public async Task Cancellation_preserves_commit_boundary_and_never_publishes(string phase)
    {
        using var fixture = new Fixture(); using var cancel = new CancellationTokenSource();
        ScriptedReadConnection? writer = null;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            BeforeWrite = () => { if (phase == "before-write") cancel.Cancel(); return Task.CompletedTask; },
            BeforeCommitAdmission = () => { if (phase == "before-admission") cancel.Cancel(); },
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                writer = new(c);
                writer.BeforeExecute = (command, token) =>
                {
                    if (phase == "dml" && command.CommandText.StartsWith("INSERT OR IGNORE INTO main.versions", StringComparison.Ordinal)) cancel.Cancel();
                    if (phase == "commit" && command.CommandText == "COMMIT") { Assert.False(token.CanBeCanceled); cancel.Cancel(); }
                };
                writer.AfterExecute = command => { if (phase == "after-commit" && command.CommandText == "COMMIT") cancel.Cancel(); };
                return writer;
            }
        });
        var result = await owner.BootstrapAndRefreshAsync(cancel.Token);
        bool committed = phase is "commit" or "after-commit";
        Assert.Equal(committed ? ResourceInventoryWriteOutcome.Committed : ResourceInventoryWriteOutcome.NotCommitted, result.StorageOutcome);
        Assert.Equal(committed, result.CommitAdmitted); Assert.False(result.WasPublished); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
        if (writer is not null) { Assert.True(writer.WasDisposed); Assert.Equal(committed, writer.Commands.Contains("COMMIT")); }
    }
    [Theory]
    [InlineData("commit-before", false, false)]
    [InlineData("commit-after", false, true)]
    [InlineData("command-cleanup", true, true)]
    [InlineData("connection-cleanup", true, true)]
    public async Task Commit_execution_uncertainty_and_confirmed_cleanup_failures_stay_distinct(string mode, bool confirmed, bool stored)
    {
        using var fixture = new Fixture(); var sentinel = new IOException("scripted commit failure");
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                var writer = new ScriptedReadConnection(c);
                writer.BeforeExecute = (command, _) => { if (mode == "commit-before" && command.CommandText == "COMMIT") throw sentinel; };
                writer.AfterExecute = command =>
                {
                    if (command.CommandText != "COMMIT") return;
                    if (mode == "commit-after") throw sentinel;
                    if (mode == "command-cleanup") writer.CommandDisposeError = sentinel;
                    if (mode == "connection-cleanup") writer.DisposeError = sentinel;
                };
                return writer;
            }
        });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.True(result.CommitAdmitted); Assert.True(result.StorageAttempted);
        Assert.Equal(confirmed ? ResourceInventoryWriteOutcome.Committed : ResourceInventoryWriteOutcome.Unknown, result.StorageOutcome);
        Assert.NotNull(result.Failure); Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(stored ? 1L : 0L, fixture.Sql("SELECT count(*) FROM sqlite_schema WHERE name='resources'"));
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Independent_readback_failure_or_tamper_prevents_publication_after_commit(bool tamper)
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            BeforeReadback = () => { if (tamper) fixture.Sql("UPDATE resources SET data=x'0000' WHERE name='Eve.bytes'"); return Task.CompletedTask; },
            WrapConnection = c => ReadOnly(c) && !tamper ? new ScriptedReadConnection(c) { OpenError = new IOException("readback") } : c
        });
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.True(result.CommitAdmitted);
        Assert.Equal(ResourceRuntimeReadback.Failed, result.Readback); Assert.False(result.WasPublished); Assert.Null(owner.Current); Assert.NotNull(result.Failure);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Manifest_or_version_drift_after_readback_does_not_publish(bool version)
    {
        using var fixture = new Fixture(); var source = new Source();
        source.BeforeObserve = n =>
        {
            if (n == 7)
            {
                if (version) source.Snapshot = _ => RuntimeFlowFixtures.Snapshot("1.3.22");
                else source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["replacement.bundle"] = source.Bundle });
            }
            return Task.CompletedTask;
        };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback);
        Assert.False(result.SourcesRechecked); Assert.False(result.WasPublished); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Invalidation_or_dispose_before_commit_rejects_admission_and_joins_retirement(bool dispose)
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        { BeforeWrite = async () => { entered.SetResult(); await release.Task.WaitAsync(Timeout); } });
        Task? disposal = null;
        var operation = owner.BootstrapAndRefreshAsync();
        try
        {
            await entered.Task.WaitAsync(Timeout);
            if (dispose) { disposal = owner.DisposeAsync().AsTask(); Assert.False(disposal.IsCompleted); }
            else owner.Invalidate();
            await Assert.ThrowsAnyAsync<InvalidOperationException>(() => owner.RefreshAsync());
            await Assert.ThrowsAnyAsync<InvalidOperationException>(() => owner.BootstrapAndRefreshAsync());
        }
        finally { release.TrySetResult(); }
        var result = await operation.WaitAsync(Timeout);
        Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, result.StorageOutcome); Assert.False(result.CommitAdmitted);
        Assert.False(result.WasPublished); Assert.Null(owner.Current);
        if (disposal is not null) await disposal.WaitAsync(Timeout);
        else await owner.DisposeAsync();
        Assert.Equal(1, source.Disposals);
    }
    [Fact]
    public async Task Prepared_inventory_owns_exact_ten_tables_and_hashes_after_source_mutation()
    {
        var source = new Source();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Equal(prepared.Identity.Key, prepared.InventoryInput.CatalogKey);
        Assert.Equal(prepared.Identity.CanonicalJson, prepared.InventoryInput.IdentityJson);
        Assert.Equal(10, prepared.InventoryInput.Tables.Length);
        var before = prepared.InventoryInput.Tables.ToDictionary(t => t.Name, t => t.CopyBytes());
        Array.Fill(source.Bundle, (byte)0); Array.Fill(source.Data, (byte)0);
        foreach (var table in prepared.InventoryInput.Tables)
        {
            Assert.Equal(before[table.Name], table.CopyBytes());
            Assert.Equal(prepared.Candidate.SourceSha256[Path.GetFileNameWithoutExtension(table.Name)], table.Sha256);
            Assert.Equal(Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(table.CopyBytes())), table.Sha256);
        }
    }
    [Fact]
    public async Task Changed_official_identity_records_previous_and_parent_without_replacing_old_rows()
    {
        using var fixture = new Fixture(); var source = new Source();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        source.Snapshot = _ => RuntimeFlowFixtures.Snapshot("1.3.22");
        var second = await owner.BootstrapAndRefreshAsync(); Published(second, owner);
        Assert.NotEqual(first.Publication!.Identity.Key, second.Publication!.Identity.Key);
        Assert.Equal(2L, fixture.Sql("SELECT count(*) FROM versions"));
        Assert.Equal(2L, fixture.Sql("SELECT count(*) FROM version_identities"));
        Assert.Equal(20L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(first.Receipt!.VersionId, fixture.Sql("SELECT previous_id FROM sync_state"));
        Assert.Equal(second.Receipt!.VersionId, fixture.Sql("SELECT active_id FROM sync_state"));
        Assert.Equal(first.Receipt.VersionId, fixture.Sql($"SELECT parent_id FROM version_parents WHERE version_id={second.Receipt.VersionId}"));
        Assert.True(second.Receipt.Report.PreviousAvailable);
        var repeated = await owner.BootstrapAndRefreshAsync(); Published(repeated, owner);
        Assert.Equal(first.Receipt.VersionId, fixture.Sql("SELECT previous_id FROM sync_state"));
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Invalidation_or_dispose_after_commit_admission_preserves_committed_outcome(bool dispose)
    {
        using var fixture = new Fixture(); ResourceRuntimeOwner? owner = null; Task? disposal = null;
        owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                var writer = new ScriptedReadConnection(c);
                writer.BeforeExecute = (command, token) =>
                {
                    if (command.CommandText != "COMMIT") return;
                    Assert.False(token.CanBeCanceled);
                    if (dispose)
                    {
                        using var admitted = new ManualResetEventSlim();
                        using (ExecutionContext.SuppressFlow()) disposal = Task.Run(async () =>
                        { var pending = owner!.DisposeAsync(); admitted.Set(); await pending; });
                        Assert.True(admitted.Wait(Timeout));
                    }
                    owner!.Invalidate();
                };
                return writer;
            }
        });
        try
        {
            var result = await owner.BootstrapAndRefreshAsync().WaitAsync(Timeout);
            Assert.True(result.CommitAdmitted); Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome);
            Assert.False(result.WasPublished); Assert.Null(owner.Current);
            Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        }
        finally { if (disposal is not null) await disposal.WaitAsync(Timeout); await owner.DisposeAsync(); }
    }
    [Fact]
    public async Task Blocked_cancellation_callback_keeps_both_entrypoints_busy_until_true_cleanup()
    {
        using var fixture = new Fixture(); var source = new Source();
        using var callbackRelease = new ManualResetEventSlim();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, cleanupEntered: () => cleanupEntered.TrySetResult());
        source.OnToken = token => token.Register(() =>
        {
            owner.Invalidate(); callbackEntered.TrySetResult();
            if (!callbackRelease.Wait(Timeout)) throw new TimeoutException("Callback release timed out");
        });
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(Timeout); };
        var bootstrap = owner.BootstrapAndRefreshAsync(); Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(Timeout); owner.Invalidate(); await callbackEntered.Task.WaitAsync(Timeout);
            observeRelease.TrySetResult(); await cleanupEntered.Task.WaitAsync(Timeout);
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.BootstrapAndRefreshAsync());
            disposal = owner.DisposeAsync().AsTask();
            Assert.Same(disposal, owner.DisposeAsync().AsTask());
            Assert.False(bootstrap.IsCompleted); Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        finally { callbackRelease.Set(); observeRelease.TrySetResult(); }
        var result = await bootstrap.WaitAsync(Timeout);
        Assert.False(result.StorageAttempted); Assert.False(result.WasPublished); Assert.NotNull(result.Failure);
        if (disposal is not null) await disposal.WaitAsync(Timeout); else await owner.DisposeAsync();
        Assert.Equal(1, source.Disposals); Assert.False(File.Exists(fixture.Inventory));
    }

    [Theory]
    [InlineData("dml", false)]
    [InlineData("dml", true)]
    [InlineData("admission", false)]
    [InlineData("admission", true)]
    [InlineData("confirmed", false)]
    [InlineData("confirmed", true)]
    public async Task Revocation_at_write_boundaries_has_truthful_durability(string phase, bool dispose)
    {
        using var fixture = new Fixture(); ResourceRuntimeOwner? owner = null; Task? disposal = null;
        void Revoke()
        {
            if (dispose)
            {
                using var admitted = new ManualResetEventSlim();
                using (ExecutionContext.SuppressFlow()) disposal = Task.Run(async () =>
                {
                    var pending = owner!.DisposeAsync(); admitted.Set(); await pending;
                });
                Assert.True(admitted.Wait(Timeout));
            }
            owner!.Invalidate();
        }
        owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            BeforeCommitAdmission = () => { if (phase == "admission") Revoke(); },
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                var writer = new ScriptedReadConnection(c);
                writer.BeforeExecute = (command, _) => { if (phase == "dml" && command.CommandText.StartsWith("INSERT OR IGNORE INTO main.versions", StringComparison.Ordinal)) Revoke(); };
                writer.AfterExecute = command => { if (phase == "confirmed" && command.CommandText == "COMMIT") Revoke(); };
                return writer;
            }
        });
        try
        {
            var result = await owner.BootstrapAndRefreshAsync().WaitAsync(Timeout);
            Assert.Equal(phase == "confirmed" ? ResourceInventoryWriteOutcome.Committed : ResourceInventoryWriteOutcome.NotCommitted, result.StorageOutcome);
            Assert.Equal(phase == "confirmed", result.CommitAdmitted); Assert.False(result.WasPublished); Assert.Null(owner.Current);
        }
        finally { if (disposal is not null) await disposal.WaitAsync(Timeout); await owner.DisposeAsync(); }
    }
    [Fact]
    public async Task Final_owner_cleanup_failure_cannot_erase_committed_matched_readback()
    {
        using var fixture = new Fixture(); var sentinel = new IOException("owner cleanup");
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), cleanupEntered: () => throw sentinel);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome); Assert.True(result.CommitAdmitted);
        Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback); Assert.True(result.SourcesRechecked);
        Assert.Same(sentinel, result.Failure); Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }

    [Fact]
    public async Task Caller_cancellation_during_final_cleanup_preserves_commit_and_readback_without_publication()
    {
        using var fixture = new Fixture(); using var cancel = new CancellationTokenSource();
        bool cancelDuringCleanup = true;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(),
            cleanupEntered: () => { if (cancelDuringCleanup) cancel.Cancel(); });
        var result = await owner.BootstrapAndRefreshAsync(cancel.Token);
        Assert.True(result.StorageAttempted); Assert.True(result.CommitAdmitted);
        Assert.Equal(ResourceInventoryWriteOutcome.Committed, result.StorageOutcome);
        Assert.NotNull(result.Receipt); Assert.Equal(ResourceRuntimeReadback.Matched, result.Readback);
        Assert.True(result.SourcesRechecked); Assert.IsAssignableFrom<OperationCanceledException>(result.Failure);
        Assert.False(result.WasPublished); Assert.Null(owner.Current);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        // A fresh explicit read-only attempt can use the durable inventory after retirement.
        cancelDuringCleanup = false;
        var refreshed = await owner.RefreshAsync();
        Assert.Same(refreshed, owner.Current); Assert.False(refreshed.ResourceAdmitted);
        Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Admitted_writer_occupies_owner_until_retired_then_new_identity_can_commit(bool afterCommit)
    {
        using var fixture = new Fixture(); var source = new Source();
        using var release = new ManualResetEventSlim();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        int writeConnections = 0; bool block = true;
        ScriptedReadConnection? firstWriter = null;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                Interlocked.Increment(ref writeConnections);
                var writer = new ScriptedReadConnection(c);
                if (!block) return writer;
                firstWriter = writer;
                void Pause()
                {
                    entered.TrySetResult();
                    if (!release.Wait(Timeout)) throw new TimeoutException("Admitted writer release timed out");
                }
                writer.BeforeExecute = (command, token) =>
                {
                    if (command.CommandText != "COMMIT") return;
                    Assert.False(token.CanBeCanceled);
                    if (!afterCommit) Pause();
                };
                writer.AfterExecute = command => { if (afterCommit && command.CommandText == "COMMIT") Pause(); };
                return writer;
            }
        });
        var first = Task.Run(() => owner.BootstrapAndRefreshAsync());
        try
        {
            await entered.Task.WaitAsync(Timeout);
            owner.Invalidate();
            Assert.False(first.IsCompleted); Assert.NotNull(firstWriter); Assert.False(firstWriter.WasDisposed);
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.BootstrapAndRefreshAsync());
            Assert.Equal(1, Volatile.Read(ref writeConnections));
        }
        finally { release.Set(); }
        var retired = await first.WaitAsync(Timeout);
        Assert.True(retired.CommitAdmitted); Assert.Equal(ResourceInventoryWriteOutcome.Committed, retired.StorageOutcome);
        Assert.False(retired.WasPublished); Assert.NotNull(retired.Failure); Assert.Null(owner.Current);
        Assert.NotNull(firstWriter); Assert.True(firstWriter.WasDisposed);
        long firstId = Assert.IsType<long>(fixture.Sql("SELECT active_id FROM sync_state"));
        block = false; source.Snapshot = _ => RuntimeFlowFixtures.Snapshot("1.3.22");
        var next = await owner.BootstrapAndRefreshAsync().WaitAsync(Timeout); Published(next, owner);
        Assert.Equal(2, Volatile.Read(ref writeConnections)); Assert.NotEqual(firstId, next.Receipt!.VersionId);
        Assert.Equal(firstId, fixture.Sql("SELECT previous_id FROM sync_state"));
        Assert.Equal(next.Receipt.VersionId, fixture.Sql("SELECT active_id FROM sync_state"));
        Assert.Equal(20L, fixture.Sql("SELECT count(*) FROM resources"));
    }
    [Fact]
    public async Task Same_identity_bootstrap_preserves_omitted_extra_raw_resource()
    {
        using var fixture = new Fixture(); await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        var first = await owner.BootstrapAndRefreshAsync(); Published(first, owner);
        string digest = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(new byte[] { 1, 2, 3 }));
        fixture.Sql($"INSERT INTO resources(version_id,name,sha256,data) SELECT active_id,'RetainedExtra.bytes','{digest}',x'010203' FROM sync_state");
        var repeated = await owner.BootstrapAndRefreshAsync(); Published(repeated, owner);
        Assert.Equal(first.Receipt!.VersionId, repeated.Receipt!.VersionId);
        Assert.Equal(11L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.Equal(digest, fixture.Sql("SELECT sha256 FROM resources WHERE name='RetainedExtra.bytes'"));
        Assert.Equal("010203", fixture.Sql("SELECT hex(data) FROM resources WHERE name='RetainedExtra.bytes'"));
        Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
    }

}
