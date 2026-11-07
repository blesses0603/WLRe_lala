namespace Lala.Core.Expedition;

public sealed record ExpeditionRole(int Index, int NpcId, long Faith, long Level = 0,
    long Degree = 0, long Potential = 0, long Strength = 0, long Constitution = 0,
    long Intelligence = 0, long Wisdom = 0, long Agility = 0);
public sealed record ExpeditionNpc(long? Element = null, long? Kind = null, long? Original = null);
public sealed record ExpeditionCondition(int Kind, long First, long Second = 0);
public sealed record ExpeditionRecommendation(ExpeditionCondition Condition, long Bonus);
public sealed record ExpeditionRecommendationResult(ExpeditionRecommendation Recommendation, bool? Met, long Awarded);
public sealed record ExpeditionSuccess(long Points, decimal Percent, bool Complete,
    IReadOnlyList<ExpeditionRecommendationResult> Recommendations);

/// <summary>Offline port of expedition/teams.py. Does not start expeditions or spend resources.</summary>
public static class ExpeditionTeams
{
    private sealed record Model(ExpeditionRole Role, long[] Stats, ExpeditionNpc Npc)
    {
        public long Cost => Stats.Take(7).Sum();
    }
    private sealed record Compiled(int Kind, long Target, long[] Weights, int[] Unknown);
    private static Model ToModel(ExpeditionRole role, IReadOnlyDictionary<int, ExpeditionNpc>? npcs)
    {
        if (role.Faith < 0 || role.Level < 0 || role.Degree < 0 || role.Potential < 0 || role.Strength < 0 ||
            role.Constitution < 0 || role.Intelligence < 0 || role.Wisdom < 0 || role.Agility < 0)
            throw new ArgumentOutOfRangeException(nameof(role), "Expedition stats and faith must be non-negative.");
        ExpeditionNpc npc = npcs is not null && npcs.TryGetValue(role.NpcId, out var found) ? found : new();
        return new(role, [checked(role.Level + (role.Degree == 2 ? 300 : role.Degree * 100)),
            role.Potential, role.Strength, role.Constitution, role.Intelligence, role.Wisdom, role.Agility, role.Degree], npc);
    }
    private static Compiled Compile(ExpeditionCondition c, Model[] models)
    {
        var weights = new long[models.Length]; var unknown = new int[models.Length];
        for (var i = 0; i < models.Length; i++)
        {
            var m = models[i];
            long? value = c.Kind switch
            {
                0 => 0, 1 => 1, 2 or 3 => m.Npc.Element is long e ? (e == c.First ? 1 : 0) : null,
                4 => m.Npc.Original is long o ? (o == c.First ? 1 : 0) : null,
                5 => m.Stats[0], 6 => m.Stats[1], 7 => m.Stats[3], 8 => m.Stats[2],
                9 => m.Stats[4], 10 => m.Stats[5], 11 => m.Stats[6], 12 => m.Stats[7],
                13 or 14 => m.Npc.Kind is long k ? (k == (c.Kind == 13 ? 0 : 1) ? 1 : 0) : null,
                _ => null
            };
            weights[i] = value ?? 0; unknown[i] = value is null ? 1 : 0;
        }
        return new(c.Kind, c.Kind is 0 or 3 ? 0 : c.Kind == 2 ? c.Second : c.Kind == 4 ? 1 : c.First, weights, unknown);
    }
    private static bool? Met(int kind, long target, long value, int unknown) => kind switch
    {
        0 => true, 3 => value != 0 ? false : unknown != 0 ? null : true,
        _ => value >= target ? true : unknown != 0 ? null : false
    };
    public static bool? ConditionMet(ExpeditionCondition condition, IReadOnlyList<ExpeditionRole> roles,
        IReadOnlyDictionary<int, ExpeditionNpc>? npcs = null)
    {
        var c = Compile(condition, roles.Select(r => ToModel(r, npcs)).ToArray());
        return Met(c.Kind, c.Target, c.Weights.Sum(), c.Unknown.Sum());
    }
    public static ExpeditionSuccess SuccessDetails(long basePoints, IEnumerable<ExpeditionRecommendation> recommendations,
        IReadOnlyList<ExpeditionRole> roles, IReadOnlyDictionary<int, ExpeditionNpc>? npcs = null)
    {
        var points = basePoints; var details = new List<ExpeditionRecommendationResult>();
        foreach (var r in recommendations.Where(r => r.Condition.Kind != 0))
        {
            var met = ConditionMet(r.Condition, roles, npcs); var bonus = met == true ? r.Bonus : 0;
            points = checked(points + bonus); details.Add(new(r, met, bonus));
        }
        return new(Math.Min(1000, points), Math.Min(1000, points) / 10m,
            points >= 1000 || details.All(r => r.Met.HasValue), details.AsReadOnly());
    }
    /// <summary>Exact 1–4 member search. Unknown joining conditions never qualify.
    /// Cancellation aborts the search; it never returns an unverified partial optimum.</summary>
    public static IReadOnlyList<int> ChooseMembers(ExpeditionCondition joining,
        IEnumerable<ExpeditionRecommendation> recommendations, long basePoints, long faithCost,
        IReadOnlyList<ExpeditionRole> roles, long threshold, IReadOnlyDictionary<int, ExpeditionNpc>? npcs = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (roles.Select(r => r.Index).Distinct().Count() != roles.Count)
            throw new ArgumentException("Role slot indices must be unique.", nameof(roles));
        threshold = Math.Max(threshold, faithCost);
        var models = roles.Select(r => ToModel(r, npcs)).OrderBy(m => Math.Max(0, checked(threshold - m.Role.Faith)))
            .ThenBy(m => m.Cost).ThenBy(m => m.Role.Index).ToArray();
        var allRecommendations = recommendations.ToArray();
        if (allRecommendations.Any(r => r.Bonus < 0))
            throw new ArgumentOutOfRangeException(nameof(recommendations), "Expedition recommendation bonuses must be non-negative.");
        var recs = allRecommendations.Where(r => r.Condition.Kind != 0 && r.Bonus != 0).ToArray();
        var conditions = new[] { Compile(joining, models) }.Concat(recs.Select(r => Compile(r.Condition, models))).ToArray();
        var gains = new[] { 0L }.Concat(recs.Select(r => r.Bonus)).ToArray();
        var n = models.Length;
        var upper = new long[conditions.Length][][];
        for (var j = 0; j < conditions.Length; j++)
        {
            upper[j] = new long[n + 1][]; upper[j][n] = new long[5];
            var top = new List<long>(5);
            for (var start = n - 1; start >= 0; start--)
            {
                cancellationToken.ThrowIfCancellationRequested();
                top.Add(conditions[j].Weights[start]); top.Sort((a, b) => b.CompareTo(a));
                if (top.Count > 4) top.RemoveAt(4);
                var bounds = new long[5];
                for (var k = 1; k <= 4; k++) bounds[k] = checked(bounds[k - 1] + (k <= top.Count ? top[k - 1] : 0));
                upper[j][start] = bounds;
            }
        }
        long? bestScore = null; long bestDeficit = 0, bestCost = 0; int[] bestTeam = [];
        void Visit(int start, List<int> team, long[] totals, int[] unknowns, long deficit, long cost)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (team.Count != 0 && Met(conditions[0].Kind, conditions[0].Target, totals[0], unknowns[0]) == true)
            {
                var points = basePoints;
                for (var j = 1; j < conditions.Length; j++)
                    if (Met(conditions[j].Kind, conditions[j].Target, totals[j], unknowns[j]) == true) points = checked(points + gains[j]);
                var score = Math.Min(1000, points); var indices = team.Select(i => models[i].Role.Index).Order().ToArray();
                bool LexSmaller() { for (var i = 0; i < indices.Length; i++) { if (indices[i] != bestTeam[i]) return indices[i] < bestTeam[i]; } return false; }
                if (bestScore is null || score > bestScore || (score == bestScore && (deficit < bestDeficit ||
                    (deficit == bestDeficit && (cost < bestCost || (cost == bestCost &&
                    (indices.Length < bestTeam.Length || (indices.Length == bestTeam.Length && LexSmaller()))))))))
                { bestScore = score; bestDeficit = deficit; bestCost = cost; bestTeam = indices; }
            }
            var slots = 4 - team.Count; if (slots == 0 || start == n) return;
            var join = conditions[0];
            if (join.Kind == 3) { if (totals[0] != 0 || unknowns[0] != 0) return; }
            else if (join.Kind != 0 && checked(totals[0] + upper[0][start][slots]) < join.Target) return;
            var maximum = basePoints;
            for (var j = 1; j < conditions.Length; j++)
            {
                var c = conditions[j]; var possible = c.Kind == 3 ? totals[j] == 0 && unknowns[j] == 0 : checked(totals[j] + upper[j][start][slots]) >= c.Target;
                if (possible) maximum = checked(maximum + gains[j]);
            }
            if (bestScore is not null)
            {
                var bound = Math.Min(1000, maximum); if (bound < bestScore) return;
                if (bound == bestScore && (deficit > bestDeficit || (deficit == bestDeficit &&
                    (cost > bestCost || (cost == bestCost && team.Count >= bestTeam.Length))))) return;
            }
            for (var i = start; i < n; i++)
            {
                team.Add(i);
                Visit(i + 1, team, conditions.Select((c, j) => checked(totals[j] + c.Weights[i])).ToArray(),
                    conditions.Select((c, j) => checked(unknowns[j] + c.Unknown[i])).ToArray(),
                    checked(deficit + Math.Max(0, checked(threshold - models[i].Role.Faith))), checked(cost + models[i].Cost));
                team.RemoveAt(team.Count - 1);
            }
        }
        Visit(0, [], new long[conditions.Length], new int[conditions.Length], 0, 0);
        return Array.AsReadOnly(bestTeam);
    }
}
