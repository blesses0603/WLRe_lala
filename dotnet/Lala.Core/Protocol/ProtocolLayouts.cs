using System.Collections.Immutable;

namespace Lala.Core.Protocol;

public sealed record EquipmentAppearance(ushort ItemId, uint DesignId);
public sealed record RoleBonuses(uint CoreHp, uint CoreSp, uint EmblemHp, uint EmblemSp,
    ushort RideHp, int StarHp, int StarSp, uint RelationHp, uint RelationSp);
public sealed record RoleSnapshot(byte Index, string Name, byte Level, byte Element,
    long MaxHp, uint Hp, long MaxSp, uint Sp, long Exp, uint Gold, byte Sex, byte Head,
    uint Palette1, uint Palette5, byte Degree, byte Job, ushort Scene, double DeleteTime,
    bool Locked, RoleBonuses Bonuses);
public sealed record WorldPlayer(uint RoleId, byte Sex, ushort Scene, ushort X, ushort Y,
    byte Face, byte Head, byte Body, uint Palette1, uint Palette5, byte HeaderFrame,
    bool SecondJobEffect, ImmutableArray<EquipmentAppearance> Equips, string Name, ushort TitleId);
public sealed record BattleUnit(byte WarStyle, byte HumanKind, uint Pid, ushort NpcIndex,
    uint MasterId, byte Col, byte Row, uint MaxHp, ushort MaxSp, uint Hp, ushort Sp,
    byte Level, byte Element, byte Degree, byte Job, ushort PetModelId, ushort ChangeBodyId,
    byte Sex, byte Head, uint Palette1, uint Palette5, string Name,
    ImmutableArray<EquipmentAppearance> Equips);

/// <summary>Offline 1262 layouts from wlre/network/layouts.py. Single-structure readers leave
/// subsequent bytes to their caller; role lists consume the entire remaining reader.
/// Malformed input throws and the caller must discard that reader and any partial result.</summary>
public static class ProtocolLayouts
{
    public static ImmutableArray<RoleSnapshot> ReadRoleList(PacketReader reader)
    {
        var roles = ImmutableArray.CreateBuilder<RoleSnapshot>();
        while (reader.Remaining != 0)
        {
            var index = reader.U8(); var name = reader.Unicode8();
            var level = reader.U8(); var element = reader.U8();
            var maxHp = reader.U32(); var hp = reader.U32();
            var maxSp = reader.U32(); var sp = reader.U32();
            var exp = reader.I64(); var gold = reader.U32();
            var sex = reader.U8(); var head = reader.U8();
            var palette1 = reader.U32(); var palette5 = reader.U32();
            var degree = reader.U8(); var job = reader.U8(); var scene = reader.U16();
            // Python reads an IEEE 754 little-endian double, not an integer timestamp.
            var deleteTime = BitConverter.Int64BitsToDouble(reader.I64());
            var locked = reader.U8() != 0;
            if (index is not (1 or 2)) throw new ProtocolException("invalid role index");
            var bonuses = new RoleBonuses(reader.U32(), reader.U32(), reader.U32(), reader.U32(),
                reader.U16(), reader.I32(), reader.I32(), reader.U32(), reader.U32());
            // Python integers do not wrap: signed star bonuses can make totals negative,
            // and the sum of unsigned bonuses can exceed UInt32.MaxValue.
            long totalHp = (long)maxHp + bonuses.CoreHp + bonuses.EmblemHp + bonuses.RideHp + bonuses.StarHp + bonuses.RelationHp;
            long totalSp = (long)maxSp + bonuses.CoreSp + bonuses.EmblemSp + bonuses.StarSp + bonuses.RelationSp;
            roles.Add(new(index, name, level, element, totalHp, hp, totalSp, sp, exp, gold,
                sex, head, palette1, palette5, degree, job, scene, deleteTime, locked, bonuses));
        }
        return roles.ToImmutable();
    }

