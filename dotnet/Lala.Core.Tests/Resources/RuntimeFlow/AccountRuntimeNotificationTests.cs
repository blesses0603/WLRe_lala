using System.Net;
using System.Reflection;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static async Task<AccountRuntimeStatus> AccountStatusWhen(AccountRuntime runtime,
        Func<AccountRuntimeStatus, bool> condition)
    {
        using var deadline = new CancellationTokenSource(AccountGuard);
        var status = runtime.Snapshot;
        while (!condition(status))
        {
            Assert.False(status.IsCompleted);
            status = await runtime.WaitForChangeAsync(status, deadline.Token);
        }
        return status;
    }
    private static AccountConnectionProfile InertAccountProfile() => new(
        new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1), 0, 0, 1, 1, 1);

    [Fact]
    public async Task Integrated_wait_uses_exact_identity_is_inert_and_isolates_cancellation()
    {
        using var fixture = new Fixture();
        var session = new AccountSession(); var generation = session.Begin("synthetic", "offline").Generation;
        var credentials = new AccountCredentials();
        await using var runtime = AccountRuntime.Create(session, generation, InertAccountProfile(), credentials, fixture.Root);
        await using var foreign = AccountRuntime.Create(session, generation, InertAccountProfile(), credentials, fixture.Root);
        var created = runtime.Snapshot;
        Assert.Same(created, runtime.Snapshot); Assert.False(created.IsCompleted);
        Assert.Same(created, await runtime.WaitForChangeAsync(created with { }).WaitAsync(AccountGuard));
        Assert.Same(created, await runtime.WaitForChangeAsync(foreign.Snapshot).WaitAsync(AccountGuard));
        await Assert.ThrowsAsync<ArgumentNullException>(() => runtime.WaitForChangeAsync(null!));
        using var canceled = new CancellationTokenSource();
        var canceledWait = runtime.WaitForChangeAsync(created, canceled.Token);
        var surviving = runtime.WaitForChangeAsync(created);
        Assert.False(canceledWait.IsCompleted); Assert.False(surviving.IsCompleted);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        canceled.Cancel();
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => canceledWait);
        Assert.Equal(canceled.Token, error.CancellationToken);
        Assert.False(surviving.IsCompleted); Assert.Same(created, runtime.Snapshot);
        runtime.Stop();
        var stopping = await surviving.WaitAsync(AccountGuard);
        Assert.NotSame(created, stopping); Assert.False(stopping.IsCompleted);
        Assert.Same(stopping, await runtime.WaitForChangeAsync(created));
        error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => runtime.WaitForChangeAsync(created, canceled.Token));
        Assert.Equal(canceled.Token, error.CancellationToken);
        await runtime.DisposeAsync();
        var completed = runtime.Snapshot;
        Assert.True(completed.IsCompleted); Assert.Equal(AccountConnectionPhase.Ended, completed.Connection.Phase);
        Assert.Same(completed, await runtime.WaitForChangeAsync(completed).WaitAsync(AccountGuard));
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => runtime.WaitForChangeAsync(completed, canceled.Token));
        Assert.Equal(canceled.Token, error.CancellationToken);
    }

    [Fact]
    public async Task Integrated_wait_fans_out_without_inline_continuations_and_preserves_racing_cancellation()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        var generation = session.Begin("synthetic", "offline").Generation;
        await using var runtime = AccountRuntime.Create(session, generation, InertAccountProfile(), new AccountCredentials(), fixture.Root);
        var created = runtime.Snapshot;
        var gate = typeof(AccountRuntime).GetField("gate", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(runtime)!;
        var waiting = Enumerable.Range(0, 64).Select(_ => runtime.WaitForChangeAsync(created)).ToArray();
        var inline = waiting[0].ContinueWith(_ => Monitor.IsEntered(gate), CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        using var canceled = new CancellationTokenSource();
        var raced = runtime.WaitForChangeAsync(created, canceled.Token);
        lock (gate) { canceled.Cancel(); runtime.Stop(); }
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => raced);
        Assert.Equal(canceled.Token, error.CancellationToken);
        foreach (var status in await Task.WhenAll(waiting).WaitAsync(AccountGuard))
        {
            Assert.NotSame(created, status); Assert.True(status.ResourceHeld); Assert.False(status.CanSendCommands);
        }
        Assert.False(await inline.WaitAsync(AccountGuard));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Integrated_wait_reports_history_and_readiness_without_a_connection_transition(bool trusted)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var preparing = AccountSignal(); var release = AccountSignal(); var finish = AccountSignal();
        source.BeforeObserve = async _ => { preparing.TrySetResult(); await release.Task.WaitAsync(AccountGuard); };
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        // White-box wiring only, never evidence of official provenance or action authority.
        if (trusted) typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var started = runtime.WaitForChangeAsync(runtime.Snapshot);
        var run = runtime.RunAsync();
        try
        {
            Assert.NotEqual(AccountConnectionPhase.Created, (await started.WaitAsync(AccountGuard)).Connection.Phase);
            await preparing.Task.WaitAsync(AccountGuard);
            var receiving = runtime.Snapshot;
            Assert.Equal(AccountConnectionPhase.ReceivingHeld, receiving.Connection.Phase);
            Assert.Empty(receiving.ResourceHistory); Assert.False(receiving.HasCurrentResources);
            var prepared = runtime.WaitForChangeAsync(receiving);
            Assert.False(prepared.IsCompleted); release.SetResult();
            var ready = await prepared.WaitAsync(AccountGuard);
            Assert.Same(receiving.Connection, ready.Connection);
            Assert.Equal(trusted, ready.HasCurrentResources); Assert.Single(ready.ResourceHistory);
            Assert.Equal(trusted, ready.ResourceHistory[0].Preparation.WasBound);
            Assert.Same(ready, runtime.Snapshot); Assert.False(ready.IsCompleted); AccountHeld(runtime, session);
            if (trusted)
            {
                var revoked = runtime.WaitForChangeAsync(ready);
                Assert.False(revoked.IsCompleted); resources.Invalidate();
                var invalid = await revoked.WaitAsync(AccountGuard);
                Assert.False(invalid.HasCurrentResources); Assert.Same(ready.Connection, invalid.Connection);
                Assert.Equal(ready.ResourceHistory, invalid.ResourceHistory); Assert.Null(runtime.Publication!.Catalogs);
                Assert.True(ready.HasCurrentResources); // Retained point-in-time value only.
            }
            runtime.Stop(); Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.True((await AccountStatusWhen(runtime, s => s.IsCompleted)).IsCompleted);
        }
        finally { release.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData("begin")]
    [InlineData("hold")]
    [InlineData("disconnect")]
    public async Task Integrated_pending_wait_reports_external_account_revocation(string change)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var finish = AccountSignal(); var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var run = runtime.RunAsync();
        try
        {
            var ready = await AccountStatusWhen(runtime, status => status.HasCurrentResources);
            var waiting = runtime.WaitForChangeAsync(ready);
            Assert.False(waiting.IsCompleted);
            switch (change)
            {
                case "begin": session.Begin("replacement", "other"); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                default: session.Disconnect(); break;
            }
            // No Snapshot polling or extra packet is needed to release the pending observer.
            var revoked = await waiting.WaitAsync(AccountGuard);
            Assert.False(revoked.HasCurrentResources); Assert.NotSame(ready, revoked);
            Assert.True(ready.HasCurrentResources); Assert.Single(revoked.ResourceHistory);
            Assert.True(revoked.ResourceHeld); Assert.False(revoked.CanSendCommands);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.True(runtime.Snapshot.IsCompleted);
        }
        finally { finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    private sealed class NotificationCleanupSource(Source source, TaskCompletionSource entered,
        Task release, bool fail) : IResourceSource, IAsyncDisposable
    {
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token) => source.ObserveAsync(token);
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token) => source.OpenAsync(url, token);
        public async ValueTask DisposeAsync()
        {
            entered.TrySetResult(); await release.WaitAsync(AccountGuard); source.Dispose();
            if (fail) throw new IOException("Synthetic cleanup failure.");
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Integrated_ended_connection_waits_for_aggregate_cleanup_and_final_completion(bool fail)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "offline").Generation;
        var cleanup = AccountSignal(); var release = AccountSignal();
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(
            fixture.Root, new NotificationCleanupSource(source, cleanup, release.Task, fail)));
        var runtime = AccountRuntime.CreateForOfflineTests(session, generation, InertAccountProfile(), new AccountCredentials(), resources);
        var created = runtime.Snapshot; var started = runtime.WaitForChangeAsync(created);
        var disposal = runtime.DisposeAsync().AsTask();
        Task<AccountRuntimeStatus>? final = null;
        try
        {
            Assert.NotSame(created, await started.WaitAsync(AccountGuard));
            await cleanup.Task.WaitAsync(AccountGuard);
            var ended = runtime.Snapshot;
            Assert.Equal(AccountConnectionPhase.Ended, ended.Connection.Phase); Assert.False(ended.IsCompleted);
            final = runtime.WaitForChangeAsync(ended);
            Assert.False(final.IsCompleted); Assert.False(disposal.IsCompleted);
        }
        finally { release.TrySetResult(); }
        var completed = await final!.WaitAsync(AccountGuard);
        Assert.True(completed.IsCompleted); Assert.Empty(completed.ResourceHistory);
        Assert.Same(completed, await runtime.WaitForChangeAsync(completed));
        if (fail) await Assert.ThrowsAsync<AccountRuntimeCleanupException>(() => disposal);
        else await disposal.WaitAsync(AccountGuard);
        Assert.Equal(1, source.Disposals); Assert.False(Directory.Exists(fixture.Root));
        var stable = runtime.Snapshot;
        session.Begin("other", "offline"); session.Hold(session.Snapshot.Generation); session.Disconnect();
        Assert.Same(stable, runtime.Snapshot); // No notification pump survives aggregate cleanup.
    }

    [Fact]
    public async Task Integrated_wait_keeps_listening_for_late_history_after_connection_ends()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var preparing = AccountSignal(); var release = AccountSignal(); var finish = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources,
            beforePreparationAdmission: async _ =>
            {
                preparing.SetResult(); await release.Task.WaitAsync(AccountGuard);
            });
        var run = runtime.RunAsync();
        try
        {
            await preparing.Task.WaitAsync(AccountGuard); runtime.Stop();
            var ended = await AccountStatusWhen(runtime, status => status.Connection.Phase == AccountConnectionPhase.Ended);
            Assert.False(ended.IsCompleted); Assert.Empty(ended.ResourceHistory);
            var lateHistory = runtime.WaitForChangeAsync(ended);
            Assert.False(lateHistory.IsCompleted); Assert.False(run.IsCompleted);
            release.SetResult();
            var observed = await lateHistory.WaitAsync(AccountGuard);
            Assert.Equal(AccountResourcePreparationStatus.Cancelled, Assert.Single(observed.ResourceHistory).Preparation.Status);
            Assert.Equal(ended.Connection.RuntimeId, observed.Connection.RuntimeId);
            Assert.Equal(AccountConnectionPhase.Ended, observed.Connection.Phase);
            var complete = await AccountStatusWhen(runtime, status => status.IsCompleted);
            Assert.Equal(observed.ResourceHistory, complete.ResourceHistory);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
        }
        finally { release.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Account_snapshot_signal_observes_same_phase_identity_replacements_only()
    {
        var session = new AccountSession();
        var first = session.SnapshotChanged; var generation = session.Begin("synthetic", "offline").Generation;
        await first.WaitAsync(AccountGuard);
        var second = session.SnapshotChanged; Assert.True(session.Hold(generation)); await second.WaitAsync(AccountGuard);
        var held = session.Snapshot; var third = session.SnapshotChanged;
        Assert.False(session.Hold(generation + 1)); Assert.False(third.IsCompleted);
        Assert.True(session.Hold(generation)); await third.WaitAsync(AccountGuard);
        Assert.Equal(held, session.Snapshot); Assert.NotSame(held, session.Snapshot);
        var fourth = session.SnapshotChanged; session.Disconnect(); await fourth.WaitAsync(AccountGuard);
    }
}
