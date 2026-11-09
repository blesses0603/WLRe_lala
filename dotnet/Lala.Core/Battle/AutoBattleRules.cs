using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;

namespace Lala.Core.Battle;

public enum AutoBattleActionKind { Skill = 1, Item = 2 }
public enum AutoBattleTargetPolicy { LowestHp = 1, Element = 2, HighestHp = 3 }
public enum AutoBattleNotice { SameSide = 1, Player = 2, Partner = 3 }
public enum AutoBattleComparison { GreaterThan = 1, LessThan = 2 }
public enum AutoBattleReason { DeadAlly, EnemyHp, LowHp, LowSp, Round, Repeat, Order, Fallback }

/// <summary>A nonnegative integer or finite binary64 source threshold. Integer evidence
/// is never rounded through double. The default value is integer zero.</summary>
public readonly record struct AutoBattleThreshold
{
    public long? Integer { get; }
    public double? FloatingPoint { get; }
    public AutoBattleThreshold(long value)
    {
        if (value < 0) throw new ArgumentOutOfRangeException(nameof(value));
        Integer = value; FloatingPoint = null;
    }
    public AutoBattleThreshold(double value)
    {
        if (!double.IsFinite(value) || value < 0) throw new ArgumentOutOfRangeException(nameof(value));
        Integer = null; FloatingPoint = value;
    }
    public static implicit operator AutoBattleThreshold(long value) => new(value);
    public static implicit operator AutoBattleThreshold(double value) => new(value);
    internal int Compare(long observation)
    {
        if (FloatingPoint is not { } value) return observation.CompareTo(Integer ?? 0);
        // Python compares integer operands to the exact binary64 value, not to a
        // separately rounded integer. BigInteger also handles finite values > Int64.
        var comparison = new BigInteger(observation).CompareTo(new BigInteger(value));
        return comparison == 0 && value != Math.Truncate(value) ? -1 : comparison;
    }
}

/// <summary>Complete typed action, not a permissive JSON settings dictionary. Thresholds
/// are absolute HP/SP values; Notice and Comparison apply only to their matching rules.</summary>
public sealed record AutoBattleAction
{
    public int Id { get; init; }
    public AutoBattleActionKind Kind { get; init; } = AutoBattleActionKind.Skill;
    public AutoBattleTargetPolicy Target { get; init; } = AutoBattleTargetPolicy.LowestHp;
    public AutoBattleNotice Notice { get; init; } = AutoBattleNotice.SameSide;
    public AutoBattleComparison Comparison { get; init; } = AutoBattleComparison.GreaterThan;
    public AutoBattleThreshold Value { get; init; }
    public bool UseNextSkill { get; init; }
}

/// <summary>Immutable per-actor rules. Defaults match the source player profile; partner
/// defaults differ only in the two notice selectors. No persisted settings or AI lifecycle.</summary>
public sealed record AutoBattleProfile
{
    public bool DeadEnabled { get; init; }
    public AutoBattleAction Dead { get; init; } = new() { Id = 60021 };
    public bool EnemyHpEnabled { get; init; }
    public AutoBattleAction EnemyHp { get; init; } = new() { Id = 10008, Comparison = AutoBattleComparison.LessThan, Value = 100L };
    public bool LowHpEnabled { get; init; } = true;
    public AutoBattleAction LowHp { get; init; } = new() { Id = -2, Kind = AutoBattleActionKind.Item, Notice = AutoBattleNotice.Player, Value = 100L };
    public bool LowSpEnabled { get; init; }
    public AutoBattleAction LowSp { get; init; } = new() { Id = 60021, Notice = AutoBattleNotice.Player, Value = 20L };
    public bool RoundEnabled { get; init; }
    public ImmutableArray<AutoBattleAction> RoundActions { get; init; } = [new(),new(),new()];
    public bool RepeatEnabled { get; init; }
    public ImmutableArray<AutoBattleAction> RepeatActions { get; init; } = [new(),new(),new(),new(),new()];
    public bool OrderEnabled { get; init; } = true;
    public ImmutableArray<AutoBattleAction> OrderActions { get; init; } = [new() { Id = 10001 },new()];
    public static AutoBattleProfile PlayerDefaults { get; } = new();
    public static AutoBattleProfile PartnerDefaults { get; } = new()
    {
        LowHp = PlayerDefaults.LowHp with { Notice = AutoBattleNotice.Partner },
        LowSp = PlayerDefaults.LowSp with { Notice = AutoBattleNotice.Partner }
    };
}

