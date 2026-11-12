using System.Reflection;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Prepared_resources_bind_accounts_without_any_additional_resource_io()
    {
        using var fixture = new Fixture(); var source = new Source(); int databaseOpens = 0;
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = connection => { databaseOpens++; return connection; }
        });
        // Lifecycle wiring only. The ordinary offline-source test continues to reject admission.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        Assert.True(startup.TryReadCatalogs(out var original));
        var baseline = (source.Observations, source.BundleRequests, databaseOpens);
        var stored = fixture.Bytes();
        var firstSession = new AccountSession(); var first = firstSession.Begin("first", "loopback");
        await using var firstResources = AccountResourceRuntime.FromPrepared(firstSession, startup);
        var bound = await firstResources.BootstrapAsync(first.Generation);
        Assert.True(bound.WasBound); Assert.Equal(AccountResourceStorageOutcome.NotAttempted, bound.StorageOutcome);
        Assert.False(bound.ReadbackMatched); Assert.False(bound.SourcesRechecked);
        Assert.True(firstResources.TryReadCatalogs(out var firstCatalogs)); Assert.Same(original, firstCatalogs);
        firstSession.Hold(first.Generation);
        Assert.False(firstResources.HasCurrentResources); // An account lifecycle change revokes its binding.
        Assert.True((await firstResources.RefreshAsync(first.Generation)).WasBound);
        firstResources.Invalidate(); await firstResources.DisposeAsync();
        Assert.True(startup.HasCurrentResources); Assert.Equal(0, source.Disposals);

        var secondSession = new AccountSession(); var second = secondSession.Begin("second", "loopback");
        await using var secondResources = AccountResourceRuntime.FromPrepared(secondSession, startup);
        Assert.True((await secondResources.BootstrapAsync(second.Generation)).WasBound);
        Assert.True(secondResources.TryReadCatalogs(out var secondCatalogs)); Assert.Same(original, secondCatalogs);
        var changed = secondResources.BindingChanged;
        startup.Stop(); await changed.WaitAsync(Timeout);
        Assert.False(secondResources.HasCurrentResources); Assert.False(secondResources.TryReadCatalogs(out _));
        Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, (await secondResources.RefreshAsync(second.Generation)).Status);
        Assert.Equal(baseline, (source.Observations, source.BundleRequests, databaseOpens));
        Assert.Equal(stored, fixture.Bytes());
    }

    [Fact]
    public async Task Prepared_resource_binding_never_prepares_missing_resources_or_ignores_cancellation()
    {
        using var fixture = new Fixture(); var source = new Source();
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,
            ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        var session = new AccountSession(); var account = session.Begin("synthetic", "loopback");
        await using var resources = AccountResourceRuntime.FromPrepared(session, startup);
        Assert.Equal(AccountResourcePreparationStatus.NotAdmitted, (await resources.BootstrapAsync(account.Generation)).Status);
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        Assert.Equal(AccountResourcePreparationStatus.Cancelled, (await resources.RefreshAsync(account.Generation, cancelled.Token)).Status);
        Assert.Equal(AccountResourcePreparationStatus.AccountChanged, (await resources.RefreshAsync(account.Generation + 1)).Status);
        Assert.Equal(0, source.Observations); Assert.Equal(0, source.BundleRequests); Assert.False(Directory.Exists(fixture.Root));
        Assert.False(resources.HasCurrentResources); Assert.False(resources.CanSendPackets);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Integrated_login_uses_startup_resources_without_another_preparation_and_releases_only_its_binding(bool retireStartup)
    {
        using var fixture = new Fixture(); var source = new Source(); int databaseOpens = 0;
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: new()
        {
            WrapConnection = connection => { databaseOpens++; return connection; }
        });
        // Synthetic provenance is never accepted outside this existing private test seam.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        Assert.True(startup.TryReadCatalogs(out var original));
        var baseline = (source.Observations, source.BundleRequests, databaseOpens);
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async client => { await AccountEnterWorld(client); await client.ExpectClosedAfterRetirement(); });
        var session = new AccountSession(); long generation = session.Begin("synthetic", "loopback").Generation;
        var input = new PreparedInput();
        await using var runtime = AccountRuntime.CreateUsingPreparedResources(session, generation, Guid.NewGuid(),
            AccountProfile(verification, formal), input, startup, sendConfirmation: new PreparedConfirm());
        var run = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.Snapshot.HasCurrentResources);
            Assert.Same(original, runtime.Publication!.Catalogs);
            Assert.Equal(AccountResourceStorageOutcome.NotAttempted, Assert.Single(runtime.Snapshot.ResourceHistory).Preparation.StorageOutcome);
            Assert.Equal(baseline, (source.Observations, source.BundleRequests, databaseOpens));
            if (retireStartup)
            {
                var changed = runtime.WaitForChangeAsync(runtime.Snapshot);
                startup.Stop(); await changed.WaitAsync(AccountGuard);
                Assert.False(runtime.Snapshot.HasCurrentResources); Assert.Null(runtime.Publication!.Catalogs);
            }
            runtime.Stop();
            Assert.True((await run.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.Null(runtime.Publication); Assert.Equal(!retireStartup, startup.HasCurrentResources);
            Assert.Equal(0, source.Disposals); Assert.Equal(1, input.Calls);
            await Task.WhenAll(first, second).WaitAsync(AccountGuard);
        }
        finally { runtime.Stop(); }
    }
}
