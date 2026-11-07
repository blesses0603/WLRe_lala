using System.Collections.Immutable;

namespace Lala.Core.Protocol;

public sealed record ItemPlugin(byte Kind, ushort Value);
public sealed record ItemSave(byte? Index, ushort ItemId, byte Count, byte Damage,
    byte SerialVersion, uint Serial, uint? Durable, uint? Firing, ushort MagicSpar,
    double AvailableTime, double LimitedTime, byte BeatLevel, byte Differ, ushort Modeling,
    ushort? GetItemId, byte SaddleBeatLevel, ushort EnhanceLevel, uint DesignId,
    ImmutableArray<ItemPlugin> Plugins, bool Locked, byte StarSoulKind, byte StarSoulLevel,
    byte? ShowMessage);
public sealed record CompanionSkillSlot(byte Level, uint Exp);
public sealed record CompanionSnapshot(byte? Index, uint NpcId, long Exp, byte Level,
    int? Hp, ushort? Sp, ushort Str, ushort Con, ushort Int, ushort Wis, ushort Agi,
    byte? Die, byte Faith, byte CanGrow, ushort? SkillPotential, string? Name,
    ImmutableArray<CompanionSkillSlot> SkillSlots, ImmutableArray<ItemSave> Equips,
    byte? SublimeCount, byte SportExp, byte Degree, byte Potential, ushort Modeling,
    byte? PartyIndex, ushort UseUpStats);
public sealed record LearnedSkill(ushort Key, byte Level, uint Exp);
public sealed record PlayerCombatData(byte Element, uint Hp, ushort Sp, ushort Str,
    ushort Con, ushort Int, ushort Wis, ushort Agi, byte Level, uint Exp,
    ushort SkillPotential, ushort AttributePotential, uint MaxHp, ushort MaxSp,
    uint EquipAtk, uint EquipDef, uint EquipMatk, uint EquipSpeedAtk, uint EquipMaxHp,
    uint EquipMaxSp, ImmutableArray<LearnedSkill> Skills, ushort SpringHp,
    ushort SpringSp, byte Degree, byte Job, byte Potential);

/// <summary>Offline 1262 item, companion and player layouts from wlre/network/live_data.py.
/// A single-structure reader leaves subsequent bytes to its caller. Nullable fields represent
/// fields absent from an equipment or simple-companion variant; zero remains a real value.
/// On malformed input discard the reader and any partial result.</summary>
public static class LiveDataLayouts
{
    public static ItemSave ReadItem(PacketReader reader, byte? index, bool equip = false)
    {
        var itemId = reader.U16(); var count = equip ? (byte)1 : reader.U8();
        var damage = reader.U8(); var serialVersion = reader.U8(); var serial = reader.U32();
        uint? durable = equip ? null : reader.U32();
        uint? firing = equip ? null : reader.U32();
        var magicSpar = reader.U16();
        var availableTime = BitConverter.Int64BitsToDouble(reader.I64());
        var limitedTime = BitConverter.Int64BitsToDouble(reader.I64());
        if (!double.IsFinite(availableTime) || !double.IsFinite(limitedTime))
            throw new ProtocolException("invalid item time");
        var beatLevel = reader.U8(); var differ = reader.U8(); var modeling = reader.U16();
        ushort? getItemId = equip ? null : reader.U16();
        var saddleBeatLevel = reader.U8(); var enhanceLevel = reader.U16(); var designId = reader.U32();
        var plugins = ImmutableArray.CreateBuilder<ItemPlugin>(4);
        for (var i = 0; i < 4; i++) plugins.Add(new(reader.U8(), reader.U16()));
        var locked = (reader.U8() & 1) != 0;
        var starSoulKind = reader.U8(); var starSoulLevel = reader.U8();
        byte? showMessage = equip ? null : reader.U8();
        return new(index, itemId, count, damage, serialVersion, serial, durable, firing, magicSpar,
            availableTime, limitedTime, beatLevel, differ, modeling, getItemId, saddleBeatLevel,
            enhanceLevel, designId, plugins.MoveToImmutable(), locked, starSoulKind, starSoulLevel,
            showMessage);
    }

