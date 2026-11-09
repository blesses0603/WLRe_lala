using Lala.Core.Inventory;

namespace Lala.Core.Battle;

/// <summary>Pure auto_battle.choose_action over caller-supplied observations. This returns
/// one detached intent and a reason, never a packet, runtime mutation, hold, or send grant.
/// No active-round gate is inferred; the scheduler and stop guards are outside this API.</summary>
public static class AutoBattleRuleChooser
{
    public static AutoBattleChoice Choose(BattleCommandContext context, CombatResourceActor actor, AutoBattleProfile profile)
    {
        ArgumentNullException.ThrowIfNull(context); ArgumentNullException.ThrowIfNull(actor);
        ArgumentNullException.ThrowIfNull(context.Resources);
        var resources = context.Resources;
        // These typed boundaries do not manufacture identities from coordinates/ownership.
        if (resources.LocalRoleId is not { } pid || actor.Pid is null)
            throw new ArgumentException("The chooser requires explicit local role and actor identities.",nameof(context));
        if (resources.Units.IsDefault || resources.Units.Any(entry => entry is null || entry.Slot is null || entry.Actor is null) ||
            resources.Units.Select(entry => entry.Slot).Distinct(StringComparer.Ordinal).Count() != resources.Units.Length)
            throw new ArgumentException("Initialized battle entries with distinct source keys are required.",nameof(context));
        ValidateActor(actor);
        foreach (var entry in resources.Units) ValidateActor(entry.Actor);
        var rules = AutoBattleProfiles.Normalize(profile,resources.Catalog);
        var ordered = resources.Units.Select(entry => entry.Actor).OrderBy(unit => unit.Col).ThenBy(unit => unit.Row).ToArray();
        var living = ordered.Where(unit => (unit.Hp ?? 0) > 0 && !unit.Exited).ToArray();
        bool Same(CombatResourceActor unit) => (unit.Col > 2) == (actor.Col > 2);
        long? Field(AutoBattleAction action,string key) => action.Id >= 0 && resources.Catalog.Skills.TryGetValue((uint)action.Id,out var data)
            ? data.Fields.GetValueOrDefault(key) : null;
        AutoBattleChoice? Done(AutoBattleReason reason,AutoBattleAction action,string? target = null,string resource = "hp")
        {
            if (action.Id == 0) return null;
            BattleCommandCandidate result;
            if (action.Kind == AutoBattleActionKind.Item)
                result = BattleCommandPlanner.Adapt(CombatResourceActionCandidates.Food(resources,actor,action.Id == -3 ? "sp" : resource,
                    action.Id < 0 ? null : (ushort)action.Id,target));
            else if (action.Id == -1)
                result = BattleCommandPlanner.Adapt(CombatResourceActionCandidates.BestSkill(resources,actor,context.NormalCatalog,target,(int)action.Target));
            else if (action.Id is not (10001 or 60021 or 60041 or 10008))
                result = BattleCommandPlanner.Adapt(CombatResourceActionCandidates.Learned(resources,actor,(uint)action.Id,target,(int)action.Target,action.UseNextSkill));
            else
            {
                var mode = action.Id switch { 10001 => "normal",60021 => "defend",60041 => "escape",_ => "catch" };
                if (target is not null || mode is "defend" or "escape") result = BattleCommandPlanner.Action(context,actor,mode,target);
                else
                {
                    var enemies = living.Where(unit => !Same(unit));
                    var candidates = action.Target == AutoBattleTargetPolicy.HighestHp
                        ? enemies.OrderByDescending(unit => unit.Hp).ThenBy(unit => unit.Col).ThenBy(unit => unit.Row)
                        : enemies.OrderBy(unit => unit.Hp).ThenBy(unit => unit.Col).ThenBy(unit => unit.Row);
                    foreach (var unit in candidates)
                    {
                        var candidate = Finish(BattleCommandPlanner.Action(context,actor,mode,BattleCommandPlanner.Slot(unit)),reason);
                        if (candidate is not null) return candidate;
                    }
                    return null;
                }
            }
            return Finish(result,reason);
        }
        if (rules.DeadEnabled && ordered.Any(unit => Same(unit) && (unit.Hp ?? 1) <= 0 && !unit.Exited && !unit.IsFly))
        {
            // Source trigger excludes flying units, but its subsequent first-target scan
            // does not. Do not "repair" that asymmetry or look at the upgraded skill here.
            var dead = ordered.First(unit => Same(unit) && (unit.Hp ?? 1) <= 0 && !unit.Exited);
            var result = Done(AutoBattleReason.DeadAlly,rules.Dead,Field(rules.Dead,"FightWay") is 8 or 24 ? BattleCommandPlanner.Slot(dead) : null);
            if (result is not null) return result;
        }
        if (rules.EnemyHpEnabled)
            foreach (var unit in living)
            {
                var comparison = rules.EnemyHp.Value.Compare(unit.Hp!.Value);
                if (Same(unit) || !(rules.EnemyHp.Comparison == AutoBattleComparison.GreaterThan ? comparison > 0 : comparison < 0)) continue;
                var result = Done(AutoBattleReason.EnemyHp,rules.EnemyHp,BattleCommandPlanner.Slot(unit));
                if (result is not null) return result;
            }
        foreach (var (enabled,reason,action,attribute) in new[] {
            (rules.LowHpEnabled,AutoBattleReason.LowHp,rules.LowHp,"hp"),
            (rules.LowSpEnabled,AutoBattleReason.LowSp,rules.LowSp,"sp") })
        {
            if (!enabled) continue;
            CombatResourceActor? first = null;
            foreach (var unit in living)
            {
                // Missing stat is source infinity, not zero. Identity access remains lazy.
                if (!unit.Stats.TryGetValue(attribute,out var value) || action.Value.Compare(value) >= 0) continue;
                if (action.Notice == AutoBattleNotice.Player && unit.Pid is null) return Failure("KeyError","'pid'");
                var match = action.Notice switch { AutoBattleNotice.SameSide => Same(unit),AutoBattleNotice.Player => unit.Pid == pid,_ => unit.MasterId == pid };
                if (match) { first = unit; break; }
            }
            if (first is null) continue;
            var explicitTarget = action.Kind == AutoBattleActionKind.Item || Field(action,"TargetKind") is 1 or 3 or 5;
            var result = Done(reason,action,explicitTarget ? BattleCommandPlanner.Slot(first) : null,attribute);
            if (result is not null) return result;
        }
        if (rules.RoundEnabled && context.Round is >= 1 and <= 3)
        {
            var result = Done(AutoBattleReason.Round,rules.RoundActions[(int)context.Round - 1]);
            if (result is not null) return result;
        }
        if (rules.RepeatEnabled)
        {
            var used = rules.RepeatActions.Where(action => action.Id != 0).ToArray();
            if (used.Length != 0)
            {
                // Equivalent to Python (round - 1) % count, including negative rounds,
                // without overflowing Int64.MinValue at the intermediate subtraction.
                var index = (int)((context.Round % used.Length - 1 + used.Length) % used.Length);
                if (index < 0) index += used.Length;
                var result = Done(AutoBattleReason.Repeat,used[index]);
                if (result is not null) return result;
            }
        }
        var preference = AutoBattleTargetPolicy.LowestHp;
        if (rules.OrderEnabled)
            foreach (var action in rules.OrderActions)
            {
                if (action.Id != 0) preference = action.Target;
                var result = Done(AutoBattleReason.Order,action);
                if (result is not null) return result;
            }
        if (!rules.OrderEnabled || rules.OrderActions.All(action => action.Id == 0))
        {
            foreach (var unit in living.Where(unit => !Same(unit)))
            {
                var result = Done(AutoBattleReason.Fallback,new() { Id = 10001 },BattleCommandPlanner.Slot(unit));
                if (result is not null) return result;
            }
        }
        else
        {
            var result = Done(AutoBattleReason.Fallback,new() { Id = 10001, Target = preference });
            if (result is not null) return result;
        }
        return Failure("ProtocolError","沒有可用行動／目標，或普攻資料不足");
    }

    private static AutoBattleChoice? Finish(BattleCommandCandidate candidate,AutoBattleReason reason) => candidate.Error switch
    {
        { Type: "ProtocolError" } => null,
        { } error => new(null,null,error),
        _ => new(candidate.Intent,reason,null)
    };
    private static AutoBattleChoice Failure(string type,string message) => new(null,null,new(type,message));
    private static void ValidateActor(CombatResourceActor actor)
    {
        if (actor.Stats is null || actor.Statuses is null || actor.Equips.IsDefault || actor.Equips.Any(equipment => equipment is null))
            throw new ArgumentException("Explicit sparse stats/statuses and initialized equipment observations are required.",nameof(actor));
    }
}
