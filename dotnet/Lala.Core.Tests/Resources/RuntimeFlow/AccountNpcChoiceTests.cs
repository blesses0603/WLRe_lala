using System.Reflection;
using Lala.Core.Gameplay;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Npc_choice_continuation_is_single_use_and_new_effect_revokes_old_grant()
    {
        using var fixture = new Fixture(); var source = new Source(); var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        typeof(ResourceRuntimeOwner).GetField("_production", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(owner, true);
        await using var startup = PreloginResourcePreparation.CreateForOfflineTests(fixture.Root, owner);
        Assert.Equal(PreloginResourceStatus.Ready, (await startup.PrepareAsync()).Status);
        await using var verification = new AccountPeer(); await using var formal = new AccountPeer();
        var received = AccountSignal();
        var first = verification.Run(AccountVerify);
        var second = formal.Run(async peer => { await AccountEnterWorld(peer); await peer.Expect(20, 6, 0); received.TrySetResult(); await peer.ExpectClosedAfterRetirement(); });
        var session = new AccountSession(); var account = session.Begin("synthetic", "loopback");
        await using var runtime = AccountRuntime.CreateUsingPreparedResources(session, account.Generation, Guid.NewGuid(),
            AccountProfile(verification, formal), new PreparedInput(), startup, sendConfirmation: new PreparedConfirm());
        var running = runtime.RunAsync();
        try
        {
            await AccountWaitFor(() => runtime.CanSendGameActions);
            var connection = (AccountConnectionRuntime)typeof(AccountRuntime).GetField("connection", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(runtime)!;
            var publication = runtime.Publication!; var attempt = publication.Receive.Attempt; ushort scene = publication.Receive.State.Player!.Scene;
            var action = new GameAction("npc", "choose", 102, 1, Count: 7, Scene: scene, Key: "42");
            await connection.ApplyCommandAsync(attempt, state => CommandState.With(state, local: new(state.Local.Session with
            {
                NpcDialogue = new() { Active = true, Scene = scene, OptionIndex = 7, SelectedChoice = 1, EffectPacket = 42, Phase = "awaiting_choice", ChoiceContinuationPending = true },
                EventFlow = state.Local.Session.EventFlow with { Blocked = true, AwaitingResponse = true }
            }, state.Local.World, state.Local.Battle)), default);
            var basis = runtime.Publication!.Receive.State;
            var method = typeof(AccountRuntime).GetMethod("ContinueNpcChoiceAsync", BindingFlags.NonPublic | BindingFlags.Instance)!;
            Task Continue() => (Task)method.Invoke(runtime, [attempt, action, basis, publication.Catalogs!, CancellationToken.None])!;
            await Continue(); await received.Task.WaitAsync(AccountGuard);
            Assert.False(runtime.Publication!.Receive.State.Local.Session.NpcDialogue.ChoiceContinuationPending);
            await Continue(); // The peer would reject a duplicate C20-6.
            await connection.ApplyCommandAsync(attempt, state => CommandState.With(state, local: new(state.Local.Session with
                { NpcDialogue = state.Local.Session.NpcDialogue with { EffectPacket = 43, Phase = "awaiting_choice", ChoiceContinuationPending = true } }, state.Local.World, state.Local.Battle)), default);
            await Continue();
            Assert.True(runtime.Publication!.Receive.State.Local.Session.NpcDialogue.ChoiceContinuationPending);
            Assert.Equal(43, runtime.Publication.Receive.State.Local.Session.NpcDialogue.EffectPacket);
            runtime.Stop(); Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally { runtime.Stop(); }
        await Task.WhenAll(first, second).WaitAsync(AccountGuard);
    }
}
