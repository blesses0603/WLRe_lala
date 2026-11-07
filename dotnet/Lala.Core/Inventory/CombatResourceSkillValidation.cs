using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;

namespace Lala.Core.Inventory;

public sealed record CombatResourceSkillRow(uint Id, string Name, long Level, string Category,
    long? Sp, string? Source, ImmutableArray<string> Reasons);

public static partial class CombatResourceKnowledge
{
    private static readonly ImmutableHashSet<long> SilenceBlockedFightWays =
        ImmutableHashSet.Create<long>(3,4,5,6,7,8,9,14,15,16,18,19,21,23,24,25);

    /// <summary>Offline diagnostic reasons only. Uses the existing read-only Allocate helper
    /// for item sufficiency; it never acquires a hold, produces a command, or grants authority.</summary>
    public static ImmutableArray<string> SkillReasons(PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions,
        uint? localRoleId, CombatResourceActor actor, uint skillId, CombatResourceCatalog catalog,
        BagReceiveSnapshot inventory, InventoryPlanningContext inventoryContext)
    {
        ArgumentNullException.ThrowIfNull(inventory); ArgumentNullException.ThrowIfNull(inventoryContext);
        var records = Learned(player,companions,localRoleId,actor,catalog);
        var data = catalog.Skills.GetValueOrDefault(skillId);
        if (data is null) return ["技能不在目前版本資料表"];
        if (!records.Any(value => value.Id == skillId)) return ["此單位尚無已學／裝備授予證據"];
        if (data.Required("Kind") == 9 || data.Required("KindSort") == 4) return ["生活／被動技能，不能主動施放"];
        if (data.Required("TargetKind") == 4) return ["無可指定的戰鬥目標"];
        var reasons = ImmutableArray.CreateBuilder<string>();
        var hp = actor.Hp ?? 0;
        if (actor.Exited || hp <= 0) reasons.Add("操作單位已陣亡／離場");
        var reduceSp = data.Required("ReduceSP");
        if ((actor.Sp ?? -1) < reduceSp) reasons.Add("SP不足／尚無SP資料");
        var reduceHp = data.Required("ReduceHP");
        if (reduceHp != 0 && reduceSp == 0 && data.Required("Kind") != 8 && HpCostReachesCurrent(hp,reduceHp))
            reasons.Add("HP不足以支付技能消耗");
        var group = WeaponGroup(actor,catalog);
        if (group is null || data.Fields.GetValueOrDefault("WeaponKind" + group.Value.ToString(CultureInfo.InvariantCulture)) != 1)
            reasons.Add("目前武器不適用");
        var character = catalog.Characters.FirstOrDefault(value => value.Skill == skillId);
        if (skillId == 15003 || character is not null && (actor.Sex != character.Sex || actor.Head != character.Head ||
            actor.Equips.Length < 2 || actor.Equips[1].ItemId != character.Body)) reasons.Add("新手特技外觀／初始衣服條件不符");
        if (skillId == 11172 && (actor.Equips.Length < 3 || actor.Equips[2].ItemId is not (20044 or 20045 or 20048 or 20050)))
            reasons.Add("艾琳專屬武器不符");
        if (actor.Pid == localRoleId && data.Required("CostItemID") is var itemId && itemId != 0 &&
            data.Required("CostItemCount") is var count && count != 0)
        {
            var candidate = InventoryPlanning.Allocate(inventory,itemId,count,inventoryContext);
            if (candidate.Error is { } error) reasons.Add(error.Message);
        }
        ArgumentNullException.ThrowIfNull(actor.Statuses);
        if (SilenceBlockedFightWays.Contains(data.Required("FightWay")) && actor.Statuses.GetValueOrDefault("silenced"))
            reasons.Add("目前狀態封鎖輔助技能");
        if (actor.Statuses.GetValueOrDefault("taunt") && (data.Required("TargetKind") != 0 || data.Required("RangeKind1") != 1))
            reasons.Add("挑戰狀態限制目標／範圍");
        return reasons.ToImmutable();
    }

    /// <summary>Source-equivalent sorted display rows with diagnostic reasons, not an action
    /// menu or selectable command. Missing SP remains unknown, even though sorting uses 99999.</summary>
    public static ImmutableArray<CombatResourceSkillRow> SkillRows(PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions,
        uint? localRoleId, CombatResourceActor actor, CombatResourceCatalog catalog,
        BagReceiveSnapshot inventory, InventoryPlanningContext inventoryContext)
    {
        var result = ImmutableArray.CreateBuilder<CombatResourceSkillRow>();
        foreach (var record in Learned(player,companions,localRoleId,actor,catalog))
        {
            var data = catalog.Skills.GetValueOrDefault(record.Id);
            var category = data?.Fields.GetValueOrDefault("KindSort") switch { 1 => "物理", 2 => "魔法", 3 => "輔助", 4 => "被動", _ => "其他" };
            long? sp = null;
            if (data is not null && data.Fields.TryGetValue("ReduceSP",out var value)) sp = value;
            result.Add(new(record.Id,data?.Name ?? "技能" + record.Id.ToString(CultureInfo.InvariantCulture), record.Level,category,sp,record.Source,
                SkillReasons(player,companions,localRoleId,actor,record.Id,catalog,inventory,inventoryContext)));
        }
        return [.. result.OrderBy(value => value.Category,StringComparer.Ordinal).ThenBy(value => value.Sp ?? 99999).ThenBy(value => value.Id)];
    }

    private static bool HpCostReachesCurrent(long hp, long percent)
    {
        // Python multiplies integers without overflow, then correctly rounds true division
        // to binary64 before math.ceil. Converting the product to double first can double-
        // round large Int64 observations; integer ceiling would also erase Python behavior.
        var product = new BigInteger(hp) * percent;
        if (product.IsZero) return 0 >= hp;
        var number = BigInteger.Abs(product);
        var exponent = (int)number.GetBitLength() - 7; // 100 has seven bits.
        if (exponent >= 0 ? number < (new BigInteger(100) << exponent) : (number << -exponent) < 100) exponent--;
        var shift = 52 - exponent;
        var numerator = shift >= 0 ? number << shift : number;
        var denominator = shift >= 0 ? new BigInteger(100) : new BigInteger(100) << -shift;
        var mantissa = BigInteger.DivRem(numerator,denominator,out var remainder);
        var midpoint = remainder * 2;
        if (midpoint > denominator || midpoint == denominator && !mantissa.IsEven) mantissa++;
        var quotient = Math.ScaleB((double)mantissa,exponent - 52) * product.Sign;
        return new BigInteger(Math.Ceiling(quotient)) >= hp;
    }
}
