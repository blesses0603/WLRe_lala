using System.Collections.Frozen;
using System.Globalization;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

public sealed record NormalAttackNpc(int Kind, int BodyType, int NormalAttackKind);

/// <summary>Immutable rules input. The resource layer must validate catalog provenance/version first.</summary>
public sealed class NormalAttackCatalogSnapshot
{
    public IReadOnlyDictionary<int, int> ItemKinds { get; }
    public IReadOnlyDictionary<uint, NormalAttackNpc> Npcs { get; }
    public NormalAttackCatalogSnapshot(IEnumerable<KeyValuePair<int, int>> itemKinds,
        IEnumerable<KeyValuePair<uint, NormalAttackNpc>> npcs)
    {
        ItemKinds = itemKinds.ToFrozenDictionary();
        Npcs = npcs.ToFrozenDictionary();
    }
}

public sealed class CombatUnitSnapshot
{
    public uint Pid { get; }
    public uint? MasterId { get; }
    public uint ChangeBodyId { get; }
    public IReadOnlyList<int> EquipmentItemIds { get; }
    public CombatUnitSnapshot(uint pid, uint? masterId, uint changeBodyId, IEnumerable<int> equipmentItemIds)
    {
        Pid = pid; MasterId = masterId; ChangeBodyId = changeBodyId;
        EquipmentItemIds = Array.AsReadOnly(equipmentItemIds.ToArray());
    }
}

public sealed record ReportedEffect(int Kind, long Value, int Sign, string? Attribute = null);

/// <summary>Pure port of battle/combat.py; does not send actions or derive absolute HP from effects.</summary>
public static class CombatRules
{
    private static readonly FrozenSet<int> BrokenWeapons = new[]
    {
        10062, 11098, 12069, 13064, 15051, 14063, 17066, 18062, 19055, 20039,
        21120, 22125, 23105, 24090, 25044
    }.ToFrozenSet();

    public static int NormalSkill(CombatUnitSnapshot unit, uint playerId, NormalAttackCatalogSnapshot catalog)
    {
        if (unit.EquipmentItemIds.Count < 3)
            throw new ProtocolException("缺少手部裝備資料，尚無法自動判斷普攻");
        int item = unit.EquipmentItemIds[2];
        int weapon;
        if (item == 0 || BrokenWeapons.Contains(item)) weapon = 0;
        else if (!catalog.ItemKinds.TryGetValue(item, out weapon))
            throw new ProtocolException($"未知武器 {item}，尚無法自動判斷普攻");
        NormalAttackNpc? npc = null;
        int body;
        if (unit.Pid == playerId) body = unit.ChangeBodyId != 0 ? 1 : 0;
        else if (unit.MasterId == playerId)
        {
            if (!catalog.Npcs.TryGetValue(unit.Pid, out npc) || npc.Kind is not (0 or 1))
                throw new ProtocolException("夥伴類型尚無法判定，尚無法自動判斷普攻");
            body = item == 0 && npc.Kind == 0 ? npc.BodyType : 1;
        }
        else throw new ProtocolException("操作單位不屬於本機角色");
        if (npc?.Kind == 1)
        {
            bool magic = item != 0 && weapon is 5 or 10;
            return npc.NormalAttackKind switch
            {
                0 => magic ? 10030 : 10023,
                1 or 2 => magic ? 10029 : 10010,
                _ => throw new ProtocolException("未知怪物普攻類型，尚無法自動判斷普攻")
            };
        }
        if (weapon == 0) return 10001;
        if (weapon is 1 or 2 or 6 or 8) return 10002;
        if (weapon is 7 or 9) return 10003;
        if (weapon is 5 or 10) return 10004;
        if (weapon == 3) return 10005;
        if (body is not (0 or 1)) throw new ProtocolException("未知身體類型，尚無法自動判斷普攻");
        if (weapon == 4) return body == 0 ? 10019 : 10020;
        if (weapon == 11)
            return item is 20037 or 20038 or 20040
                ? (body == 0 ? 10026 : 10027)
                : (body == 0 ? 10007 : 10018);
        throw new ProtocolException("此裝備無已確認的普攻");
    }

    public static string? EffectText(ReportedEffect effect)
    {
        if (effect.Kind == 0 && effect.Value == 0) return null;
        string attribute = effect.Kind switch
        {
            25 => "HP", 26 => "SP",
            _ => !string.IsNullOrEmpty(effect.Attribute) ? effect.Attribute
                : "屬性" + effect.Kind.ToString(CultureInfo.InvariantCulture)
        };
        string value = effect.Value.ToString(CultureInfo.InvariantCulture);
        if (effect.Kind is 25 or 26)
        {
            string? description = effect.Sign switch
            {
                0 => "回復", 1 => "傷害", 2 => "爆擊傷害", 3 => "無視護盾傷害", _ => null
            };
            if (description is not null) return $"{attribute} {description} {value}";
        }
        return $"{attribute}={value}（sign {effect.Sign.ToString(CultureInfo.InvariantCulture)}）";
    }
}