public sealed record AutoBattleChoice(BattleCommandIntent? Intent, AutoBattleReason? Reason, InventoryPlanningError? Error)
{
    public bool Success => Intent is not null && Error is null;
    public string? ReasonKey => Reason switch
    {
        AutoBattleReason.DeadAlly => "deadAction", AutoBattleReason.EnemyHp => "enemyHpAction",
        AutoBattleReason.LowHp => "lowHpAction", AutoBattleReason.LowSp => "lowSpAction",
        AutoBattleReason.Round => "roundAction", AutoBattleReason.Repeat => "repeatAction",
        AutoBattleReason.Order => "orderAction", AutoBattleReason.Fallback => "fallback", _ => null
    };
    public string? ReasonText => Reason switch
    {
        AutoBattleReason.DeadAlly => "同方陣亡", AutoBattleReason.EnemyHp => "敵方HP條件",
        AutoBattleReason.LowHp => "自方HP條件", AutoBattleReason.LowSp => "自方SP條件",
        AutoBattleReason.Round => "指定回合", AutoBattleReason.Repeat => "循環行動",
        AutoBattleReason.Order => "順序行動", AutoBattleReason.Fallback => "最後普攻", _ => null
    };
}

/// <summary>Bounded typed profile validation only. This does not import, save, or activate
/// settings. An empty catalog retains source permissiveness; it is not proof of validity.</summary>
public static class AutoBattleProfiles
{
    public static AutoBattleProfile Normalize(AutoBattleProfile profile, CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(profile); ArgumentNullException.ThrowIfNull(catalog);
        ArgumentNullException.ThrowIfNull(catalog.Skills); ArgumentNullException.ThrowIfNull(catalog.Items);
        AutoBattleAction Check(AutoBattleAction action)
        {
            ArgumentNullException.ThrowIfNull(action);
            if (action.Id is < -3 or > 65535) throw new ArgumentException("Action ID must be between -3 and 65535.",nameof(profile));
            var normalized = action.Id is -2 or -3 ? action with { Kind = AutoBattleActionKind.Item } : action;
            if (!Enum.IsDefined(normalized.Kind) || !Enum.IsDefined(action.Target) || !Enum.IsDefined(action.Notice) || !Enum.IsDefined(action.Comparison))
                throw new ArgumentException("Unknown typed rule selector.",nameof(profile));
            if (normalized.Kind == AutoBattleActionKind.Item)
            {
                if (normalized.UseNextSkill) throw new ArgumentException("Items have no next skill.",nameof(profile));
                if (!catalog.Items.IsEmpty && action.Id is not (0 or -2 or -3) &&
                    (action.Id < 0 || catalog.Items.GetValueOrDefault((ushort)action.Id)?.Kind is not (23 or 32)))
                    throw new ArgumentException("Item action requires observed food or cooking data.",nameof(profile));
            }
            else if (!catalog.Skills.IsEmpty && action.Id is not (0 or -1 or 10001 or 60021 or 60041 or 10008) && !catalog.Skills.ContainsKey((uint)action.Id))
                throw new ArgumentException("Skill action is absent from the supplied catalog.",nameof(profile));
            return normalized;
        }
        ImmutableArray<AutoBattleAction> Rows(ImmutableArray<AutoBattleAction> rows,int count)
        {
            if (rows.IsDefault || rows.Length > count) throw new ArgumentException("Initialized rule arrays within the source limits are required.",nameof(profile));
            var result = rows.Select(Check).ToImmutableArray();
            while (result.Length < count) result = result.Add(new());
            return result;
        }
        return profile with { Dead = Check(profile.Dead), EnemyHp = Check(profile.EnemyHp), LowHp = Check(profile.LowHp), LowSp = Check(profile.LowSp),
            RoundActions = Rows(profile.RoundActions,3), RepeatActions = Rows(profile.RepeatActions,5), OrderActions = Rows(profile.OrderActions,2) };
    }
}