    public static CompanionSnapshot ReadCompanion(PacketReader reader, byte? index, uint npcId, bool simple = false)
    {
        long exp; byte level; ushort str, con, intelligence, wis, agi; byte faith, canGrow;
        int? hp = null; ushort? sp = null; byte? die = null; ushort? skillPotential = null; string? name = null;
        if (simple)
        {
            canGrow = reader.U8(); str = reader.U16(); con = reader.U16(); intelligence = reader.U16();
            wis = reader.U16(); agi = reader.U16(); level = reader.U8(); exp = reader.U32();
            faith = 0; // Its wire field follows the skill slots in this variant.
        }
        else
        {
            exp = reader.I32(); level = reader.U8(); hp = reader.I32(); sp = reader.U16();
            intelligence = reader.U16(); str = reader.U16(); con = reader.U16(); agi = reader.U16(); wis = reader.U16();
            die = reader.U8(); faith = reader.U8(); canGrow = reader.U8();
            skillPotential = reader.U16(); name = reader.Unicode8();
        }
        var skills = ImmutableArray.CreateBuilder<CompanionSkillSlot>(5);
        for (var i = 0; i < 5; i++) skills.Add(new(reader.U8(), reader.U32()));
        if (simple) faith = reader.U8();
        var equips = ImmutableArray.CreateBuilder<ItemSave>(9);
        for (byte i = 1; i <= 9; i++) equips.Add(ReadItem(reader, i, true));
        byte? sublimeCount = simple ? null : reader.U8();
        var sportExp = reader.U8(); var degree = reader.U8(); var potential = reader.U8(); var modeling = reader.U16();
        byte? partyIndex = simple ? null : reader.U8();
        return new(index, npcId, exp, level, hp, sp, str, con, intelligence, wis, agi, die, faith,
            canGrow, skillPotential, name, skills.MoveToImmutable(), equips.MoveToImmutable(),
            sublimeCount, sportExp, degree, potential, modeling, partyIndex, reader.U16());
    }

    public static PlayerCombatData ReadPlayerInfo(PacketReader reader)
    {
        var element = reader.U8(); var hp = reader.U32(); var sp = reader.U16();
        var str = reader.U16(); var con = reader.U16(); var intelligence = reader.U16(); var wis = reader.U16(); var agi = reader.U16();
        var level = reader.U8(); var exp = reader.U32();
        var skillPotential = reader.U16(); var attributePotential = reader.U16();
        var maxHp = reader.U32(); var maxSp = reader.U16();
        var equipAtk = reader.U32(); var equipDef = reader.U32(); var equipMatk = reader.U32();
        var equipSpeedAtk = reader.U32(); var equipMaxHp = reader.U32(); var equipMaxSp = reader.U32();
        reader.Take(12); // Organization serial and join time are not returned by Python.
        var count = reader.U16(); var skills = ImmutableArray.CreateBuilder<LearnedSkill>(count);
        for (var i = 0; i < count; i++) skills.Add(new(reader.U16(), reader.U8(), reader.U32()));
        return new(element, hp, sp, str, con, intelligence, wis, agi, level, exp, skillPotential,
            attributePotential, maxHp, maxSp, equipAtk, equipDef, equipMatk, equipSpeedAtk,
            equipMaxHp, equipMaxSp, skills.MoveToImmutable(), reader.U16(), reader.U16(),
            reader.U8(), reader.U8(), reader.U8());
    }
}

