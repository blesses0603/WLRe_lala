using System.Globalization;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

/// <summary>
/// Receive-only adapter over the immutable efficiency reducer. The caller supplies complete
/// post-live knowledge and post-local role/name evidence, plus an explicit observation time.
/// This adapter never fabricates knowledge, dispatches another reducer, or sends a command.
/// </summary>
public static class EfficiencyReceiveReducer
{
    public static EfficiencySnapshot Apply(EfficiencySnapshot state,
        EfficiencyKnowledgeSnapshot knowledge, ServerEvent observation, double observedAt, bool? offline = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(knowledge);
        ArgumentNullException.ThrowIfNull(observation);
        // Source returns before inspecting the payload when role/time is ineligible.
        var adapted = knowledge.RoleId is null or 0 || !double.IsFinite(observedAt)
            ? new EfficiencyRefresh { ObservedAt = observedAt, Offline = offline }
            : Adapt(observation, observedAt, offline);
        return EfficiencyReducer.Apply(state, knowledge, adapted);
    }

    /// <summary>Every other decoded event still refreshes known rows. In particular winner,
    /// fight exit, unit updates and unsupported events are not completion or no-op signals.</summary>
    public static EfficiencyEvent Adapt(ServerEvent observation, double observedAt, bool? offline = null)
    {
        ArgumentNullException.ThrowIfNull(observation);
        EfficiencyEvent result = observation switch
        {
            ServerLayoutEvent { Event: BattleStartEvent start } => new EfficiencyBattleStart(
                start.Units.Select(BattleUnit)),
            EventEndEvent => new EfficiencyEventEnd(),
            ServerLiveDataEvent { Event: StarInfoEvent star } => new EfficiencyStarInfo(star.Exp),
            AttributeSetEvent { Kind: 36, Parameter: 0, Entity: "self" } attribute =>
                new EfficiencyAttributeSet(EfficiencySubject.Player, 36, attribute.Value, HumanKind: attribute.HumanKind),
            AttributeSetEvent { Kind: 36, Parameter: 0, HumanKind: 4 } attribute => CompanionExperience(attribute),
            _ => new EfficiencyRefresh()
        };
        return result with { ObservedAt = observedAt, Offline = offline };
    }

    private static EfficiencyBattleUnit BattleUnit(Protocol.BattleUnit unit)
    {
        ArgumentNullException.ThrowIfNull(unit);
        return new(unit.Pid, unit.MasterId, unit.NpcIndex);
    }

    private static EfficiencyEvent CompanionExperience(AttributeSetEvent attribute)
    {
        // Decode S8-2 uses the entity string as its subject. Do not borrow an inconsistent
        // Index from a hand-built event or treat a remote player as the local companion.
        const string prefix = "follow:";
        if (!attribute.Entity.StartsWith(prefix, StringComparison.Ordinal)) return new EfficiencyRefresh();
        if (!int.TryParse(attribute.Entity.AsSpan(prefix.Length), NumberStyles.None,
            CultureInfo.InvariantCulture, out var slot) || slot is < 0 or > ushort.MaxValue)
            throw new ArgumentException("Efficiency companion subjects require a UInt16 slot.", nameof(attribute));
        return new EfficiencyAttributeSet(EfficiencySubject.Companion(slot), 36, attribute.Value, HumanKind: 4);
    }
}
