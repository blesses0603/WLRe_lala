namespace Lala.Core.Battle;

/// <summary>
/// Immutable snapshot-in/snapshot-out efficiency observation. Calculations are shared with
/// the single-owner tracker, but every call stages in a detached owner. A failed observation
/// cannot change its input or any earlier publication. No transport, clock or resource I/O.
/// </summary>
public static class EfficiencyReducer
{
    /// <summary>Use a recorded timestamp. An eligible event without one is rejected rather
    /// than silently consulting a process clock. Missing/zero role IDs still skip observation.</summary>
    public static EfficiencySnapshot Apply(EfficiencySnapshot state,
        EfficiencyKnowledgeSnapshot knowledge, EfficiencyEvent observation) =>
        Apply(state, knowledge, observation, MissingObservationTime);

    /// <summary>The explicit clock is evaluated only for an eligible event without
    /// ObservedAt, matching the tracker. Nonfinite times retain source role-reset ordering.</summary>
    public static EfficiencySnapshot Apply(EfficiencySnapshot state,
        EfficiencyKnowledgeSnapshot knowledge, EfficiencyEvent observation, Func<double> monotonicSeconds)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(knowledge);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(monotonicSeconds);
        return new EfficiencyTracker(state, monotonicSeconds).Observe(knowledge, observation);
    }

    private static double MissingObservationTime() => throw new InvalidOperationException(
        "Efficiency observation requires an explicit timestamp or an injected clock.");
}
