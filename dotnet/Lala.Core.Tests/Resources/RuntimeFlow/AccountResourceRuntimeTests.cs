using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Public_resource_factory_is_inert_and_rejects_invalid_accounts_before_io()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        await using var runtime = AccountResourceRuntime.Create(session, fixture.Root);
        Assert.False(runtime.HasCurrentResources); Assert.False(runtime.TryReadCatalogs(out var catalogs)); Assert.Null(catalogs);
        await Assert.ThrowsAsync<InvalidOperationException>(() => runtime.BootstrapAsync(session.Snapshot.Generation));
        var snapshot = session.Begin("synthetic", "synthetic");
        await Assert.ThrowsAsync<InvalidOperationException>(() => runtime.RefreshAsync(snapshot.Generation + 1));
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        var result = await runtime.BootstrapAsync(snapshot.Generation, cancelled.Token);
        Assert.Equal(AccountResourcePreparationStatus.Cancelled, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.StorageOutcome);
        Assert.False(Directory.Exists(fixture.Root)); Assert.Same(snapshot, session.Snapshot);
        Assert.False(runtime.CanLogin); Assert.False(runtime.CanSendPackets);
        Assert.Throws<ArgumentException>(() => AccountResourceRuntime.Create(session, "relative"));
        Assert.Throws<ArgumentNullException>(() => AccountResourceRuntime.Create(null!, fixture.Root));
    }

    [Fact]
    public async Task Public_facade_bootstrap_and_readonly_refresh_preserve_offline_nonadmission()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        var snapshot = session.Begin("synthetic", "synthetic");
        await using var runtime = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()));
        var result = await runtime.BootstrapAsync(snapshot.Generation);
        Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.Committed, result.StorageOutcome);
        Assert.True(result.ReadbackMatched); Assert.True(result.SourcesRechecked); Assert.False(result.WasBound);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        Assert.False(runtime.HasCurrentResources); Assert.False(runtime.TryReadCatalogs(out var catalogs)); Assert.Null(catalogs);
        Assert.False(result.CanLogin); Assert.False(result.CanSendPackets); Assert.Same(snapshot, session.Snapshot);
        var refresh = await runtime.RefreshAsync(snapshot.Generation);
        Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, refresh.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, refresh.StorageOutcome);
        Assert.True(refresh.ReadbackMatched); Assert.True(refresh.SourcesRechecked);
        Assert.Equal(1L, fixture.Sql("SELECT count(*) FROM versions"));
    }

    [Theory]
    [InlineData("hold")]
    [InlineData("begin")]
    [InlineData("invalidate")]
    [InlineData("dispose")]
    public async Task Whitebox_admitted_state_exercises_public_binding_and_revocation_wiring(string change)
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        var snapshot = session.Begin("synthetic", "synthetic");
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        // White-box state-machine test ONLY: simulate the owner's private trust bit. This
        // is not a production acquisition/trust test and introduces no production bypass.
        // The ordinary offline-factory test above must continue to reject the same source.
        typeof(ResourceRuntimeOwner).GetField("_production", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!.SetValue(owner, true);
        await using var runtime = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        var result = await runtime.BootstrapAsync(snapshot.Generation);
        Assert.Equal(AccountResourcePreparationStatus.Bound, result.Status); Assert.True(result.WasBound);
        Assert.True(runtime.HasCurrentResources); Assert.True(runtime.TryReadCatalogs(out var catalogs)); Assert.NotNull(catalogs);
        Assert.False(catalogs.RuntimeAdmitted); Assert.False(catalogs.CanSendPackets);
        Assert.Same(snapshot, session.Snapshot); Assert.False(runtime.CanLogin); Assert.False(runtime.CanSendPackets);
        switch (change)
        {
            case "hold": session.Hold(snapshot.Generation); break;
            case "begin": session.Begin("replacement", "synthetic"); break;
            case "invalidate": runtime.Invalidate(); break;
            case "dispose": await runtime.DisposeAsync(); break;
        }
        Assert.True(result.WasBound); // Historical receipt does not turn into current authority.
        Assert.False(runtime.HasCurrentResources); Assert.False(runtime.TryReadCatalogs(out catalogs)); Assert.Null(catalogs);
    }

    [Fact]
    public async Task Public_facade_refresh_does_not_create_missing_inventory()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "synthetic").Generation;
        await using var runtime = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()));
        var result = await runtime.RefreshAsync(generation);
        Assert.Equal(AccountResourcePreparationStatus.Failed, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.StorageOutcome);
        Assert.False(result.ReadbackMatched); Assert.False(Directory.Exists(fixture.Root));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Public_facade_rejects_account_changes_during_preparation_but_preserves_commit(bool sameGeneration)
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        var snapshot = session.Begin("synthetic", "synthetic");
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            BeforeReadback = () =>
            {
                if (sameGeneration) session.Hold(snapshot.Generation); else session.Begin("replacement", "synthetic");
                return Task.CompletedTask;
            }
        });
        await using var runtime = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        var result = await runtime.BootstrapAsync(snapshot.Generation);
        Assert.Equal(AccountResourcePreparationStatus.AccountChanged, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.Committed, result.StorageOutcome);
        Assert.True(result.ReadbackMatched); Assert.True(result.SourcesRechecked);
        Assert.False(runtime.HasCurrentResources); Assert.False(runtime.TryReadCatalogs(out _));
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }

    [Theory]
    [InlineData("cancel")]
    [InlineData("invalidate")]
    [InlineData("source-drift")]
    public async Task Public_facade_late_failure_never_claims_committed_storage_rolled_back(string mode)
    {
        using var fixture = new Fixture(); var session = new AccountSession(); using var cancel = new CancellationTokenSource();
        long generation = session.Begin("synthetic", "synthetic").Generation;
        AccountResourceRuntime? runtime = null; var source = new Source();
        if (mode == "source-drift") source.Snapshot = n => n < 7 ? RuntimeFlowFixtures.Snapshot() : RuntimeFlowFixtures.Snapshot(dataVersion: "1.3.22");
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            BeforeReadback = () =>
            {
                if (mode == "cancel") cancel.Cancel();
                if (mode == "invalidate") runtime!.Invalidate();
                return Task.CompletedTask;
            }
        });
        await using (runtime = AccountResourceRuntime.CreateForOfflineTests(session, owner))
        {
            var result = await runtime.BootstrapAsync(generation, cancel.Token);
            Assert.Equal(mode == "source-drift" ? AccountResourcePreparationStatus.Failed : AccountResourcePreparationStatus.Cancelled, result.Status);
            Assert.Equal(AccountResourceStorageOutcome.Committed, result.StorageOutcome);
            Assert.False(result.WasBound); Assert.False(runtime.HasCurrentResources);
            Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Public_facade_preserves_uncertain_commit_and_confirmed_cleanup_outcomes(bool confirmed)
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "synthetic").Generation;
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: new()
        {
            WrapConnection = c =>
            {
                if (ReadOnly(c)) return c;
                var writer = new ScriptedReadConnection(c);
                writer.AfterExecute = command =>
                {
                    if (command.CommandText != "COMMIT") return;
                    if (!confirmed) throw new IOException("synthetic uncertain commit");
                    writer.CommandDisposeError = new IOException("synthetic cleanup failure");
                };
                return writer;
            }
        });
        await using var runtime = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        var result = await runtime.BootstrapAsync(generation);
        Assert.Equal(AccountResourcePreparationStatus.Failed, result.Status);
        Assert.Equal(confirmed ? AccountResourceStorageOutcome.Committed : AccountResourceStorageOutcome.Unknown, result.StorageOutcome);
        Assert.False(result.ReadbackMatched); Assert.False(result.WasBound);
        Assert.Equal(10L, fixture.Sql("SELECT count(*) FROM resources"));
    }

    [Fact]
    public async Task Public_facade_rejects_overlap_and_disposal_joins_owned_cleanup()
    {
        using var fixture = new Fixture(); var session = new AccountSession(); var source = new Source();
        long generation = session.Begin("synthetic", "synthetic").Generation;
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.BeforeObserve = _ => { entered.TrySetResult(); return release.Task; };
        var runtime = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        var pending = runtime.BootstrapAsync(generation);
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(Timeout);
            await Assert.ThrowsAsync<InvalidOperationException>(() => runtime.RefreshAsync(generation));
            Assert.Equal(1, source.Observations);
            disposal = runtime.DisposeAsync().AsTask();
            Assert.False(disposal.IsCompleted); Assert.False(runtime.HasCurrentResources);
            await Assert.ThrowsAsync<ObjectDisposedException>(() => runtime.BootstrapAsync(generation));
            Assert.Throws<ObjectDisposedException>(() => runtime.Invalidate());
        }
        finally { release.TrySetResult(); }
        var result = await pending.WaitAsync(Timeout);
        await (disposal ?? runtime.DisposeAsync().AsTask()).WaitAsync(Timeout);
        Assert.False(result.WasBound); Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.StorageOutcome);
        Assert.Equal(1, source.Disposals); Assert.False(Directory.Exists(fixture.Root));
    }
}
