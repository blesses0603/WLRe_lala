using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

/// <summary>Complete pure wlre/core/state_battle_events.py port over decoded typed events.
/// The current own-role identity is supplied by the caller, never inferred from a unit's
/// master, account, NPC index, or slot. Unrelated events (including malformed S51 metadata)
/// are ignored exactly as dispatch_local does. Strict packet errors remain decoder errors.
/// This does not run observers, AI, the session lifecycle, or increment packet_count.</summary>
public static class BattleEventReducer
{
    public static BattleEventSnapshot Apply(BattleEventSnapshot state, ServerEvent message, uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(message);
        return message switch
        {
            ServerLayoutEvent layout => Apply(state, layout.Event, ownRoleId),
            BattleAttributeSetEvent attributes => ApplyAttributes(state, attributes.Values),
            RoundStartEvent round => state with
            {
                Round = round.Round,
                Commands = state.Round == round.Round ? state.Commands : [],
                HasCommands = state.Round != round.Round || state.HasCommands
            },
            BattleUnitExitEvent exit => ApplyExit(state, new(exit.Col, exit.Row), ownRoleId),
            FightExitEvent exit when exit.RoleId == ownRoleId => state with { Active = false },
            AttackResultEvent attack => ApplyAttack(state, attack.Actions),
            WarStyleEvent style => state with { WarStyle = style.Value },
            WinnerEvent winner => state with { WinnerSide = winner.Side, Active = false },
            _ => state
        };
    }

    public static BattleEventSnapshot Apply(BattleEventSnapshot state, LayoutEvent message, uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(message);
        // Layout updates never use own-role identity, but accept the same caller context.
        _ = ownRoleId;
        return message switch
        {
            BattleStartEvent start => new BattleEventSnapshot
            {
                BattleCount = state.BattleCount + 1,
                Stage = start.Stage,
                FightNumber = start.FightNumber,
                Round = 0,
                Active = true,
                HasCommands = true,
                Units = ReplaceUnits([], start.Units)
            },
            BattleUnitsEvent units => state with { Units = ReplaceUnits(state.Units, units.Units) },
            _ => state
        };
    }

    public static BattleEventSnapshot Apply(BattleEventSnapshot state, BattleCommandSentEvent message)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(message);
        var entry = new BattleCommandSnapshot(message, BattleCommandStatus.Sent);
        var index = CommandIndex(state.Commands, message.Slot);
        return state with
        {
            HasCommands = true,
            Commands = index < 0 ? state.Commands.Add(entry) : state.Commands.SetItem(index, entry)
        };
    }

    private static ImmutableArray<BattleUnitState> ReplaceUnits(ImmutableArray<BattleUnitState> current,
        ImmutableArray<BattleUnit> incoming)
    {
        foreach (var unit in incoming)
        {
            var replacement = new BattleUnitState(unit);
            var index = UnitIndex(current, replacement.Slot);
            // Python dict assignment replaces in place, preserving first insertion order.
            current = index < 0 ? current.Add(replacement) : current.SetItem(index, replacement);
        }
        return current;
    }

    private static BattleEventSnapshot ApplyAttributes(BattleEventSnapshot state, ImmutableArray<BattleAttributeValue> values)
    {
        var units = state.Units;
        foreach (var value in values)
        {
            var index = UnitIndex(units, new(value.Col, value.Row));
            if (index < 0) continue; // No buffering for a unit that might arrive later.
            var unit = units[index];
            units = units.SetItem(index, unit with
            {
                Attributes = unit.Attributes.SetItem(value.Kind, value.Value),
                Hp = value.Kind == 25 ? value.Value : unit.Hp,
                Sp = value.Kind == 26 ? value.Value : unit.Sp
            });
        }
        return units == state.Units ? state : state with { Units = units };
    }

    private static BattleEventSnapshot ApplyExit(BattleEventSnapshot state, BattleSlot slot, uint? ownRoleId)
    {
        var index = UnitIndex(state.Units, slot);
        if (index < 0) return state;
        var unit = state.Units[index];
        return state with
        {
            Units = state.Units.SetItem(index, unit with { Exited = true }),
            Active = unit.Layout.Pid == ownRoleId ? false : state.Active
        };
    }

    private static BattleEventSnapshot ApplyAttack(BattleEventSnapshot state, ImmutableArray<AttackAction> actions)
    {
        var commands = state.Commands;
        foreach (var action in actions)
        {
            var index = CommandIndex(commands, new(action.Col, action.Row));
            if (index >= 0)
                commands = commands.SetItem(index, commands[index] with { Status = BattleCommandStatus.Resolved });
        }
        // S50 reports do not establish absolute HP/SP, slot-to-role ownership, or shield state.
        // Duplicates are counted, and late reports are retained, just as in the Python reducer.
        return state with
        {
            Actions = state.Actions + actions.Length,
            LastActions = actions,
            HasLastActions = true,
            Commands = commands
        };
    }

    private static int UnitIndex(ImmutableArray<BattleUnitState> units, BattleSlot slot)
    {
        for (var i = 0; i < units.Length; i++) if (units[i].Slot == slot) return i;
        return -1;
    }

    private static int CommandIndex(ImmutableArray<BattleCommandSnapshot> commands, BattleSlot slot)
    {
        for (var i = 0; i < commands.Length; i++) if (commands[i].Slot == slot) return i;
        return -1;
    }
}
