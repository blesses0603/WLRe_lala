using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

/// <summary>Pure combat.py unit_label / attack_lines formatting over received snapshots.
/// Reports never establish absolute HP/SP, resolve commands, or mutate battle state.</summary>
public static class BattleDisplayRules
{
    private static readonly FrozenDictionary<ushort, string> SkillNames = new Dictionary<ushort, string>
    {
        [10001] = "空手普攻", [10002] = "刃技普攻", [10003] = "棒技普攻", [10004] = "魔杖／法器普攻",
        [10005] = "槍技普攻", [10007] = "銃普攻", [10018] = "人型夥伴銃普攻", [10019] = "弓普攻",
        [10020] = "人型夥伴弓普攻", [10026] = "火箭筒普攻", [10027] = "人型夥伴火箭筒普攻",
        [10010] = "怪物貼地普攻", [10023] = "怪物跳躍普攻", [10029] = "怪物貼地魔法普攻",
        [10030] = "怪物跳躍魔法普攻", [60021] = "防禦", [60041] = "逃跑", [10008] = "捕捉"
    }.ToFrozenDictionary();

    public static string UnitLabel(BattleEventSnapshot state, BattleSlot slot)
    {
        ArgumentNullException.ThrowIfNull(state);
        var name = state.UnitAt(slot)?.Layout.Name;
        // Source truthiness preserves whitespace and punctuation verbatim.
        return $"{(string.IsNullOrEmpty(name) ? "未知單位" : name)}({slot})";
    }

    public static ImmutableArray<string> AttackLines(AttackResultEvent report, BattleEventSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(report);
        ArgumentNullException.ThrowIfNull(state);
        var lines = ImmutableArray.CreateBuilder<string>();
        foreach (var action in report.Actions)
        {
            var actor = UnitLabel(state, new(action.Col, action.Row));
            var skill = action.SkillId.ToString(CultureInfo.InvariantCulture);
            var name = SkillNames.TryGetValue(action.SkillId, out var fixedName) ? fixedName
                : string.IsNullOrEmpty(action.SkillName) ? "技能" : action.SkillName;
            foreach (var target in action.Targets)
            {
                var effects = new List<string>();
                foreach (var value in target.Attributes)
                {
                    var text = CombatRules.EffectText(new(value.Kind, value.Value, value.Sign, value.Attribute));
                    if (text is not null) effects.Add(text);
                }
                var result = effects.Count == 0 ? "無有效屬性變化" : string.Join("、", effects);
                lines.Add($"{actor} → {UnitLabel(state, new(target.Col, target.Row))}｜{name}({skill})｜{result}");
            }
        }
        return lines.ToImmutable();
    }
}
