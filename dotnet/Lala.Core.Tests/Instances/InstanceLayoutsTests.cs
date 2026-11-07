using Lala.Core.Instances;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Instances;

public sealed class InstanceLayoutsTests
{
    [Fact]
    public void MainRoomReadsOneRecordAndLeavesNextBytes()
    {
        var reader = new PacketReader(new byte[] { 1, 2, 4, 65, 0, 0, 0, 3, 0, 2, 255, 255, 99 });
        Assert.Equal(new MainInstanceRoom(513, "A", 3, "", false, 65535), InstanceLayouts.ReadMainRoom(reader));
        Assert.Equal((byte)99, reader.U8());
        reader.End();
    }

    [Fact]
    public void FixedRowsLeaveTheFollowingRecordToTheirCaller()
    {
        var coopRoom = new PacketReader(new byte[] { 255, 7, 8, 1, 2, 255, 254, 255, 255, 255, 255, 99 });
        // The source does not impose the room-list capacity/member bounds used by S186-3.
        Assert.Equal(new CoopInstanceRoom(true, 7, 8, 513, 255, 254, uint.MaxValue), InstanceLayouts.ReadCoopRoom(coopRoom));
        Assert.Equal((byte)99, coopRoom.U8());
        coopRoom.End();
        var member = new PacketReader(new PacketWriter().U32(0).U8(7).U32(8).U32(9).U32(10).U32(11).U8(99).Build());
        Assert.Equal(new CoopInstanceMember(0, 7, 8, 9, 10, 11), InstanceLayouts.ReadCoopMember(member));
        Assert.Equal((byte)99, member.U8());
        member.End();
        var settlement = new PacketReader(new PacketWriter().U32(uint.MaxValue).U8(7).U8(8).U8(99).Build());
        Assert.Equal(new InstanceSettlementRecord(uint.MaxValue, 7, 8), InstanceLayouts.ReadSettlementRecord(settlement));
        Assert.Equal((byte)99, settlement.U8());
        settlement.End();
        var award = new PacketReader(new PacketWriter().U8(255).U32(uint.MaxValue).U32(0).U8(99).Build());
        Assert.Equal(new InstanceAward(255, uint.MaxValue, 0), InstanceLayouts.ReadAward(award));
        Assert.Equal((byte)99, award.U8());
        award.End();
    }

    [Fact]
    public void EveryIncompleteRowThrowsWithoutReturningPartialObjects()
    {
        var layouts = new (int Bytes, Func<PacketReader, object> Read)[]
        {
            (8, reader => InstanceLayouts.ReadMainRoom(reader)),
            (11, reader => InstanceLayouts.ReadCoopRoom(reader)),
            (21, reader => InstanceLayouts.ReadCoopMember(reader)),
            (6, reader => InstanceLayouts.ReadSettlementRecord(reader)),
            (9, reader => InstanceLayouts.ReadAward(reader))
        };
        foreach (var (length, read) in layouts)
        {
            for (var size = 0; size < length; size++)
                Assert.Throws<ProtocolException>(() => read(new PacketReader(new byte[size])));
            var reader = new PacketReader(new byte[length]);
            Assert.NotNull(read(reader));
            reader.End();
        }
    }
}
