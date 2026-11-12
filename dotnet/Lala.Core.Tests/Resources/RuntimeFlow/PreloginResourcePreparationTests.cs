using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;
public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Prelogin_public_factory_and_disposal_are_inert_without_any_account()
    {
        using var fixture = new Fixture();
        await using var preparation = PreloginResourcePreparation.Create(fixture.Root);
        Assert.False(Directory.Exists(fixture.Root));
        Assert.False(preparation.HasCurrentResources); Assert.False(preparation.HasVisualAssets);
        Assert.False(preparation.CanLogin); Assert.False(preparation.CanSendPackets);
        Assert.False(preparation.Matches(RuntimeFlowFixtures.Snapshot()));
        await preparation.DisposeAsync();
        Assert.Equal(PreloginResourceStatus.Cancelled, (await preparation.PrepareAsync()).Status);
        Assert.False(Directory.Exists(fixture.Root));
    }
    [Fact]
    public async Task Prelogin_offline_source_can_write_but_cannot_mint_admission()
    {
        using var fixture = new Fixture();
        await using var preparation = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source()));
        var task = preparation.PrepareAsync(); Assert.Same(task, preparation.PrepareAsync());
        var result = await task;
        Assert.Equal(PreloginResourceStatus.NotAdmitted, result.Status);
        Assert.Equal(AccountResourceStorageOutcome.Committed, result.StorageOutcome);
        Assert.True(result.ReadbackMatched); Assert.True(result.SourcesRechecked);
        Assert.False(preparation.HasCurrentResources); Assert.False(preparation.TryReadCatalogs(out _));
        Assert.False(preparation.Matches(RuntimeFlowFixtures.Snapshot()));
    }
    [Fact]
    public async Task Prelogin_stop_revokes_immediately_and_disposal_waits_for_late_source()
    {
        using var fixture = new Fixture();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var source = new Source { BeforeObserve = async _ => { entered.TrySetResult(); await release.Task; } };
        await using var preparation = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source));
        var run = preparation.PrepareAsync();
        try
        {
            await entered.Task.WaitAsync(Timeout); preparation.Stop();
            var dispose = preparation.DisposeAsync().AsTask();
            Assert.False(dispose.IsCompleted); Assert.False(preparation.HasCurrentResources);
            release.TrySetResult();
            Assert.Equal(PreloginResourceStatus.Cancelled, (await run.WaitAsync(Timeout)).Status);
            await dispose.WaitAsync(Timeout);
            Assert.False(Directory.Exists(fixture.Root)); Assert.Equal(1, source.Disposals);
        }
        finally { release.TrySetResult(); }
    }
    [Fact]
    public async Task Prelogin_whitebox_current_identity_is_exact_and_revocable()
    {
        using var fixture = new Fixture();
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        // State-machine wiring only, not provenance: same explicit white-box seam as account tests.
        typeof(ResourceRuntimeOwner).GetField("_production", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.SetValue(owner, true);
        await using var preparation = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await preparation.PrepareAsync()).Status);
        Assert.True(preparation.Matches(RuntimeFlowFixtures.Snapshot()));
        Assert.False(preparation.Matches(RuntimeFlowFixtures.Snapshot(dataVersion: "9.9.9")));
        Assert.False(preparation.Matches(RuntimeFlowFixtures.Snapshot(packageVersion: "9999_2026_10_21_18_27_33_84")));
        Assert.False(preparation.Matches(null)); Assert.True(preparation.TryReadCatalogs(out _));
        preparation.Stop();
        Assert.False(preparation.HasCurrentResources); Assert.False(preparation.Matches(RuntimeFlowFixtures.Snapshot()));
        Assert.False(preparation.TryReadCatalogs(out _)); Assert.False(preparation.CanLogin);
    }
}
