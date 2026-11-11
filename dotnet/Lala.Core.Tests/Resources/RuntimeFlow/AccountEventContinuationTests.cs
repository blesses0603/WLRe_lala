using System.Reflection;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    [Fact]
    public async Task Core_event_worker_does_not_advance_a_manual_npc_conversation()
    {
        using var fixture=new Fixture();var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,new Source());
        typeof(ResourceRuntimeOwner).GetField("_production",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(owner,true);
        await using var startup=PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,owner);
        Assert.Equal(PreloginResourceStatus.Ready,(await startup.PrepareAsync()).Status);
        var allowGrant=AccountSignal();var finishDialogue=AccountSignal();
        await using var verification=new AccountPeer();await using var formal=new AccountPeer();
        var first=verification.Run(AccountVerify);
        var second=formal.Run(async peer=>
        {
            await AccountEnterWorld(peer);await peer.WaitFor(allowGrant.Task);await peer.Send(new Packet(20,10));
            await peer.WaitFor(finishDialogue.Task);await peer.Send(new Packet(20,8));
            // A forbidden C20-6 would be buffered ahead of this party action.
            await peer.Expect(33,5,1);await peer.Send(new Packet(33,2,[0,0,1,0]));
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();var account=session.Begin("synthetic","loopback");
        await using var runtime=AccountRuntime.CreateUsingPreparedResources(session,account.Generation,Guid.NewGuid(),
            AccountProfile(verification,formal),new PreparedInput(),startup,sendConfirmation:new PreparedConfirm());
        var running=runtime.RunAsync();
        try
        {
            await AccountWaitFor(()=>runtime.CanSendGameActions);
            var connection=(AccountConnectionRuntime)typeof(AccountRuntime).GetField("connection",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(runtime)!;
            await connection.ApplyCommandAsync(runtime.Publication!.Receive.Attempt,state=>Lala.Core.Gameplay.CommandState.With(state,
                local:new(state.Local.Session with{NpcDialogue=new(){Active=true,Phase="awaiting_reply"}},state.Local.World,state.Local.Battle)),default);
            allowGrant.TrySetResult();
            await AccountWaitFor(()=>runtime.Publication!.Receive.State.Local.Session.EventFlow.LastSource=="S20-10");
            await Task.Delay(350);
            Assert.Equal(0,runtime.Publication!.Receive.State.Local.Session.EventFlow.RequestsSent);Assert.Empty(runtime.ActionLog);
            finishDialogue.TrySetResult();await AccountWaitFor(()=>!runtime.Publication!.Receive.State.Local.Session.EventFlow.Blocked);
            await runtime.ExecuteActionAsync(new("party","flag"));
            runtime.Stop();Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally{allowGrant.TrySetResult();finishDialogue.TrySetResult();runtime.Stop();}
        await Task.WhenAll(first,second).WaitAsync(AccountGuard);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Core_event_reply_does_not_wait_behind_a_general_actions_ack_and_rejection_is_not_retried(bool reject)
    {
        using var fixture=new Fixture();var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,new Source());
        typeof(ResourceRuntimeOwner).GetField("_production",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(owner,true);
        await using var startup=PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,owner);
        Assert.Equal(PreloginResourceStatus.Ready,(await startup.PrepareAsync()).Status);
        await using var verification=new AccountPeer();await using var formal=new AccountPeer();
        var coreWritten=AccountSignal();var allowReplies=AccountSignal();
        var first=verification.Run(AccountVerify);
        var second=formal.Run(async peer=>
        {
            await AccountEnterWorld(peer);await peer.Expect(33,5,1);
            await peer.Send(new Packet(20,10));
            // The party action is still waiting for its ACK. Core protocol writes
            // must remain possible, without stealing that action's Pending status.
            await peer.Expect(20,6,0);
            coreWritten.TrySetResult();await peer.WaitFor(allowReplies.Task);
            if(reject)await peer.Send(new Packet(20,74,[1]));
            else await peer.Send(new Packet(20,8));
            await peer.Send(new Packet(33,2,[0,0,1,0]));
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();var account=session.Begin("synthetic","loopback");
        await using var runtime=AccountRuntime.CreateUsingPreparedResources(session,account.Generation,Guid.NewGuid(),
            AccountProfile(verification,formal),new PreparedInput(),startup,sendConfirmation:new PreparedConfirm());
        var running=runtime.RunAsync();
        try
        {
            await AccountWaitFor(()=>runtime.CanSendGameActions);
            var action=runtime.ExecuteActionAsync(new("party","flag"));
            await coreWritten.Task.WaitAsync(AccountGuard);
            Assert.Equal("組隊操作",runtime.ActionStatus!.Label);Assert.True(runtime.ActionStatus.Pending);
            Assert.False(action.IsCompleted);allowReplies.TrySetResult();await action.WaitAsync(AccountGuard);
            if(reject)
            {
                await AccountWaitFor(()=>!runtime.CanSendGameActions);
                Assert.Contains(runtime.ActionLog,line=>line.Contains("結果未確認，已停止重送"));
            }
            else await AccountWaitFor(()=>runtime.ActionLog.Any(line=>line.Contains("已完成（接續 1 步）")));
            Assert.Equal("組隊操作",runtime.ActionStatus!.Label);Assert.False(runtime.ActionStatus.Pending);
            Assert.Equal(2,runtime.ActionLog.Length);
            runtime.Stop();Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally{allowReplies.TrySetResult();runtime.Stop();}
        await Task.WhenAll(first,second).WaitAsync(AccountGuard);
    }

    [Fact]
    public async Task Repeated_scene_steps_consume_one_coalesced_grant_and_event_end_stops_sending()
    {
        using var fixture=new Fixture();var source=new Source();var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,source);
        typeof(ResourceRuntimeOwner).GetField("_production",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(owner,true);
        await using var startup=PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,owner);
        Assert.Equal(PreloginResourceStatus.Ready,(await startup.PrepareAsync()).Status);
        var allowNext=AccountSignal();var resumed=AccountSignal();
        await using var verification=new AccountPeer();await using var formal=new AccountPeer();
        var first=verification.Run(AccountVerify);
        var second=formal.Run(async peer=>
        {
            await AccountEnterWorld(peer);await peer.Send(new Packet(20,10));
            for(int i=0;i<40;i++)
            {
                await peer.Expect(20,6,0);
                if(i<39)await peer.Send(new Packet(22,10,[1,0,255,255]),new Packet(20,11),new Packet(20,10));
                else await peer.Send(new Packet(20,8));
            }
            await peer.WaitFor(allowNext.Task);await peer.Send(new Packet(20,10));
            await peer.Expect(20,6,0);await peer.Send(new Packet(20,8));resumed.TrySetResult();
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();var account=session.Begin("synthetic","loopback");
        await using var runtime=AccountRuntime.CreateUsingPreparedResources(session,account.Generation,Guid.NewGuid(),
            AccountProfile(verification,formal),new PreparedInput(),startup,sendConfirmation:new PreparedConfirm());
        var running=runtime.RunAsync();
        try
        {
            // Ordinary world scripts complete even when battle AI has never been enabled.
            await AccountWaitFor(()=>runtime.ActionLog.Any(line=>line.Contains("已完成（接續 40 步）")));
            Assert.Equal(40,runtime.Publication!.Receive.State.Local.Session.EventFlow.RequestsSent);
            Assert.Single(runtime.ActionLog);Assert.Null(runtime.ActionStatus);
            Assert.DoesNotContain(runtime.ActionLog,line=>line.Contains("正在送出")||line.Contains("已收到伺服器狀態更新"));
            // Toggling AI cannot replay an already consumed grant or cancel core synchronization.
            await runtime.SetAutomationAsync("battle",true);await runtime.SetAutomationAsync("battle",false);
            allowNext.TrySetResult();await resumed.Task.WaitAsync(AccountGuard);
            await AccountWaitFor(()=>runtime.ActionLog.Length==2&&runtime.ActionLog.Last().Contains("已完成（接續 1 步）"));
            Assert.Equal(41,runtime.Publication!.Receive.State.Local.Session.EventFlow.RequestsSent);
            await runtime.SetAutomationAsync("battle",false);runtime.Stop();
            Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally{allowNext.TrySetResult();runtime.Stop();}
        await Task.WhenAll(first,second).WaitAsync(AccountGuard);
    }
}
