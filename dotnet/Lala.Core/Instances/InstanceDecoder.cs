using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Instances;

/// <summary>Complete offline S85/S186 decoder from wlre/network/instances.py. All recognized
/// layouts consume exactly their payload. Unknown mains, subtypes and inner kinds return null,
/// leaving their opaque bytes uninterpreted. Recognized malformed input throws ProtocolException.
/// This API does not send requests, enter rooms, start fights or infer successful actions.</summary>
public static class InstanceDecoder
{
    public static InstanceEvent? Decode(Packet packet)
    {
        if (packet.Main is not (85 or 186)) return null;
        var reader = new PacketReader(packet.Payload.Span);
        var result = packet.Main == 85 ? ReadMain(packet.Sub, reader) : ReadCoop(packet.Sub, reader);
        if (result is not null) reader.End();
        return result;
    }

    private static InstanceEvent? ReadMain(byte sub, PacketReader reader)
    {
        switch (sub)
        {
            case 1:
                var rooms = ReadRows(reader, ReadCount(reader, 200, "S85-1 room count"), InstanceLayouts.ReadMainRoom);
                return new MainRoomListEvent(rooms);
            case 2: case 3:
                return new MainResultEvent(sub == 2 ? "create" : "join", reader.U8());
            case 4:
                var roomId = reader.U16();
                return new MainMembersEvent(roomId, ReadRows(reader,
                    ReadCount(reader, 16, "S85-4 member count"), r => new MainInstanceMember(r.U32())));
            case 5:
                return reader.U8() switch
                {
                    1 => new MainRoomPhaseEvent(reader.U8(), reader.U16(), reader.U8(), reader.U32()),
                    2 => new MainPhaseSignalEvent(2),
                    3 => new MainPhaseSignalEvent(3),
                    4 => new MainPhaseSignalEvent(4),
                    5 => new MainKickedEvent(reader.U32()),
                    _ => null
                };
            case 7: return new MainMemberJoinedEvent(reader.U8(), reader.U32(), reader.U16());
            case 9: return reader.U8() == 1 ? new MainTimeEvent(reader.U32()) : null;
            case 10: return ReadObjective(reader);
            case 12: return new MainMemberLeftEvent(reader.U8(), reader.U32(), reader.U32(), reader.U32() == 1);
            case 15: return new MainCompletedEvent();
            case 17: return new MainMinPlayersEvent();
            case 21: return ReadNewInfo(reader);
            default: return null;
        }
    }

    private static MainObjectiveEvent? ReadObjective(PacketReader reader)
    {
        var kind = reader.U8();
        return kind switch
        {
            1 => new MainObjectiveKillsEvent(reader.U8(), reader.U8(), reader.Unicode8()),
            2 => new MainObjectiveDefeatedEvent(reader.U8() == 1, reader.Unicode8()),
            3 => new MainObjectiveRequirementEvent(reader.U8(), reader.U8(), reader.U16()),
            4 => new MainObjectiveNpcEvent(reader.U16()),
            5 or 6 => new MainObjectiveRolesEvent(kind, ReadRows(reader,
                ReadCount(reader, 16, "S85-10 score role count"), r => r.U32())),
            _ => null
        };
    }

    private static MainNewInfoEvent? ReadNewInfo(PacketReader reader)
    {
        var kind = reader.U8();
        return kind switch
        {
            0 => new MainNewInfoSnapshotEvent(reader.U8(), reader.U8(), reader.U16(), reader.U32(), reader.U8() != 0, reader.U32()),
            1 => new MainNewInfoPhaseEvent(reader.U8(), reader.U32()),
            2 => new MainNewInfoCountEvent(reader.U32()),
            3 => new MainNewInfoObjectiveEvent(reader.U8(), reader.U16(), reader.U8(), reader.U8()),
            4 => new MainNewInfoKillerEvent(reader.U8(), reader.U8(), reader.Unicode8()),
            5 => new MainNewInfoNpcEvent(reader.U16()),
            98 => new MainNewInfoTextEvent(reader.U16(), reader.Unicode8(), reader.U16()),
            100 => new MainNewInfoRecordsEvent(ReadRows(reader,
                ReadCount(reader, 16, "S85-21-100 settlement count"), InstanceLayouts.ReadSettlementRecord)),
            6 or 99 or 101 or 102 => new MainNewInfoSignalEvent(kind),
            _ => null
        };
    }

