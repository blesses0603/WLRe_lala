using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Protocol;

public class SceneNpcProtocolTests
{
    [Theory]
    [InlineData(4,14)]
    [InlineData(5,6)]
    [InlineData(6,3)]
    public void Live_npc_status_teleport_and_visibility_have_checked_boundaries(byte sub,int bytes)
    {
        var packet=new Packet(22,sub,new byte[bytes]);var value=ServerProtocol.Decode(packet);
        Assert.NotEqual("unimplemented",value.Type);
        for(int i=1;i<bytes;i++)Assert.Throws<ProtocolException>(()=>ServerProtocol.Decode(new(22,sub,new byte[i])));
        Assert.Throws<ProtocolException>(()=>ServerProtocol.Decode(new(22,sub,new byte[bytes+1])));
    }
    [Fact]
    public void Npc_movement_decodes_unsigned_scene_index_coordinates_and_speed()
    {
        var bytes = new PacketWriter().U16(40001).U16(6920).U16(7100).U8(5).Build();
        var move = Assert.IsType<SceneNpcMoveEvent>(ServerProtocol.Decode(new(22,2,bytes)));
        Assert.Equal(new SceneNpcMoveEvent(40001,6920,7100,5), move);
        for (int i=0;i<bytes.Length;i++) Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new(22,2,bytes[..i])));
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new(22,2,[..bytes,0])));
    }
    [Theory]
    [InlineData(3,false)]
    [InlineData(10,false)]
    [InlineData(11,true)]
    public void Visibility_is_scene_data_not_a_permission_or_player_movement(byte sub,bool visible)
    {
        var bytes = new PacketWriter().U16(401).U16(65535).Build();
        var e = Assert.IsType<SceneNpcVisibilityEvent>(ServerProtocol.Decode(new(22,sub,bytes)));
        Assert.Equal((ushort)401,e.Index); Assert.True(e.Permanent); Assert.Equal(visible,e.Visible);
        Assert.False(Assert.IsType<SceneNpcVisibilityEvent>(ServerProtocol.Decode(new(22,sub,[1,0,30,0]))).Permanent);
        for(int i=0;i<bytes.Length;i++) Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new(22,sub,bytes[..i])));
        Assert.Throws<ProtocolException>(() => ServerProtocol.Decode(new(22,sub,[..bytes,0])));
    }
}
