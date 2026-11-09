using System.Reflection;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private sealed class PreparedConfirm : IAccountLoginSendConfirmation
    {
        internal readonly List<AccountLoginRecipient> Recipients = [];
        public ValueTask<bool> ConfirmAsync(AccountLoginRecipient recipient, System.Net.IPEndPoint endpoint, CancellationToken token)
        { token.ThrowIfCancellationRequested(); Recipients.Add(recipient); return ValueTask.FromResult(true); }
    }
    private sealed class PreparedInput : IAccountLoginInput
    {
        internal int Calls;
        internal AccountLoginDisclosure? Seen;
        internal AccountLoginCredentials? Credentials;
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Calls++; Seen = disclosure;
            Credentials = new("synthetic", "fake_password");
            return ValueTask.FromResult<AccountLoginCredentials?>(Credentials);
        }
    }
    private sealed class PreparedSelector : IAccountRoleSelector
    {
        internal int Calls;
        public ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Calls++;
            return ValueTask.FromResult<AccountRoleSelectionChoice?>(request.Choose(1));
        }
    }
    private sealed class IntegratedClock : TimeProvider
    {
        private long timestamp;
        public override long TimestampFrequency => TimeSpan.TicksPerSecond;
        public override long GetTimestamp() => Interlocked.Read(ref timestamp);
        internal void Advance() => Interlocked.Add(ref timestamp, TimeSpan.FromMinutes(2).Ticks);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Prepared_integrated_account_binds_resources_survives_validity_then_retires(bool hold)
    {
        using var fixture = new Fixture(); var source = new Source(); var input = new PreparedInput();
        var selector = new PreparedSelector(); var confirmation = new PreparedConfirm(); var clock = new IntegratedClock();
        var session = new AccountSession(); long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var afterValidity = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client =>
        {
            await AccountEnterWorld(client);
            await client.WaitFor(afterValidity.Task); await client.Send(AccountWorld);
            await client.ExpectClosedAfterRetirement();
        });
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        // WHITE-BOX wiring only, exactly as the existing integrated projection test:
        // synthetic source does not establish official provenance or live acceptance.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, owner);
        await using var runtime = AccountRuntime.CreatePreparedForOfflineTests(session, generation, Guid.NewGuid(),
            AccountProfile(verification, formal), input, fixture.Root, resources, roleSelector: selector, clock: clock, sendConfirmation: confirmation);
        Assert.Equal(0, input.Calls); Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
        Assert.Equal(Path.GetFullPath(fixture.Root), runtime.Disclosure!.Resources.AbsoluteDataRoot);
        Assert.Equal(AccountRoleSelectionMode.Interactive, runtime.Disclosure.Login.RoleSelectionMode);
        var run = runtime.RunAsync(); Assert.Same(run, runtime.RunAsync());
        try
        {
            await AccountWaitFor(() => runtime.Snapshot.HasCurrentResources);
            Assert.Same(runtime.Disclosure.Login, input.Seen);
            Assert.Equal(1, input.Calls); Assert.Equal(1, selector.Calls);
            Assert.Equal(new[] { AccountLoginRecipient.Verification, AccountLoginRecipient.Formal }, confirmation.Recipients);
            Assert.True(Assert.Single(runtime.Snapshot.ResourceHistory).Preparation.WasBound);
            Assert.Equal(AccountResourceStorageOutcome.Committed, runtime.Snapshot.ResourceHistory[0].Preparation.StorageOutcome);
            Assert.NotNull(runtime.Publication!.Catalogs);
            Assert.True(File.Exists(runtime.Disclosure.Resources.InventoryPath));
            var current = runtime.Snapshot;
            var revision = runtime.Publication!.Receive.Revision;
            clock.Advance();
            // Exercise real receive after the construction-time credential window elapsed.
            afterValidity.SetResult();
            await AccountWaitFor(() => runtime.Publication?.Receive.Revision > revision);
            Assert.False(run.IsCompleted); Assert.True(runtime.Snapshot.HasCurrentResources);
            Assert.NotNull(runtime.Publication!.Catalogs); AccountHeld(runtime, session);
            using var deadline = new CancellationTokenSource(AccountGuard);
            var changed = runtime.WaitForChangeAsync(current, deadline.Token);
            if (hold) Assert.True(session.Hold(generation));
            else runtime.Stop();
            Assert.False(runtime.Snapshot.HasCurrentResources);
            if (!hold) Assert.Null(runtime.Publication);
            await changed;
            var result = await run.WaitAsync(AccountGuard);
            Assert.True(result.ResourcesReleased); Assert.True(runtime.Snapshot.IsCompleted);
            Assert.Null(runtime.Publication); Assert.Same(run, runtime.RunAsync());
            Assert.Equal(1, input.Calls); Assert.Equal(1, selector.Calls);
            Assert.Single(result.ResourceHistory);
            await Task.WhenAll(first, second).WaitAsync(AccountGuard);
        }
        finally { afterValidity.TrySetResult(); runtime.Stop(); }
    }

    [Fact]
    public async Task Prepared_public_factory_discloses_separate_resource_scope_and_disposal_is_inert()
    {
        using var fixture = new Fixture(); var input = new PreparedInput();
        var session = new AccountSession(); long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var root = Path.Combine(fixture.Root, "unused", "..", "selected");
        var runtime = AccountRuntime.CreatePrepared(session, generation, Guid.NewGuid(), AccountProfile(verification, formal), input, root);
        var disclosure = runtime.Disclosure!;
        Assert.Equal(Path.GetFullPath(root), disclosure.Resources.AbsoluteDataRoot);
        Assert.EndsWith("official_sync/derived_catalogs/core_emojis_v1.sqlite3".Replace('/',Path.DirectorySeparatorChar),disclosure.Resources.EmojiCachePath);
        Assert.False(runtime.TryReadEmojiImage(1,out var emoji));Assert.Null(emoji);
        Assert.False(runtime.TryGetEmojiGallery(out var gallery));Assert.Null(gallery);

        Assert.EndsWith("official_sync/derived_catalogs/resource_inventory.sqlite3".Replace('/', Path.DirectorySeparatorChar), disclosure.Resources.InventoryPath);
        Assert.EndsWith("official_sync/bundles".Replace('/', Path.DirectorySeparatorChar), disclosure.Resources.BundleCacheDirectory);
        Assert.Equal("https://wlreftpsrc.chinesegamer.net/WLN/TW/ResourcePath_PC.dat", disclosure.Resources.VersionMapUrl);
        Assert.Equal("https://wlreftpsrc.chinesegamer.net/WLN/TW/", disclosure.Resources.ResourceUrlPrefix);
        await runtime.DisposeAsync();
        Assert.Equal(0, input.Calls); Assert.False(Directory.Exists(fixture.Root));
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        Assert.True(runtime.Snapshot.IsCompleted); Assert.Null(runtime.Publication);
    }

    [Fact]
    public async Task Prepared_integrated_expired_before_run_never_acquires_or_prepares()
    {
        using var fixture = new Fixture(); var source = new Source(); var input = new PreparedInput(); var clock = new IntegratedClock();
        var session = new AccountSession(); long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreatePreparedForOfflineTests(session, generation, Guid.NewGuid(),
            AccountProfile(verification, formal), input, fixture.Root, resources, clock: clock);
        clock.Advance();
        var result = await runtime.RunAsync().WaitAsync(AccountGuard);
        Assert.True(result.ResourcesReleased); Assert.Empty(result.ResourceHistory);
        Assert.Equal(0, input.Calls); Assert.Equal(0, source.Observations);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        Assert.False(Directory.Exists(fixture.Root));
    }

    [Fact]
    public async Task Exact_resource_snapshot_rejects_same_generation_replacement_before_io()
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        var expected = session.Begin("synthetic", "loopback");
        await using var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        Assert.True(session.Hold(expected.Generation));
        var result = await resources.BootstrapAsync(expected, CancellationToken.None);
        Assert.Equal(AccountResourcePreparationStatus.AccountChanged, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.StorageOutcome);
        Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
    }
    private sealed class DeferredPreparedInput(Func<AccountLoginDisclosure, CancellationToken, ValueTask<AccountLoginCredentials?>> acquire) : IAccountLoginInput
    {
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token) => acquire(disclosure, token);
    }
    private sealed class DeferredPreparedSelector(Func<AccountRoleSelectionRequest, CancellationToken, ValueTask<AccountRoleSelectionChoice?>> select) : IAccountRoleSelector
    {
        public ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token) => select(request, token);
    }

    [Theory]
    [InlineData("input")]
    [InlineData("selector")]
    [InlineData("resources")]
    public async Task Prepared_integrated_stop_drains_noncooperative_owned_callbacks(string stage)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        long generation = session.Begin("synthetic", "loopback").Generation;
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var entered = AccountSignal(); var release = AccountSignal();
        var value = new AccountLoginCredentials("synthetic", "fake_password");
        var input = new DeferredPreparedInput(async (_, _) =>
        {
            if (stage == "input") { entered.TrySetResult(); await release.Task; }
            return value;
        });
        var selector = new DeferredPreparedSelector(async (request, _) =>
        {
            if (stage == "selector") { entered.TrySetResult(); await release.Task; }
            return request.Choose(1);
        });
        if (stage == "resources") source.BeforeObserve = async _ => { entered.TrySetResult(); await release.Task; };
        Task first = Task.CompletedTask, second = Task.CompletedTask;
        if (stage != "input")
        {
            first = verification.Run(AccountVerify);
            second = formal.Run(async client =>
            {
                if (stage == "selector")
                {
                    await client.Expect(63, 7, 2);
                    await client.Send(new Lala.Core.Protocol.Packet(63, 7, [0, 2]), AccountRoles);
                }
                else await AccountEnterWorld(client);
                await client.ExpectClosedAfterRetirement();
            });
        }
        var resources = AccountResourceRuntime.CreateForOfflineTests(session, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        await using var runtime = AccountRuntime.CreatePreparedForOfflineTests(session, generation, Guid.NewGuid(),
            AccountProfile(verification, formal), input, fixture.Root, resources, roleSelector: selector);
        var run = runtime.RunAsync();
        try
        {
            await entered.Task.WaitAsync(AccountGuard);
            runtime.Stop();
            var disposal = runtime.DisposeAsync().AsTask();
            Assert.Null(runtime.Publication); Assert.False(runtime.Snapshot.HasCurrentResources);
            Assert.False(run.IsCompleted); Assert.False(disposal.IsCompleted);
            Assert.Same(disposal, runtime.DisposeAsync().AsTask());
            release.SetResult();
            var result = await run.WaitAsync(AccountGuard); await disposal.WaitAsync(AccountGuard);
            Assert.True(result.ResourcesReleased); Assert.True(value.IsDisposed);
            Assert.True(runtime.Snapshot.IsCompleted); Assert.False(Directory.Exists(fixture.Root));
            if (stage == "resources")
                Assert.Equal(AccountResourceStorageOutcome.NotAttempted, Assert.Single(result.ResourceHistory).Preparation.StorageOutcome);
            else Assert.Empty(result.ResourceHistory);
            await Task.WhenAll(first, second).WaitAsync(AccountGuard);
        }
        finally { release.TrySetResult(); runtime.Stop(); }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Reserved_resource_attempt_retires_before_execution_without_io(bool disposeBeforeExecute)
    {
        using var fixture = new Fixture(); var source = new Source(); int hooks = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            afterAdmission: () => { hooks++; return Task.CompletedTask; });
        var execute = owner.Reserve(bootstrap: true, CancellationToken.None);
        Task? disposal = null;
        if (disposeBeforeExecute)
        {
            disposal = owner.DisposeAsync().AsTask();
            Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        else owner.Invalidate();
        // This deterministic admission-to-execution gap has no token propagation or
        // scheduler timing dependency. Retirement must win before the first hook/I/O.
        var result = await execute().WaitAsync(AccountGuard);
        Assert.NotNull(result.Failure); Assert.False(result.StorageAttempted);
        Assert.Null(result.Publication); Assert.Equal(0, hooks);
        Assert.Equal(0, source.Observations); Assert.Equal(0, source.BundleRequests);
        Assert.False(Directory.Exists(fixture.Root));
        await (disposal ?? owner.DisposeAsync().AsTask()).WaitAsync(AccountGuard);
        Assert.Equal(1, source.Disposals);
    }

    [Fact]
    public async Task Reserved_resource_attempt_rejects_duplicate_execution_without_retiring_active_work()
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = AccountSignal(); var release = AccountSignal(); int hooks = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            afterAdmission: async () => { Interlocked.Increment(ref hooks); entered.TrySetResult(); await release.Task; });
        var execute = owner.Reserve(bootstrap: true, CancellationToken.None);
        var first = execute();
        try
        {
            await entered.Task.WaitAsync(AccountGuard);
            await Assert.ThrowsAsync<InvalidOperationException>(() => execute().WaitAsync(AccountGuard));
            Assert.Equal(1, hooks);
            Assert.False(first.IsCompleted); Assert.Equal(0, source.Observations);
            owner.Invalidate();
        }
        finally { release.TrySetResult(); }
        var result = await first.WaitAsync(AccountGuard);
        Assert.NotNull(result.Failure); Assert.False(result.StorageAttempted);
        Assert.Equal(0, source.Observations); Assert.False(Directory.Exists(fixture.Root));
        await owner.DisposeAsync(); Assert.Equal(1, source.Disposals);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Scheduled_resource_revision_rejects_retirement_before_owner_reservation(bool refresh)
    {
        using var fixture = new Fixture(); var source = new Source(); var session = new AccountSession();
        var expected = session.Begin("synthetic", "loopback");
        await using var resources = AccountResourceRuntime.CreateForOfflineTests(session,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        long scheduledRevision = resources.Revision;
        resources.Invalidate();
        Assert.Same(expected, session.Snapshot);
        var result = refresh
            ? await resources.RefreshAsync(expected, CancellationToken.None, scheduledRevision)
            : await resources.BootstrapAsync(expected, CancellationToken.None, scheduledRevision);
        Assert.Equal(AccountResourcePreparationStatus.Revoked, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.StorageOutcome);
        Assert.Equal(0, source.Observations); Assert.Equal(0, source.BundleRequests);
        Assert.False(resources.HasCurrentResources); Assert.False(Directory.Exists(fixture.Root));
    }

}
