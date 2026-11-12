using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Instances;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Sessions.Receive;

/// <summary>
/// One receive attempt's canonical state. The complete State.apply composition runs
/// before the bounded SessionLogic.receive battle overlay. Both results stage privately;
/// observation inputs and publications always see the same immutable committed snapshot.
/// A new coordinator never imports pending runtime context from a historical snapshot.
/// This records cooperative fight consumption but never runs post-battle scheduling or outgoing actions.
/// </summary>
internal sealed class ReceiveStateCoordinator(ServiceStateSnapshot initial)
{
    private readonly Thread writer = Thread.CurrentThread;
    private ServiceStateSnapshot state = initial;
    private BattleReceiveContext battleContext = new();

    internal ServiceStateSnapshot Snapshot() { AssertWriter(); return state; }
    internal ServiceStateSnapshot ConfirmWorldAcknowledged()
    {
        AssertWriter();
        if (state.Phase == "world_ready") return state;
        return state = Lala.Core.Gameplay.CommandState.With(state, local: new(
            state.Local.Session with { Phase = "world_ready" }, state.Local.World with { Phase = "world_ready" }, state.Local.Battle));
    }
    internal ServiceStateSnapshot ApplyCommand(Func<ServiceStateSnapshot, ServiceStateSnapshot> transition)
    {
        AssertWriter();
        var next = transition(state);
        if (next.PacketCount != state.PacketCount || next.Player != state.Player || next.Phase != state.Phase)
            throw new InvalidOperationException("Local commands cannot replace server identity, phase or packet count.");
        return state = next;
    }

    internal ServiceStateSnapshot Apply(ServerEvent observation, ServiceObservationContext context)
    {
        AssertWriter();
        // A private coordinator keeps failures in either layer from advancing canonical
        // state or consuming an announcement. Its validation also rejects stale bases.
        var reduced = new ServiceStateCoordinator(state).Apply(observation, context);
        var (nextContext, battle, instances) = battleContext.Apply(
            reduced.Local.Battle, reduced.Instances, observation, reduced.Player?.RoleId);
        var next = ReferenceEquals(battle, reduced.Local.Battle) && ReferenceEquals(instances, reduced.Instances)
            ? reduced : WithReceiveState(reduced, battle, instances);
        state = next = Lala.Core.Gameplay.ManualGameCommands.ReconcileArkFight(next, context.Inputs.ObservedAt);
        battleContext = nextContext;
        return next;
    }

