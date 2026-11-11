using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    [Fact]
    public async Task Character_history_is_published_separately_from_bounded_raw_receipts()
    {
        var packets=new List<Packet> { World,new(1,11),new(26,4,[100,0,0,0]) };
        for(int i=0;i<650;i++) packets.Add(new(22,2,new PacketWriter().U16(i).U16(20).U16(30).U8(1).Build()));
        packets.Add(new(90,1,[1,2,3]));
        await using var attempt=Attempt(new ScriptedTransport([Wire(packets)]));
        var result=await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(Lala.Core.Sessions.Receive.ReceiveEnd.Completed,result.End);
        Assert.Equal(packets.Count,result.Publication.ServerSequence);
        Assert.Equal(500,result.Publication.Events.Length);
        Assert.Contains(result.Publication.CharacterEvents,e=>e.Type=="gold_snapshot");
        Assert.All(result.Publication.CharacterEvents,e=>Assert.Equal(17u,e.OwnerRoleId));
        Assert.DoesNotContain(result.Publication.CharacterEvents,e=>e.Main==22||e.Type=="unimplemented");
        Assert.Equal(650,result.Publication.Snapshot.PacketCount-4);
        Assert.Equal((ushort)20,result.Publication.Snapshot.Player!.X);
        Assert.Equal((ushort)30,result.Publication.Snapshot.Player.Y);
    }
}
