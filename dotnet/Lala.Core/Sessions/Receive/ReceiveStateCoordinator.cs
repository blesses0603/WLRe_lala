using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Sessions.Receive;

/// <summary>
/// One receive attempt's canonical state. The complete State.apply composition runs
/// before the bounded SessionLogic.receive battle overlay. Both results stage privately;
/// observation inputs and publications always see the same immutable committed snapshot.
/// A new coordinator never imports pending runtime context from a historical snapshot.
/// This does not run post-battle scheduling, instance consumption or outgoing actions.
/// </summary>
internal sealed class ReceiveStateCoordinator(ServiceStateSnapshot initial)
{
    private readonly Thread writer = Thread.CurrentThread;
    private ServiceStateSnapshot state = initial;
    private BattleReceiveContext battleContext = new();

    internal ServiceStateSnapshot Snapshot() { AssertWriter(); return state; }

    internal ServiceStateSnapshot Apply(ServerEvent observation, ServiceObservationContext context)
    {
        AssertWriter();
        // A private coordinator keeps failures in either layer from advancing canonical
        // state or consuming an announcement. Its validation also rejects stale bases.
        var reduced = new ServiceStateCoordinator(state).Apply(observation, context);
        var (nextContext, battle) = battleContext.Apply(reduced.Local.Battle, observation, reduced.Player?.RoleId);
        var next = ReferenceEquals(battle, reduced.Local.Battle) ? reduced : WithBattle(reduced, battle);
        state = next;
        battleContext = nextContext;
        return next;
    }

    private void AssertWriter()
    {
        if (!ReferenceEquals(Thread.CurrentThread, writer))
            throw new InvalidOperationException("Receive state may only be accessed by its owning thread; use immutable snapshots.");
    }

    private static ServiceStateSnapshot WithBattle(ServiceStateSnapshot value, BattleEventSnapshot battle) => new(
        local: new(value.Local.Session, value.Local.World, battle), dailyTasks: value.DailyTasks,
        timeCube: value.TimeCube, recovery: value.Recovery, guild: value.Guild, activities: value.Activities,
        storage: value.Storage, expedition: value.Expedition, observation: value.Observation, crafting: value.Crafting,
        bag: value.Bag, companions: value.Companions, party: value.Party, instances: value.Instances,
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
        internal (BattleReceiveContext Context, BattleEventSnapshot Battle) Apply(
            BattleEventSnapshot battle, ServerEvent observation, uint? ownRoleId)
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
            }
            return (next, battle);
        }
    }
}
