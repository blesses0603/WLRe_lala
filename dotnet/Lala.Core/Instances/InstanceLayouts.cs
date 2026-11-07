using Lala.Core.Protocol;

namespace Lala.Core.Instances;

/// <summary>Pure row layouts extracted from wlre/network/instances.py. Each reads one row,
/// leaving subsequent bytes to its caller. A malformed row throws; discard the reader afterward.</summary>
public static class InstanceLayouts
{
    public static MainInstanceRoom ReadMainRoom(PacketReader reader) => new(reader.U16(),
        reader.Unicode8(), reader.U8(), reader.Unicode8(), reader.U8() == 1, reader.U16());

    public static CoopInstanceRoom ReadCoopRoom(PacketReader reader) => new(reader.U8() != 0,
        reader.U8(), reader.U8(), reader.U16(), reader.U8(), reader.U8(), reader.U32());

    // Zero role IDs occupy real wire slots and must still consume all fields. Only the
    // packet decoder filters them from the published member list after choosing the host.
    public static CoopInstanceMember ReadCoopMember(PacketReader reader) => new(reader.U32(),
        reader.U8(), reader.U32(), reader.U32(), reader.U32(), reader.U32());

    public static InstanceSettlementRecord ReadSettlementRecord(PacketReader reader) =>
        new(reader.U32(), reader.U8(), reader.U8());

    public static InstanceAward ReadAward(PacketReader reader) => new(reader.U8(), reader.U32(), reader.U32());
}
