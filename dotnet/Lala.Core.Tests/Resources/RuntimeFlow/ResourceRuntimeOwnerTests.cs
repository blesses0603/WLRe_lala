using System.Globalization;
using System.Text;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class ResourceRuntimeOwnerTests
{
    private static readonly TimeSpan TestTimeout = TimeSpan.FromSeconds(15);

    private class Source : IResourceSource, IDisposable
    {
        internal byte[] Bundle = RuntimeFlowFixtures.Read("all-ten.bundle");
        internal byte[] Main = BundleSourceFixtures.Bytes("main-valid");
        internal byte[] Data;
        internal int Observations;
        internal int Disposals;
        internal Action<CancellationToken>? OnToken;
        internal Func<int, OfficialVersionSnapshot> Snapshot = _ => RuntimeFlowFixtures.Snapshot();
        internal Action? OnDispose;
        public void Dispose() { Interlocked.Increment(ref Disposals); OnDispose?.Invoke(); }
        internal Func<int, Task>? BeforeObserve;
        internal Source() => Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = Bundle });
        public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
        {
            int n = ++Observations;
            OnToken?.Invoke(token);
            if (BeforeObserve is not null) await BeforeObserve(n);
            token.ThrowIfCancellationRequested(); return Snapshot(n);
        }
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            byte[] bytes = url[(url.LastIndexOf('/') + 1)..] switch
            {
                "DataPackage.bytes" => Data, "MainPackage.bytes" => Main,
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                "all-ten.bundle" => Bundle,
                _ => throw new InvalidOperationException("Unexpected offline target")
            };
            return ValueTask.FromResult(new ResourceResponse(url, 200, bytes.Length.ToString(CultureInfo.InvariantCulture), new MemoryStream(bytes, false)));
        }
    }
    private sealed class AsyncSource : Source, IAsyncDisposable
    {
        public async ValueTask DisposeAsync() { await Task.Yield(); Dispose(); }
    }
    private static IEnumerable<Exception> Failures(Exception error)
        => error is AggregateException aggregate ? aggregate.Flatten().InnerExceptions : new[] { error };
    private static void Register(CancellationToken token, int mode, Action callback)
    {
        if (mode == 0) token.Register(callback);
        else if (mode == 1) token.UnsafeRegister(_ => callback(), null);
        else { using (ExecutionContext.SuppressFlow()) token.Register(callback); }
    }
    private sealed class Fixture : IDisposable
    {
        internal string Root = Path.Combine(Path.GetTempPath(), "lala-owner-" + Guid.NewGuid().ToString("N"));
        internal string Inventory => Path.Combine(Root, "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        internal async Task PopulateAsync(Source source)
        {
            var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
            using var db = new DatabaseReadTestDatabase();
            db.Execute("DELETE FROM resources; DELETE FROM version_identities; DELETE FROM sync_state; DELETE FROM versions;");
            db.Execute("INSERT INTO versions VALUES(1,@p0)", prepared.Identity.Key);
            db.Execute("INSERT INTO version_identities VALUES(1,@p0)", prepared.Identity.CanonicalJson);
            db.Execute("INSERT INTO sync_state VALUES(1,1)");
            foreach (string name in BundleSourcePlan.RequiredTables)
            {
                string path = RuntimeFlowFixtures.AssetRoot + name + ".bytes";
                var selected = prepared.RecheckContext.Plan.AssetSourceNames[path];
                byte[] raw = UnityTextAssetExtractor.Extract(path, prepared.RecheckContext.Sources.Where(s => selected.Contains(s.Spec.Name)).ToArray());
                db.Execute("INSERT INTO resources VALUES(1,@p0,@p1,@p2)", name + ".bytes", prepared.Candidate.SourceSha256[name], raw);
            }
            Directory.CreateDirectory(Path.GetDirectoryName(Inventory)!);
            File.Copy(db.FileName, Inventory);
            source.Observations = 0;
        }
        public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }
    [Fact]
    public async Task Real_database_match_is_published_but_offline_success_never_admits()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var publication = await owner.RefreshAsync();
        Assert.Same(publication, owner.Current);
        Assert.Equal(8, source.Observations); // Six preparation observations plus two after DB read.
        Assert.False(publication.ResourceAdmitted); Assert.False(publication.TlsOriginObserved);
        Assert.False(publication.CanLogin); Assert.False(publication.CanSendPackets);
        Assert.False(publication.Candidate.RuntimeAdmitted);
        owner.Invalidate(); Assert.Null(owner.Current);
        var next = await owner.RefreshAsync(); Assert.True(next.Generation > publication.Generation);
    }
    [Fact]
    public async Task Missing_inventory_fails_without_creating_database_or_publication()
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await Assert.ThrowsAnyAsync<Exception>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.False(File.Exists(fixture.Inventory));
    }
    [Fact]
    public async Task Stored_blob_tampering_is_rejected_even_when_recorded_hash_is_unchanged()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        { DataSource = fixture.Inventory, Pooling = false }.ToString()))
        {
            connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "UPDATE resources SET data=x'00000000' WHERE name='Eve.bytes'";
            Assert.Equal(1, command.ExecuteNonQuery());
        }
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        await Assert.ThrowsAsync<ResourceValidationException>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.Equal(6, source.Observations);
    }
    [Fact]
    public async Task Same_version_manifest_replacement_after_database_read_is_rejected()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        source.BeforeObserve = n =>
        {
            if (n == 7) source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]>
                { ["replacement.bundle"] = source.Bundle });
            return Task.CompletedTask;
        };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => owner.RefreshAsync());
        Assert.Equal(BundleSourceFailure.ManifestChanged, error.Failure); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Cancellation_after_database_read_prevents_publication()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        using var cancel = new CancellationTokenSource();
        source.BeforeObserve = n => { if (n == 7) cancel.Cancel(); return Task.CompletedTask; };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancel.Token));
        Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Already_cancelled_caller_cannot_enter_source_or_admission_hook()
    {
        using var fixture = new Fixture(); var source = new Source();
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        int hooks = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            () => { hooks++; return Task.CompletedTask; });
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancellation.Token).WaitAsync(TestTimeout));
        Assert.Equal(0, hooks); Assert.Equal(0, source.Observations); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Refresh_flood_is_rejected_until_cancelled_operation_finishes_retirement()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.BeforeObserve = async n => { if (n == 1) { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); } };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var first = owner.RefreshAsync();
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            owner.Invalidate(); Assert.Null(owner.Current);
            for (int i = 0; i < 100; i++)
                await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            Assert.Equal(1, source.Observations);
        }
        finally { release.TrySetResult(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first.WaitAsync(TestTimeout));
        source.BeforeObserve = null;
        var next = await owner.RefreshAsync().WaitAsync(TestTimeout); Assert.Same(next, owner.Current);
    }
    [Fact]
    public async Task Disposal_waits_for_retirement_and_never_publishes_late_results()
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.BeforeObserve = async _ => { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); };
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var first = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask(); Assert.False(disposal.IsCompleted);
            Assert.Null(owner.Current);
        }
        finally { release.TrySetResult(); disposal ??= owner.DisposeAsync().AsTask(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first.WaitAsync(TestTimeout));
        await disposal.WaitAsync(TestTimeout); Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Disposal_joins_admitted_attempt_before_first_source_operation()
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, async () =>
        { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); });
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask();
            Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals); Assert.Equal(0, source.Observations);
        }
        finally { release.TrySetResult(); disposal ??= owner.DisposeAsync().AsTask(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => refresh.WaitAsync(TestTimeout));
        await disposal.WaitAsync(TestTimeout); Assert.Equal(1, source.Disposals); Assert.Equal(0, source.Observations);
    }
    [Fact]
    public async Task Blocked_reentrant_throwing_callback_is_joined_before_retirement_and_disposal()
    {
        using var fixture = new Fixture(); var source = new Source();
        using var callbackRelease = new ManualResetEventSlim();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            cleanupEntered: () => cleanupEntered.TrySetResult());
        source.OnToken = token => token.Register(() =>
        {
            bool revoked = owner.Current is null;
            owner.Invalidate();
            callbackEntered.TrySetResult(revoked);
            if (!callbackRelease.Wait(TestTimeout)) throw new TimeoutException("Callback release timed out");
            throw new InvalidOperationException("callback failure");
        });
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            owner.Invalidate(); Assert.True(await callbackEntered.Task.WaitAsync(TestTimeout));
            observeRelease.TrySetResult(); await cleanupEntered.Task.WaitAsync(TestTimeout);
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            disposal = owner.DisposeAsync().AsTask();
            Assert.Same(disposal, owner.DisposeAsync().AsTask());
            Assert.False(refresh.IsCompleted); Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        finally { callbackRelease.Set(); observeRelease.TrySetResult(); }
        var refreshFailure = await Assert.ThrowsAnyAsync<Exception>(() => refresh.WaitAsync(TestTimeout));
        var disposalFailure = await Assert.ThrowsAnyAsync<Exception>(() => disposal!.WaitAsync(TestTimeout));
        Assert.Contains(Failures(refreshFailure), e => e is InvalidOperationException && e.Message == "callback failure");
        Assert.Contains(Failures(disposalFailure), e => e is InvalidOperationException && e.Message == "callback failure");
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData(0, false)]
    [InlineData(1, false)]
    [InlineData(2, false)]
    [InlineData(0, true)]
    [InlineData(1, true)]
    [InlineData(2, true)]
    public async Task Callback_self_disposal_rejects_join_while_external_disposal_waits_for_retirement(int registration, bool externalFirst)
    {
        using var fixture = new Fixture(); var source = new Source();
        using var callbackRelease = new ManualResetEventSlim();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackObserved = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            cleanupEntered: () => cleanupEntered.TrySetResult());
        source.OnToken = token => Register(token, registration, () =>
        {
            Exception? failure = null;
            try { owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult(); }
            catch (Exception error) { failure = error; }
            callbackObserved.TrySetResult(failure);
            if (!callbackRelease.Wait(TestTimeout)) throw new TimeoutException("Callback release timed out");
        });
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            if (externalFirst) disposal = owner.DisposeAsync().AsTask();
            else owner.Invalidate();
            var failure = Assert.IsType<InvalidOperationException>(await callbackObserved.Task.WaitAsync(TestTimeout));
            Assert.Contains("own active operation", failure.Message);
            disposal ??= owner.DisposeAsync().AsTask();
            var joins = await Task.WhenAll(Enumerable.Range(0, 8)
                .Select(_ => Task.Run(() => (object)owner.DisposeAsync().AsTask()))).WaitAsync(TestTimeout);
            Assert.All(joins, join => Assert.Same(disposal, join));
            Assert.Null(owner.Current);
            observeRelease.TrySetResult(); await cleanupEntered.Task.WaitAsync(TestTimeout);
            Assert.False(refresh.IsCompleted); Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        finally { callbackRelease.Set(); observeRelease.TrySetResult(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => refresh.WaitAsync(TestTimeout));
        await disposal!.WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
        await Assert.ThrowsAsync<ObjectDisposedException>(() => owner.RefreshAsync());
    }
    [Fact]
    public async Task Uncaught_callback_self_disposal_failure_is_reported_after_cleanup()
    {
        using var fixture = new Fixture(); var source = new Source();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        source.OnToken = token => token.Register(() =>
            owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult());
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask();
        }
        finally { observeRelease.TrySetResult(); }
        var refreshFailure = await Assert.ThrowsAnyAsync<Exception>(() => refresh.WaitAsync(TestTimeout));
        var disposalFailure = await Assert.ThrowsAnyAsync<Exception>(() => disposal!.WaitAsync(TestTimeout));
        Assert.Contains(Failures(refreshFailure), e => e is InvalidOperationException && e.Message.Contains("own active operation"));
        Assert.Contains(Failures(disposalFailure), e => e is InvalidOperationException && e.Message.Contains("own active operation"));
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Source_self_disposal_rejects_join_without_completing_external_cleanup(bool asynchronous)
    {
        using var fixture = new Fixture(); Source source = asynchronous ? new AsyncSource() : new Source();
        using var sourceRelease = new ManualResetEventSlim();
        var reentry = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        source.OnDispose = () =>
        {
            Exception? failure = null;
            try { owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult(); }
            catch (Exception error) { failure = error; }
            reentry.TrySetResult(failure);
            if (!sourceRelease.Wait(TestTimeout)) throw new TimeoutException("Source release timed out");
        };
        var firstDisposal = Task.Run(async () => await owner.DisposeAsync());
        Task? disposal = null;
        try
        {
            var failure = Assert.IsType<InvalidOperationException>(await reentry.Task.WaitAsync(TestTimeout));
            Assert.Contains("own active operation", failure.Message);
            disposal = owner.DisposeAsync().AsTask();
            Assert.Same(disposal, owner.DisposeAsync().AsTask());
            Assert.False(firstDisposal.IsCompleted); Assert.False(disposal.IsCompleted);
            Assert.Equal(1, source.Disposals);
        }
        finally { sourceRelease.Set(); }
        await firstDisposal.WaitAsync(TestTimeout); await disposal!.WaitAsync(TestTimeout);
        await owner.DisposeAsync().AsTask().WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals);
    }
    [Fact]
    public async Task Captured_operation_context_can_join_disposal_after_real_retirement()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Task? lateDisposal = null;
        source.BeforeObserve = n =>
        {
            if (n == 1) lateDisposal = Task.Run(async () =>
            {
                await release.Task.WaitAsync(TestTimeout);
                await owner.DisposeAsync();
            });
            return Task.CompletedTask;
        };
        try { await owner.RefreshAsync().WaitAsync(TestTimeout); }
        finally { release.TrySetResult(); }
        await lateDisposal!.WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Failed_retry_revokes_prior_publication_and_fabricated_publications_never_admit()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var prior = await owner.RefreshAsync();
        File.Delete(fixture.Inventory);
        await Assert.ThrowsAnyAsync<Exception>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.False(prior.ResourceAdmitted);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var production = ResourceRuntimeOwner.Create(fixture.Root);
        var fabricated = new ResourceRuntimePublication(production, prior.Generation, prepared);
        Assert.False(fabricated.ResourceAdmitted); Assert.False(fabricated.TlsOriginObserved);
        Assert.False(production.IsCurrentAdmission(prior));
        Assert.False(owner.IsCurrentAdmission(fabricated));
        production.Invalidate(); Assert.False(fabricated.ResourceAdmitted);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Post_database_full_version_or_executable_drift_prevents_publication(bool executable)
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        source.Snapshot = n => n < 7 ? RuntimeFlowFixtures.Snapshot() : executable
            ? OfficialVersionSnapshot.Parse(Encoding.UTF8.GetBytes(System.Text.Json.JsonSerializer.Serialize(new
            {
                schema_version = 1, origin = "official_pc_version_endpoint", data_ver = "1.3.21", exe_version = "1.4.0",
                packages = new { DataPackage = RuntimeFlowFixtures.Version,
                    MainPackage = BundleSourceFixtures.Case("main-valid").Text("package_version") },
                checked_at_utc = "2026-01-02T03:04:05Z", assets_ready = false
            })))
            : RuntimeFlowFixtures.Snapshot(packageVersion: "1286_2026_10_29_13_42_37_95");
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => owner.RefreshAsync());
        Assert.Equal(BundleSourceFailure.VersionsChanged, error.Failure); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Production_construction_is_lazy_and_disposal_revokes_without_io()
    {
        using var fixture = new Fixture();
        var owner = ResourceRuntimeOwner.Create(fixture.Root);
        Assert.Null(owner.Current); Assert.False(Directory.Exists(fixture.Root));
        await owner.DisposeAsync(); await owner.DisposeAsync();
        await Assert.ThrowsAsync<ObjectDisposedException>(() => owner.RefreshAsync());
        Assert.False(Directory.Exists(fixture.Root));
        Assert.Throws<ArgumentException>(() => ResourceRuntimeOwner.Create("relative"));
    }
}
