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
    public async Task A_reply_from_a_replacement_character_cannot_confirm_the_previous_characters_action()
    {
        using var fixture=new Fixture();var source=new Source();var owner=ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root,source);
        typeof(ResourceRuntimeOwner).GetField("_production",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(owner,true);
        await using var startup=PreloginResourcePreparation.CreateForOfflineTests(fixture.Root,owner);
        Assert.Equal(PreloginResourceStatus.Ready,(await startup.PrepareAsync()).Status);
        await using var verification=new AccountPeer();await using var formal=new AccountPeer();
        var first=verification.Run(AccountVerify);
        byte[] other=AccountWorld.Payload.ToArray();System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(other,18);
        var second=formal.Run(async peer=>
        {
            await AccountEnterWorld(peer);await peer.Expect(33,5,1);
            await peer.Send(new Packet(3,1,other),new Packet(33,2,[0,0,1,0]));
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();var account=session.Begin("synthetic","loopback");
        await using var runtime=AccountRuntime.CreateUsingPreparedResources(session,account.Generation,Guid.NewGuid(),
            AccountProfile(verification,formal),new PreparedInput(),startup,sendConfirmation:new PreparedConfirm());
        var running=runtime.RunAsync();
        try
        {
            await AccountWaitFor(()=>runtime.CanSendGameActions);
            await Assert.ThrowsAsync<ProtocolException>(()=>runtime.ExecuteActionAsync(new("party","flag")));
            Assert.True(runtime.ActionStatus!.Uncertain);Assert.False(runtime.CanSendGameActions);Assert.Empty(runtime.ActionLog);
            runtime.Stop();Assert.True((await running.WaitAsync(AccountGuard)).ResourcesReleased);
        }
        finally{runtime.Stop();}
        await Task.WhenAll(first,second).WaitAsync(AccountGuard);
    }
}
