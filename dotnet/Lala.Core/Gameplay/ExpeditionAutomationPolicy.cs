using System.Collections.Immutable;

namespace Lala.Core.Gameplay;

internal sealed record ExpeditionAutomationCandidate(ushort Task,ImmutableArray<int> Slots,long Points,int Seconds,int Faith);
/// <summary>Python expedition manager ordering and selected-team-only recovery policy.
/// A candidate remains an assessment; the actual command planner revalidates all state.</summary>
internal static class ExpeditionAutomationPolicy
{
    internal static ExpeditionAutomationCandidate? Choose(IEnumerable<ExpeditionAutomationCandidate> candidates)
        =>candidates.OrderByDescending(v=>v.Points).ThenByDescending(v=>v.Seconds).ThenBy(v=>v.Task).FirstOrDefault();
    internal static int? FirstDeficit(ExpeditionAutomationCandidate chosen,IReadOnlyDictionary<int,int> faith)
        =>chosen.Slots.Order().Where(i=>faith.TryGetValue(i,out int value)&&value<chosen.Faith).Select(i=>(int?)i).FirstOrDefault();
}
