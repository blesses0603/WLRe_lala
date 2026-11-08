using System.Reflection;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static async Task<AccountRuntimePublicationSnapshot> AccountPublicationWhen(AccountRuntime runtime,
        Func<AccountRuntimePublicationSnapshot, bool> condition, AccountRuntimePublicationSnapshot? initial = null)
    {
        using var deadline = new CancellationTokenSource(AccountGuard);
        var snapshot = initial ?? runtime.PublicationSnapshot;
        while (!condition(snapshot))
        {
            Assert.False(snapshot.IsCompleted);
            snapshot = await runtime.WaitForPublicationChangeAsync(snapshot, deadline.Token);
        }
        return snapshot;
    }
    private static bool ReceivingPublication(AccountRuntimePublicationSnapshot snapshot) =>
        snapshot.Connection.Phase == AccountConnectionPhase.ReceivingHeld &&
        snapshot.Publication is { Receive: { Phase: AccountReceivePhase.Running, Revision: >= 4 } };
    private static ResourceRuntimeOwner PublicationOwner(Fixture fixture, Source source)
    {
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        // Private trust simulation verifies joins only, never production provenance/admission.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        return owner;
    }

    [Fact]
    public async Task Publication_wait_is_inert_exact_identity_cancellable_and_terminal_after_disposal()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "offline").Generation;
        var credentials = new AccountCredentials();
        await using var runtime = AccountRuntime.Create(session, generation, InertAccountProfile(), credentials, fixture.Root);
        await using var foreign = AccountRuntime.Create(session, generation, InertAccountProfile(), credentials, fixture.Root);
        var created = runtime.PublicationSnapshot;
        Assert.Same(created, runtime.PublicationSnapshot); Assert.Null(created.Publication); Assert.False(created.IsCompleted);
        Assert.Same(created.Connection, runtime.Snapshot.Connection);
        Assert.Equal(nameof(AccountRuntimePublicationSnapshot), created.ToString());
        Assert.Same(created, await runtime.WaitForPublicationChangeAsync(created with { }).WaitAsync(AccountGuard));
        Assert.Same(created, await runtime.WaitForPublicationChangeAsync(foreign.PublicationSnapshot).WaitAsync(AccountGuard));
        await Assert.ThrowsAsync<ArgumentNullException>(() => runtime.WaitForPublicationChangeAsync(null!));
        using var canceled = new CancellationTokenSource();
        var waiting = runtime.WaitForPublicationChangeAsync(created, canceled.Token);
        var surviving = runtime.WaitForPublicationChangeAsync(created);
        Assert.False(waiting.IsCompleted); Assert.False(surviving.IsCompleted);
        canceled.Cancel();
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => waiting);
        Assert.Equal(canceled.Token, error.CancellationToken); Assert.False(surviving.IsCompleted);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        runtime.Stop(); // Null to null must still invalidate the exact observation token.
        var stopping = await surviving.WaitAsync(AccountGuard);
        Assert.Null(stopping.Publication); Assert.NotSame(created, stopping); Assert.False(stopping.IsCompleted);
        Assert.Same(stopping, await runtime.WaitForPublicationChangeAsync(created));
        var final = runtime.WaitForPublicationChangeAsync(stopping);
        await runtime.DisposeAsync();
        Assert.NotSame(stopping, await final.WaitAsync(AccountGuard));
        var completed = runtime.PublicationSnapshot;
        Assert.True(completed.IsCompleted); Assert.Null(completed.Publication);
        Assert.Same(completed, await runtime.WaitForPublicationChangeAsync(completed).WaitAsync(AccountGuard));
        error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => runtime.WaitForPublicationChangeAsync(completed, canceled.Token));
        Assert.Equal(canceled.Token, error.CancellationToken);
        Assert.Empty(credentials.Requests); Assert.False(Directory.Exists(fixture.Root));
        session.Begin("replacement", "offline"); session.Hold(session.Snapshot.Generation); session.Disconnect();
        Assert.Same(completed, runtime.PublicationSnapshot);
    }

    [Fact]
    public async Task Publication_wait_fans_out_without_inline_continuations_and_cancellation_wins()
    {
        using var fixture = new Fixture(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "offline").Generation;
        await using var runtime = AccountRuntime.Create(session, generation, InertAccountProfile(), new AccountCredentials(), fixture.Root);
        var created = runtime.PublicationSnapshot;
        var gate = typeof(AccountRuntime).GetField("gate", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(runtime)!;
        var waits = Enumerable.Range(0, 64).Select(_ => runtime.WaitForPublicationChangeAsync(created)).ToArray();
        var inline = waits[0].ContinueWith(_ => Monitor.IsEntered(gate), CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        using var canceled = new CancellationTokenSource();
        var raced = runtime.WaitForPublicationChangeAsync(created, canceled.Token);
        lock (gate) { canceled.Cancel(); runtime.Stop(); }
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => raced);
        Assert.Equal(canceled.Token, error.CancellationToken);
        foreach (var snapshot in await Task.WhenAll(waits).WaitAsync(AccountGuard))
        {
            Assert.NotSame(created, snapshot); Assert.True(snapshot.ResourceHeld); Assert.False(snapshot.CanSendCommands);
        }
        Assert.False(await inline.WaitAsync(AccountGuard));
    }

    [Fact]
    public async Task Publication_wait_receives_real_packet_commits_without_waking_lifecycle_waiters()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var sends = Enumerable.Range(0, 32).Select(_ => AccountSignal()).ToArray(); var finish = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client);
            for (int i = 0; i < sends.Length; i++)
            {
                await client.WaitFor(sends[i].Task);
                await client.Send(new Packet(26, 4, new PacketWriter().U32((uint)(i + 1)).Build()));
            }
            await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var run = runtime.RunAsync();
        try
        {
            await AccountStatusWhen(runtime, status => status.ResourceHistory.Length == 1);
            var snapshot = await AccountPublicationWhen(runtime, ReceivingPublication);
            var status = runtime.Snapshot; var statusWait = runtime.WaitForChangeAsync(status);
            long revision = snapshot.Publication!.Receive.Revision;
            var original = snapshot;
            for (int i = 0; i < sends.Length; i++)
            {
                Assert.Same(snapshot, runtime.PublicationSnapshot);
                Assert.Same(snapshot.Publication, runtime.Publication);
                // Subscribe first on even packets; on odd packets intentionally wait with
                // a stale pre-commit token after another waiter has observed the commit.
                var pending = i % 2 == 0 ? runtime.WaitForPublicationChangeAsync(snapshot) : null;
                if (pending is not null) Assert.False(pending.IsCompleted);
                sends[i].SetResult();
                var next = pending is null
                    ? await AccountPublicationWhen(runtime, value => value.Publication?.Receive.Revision == revision + i + 1, snapshot)
                    : await pending.WaitAsync(AccountGuard);
                Assert.Same(next, await runtime.WaitForPublicationChangeAsync(snapshot).WaitAsync(AccountGuard));
                Assert.Equal(revision + i + 1, next.Publication!.Receive.Revision);
                Assert.Equal((uint)(i + 1), next.Publication.Receive.State.Local.Session.Gold.Amount);
                Assert.Same(snapshot.Connection, next.Connection); Assert.Null(next.Publication.Catalogs);
                Assert.NotSame(snapshot.Publication.Receive, next.Publication.Receive);
                Assert.True(next.Publication.ResourceHeld); Assert.False(next.Publication.CanSendCommands);
                Assert.Same(status, runtime.Snapshot); Assert.False(statusWait.IsCompleted);
                snapshot = next;
            }
            Assert.Equal(revision, original.Publication!.Receive.Revision);
            Assert.Null(original.Publication.Receive.State.Local.Session.Gold.Amount);
            runtime.Stop(); Assert.Null(runtime.Publication);
            await statusWait.WaitAsync(AccountGuard);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { foreach (var signal in sends) signal.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Publication_wait_reports_catalog_binding_and_revocation_without_packets()
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
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var run = runtime.RunAsync();
        try
        {
            await preparing.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, ReceivingPublication);
            Assert.Null(receiving.Publication!.Catalogs);
            var pending = runtime.WaitForPublicationChangeAsync(receiving); Assert.False(pending.IsCompleted);
            release.SetResult(); var ready = await pending.WaitAsync(AccountGuard);
            Assert.NotNull(ready.Publication!.Catalogs); Assert.Same(receiving.Connection, ready.Connection);
            Assert.Same(receiving.Publication.Receive, ready.Publication.Receive);
            Assert.Same(ready, runtime.PublicationSnapshot); Assert.Same(ready.Publication, runtime.Publication);
            var revoked = runtime.WaitForPublicationChangeAsync(ready); Assert.False(revoked.IsCompleted);
            resources.Invalidate(); var invalid = await revoked.WaitAsync(AccountGuard);
            Assert.Null(invalid.Publication!.Catalogs); Assert.Same(ready.Connection, invalid.Connection);
            Assert.Same(ready.Publication.Receive, invalid.Publication.Receive);
            Assert.NotNull(ready.Publication.Catalogs); Assert.False(ready.Publication.Catalogs.RuntimeAdmitted);
            runtime.Stop(); Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { release.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData("stop")]
    [InlineData("hold")]
    [InlineData("begin")]
    [InlineData("disconnect")]
    public async Task Publication_wait_revokes_current_attempt_without_an_extra_packet(string change)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var finish = AccountSignal(); var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources);
        var run = runtime.RunAsync();
        try
        {
            var ready = await AccountPublicationWhen(runtime, value => ReceivingPublication(value) && value.Publication!.Catalogs is not null);
            var pending = runtime.WaitForPublicationChangeAsync(ready); Assert.False(pending.IsCompleted);
            switch (change)
            {
                case "stop": runtime.Stop(); break;
                case "hold": Assert.True(session.Hold(generation)); break;
                case "begin": session.Begin("replacement", "other"); break;
                default: session.Disconnect(); break;
            }
            // Stop must revoke synchronously. External account changes must also wake
            // this already-pending publication waiter without any getter driving refresh.
            if (change == "stop") Assert.Null(runtime.Publication);
            var revoked = await pending.WaitAsync(AccountGuard); Assert.Null(revoked.Publication);
            Assert.Null(runtime.Publication);
            Assert.NotSame(ready, revoked); Assert.NotNull(ready.Publication!.Catalogs);
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            var completed = runtime.PublicationSnapshot; Assert.True(completed.IsCompleted);
            Assert.Same(completed, await runtime.WaitForPublicationChangeAsync(ready));
        }
        finally { finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Publication_wait_reconnects_with_fresh_attempt_and_exact_generation_catalog_join()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var reconnect = AccountSignal(); var allowReplacement = AccountSignal(); var refresh = AccountSignal();
        var releaseRefresh = AccountSignal(); var finish = AccountSignal();
        int blockRefresh = 0;
        source.BeforeObserve = async _ =>
        {
            if (Volatile.Read(ref blockRefresh) != 0)
            { refresh.TrySetResult(); await releaseRefresh.Task.WaitAsync(AccountGuard); }
        };
        var first = verification.Run(AccountVerify, async client =>
        {
            await client.WaitFor(allowReplacement.Task); await AccountVerify(client);
        });
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(reconnect.Task); await client.CloseSendAndExpectEof();
        }, async client =>
        {
            await AccountEnterWorld(client); await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
        });
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, PublicationOwner(fixture, source));
        await using var runtime = AccountRuntime.CreateForOfflineTests(session, generation,
            AccountProfile(verification, formal), new AccountCredentials(), resources,
            new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) });
        var run = runtime.RunAsync();
        try
        {
            var ready = await AccountPublicationWhen(runtime, value => ReceivingPublication(value) && value.Publication!.Catalogs is not null);
            Volatile.Write(ref blockRefresh, 1);
            var pending = runtime.WaitForPublicationChangeAsync(ready); reconnect.SetResult();
            var retired = await pending.WaitAsync(AccountGuard); Assert.NotSame(ready, retired);
            Assert.Null(retired.Publication?.Catalogs);
            var replacement = await AccountPublicationWhen(runtime, value => value.Connection.Generation == generation + 1);
            Assert.NotEqual(ready.Publication!.Receive.Attempt, replacement.Publication?.Receive.Attempt);
            Assert.Null(replacement.Publication?.Catalogs);
            allowReplacement.SetResult(); await refresh.Task.WaitAsync(AccountGuard);
            var receiving = await AccountPublicationWhen(runtime, value => value.Connection.Generation == generation + 1 && ReceivingPublication(value));
            Assert.Null(receiving.Publication!.Catalogs);
            Assert.NotEqual(ready.Publication.Receive.Attempt, receiving.Publication.Receive.Attempt);
            Assert.Equal(ready.Publication.Receive.Revision, receiving.Publication.Receive.Revision); // Revision resets per attempt.
            Assert.Same(receiving, await runtime.WaitForPublicationChangeAsync(ready).WaitAsync(AccountGuard));
            var bound = runtime.WaitForPublicationChangeAsync(receiving); releaseRefresh.SetResult();
            var current = await bound.WaitAsync(AccountGuard);
            Assert.Same(receiving.Publication.Receive, current.Publication!.Receive);
            Assert.NotNull(current.Publication.Catalogs); Assert.NotNull(ready.Publication.Catalogs);
            Assert.NotSame(ready.Publication.Catalogs, current.Publication.Catalogs);
            Assert.Equal(generation + 1, current.Connection.Generation);
            runtime.Stop(); Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { reconnect.TrySetResult(); allowReplacement.TrySetResult(); releaseRefresh.TrySetResult(); finish.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Publication_wait_defers_completion_until_owned_cleanup_finishes(bool fail)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "offline").Generation;
        var cleanup = AccountSignal(); var release = AccountSignal();
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(
            fixture.Root, new NotificationCleanupSource(source, cleanup, release.Task, fail)));
        var runtime = AccountRuntime.CreateForOfflineTests(session, generation, InertAccountProfile(), new AccountCredentials(), resources);
        var initial = runtime.PublicationSnapshot; var started = runtime.WaitForPublicationChangeAsync(initial);
        var disposal = runtime.DisposeAsync().AsTask();
        Task<AccountRuntimePublicationSnapshot>? final = null;
        try
        {
            Assert.NotSame(initial, await started.WaitAsync(AccountGuard));
            await cleanup.Task.WaitAsync(AccountGuard);
            var ended = runtime.PublicationSnapshot;
            Assert.Equal(AccountConnectionPhase.Ended, ended.Connection.Phase); Assert.False(ended.IsCompleted);
            Assert.Null(ended.Publication); Assert.False(disposal.IsCompleted);
            final = runtime.WaitForPublicationChangeAsync(ended); Assert.False(final.IsCompleted);
        }
        finally { release.TrySetResult(); }
        var completed = await final!.WaitAsync(AccountGuard); Assert.True(completed.IsCompleted);
        Assert.Same(completed, await runtime.WaitForPublicationChangeAsync(completed));
        if (fail) await Assert.ThrowsAsync<AccountRuntimeCleanupException>(() => disposal);
        else await disposal.WaitAsync(AccountGuard);
        Assert.Equal(1, source.Disposals); Assert.False(Directory.Exists(fixture.Root));
    }
}
