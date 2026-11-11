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
    public async Task Field_storage_automation_waits_for_peer_health_and_finishes_sent_receipt_when_paused()
    {
        using var fixture = new Fixture(); var source = new Source(); var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        var baseline = (source.Observations, source.BundleRequests);
        var received = AccountSignal(); var allowHealth = AccountSignal();
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async peer =>
        {
            await AccountEnterWorld(peer);
            await peer.Expect(23, 147, 3); received.TrySetResult();
            await peer.Send(new Packet(23, 208, [5, 3, 1, 0]));
            await peer.WaitFor(allowHealth.Task);
            await peer.Send(new Packet(8, 1, new PacketWriter().U8(25).U8(1).U32(100).U32(0).Build()));
            await peer.ExpectClosedAfterRetirement(); // No repeated supply is allowed.
        });
        var session = new AccountSession(); var account = session.Begin("synthetic", "loopback");
        await using var runtime = AccountRuntime.CreateUsingPreparedResources(session, account.Generation, Guid.NewGuid(),
            AccountProfile(verification, formal), new PreparedInput(), startup, sendConfirmation: new PreparedConfirm());
        var running = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.CanSendGameActions);
            var connection = (AccountConnectionRuntime)typeof(AccountRuntime).GetField("connection", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(runtime)!;
            var attempt = runtime.Publication!.Receive.Attempt;
            // Synthetic observed stats only; transport, decoding and receipt ownership are real.
            var seed = RecoveryState();
            await connection.ApplyCommandAsync(attempt, state => new(local: state.Local, playerKnowledge: seed.PlayerKnowledge, recovery: seed.Recovery), default);
            await runtime.SetAutomationAsync("battle", true, new() { FieldHeal = true, HpRecovery = new() { Enabled = false, Storage = "first" } });
            await received.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(() => runtime.Publication!.Receive.Events.Any(e => e.Type == "potion_used"));
            Assert.True(runtime.ActionStatus!.Pending);
            Assert.Equal(500, runtime.Publication!.Receive.State.Recovery.Resources["hp"].Value);
            var pause = runtime.SetAutomationAsync("battle", false);
            Assert.False(pause.IsCompleted);
            allowHealth.TrySetResult(); await pause.WaitAsync(AccountGuard);
            Assert.False(runtime.ActionStatus!.Pending); Assert.False(runtime.ActionStatus.Uncertain);
            Assert.Equal(420, runtime.Publication!.Receive.State.Recovery.Resources["hp"].Value);
            Assert.Equal(100, runtime.Publication.Receive.State.PlayerKnowledge.Stats["hp"]);
            Assert.False(runtime.Automations["battle"].Enabled);
            Assert.Equal(baseline, (source.Observations, source.BundleRequests));
            runtime.Stop(); Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { allowHealth.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