public abstract record LiveDataEvent(byte Main, byte Sub)
{
    public abstract string Type { get; }
}
public sealed record StarInfoEvent(byte Level, byte StarCore, long Exp) : LiveDataEvent(5, 47)
{
    public override string Type => "star_info";
}
public sealed record BagSnapshotEvent(byte Capacity, ImmutableArray<ItemSave> Items) : LiveDataEvent(23, 5)
{
    public override string Type => "bag_snapshot";
}
public sealed record BagAddEvent(ItemSave Item, ushort Source) : LiveDataEvent(23, 6)
{
    public override string Type => "bag_add";
}
public sealed record BagDeleteEvent(byte Index, byte Count, byte ShowMessage) : LiveDataEvent(23, 9)
{
    public override string Type => "bag_delete";
}
/// <summary>Result zero acknowledges purchase processing, not a balance or inventory sync.</summary>
public sealed record ShopPurchaseResultEvent(byte Result) : LiveDataEvent(27, 1)
{
    public override string Type => "shop_purchase_result";
}
public sealed record BagSellEvent(uint Gold, byte Index, byte Count) : LiveDataEvent(27, 6)
{
    public override string Type => "bag_sell";
}
public sealed record SaleNoticeEvent(byte Result) : LiveDataEvent(27, 8)
{
    public override string Type => "sale_notice";
}
public sealed record EquipDamageEvent(byte Sub, byte NpcIndex, byte Index, uint Damage, byte? Grid = null) : LiveDataEvent(23, Sub)
{
    public override string Type => "equip_damage";
}
public sealed record EquipBrokenEvent(byte Sub, byte NpcIndex, ushort ItemId, byte? Grid = null, byte? Index = null) : LiveDataEvent(23, Sub)
{
    public override string Type => "equip_broken";
}
public sealed record BagDamageEvent(byte Grid, byte Index, uint Damage, byte NpcIndex) : LiveDataEvent(23, 140)
{
    public override string Type => "bag_damage";
}
public sealed record BagBrokenEvent(byte Grid, byte Index, ushort ItemId, byte NpcIndex) : LiveDataEvent(23, 140)
{
    public override string Type => "bag_broken";
}
public sealed record UnknownDamageEvent(byte Grid, byte Index, byte NpcIndex, uint? Damage, ushort? ItemId) : LiveDataEvent(23, 140)
{
    public override string Type => "unknown_damage";
}
public sealed record ItemServerTimeEvent(byte Kind) : LiveDataEvent(23, 140)
{
    public override string Type => "item_server_time";
}
public sealed record PlayerEquipDataEvent(ImmutableArray<ItemSave> Equips) : LiveDataEvent(23, 11)
{
    public override string Type => "player_equip_data";
}
public sealed record ItemUseResultEvent(byte Result, byte? NpcIndex, ushort? ItemId) : LiveDataEvent(23, 15)
{
    public override string Type => "item_use_result";
}
public sealed record PlayerCombatDataEvent(PlayerCombatData Data) : LiveDataEvent(5, 3)
{
    public override string Type => "player_combat_data";
}
public sealed record CompanionSnapshotEvent(ImmutableArray<CompanionSnapshot> Companions) : LiveDataEvent(15, 8)
{
    public override string Type => "companion_snapshot";
}
public sealed record CompanionAddEvent(uint OwnerId, CompanionSnapshot Companion, byte ShowMessage) : LiveDataEvent(15, 1)
{
    public override string Type => "companion_add";
}
public sealed record CompanionDeleteEvent(uint OwnerId, byte Index, byte Kind) : LiveDataEvent(15, 2)
{
    public override string Type => "companion_delete";
}
public sealed record ActiveCompanionEvent(byte Sub, uint? NpcId) : LiveDataEvent(19, Sub)
{
    public override string Type => "active_companion";
}
public sealed record BattleEquipEvent(uint OwnerId, byte NpcIndex, byte EquipIndex, ushort ItemId, uint DesignId) : LiveDataEvent(11, 252)
{
    public override string Type => "battle_equip";
}

