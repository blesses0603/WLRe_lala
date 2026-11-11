using System.Reflection;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Updating_settings_never_starts_stopped_automation_and_preserves_active_run_on_invalid_draft()
    {
        using var fixture = new Fixture(); var source = new Source();
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        var baseline = (source.Observations, source.BundleRequests);
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async peer => { await AccountEnterWorld(peer); await peer.ExpectClosedAfterRetirement(); });
        var session = new AccountSession(); var account = session.Begin("synthetic", "loopback");
        await using var runtime = AccountRuntime.CreateUsingPreparedResources(session, account.Generation, Guid.NewGuid(),
            AccountProfile(verification, formal), new PreparedInput(), startup, sendConfirmation: new PreparedConfirm());
        var running = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.CanSendGameActions);
            Assert.False(await runtime.UpdateAutomationSettingsAsync("battle", new()));
            Assert.Empty(runtime.Automations);
            await runtime.SetAutomationAsync("battle", true);
            await AccountWaitFor(() => runtime.Automations.GetValueOrDefault("battle")?.Enabled == true);
            await Assert.ThrowsAsync<ProtocolException>(() => runtime.UpdateAutomationSettingsAsync("battle", new() { RequiredParty = [1, 1] }));
            Assert.True(runtime.Automations["battle"].Enabled);
            await Assert.ThrowsAsync<ProtocolException>(() => runtime.UpdateAutomationSettingsAsync("battle", new() { HpRecovery = new() { Items = [] } }));
            Assert.True(runtime.Automations["battle"].Enabled);
            Assert.True(await runtime.UpdateAutomationSettingsAsync("battle", new() { RequiredParty = [42] }));
            await AccountWaitFor(() => runtime.Automations.GetValueOrDefault("battle")?.Enabled == true);
            await runtime.SetAutomationAsync("battle", false);
            Assert.False(await runtime.UpdateAutomationSettingsAsync("battle", new()));
            Assert.False(runtime.Automations["battle"].Enabled);
            var beforeReset = runtime.Publication!.Receive.State;
            await runtime.ResetEfficiencyAsync();
            var afterReset = runtime.Publication!.Receive.State;
            Assert.Same(beforeReset.Player, afterReset.Player); Assert.Same(beforeReset.Bag, afterReset.Bag);
            Assert.Equal(beforeReset.PacketCount, afterReset.PacketCount);
            Assert.All(afterReset.Efficiency.Rows.Values, row => { Assert.Equal(0, row.Count); Assert.Equal(System.Numerics.BigInteger.Zero, row.Earned); });
            Assert.Equal(baseline, (source.Observations, source.BundleRequests));
            runtime.Stop(); Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
