using System.Reflection;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Game_action_waits_for_actual_peer_and_never_retries_uncertain_requests(bool cancelAfterWrite)
    {
        using var fixture = new Fixture(); var source = new Source();
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        // The same private lifecycle seam as the resource tests; no synthetic provenance is accepted by production.
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        int observations = source.Observations, requests = source.BundleRequests;
        var received = AccountSignal(); var allowAck = AccountSignal();
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async peer =>
        {
            await AccountEnterWorld(peer);
            await peer.Expect(33, 5, 1); received.SetResult();
            await peer.WaitFor(allowAck.Task);
            if (!cancelAfterWrite) await peer.Send(new Packet(33, 2, [0, 0, 1, 0]));
            await peer.ExpectClosedAfterRetirement(); // Any repeated command fails this assertion.
        });
        var session = new AccountSession(); var account = session.Begin("synthetic", "loopback");
        await using var runtime = AccountRuntime.CreateUsingPreparedResources(session, account.Generation, Guid.NewGuid(),
            AccountProfile(verification, formal), new PreparedInput(), startup, sendConfirmation: new PreparedConfirm());
        var running = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.CanSendGameActions);
            using var cancel = new CancellationTokenSource();
            var count = runtime.Publication!.Receive.State.PacketCount;
            var operation = runtime.ExecuteActionAsync(new("party", "flag"), cancel.Token);
            await received.Task.WaitAsync(AccountGuard);
            Assert.False(operation.IsCompleted); Assert.True(runtime.ActionStatus!.Pending);
            Assert.Equal(count, runtime.Publication!.Receive.State.PacketCount); // A local intent is not a server packet.
            await Assert.ThrowsAsync<ProtocolException>(() => runtime.ExecuteActionAsync(new("party", "flag")));
            if (cancelAfterWrite)
            {
                cancel.Cancel(); await Assert.ThrowsAsync<ProtocolException>(() => operation);
                Assert.True(runtime.ActionStatus!.Uncertain);
                await Assert.ThrowsAsync<ProtocolException>(() => runtime.ExecuteActionAsync(new("party", "flag")));
            }
            else
            {
                allowAck.TrySetResult(); await operation.WaitAsync(AccountGuard);
                Assert.False(runtime.ActionStatus!.Pending); Assert.False(runtime.ActionStatus.Uncertain);
                Assert.True(runtime.Publication!.Receive.State.Party.Enabled);
            }
            Assert.Equal(observations, source.Observations); Assert.Equal(requests, source.BundleRequests);
            runtime.Stop(); Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
            Assert.True(startup.HasCurrentResources);
        }
        finally { allowAck.TrySetResult(); runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