/// <summary>Complete-packet boundary for every decode_live branch, including protocol.py's
/// reader.end() check. Unknown main/sub pairs return null without parsing. Recognized malformed
/// packets throw; no partial event or opaque payload is returned. No network or state mutation.</summary>
public static class LiveDataProtocol
{
    public static LiveDataEvent? Decode(Packet packet)
    {
        var reader = new PacketReader(packet.Payload.Span);
        LiveDataEvent? result = (packet.Main, packet.Sub) switch
        {
            (5, 47) => ReadStarInfo(reader),
            (23, 5) => ReadBag(reader),
            (23, 6) => new BagAddEvent(LiveDataLayouts.ReadItem(reader, reader.U8()), reader.U16()),
            (23, 9) => new BagDeleteEvent(reader.U8(), reader.U8(), reader.U8()),
            (27, 1) => new ShopPurchaseResultEvent(reader.U8()),
            (27, 6) => new BagSellEvent(reader.U32(), reader.U8(), reader.U8()),
            (27, 8) => new SaleNoticeEvent(reader.U8()),
            (23, 27) => new EquipDamageEvent(packet.Sub, 0, reader.U8(), reader.U8()),
            (23, 28) => new EquipDamageEvent(packet.Sub, reader.U8(), reader.U8(), reader.U8()),
            (23, 35) => new EquipBrokenEvent(packet.Sub, reader.U8(), reader.U16()),
            (23, 140) => ReadDamage(reader),
            (23, 11) => ReadPlayerEquips(reader),
            (23, 15) => ReadItemUse(reader),
            (5, 3) => new PlayerCombatDataEvent(LiveDataLayouts.ReadPlayerInfo(reader)),
            (15, 8) => ReadCompanions(reader),
            (15, 1) => new CompanionAddEvent(reader.U32(), LiveDataLayouts.ReadCompanion(reader, null, reader.U32(), true), reader.U8()),
            (15, 2) => new CompanionDeleteEvent(reader.U32(), reader.U8(), reader.U8()),
            (19, 1) or (19, 4) => new ActiveCompanionEvent(packet.Sub, reader.U32()),
            (19, 2) => new ActiveCompanionEvent(packet.Sub, null),
            (11, 252) => new BattleEquipEvent(reader.U32(), reader.U8(), reader.U8(), reader.U16(), reader.U32()),
            _ => null
        };
        if (result is not null) reader.End();
        return result;
    }

    private static StarInfoEvent ReadStarInfo(PacketReader reader)
    {
        var result = new StarInfoEvent(reader.U8(), reader.U8(), reader.I64());
        reader.Take(30); // Exactly 30 awaken-star point bytes, not optional padding.
        return result;
    }
    private static BagSnapshotEvent ReadBag(PacketReader reader)
    {
        var capacity = reader.U8(); var items = ImmutableArray.CreateBuilder<ItemSave>();
        while (reader.Remaining != 0) items.Add(LiveDataLayouts.ReadItem(reader, reader.U8()));
        return new(capacity, items.ToImmutable());
    }
    private static PlayerEquipDataEvent ReadPlayerEquips(PacketReader reader)
    {
        var equips = ImmutableArray.CreateBuilder<ItemSave>();
        while (reader.Remaining != 0) equips.Add(LiveDataLayouts.ReadItem(reader, null, true));
        return new(equips.ToImmutable());
    }
    private static CompanionSnapshotEvent ReadCompanions(PacketReader reader)
    {
        var companions = ImmutableArray.CreateBuilder<CompanionSnapshot>();
        while (reader.Remaining != 0)
            companions.Add(LiveDataLayouts.ReadCompanion(reader, reader.U8(), reader.U16()));
        return new(companions.ToImmutable());
    }
    private static ItemUseResultEvent ReadItemUse(PacketReader reader)
    {
        var kind = reader.U8();
        return kind == 2 ? new(kind, reader.U8(), reader.U16()) : new(kind, null, null);
    }
    private static LiveDataEvent ReadDamage(PacketReader reader)
    {
        var kind = reader.U8();
        if (kind == 1)
        {
            var grid = reader.U8(); var index = reader.U8(); var damage = reader.U32(); var npc = reader.U8();
            return grid switch
            {
                1 => new BagDamageEvent(grid, index, damage, npc),
                2 or 3 => new EquipDamageEvent(140, grid == 2 ? (byte)0 : npc, index, damage, grid),
                _ => new UnknownDamageEvent(grid, index, npc, damage, null)
            };
        }
        if (kind == 2)
        {
            var grid = reader.U8(); var index = reader.U8(); var npc = reader.U8(); var item = reader.U16();
            return grid switch
            {
                1 => new BagBrokenEvent(grid, index, item, npc),
                2 or 3 => new EquipBrokenEvent(140, grid == 2 ? (byte)0 : npc, item, grid, index),
                _ => new UnknownDamageEvent(grid, index, npc, null, item)
            };
        }
        if (kind == 4)
        {
            var index = reader.U8(); var damage = reader.U8();
            return new EquipDamageEvent(140, reader.U8(), index, damage);
        }
        if (kind is 3 or 5)
        {
            reader.Take(kind == 3 ? 8 : 16);
            return new ItemServerTimeEvent(kind);
        }
        throw new ProtocolException("未知裝備損害度回覆");
    }
}