    private static InstanceEvent? ReadCoop(byte sub, PacketReader reader)
    {
        switch (sub)
        {
            case 2: return ReadCoopResult(reader);
            case 3: return ReadCoopMembers(reader);
            case 6: return new CoopMemberRefreshRequestEvent(reader.U16());
            case 10:
                // Empty is a closed dialog, not evidence that a reward was received.
                if (reader.Remaining % 9 != 0 || reader.Remaining > 36)
                    throw new ProtocolException("S186-10 awards must contain 0 to 4 nine-byte records");
                return new CoopRewardReceiptEvent(ReadRows(reader, reader.Remaining / 9, InstanceLayouts.ReadAward));
            case 11: return new CoopRewardStatusEvent(reader.U8(), reader.U8(), reader.U8(), reader.U8(), reader.U8());
            case 13: return new CoopPhaseEvent();
            case 15: return new CoopFightCountEvent(reader.U8());
            case 17:
                var count = reader.U16();
                if (count > 1000) throw new ProtocolException("S186-17 room count exceeds 1000");
                return new CoopRoomListEvent(ReadRows(reader, count, InstanceLayouts.ReadCoopRoom));
            case 20: return new CoopStandbyEvent(reader.U8() != 0);
            default: return null;
        }
    }

    private static CoopInstanceEvent ReadCoopResult(PacketReader reader)
    {
        var code = reader.U8();
        if (code is not (17 or 18))
            return new CoopResultEvent(code, code is 16 or 19 ? reader.U32() : null);
        var count = ReadCount(reader, 8, "S186-2 match count");
        if (count == 0) throw new ProtocolException("S186-2 match count must be positive");
        var roster = ImmutableArray.CreateBuilder<uint>(code == 17 ? count : count * 2);
        for (var i = 0; i < (code == 17 ? count : count * 2); i++)
        {
            roster.Add(reader.U32());
            if (code == 17)
            {
                reader.Take(4); // level, element, sex, head
                reader.Take(8); // palettes 1 and 5
                reader.Unicode8(); // Validate without retaining NPC metadata or names.
            }
        }
        return new CoopMatchEvent(code, count, roster.MoveToImmutable());
    }

    private static CoopMembersEvent ReadCoopMembers(PacketReader reader)
    {
        var created = reader.U8() != 0; var joined = reader.U8() != 0;
        var roomId = reader.U16(); var standby = reader.U8() != 0;
        var kind = reader.U8(); var npcId = reader.U8();
        var capacity = ReadCount(reader, 8, "S186-3 member capacity");
        uint? hostId = null;
        var members = ImmutableArray.CreateBuilder<CoopInstanceMember>(capacity);
        for (var slot = 0; slot < capacity; slot++)
        {
            var member = InstanceLayouts.ReadCoopMember(reader);
            if (slot == 0) hostId = member.RoleId;
            if (member.RoleId != 0) members.Add(member);
        }
        return new(roomId, hostId, created, joined, standby, kind, npcId, capacity, members.ToImmutable());
    }

    private static byte ReadCount(PacketReader reader, int maximum, string name)
    {
        var count = reader.U8();
        if (count > maximum) throw new ProtocolException($"{name} exceeds {maximum}");
        return count;
    }

    private static ImmutableArray<T> ReadRows<T>(PacketReader reader, int count, Func<PacketReader, T> read)
    {
        var rows = ImmutableArray.CreateBuilder<T>(count);
        for (var i = 0; i < count; i++) rows.Add(read(reader));
        return rows.MoveToImmutable();
    }
}
