using Lala.Core.Protocol;

namespace Lala.Core.Battle;

/// <summary>Pure receive-only port of attribute_points.apply_event. Decode before reducing.
/// Only an already-pending observation can change. ACK alone does not imply synchronized
/// stats, matching stats alone do not imply ACK, and duplicate/late packets apply in arrival
/// order. No allocation validation/planning, begin, expiry, commands, sends, live knowledge
/// updates, session/lifecycle ownership or coordinator integration is implemented here.</summary>
public static class AttributeAllocationReducer
{
    public static AttributeAllocationSnapshot Apply(AttributeAllocationSnapshot state,
        ServerEvent observation, AttributeAllocationContext context)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        if (observation is ServerLiveDataEvent live) return Apply(state, live.Event, context);
        return ApplyRelevant(state, observation is AttributeAllocationSuccessEvent,
            observation is AttributeSetEvent, context);
    }

    public static AttributeAllocationSnapshot Apply(AttributeAllocationSnapshot state,
        LiveDataEvent observation, AttributeAllocationContext context)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        return ApplyRelevant(state, false, observation is PlayerCombatDataEvent, context);
    }

    private static AttributeAllocationSnapshot ApplyRelevant(AttributeAllocationSnapshot state,
        bool acknowledgement, bool statsObservation, AttributeAllocationContext context)
    {
        if (!state.Pending) return state;
        if (acknowledgement) state = state with
        {
            Acknowledged = true, Status = "伺服器已回覆成功，等待能力值同步"
        };
        if (!acknowledgement && !statsObservation) return state;
        // Any S8 entity/kind can trigger comparison of current player knowledge. The
        // incoming attribute's value is not itself a source of current/expected stats.
        if (!state.Acknowledged || state.Expected is { } expected && expected.Any(entry =>
                !context.PlayerStats.TryGetValue(entry.Key, out var current) || current != entry.Value))
            return state;
        // Source intentionally does not clear Uncertain, even on an inconsistent imported
        // Pending+Uncertain seed. Null/empty expected passes vacuously after an ACK.
        return state with
        {
            Pending = false, Acknowledged = false, Expected = null,
            SentAt = null, Status = "配點成功，能力值已同步"
        };
    }
}
