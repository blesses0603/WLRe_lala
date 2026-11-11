using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed partial class HeldAccountConnectionTests
{
    [Fact]
    public async Task Server_world_identity_replacement_updates_own_acknowledgement_and_character_history()
    {
        await using var verification=new Peer();await using var formal=new Peer();
        var first=verification.Run(Verify);var done=Signal();
        byte[] other=World.Payload.ToArray();System.Buffers.Binary.BinaryPrimitives.WriteUInt32LittleEndian(other,18);
        var second=formal.Run(async peer=>
        {
            await EnterWorld(peer);await peer.Send(new Packet(3,1,other),new Packet(12,1,new PacketWriter().U32(18).U16(101).U16(30).U16(40).Build()));
            await peer.Expect(3,2);done.TrySetResult();await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();long generation=session.Begin("synthetic","loopback").Generation;
        await using var owner=Attach(session,generation,verification,formal);var run=owner.RunAsync();
        await done.Task.WaitAsync(Guard);await owner.DisposeAsync();var result=await run.WaitAsync(Guard);
        Assert.Equal(18u,result.Publication.Snapshot.Player!.RoleId);
        Assert.All(result.Publication.CharacterEvents,e=>Assert.Equal(18u,e.OwnerRoleId));
        await Task.WhenAll(first,second).WaitAsync(Guard);
    }

    [Fact]
    public async Task Own_position_changes_acknowledge_map_and_appearance_but_nearby_changes_do_not()
    {
        await using var verification=new Peer();await using var formal=new Peer();var done=Signal();
        var first=verification.Run(Verify);
        Packet Position(uint role,ushort scene)=>new(12,1,new PacketWriter().U32(role).U16(scene).U16(30).U16(40).Build());
        var second=formal.Run(async peer=>
        {
            await EnterWorld(peer);
            await peer.Send(Position(18,102),Position(17,101));
            await peer.Expect(3,2);
            await peer.Send(Position(17,102));await peer.Expect(12,1);await peer.Expect(3,2);
            await peer.Send(new Packet(1,23));await peer.Expect(63,5);done.TrySetResult();
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();long generation=session.Begin("synthetic","loopback").Generation;
        await using var owner=Attach(session,generation,verification,formal);var run=owner.RunAsync();
        await done.Task.WaitAsync(Guard);await owner.DisposeAsync();Assert.True((await run.WaitAsync(Guard)).ResourcesReleased);
        await Task.WhenAll(first,second).WaitAsync(Guard);
    }

    [Fact]
    public async Task Expedition_clock_is_requested_once_after_both_rosters_are_received()
    {
        await using var verification=new Peer();await using var formal=new Peer();var done=Signal();
        var first=verification.Run(Verify);
        var teams=new PacketWriter();for(int i=1;i<=10;i++)teams.U8(i).Raw(new byte[20]);
        var roster=new Packet(31,13,teams.Raw(new byte[100+140+1+4+27]).Build());
        var outpost=new Packet(31,6,[4,0]);
        var second=formal.Run(async peer=>
        {
            await EnterWorld(peer);await peer.Send(roster,outpost);await peer.Expect(31,28);
            await peer.Send(roster,outpost,new(1,23));await peer.Expect(63,5);done.TrySetResult();
            await peer.ExpectClosedAfterRetirement();
        });
        var session=new AccountSession();long generation=session.Begin("synthetic","loopback").Generation;
        await using var owner=Attach(session,generation,verification,formal);var run=owner.RunAsync();
        await done.Task.WaitAsync(Guard);await owner.DisposeAsync();Assert.True((await run.WaitAsync(Guard)).ResourcesReleased);
        await Task.WhenAll(first,second).WaitAsync(Guard);
    }
}
