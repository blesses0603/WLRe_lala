using System.Collections.Immutable;
using System.Reflection;
using Lala.Core.Battle;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public void Cancelled_unsent_event_preserves_new_cooperative_evidence_and_cannot_restore_an_old_battle()
    {
        var seed=SubmissionState();var basis=CommandState.With(seed,local:new(seed.Local.Session with
            {PostBattle=new(){Role=17,Scene=101,Battle=1,Phase="exit_delay",ExitPacket=10,CoopCount=2}},seed.Local.World,seed.Local.Battle with{Active=false}));
        var current=CommandState.With(basis,local:new(basis.Local.Session with
            {EventFlow=new(){LastSource="C20-6",AwaitingResponse=true,RequestsSent=1},PostBattle=basis.Local.Session.PostBattle with{Phase="awaiting_response",CoopCount=4}},basis.Local.World,basis.Local.Battle));
        var method=typeof(AccountRuntime).GetMethod("ClearUnsent",BindingFlags.Static|BindingFlags.NonPublic)!;
        var cleared=(ServiceStateSnapshot)method.Invoke(null,[current,"event",basis])!;
        Assert.Equal("exit_delay",cleared.Local.Session.PostBattle.Phase);Assert.Equal(4,cleared.Local.Session.PostBattle.CoopCount);
        var nextBattle=CommandState.With(current,local:new(current.Local.Session with{PostBattle=current.Local.Session.PostBattle with{Battle=2,Phase="fighting"}},current.Local.World,current.Local.Battle with{BattleCount=2,Active=true}));
        Assert.Same(nextBattle,method.Invoke(null,[nextBattle,"event",basis]));
    }
    private static AutoBattleProfile DefendProfile()=>new(){OrderEnabled=true,OrderActions=[new(){Id=60021},new()]};

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Complete_round_then_post_battle_continuation_is_delayed_single_use_and_independent_of_AI(bool permission)
    {
        using var fixture=new Fixture();var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,new Source());
        typeof(ResourceRuntimeOwner).GetField("_production",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(owner,true);
        await using var startup=PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,owner);
        Assert.Equal(PreloginResourceStatus.Ready,(await startup.PrepareAsync()).Status);
        var firstRound=AccountSignal();var nextRound=AccountSignal();var secondRound=AccountSignal();var completed=AccountSignal();
        await using var verification=new AccountPeer();await using var formal=new AccountPeer();
        var verify=verification.Run(AccountVerify);
        var peerTask=formal.Run(async peer=>
        {
            await AccountEnterWorld(peer);
            await peer.Expect(50,1,1);await peer.Expect(50,1,2);firstRound.TrySetResult();
            await peer.WaitFor(nextRound.Task);await peer.Send(new Packet(52,1,[2,0]));
            await peer.Expect(50,1,1);await peer.Expect(50,1,2);secondRound.TrySetResult();
            var exit=new Packet(11,0,new PacketWriter().U32(17).U16(0).Build());
            var watch=System.Diagnostics.Stopwatch.StartNew();
            if(permission)await peer.Send(exit,exit,new Packet(20,10),new Packet(20,11));else await peer.Send(exit,exit);
            await peer.Expect(20,6,0);Assert.True(watch.Elapsed>=TimeSpan.FromSeconds(2.4));
            await peer.Send(new Packet(20,8));completed.TrySetResult();await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();var account=session.Begin("synthetic","loopback");
        await using var runtime=AccountRuntime.CreateUsingPreparedResources(session,account.Generation,Guid.NewGuid(),AccountProfile(verification,formal),new PreparedInput(),startup,sendConfirmation:new PreparedConfirm());
        var running=runtime.RunAsync();
        try
        {
            await AccountWaitFor(()=>runtime.CanSendGameActions);
            var connection=(AccountConnectionRuntime)typeof(AccountRuntime).GetField("connection",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(runtime)!;
            await connection.ApplyCommandAsync(runtime.Publication!.Receive.Attempt,s=>CommandState.With(s,local:new(s.Local.Session with
                {PostBattle=new(){Role=17,Scene=101,Battle=1,Phase="fighting"}},s.Local.World,SubmissionState().Local.Battle)),default);
            var settings=new GameAutomationSettings{Player=DefendProfile(),Partner=DefendProfile()};
            await runtime.SetAutomationAsync("battle",true,settings);await firstRound.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(()=>runtime.Publication!.Receive.State.Local.Battle.Commands.Length==2);
            await runtime.SetAutomationAsync("battle",false);await runtime.SetAutomationAsync("battle",true,settings);
            await Task.Delay(350);nextRound.TrySetResult();await secondRound.Task.WaitAsync(AccountGuard);
            await runtime.SetAutomationAsync("battle",false);await completed.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(()=>runtime.Publication!.Receive.State.Local.Session.PostBattle.Phase=="completed");
            Assert.Equal(1,runtime.Publication!.Receive.State.Local.Session.EventFlow.RequestsSent);
            Assert.False(runtime.ActionStatus!.Uncertain);
            runtime.Stop();Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally{nextRound.TrySetResult();runtime.Stop();}
        await Task.WhenAll(verify,peerTask).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData(0,2.5)]
    [InlineData(1,2.5)]
    [InlineData(3,5)]
    public void Cooperative_exit_uses_verified_winner_and_consumes_count_only_once(int count,double delay)
    {
        var s=SubmissionState();var local=new LocalStateSnapshot(s.Local.Session with{PostBattle=new(){Role=17,Scene=101,Battle=1,Phase="fighting",Style=16,CoopCount=count}},s.Local.World,s.Local.Battle with{WinnerSide=2});
        var next=PostBattleLifecycle.Observe(local,local,new FightExitEvent(17,0),10,count);
        Assert.Equal(10+delay,next.Session.PostBattle.Due);
        var again=PostBattleLifecycle.Observe(next,next,new FightExitEvent(17,0),11,count);
        Assert.Equal(next.Session.PostBattle,again.Session.PostBattle);
        var nearby=PostBattleLifecycle.Observe(local,local,new FightExitEvent(99,0),10,count);
        Assert.Equal("fighting",nearby.Session.PostBattle.Phase);
        var end=PostBattleLifecycle.Observe(next,next,new EventEndEvent(),12,count);
        Assert.False(end.Session.PostBattle.Pending);
    }

    [Fact]
    public async Task Round_is_fully_planned_before_submission_and_excludes_already_commanded_units()
    {
        var c=(await new OfflineBundleRuntimePreparation().PrepareAsync(new Source())).Candidate;var state=SubmissionState();
        var options=new GameAutomationSettings{Player=DefendProfile(),Partner=DefendProfile()};
        var plans=AutomaticBattleRound.Plan(state,c,options,"synthetic",10);
        Assert.Equal(2,plans.Length);Assert.Empty(state.Local.Battle.Commands);
        var after=plans[0].Plan.AfterWrite!(state);
        Assert.Single(AutomaticBattleRound.Plan(after,c,options,"synthetic",10));
        Assert.All(plans,p=>Assert.Equal((ushort)1,p.Action.Index));
    }
}