    private void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("Receive state may only be accessed by its owning thread; use immutable snapshots.");
    }

    private static ServiceStateSnapshot WithReceiveState(ServiceStateSnapshot value,
        BattleEventSnapshot battle, InstanceReceiveSnapshot instances) => new(
        local: new(value.Local.Session, value.Local.World, battle), dailyTasks: value.DailyTasks,
        timeCube: value.TimeCube, recovery: value.Recovery, guild: value.Guild, activities: value.Activities,
        storage: value.Storage, expedition: value.Expedition, observation: value.Observation, crafting: value.Crafting,
        bag: value.Bag, companions: value.Companions, party: value.Party, instances: instances,
        tent: value.Tent, playerKnowledge: value.PlayerKnowledge, attributeAllocation: value.AttributeAllocation,
        shopEvidence: value.ShopEvidence, efficiency: value.Efficiency, guildActions: value.GuildActions,
        ark: value.Ark, chat: value.Chat);

    /// <summary>Only receive context from wlre/network/client.py SessionLogic.receive:
    /// last S11-10 wins, one S11-250 consumes it, and the first own exit per count/role
    /// clears it. Zero is a known style/role. Winner, role/world receipts, event end and
    /// duplicate exits do not reset it. Unit WarStyle and Master never establish it.</summary>
    private sealed record BattleReceiveContext(byte? Announcement = null,
        (BigInteger BattleCount, uint RoleId)? LastOwnExit = null)
    {
        internal (BattleReceiveContext Context, BattleEventSnapshot Battle, InstanceReceiveSnapshot Instances) Apply(
            BattleEventSnapshot battle, InstanceReceiveSnapshot instances, ServerEvent observation, uint? ownRoleId)
        {
            var next = this;
            if (observation is WarStyleEvent style) next = next with { Announcement = style.Value };
            else if (observation is ServerLayoutEvent { Event: BattleStartEvent } && Announcement is { } announced)
            {
                battle = battle with { WarStyle = announced };
                next = next with { Announcement = null };
            }

            var ownExit = ownRoleId is { } role && observation switch
            {
                FightExitEvent exit => exit.RoleId == role,
                BattleUnitExitEvent exit => battle.UnitAt(new(exit.Col, exit.Row))?.Layout.Pid == role,
                _ => false
            };
            if (ownExit && battle.BattleCount > 0 && LastOwnExit != (battle.BattleCount, ownRoleId!.Value))
            {
                next = next with { Announcement = null, LastOwnExit = (battle.BattleCount, ownRoleId.Value) };
                battle = battle with { Active = false };
                if (battle.WarStyle == 16) instances = ConsumeCoopFight(instances, battle, ownRoleId.Value);
            }
            return (next, battle, instances);
        }
    }

    // Only the immutable bookkeeping from instance_combat.consume_coop_fight. The
    // Python delay return, post_event/event_flow changes and continuation are not ported.
    private static InstanceReceiveSnapshot ConsumeCoopFight(InstanceReceiveSnapshot instances,
        BattleEventSnapshot battle, uint ownRoleId)
    {
        var coop = instances.Coop;
        var consumed = coop.MapValue.GetValueOrDefault("fight_consumed_battle", StateValue.Null);
        // Independent of the per-role exit guard: a new own role cannot consume this
        // battle again. S186-15 and room observers retain their source-owned reset rules.
        if (SameBattle(consumed, battle.BattleCount)) return instances;
        var count = Integer(coop.MapValue.GetValueOrDefault("fight_count", StateValue.Null));
        coop = coop.SetKey("fight_consumed_battle", StateValue.Scalar(battle.BattleCount));
        bool? won = null;
        if (count is { } remaining && remaining >= 1)
        {
            coop = coop.SetKey("fight_count", StateValue.Scalar(remaining - 1));
            won = OwnVictory(battle, ownRoleId);
        }
        return instances with { Coop = coop.SetKey("last_fight_victory", StateValue.Scalar(won)) };
    }

    private static bool? OwnVictory(BattleEventSnapshot battle, uint ownRoleId)
    {
        if (battle.WinnerSide is not (1 or 2) || ownRoleId == 0) return null;
        // Exited units still supply identity/side evidence. Never use Master, a
        // default own slot, or agreement on side when distinct columns disagree.
        var columns = battle.Units.Where(unit => unit.Layout.Pid == ownRoleId)
            .Select(unit => unit.Layout.Col).Distinct().ToArray();
        return columns.Length == 1 && columns[0] is >= 1 and <= 4
            ? battle.WinnerSide == (columns[0] > 2 ? 1 : 2) : null;
    }

    // The source marker uses ==, unlike the strict integer count check below.
    // Imported integral floats and booleans can therefore identify the same battle.
    private static bool SameBattle(StateValue value, BigInteger battleCount) =>
        value.Kind == StateValueKind.Scalar && value.ScalarValue switch
        {
            bool flag => battleCount == (flag ? 1 : 0),
            float number => float.IsFinite(number) && MathF.Truncate(number) == number && new BigInteger(number) == battleCount,
            double number => double.IsFinite(number) && Math.Truncate(number) == number && new BigInteger(number) == battleCount,
            decimal number => decimal.Truncate(number) == number && new BigInteger(number) == battleCount,
            _ => Integer(value) == battleCount
        };

    // Python type(count) is int: booleans, floating values and numeric strings
    // are not counts. BigInteger preserves source integer range without narrowing.
    private static BigInteger? Integer(StateValue value) => value.Kind != StateValueKind.Scalar ? null :
        value.ScalarValue switch
        {
            sbyte number => number, byte number => number, short number => number, ushort number => number,
            int number => number, uint number => number, long number => number, ulong number => number,
            BigInteger number => number, _ => null
        };

}