    public static WorldPlayer ReadWorldPlayer(PacketReader reader)
    {
        var roleId = reader.U32(); var sex = reader.U8(); var scene = reader.U16();
        var x = reader.U16(); var y = reader.U16();
        var face = reader.U8(); var head = reader.U8(); var body = reader.U8();
        var palette1 = reader.U32(); var palette5 = reader.U32();
        var headerFrame = reader.U8(); var secondJobEffect = reader.U8() != 0;
        var equips = ReadEquipment(reader, reader.U8());
        var name = reader.Unicode8();
        DiscardNamecard(reader);
        return new(roleId, sex, scene, x, y, face, head, body, palette1, palette5,
            headerFrame, secondJobEffect, equips, name, reader.U16());
    }

    public static BattleUnit ReadBattleUnit(PacketReader reader)
    {
        var warStyle = reader.U8(); var humanKind = reader.U8(); var pid = reader.U32();
        var npcIndex = reader.U16(); var masterId = reader.U32();
        var col = reader.U8(); var row = reader.U8();
        var maxHp = reader.U32(); var maxSp = reader.U16(); var hp = reader.U32(); var sp = reader.U16();
        var level = reader.U8(); var element = reader.U8(); var degree = reader.U8(); var job = reader.U8();
        var petModelId = reader.U16(); var changeBodyId = reader.U16();
        var sex = reader.U8(); var head = reader.U8(); var palette1 = reader.U32(); var palette5 = reader.U32();
        var name = reader.Unicode8();
        if (col is < 1 or > 4 || row is < 1 or > 4) throw new ProtocolException("invalid battle slot");
        return new(warStyle, humanKind, pid, npcIndex, masterId, col, row, maxHp, maxSp, hp, sp,
            level, element, degree, job, petModelId, changeBodyId, sex, head, palette1, palette5,
            name, ReadEquipment(reader, 9));
    }

    private static ImmutableArray<EquipmentAppearance> ReadEquipment(PacketReader reader, int count)
    {
        var equips = ImmutableArray.CreateBuilder<EquipmentAppearance>(count);
        for (var i = 0; i < count; i++) equips.Add(new(reader.U16(), reader.U32()));
        return equips.MoveToImmutable();
    }

    // Consume and validate the signature without retaining private namecard data in events.
    internal static void DiscardNamecard(PacketReader reader)
    {
        reader.Take(8);
        reader.Unicode8();
    }
}

public abstract record LayoutEvent(byte Main, byte Sub)
{
    public abstract string Type { get; }
}
public sealed record RoleListAvailableEvent(ImmutableArray<RoleSnapshot> Roles) : LayoutEvent(63, 1)
{
    public override string Type => "role_list_available";
    public bool Parsed => true;
}
public sealed record WorldPlayerEvent(WorldPlayer Player) : LayoutEvent(3, 1)
{
    public override string Type => "world_player";
}
public sealed record BattleStartEvent(byte Stage, byte FightNumber, ImmutableArray<BattleUnit> Units) : LayoutEvent(11, 250)
{
    public override string Type => "battle_start";
}
public sealed record BattleUnitsEvent(ImmutableArray<BattleUnit> Units) : LayoutEvent(11, 5)
{
    public override string Type => "battle_units";
}

/// <summary>Complete-packet boundary for the four migrated layout events. Unknown packets return
/// null; recognized malformed packets throw. No partial event or opaque payload is returned.</summary>
public static class LayoutProtocol
{
    public static LayoutEvent? Decode(Packet packet)
    {
        var reader = new PacketReader(packet.Payload.Span);
        LayoutEvent? result = (packet.Main, packet.Sub) switch
        {
            (63, 1) => new RoleListAvailableEvent(ProtocolLayouts.ReadRoleList(reader)),
            (3, 1) => new WorldPlayerEvent(ProtocolLayouts.ReadWorldPlayer(reader)),
            (11, 250) => new BattleStartEvent(reader.U8(), reader.U8(), ReadUnits(reader)),
            (11, 5) => new BattleUnitsEvent(ReadUnits(reader)),
            _ => null
        };
        if (result is not null) reader.End();
        return result;
    }

    private static ImmutableArray<BattleUnit> ReadUnits(PacketReader reader)
    {
        var count = reader.U8();
        var units = ImmutableArray.CreateBuilder<BattleUnit>(count);
        for (var i = 0; i < count; i++) units.Add(ProtocolLayouts.ReadBattleUnit(reader));
        return units.MoveToImmutable();
    }
}
