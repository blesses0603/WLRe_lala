using System.Collections.Immutable;
using System.Diagnostics;
using System.Numerics;

namespace Lala.Core.Battle;

/// <summary>
/// Single-owner, local-only completed-battle observer. Call after ordinary knowledge updates.
/// It sends no commands, reads no catalogs, and treats missing EXP evidence as unknown, never zero.
/// Publish Snapshot to other threads rather than sharing the mutable tracker.
/// </summary>
public sealed class EfficiencyTracker
{
    private readonly Func<double> monotonicSeconds;
    private readonly Dictionary<EfficiencySubject, EfficiencyRowSnapshot> rows = [];
    private readonly List<EfficiencySubject> dirty = [];
    private readonly HashSet<EfficiencySubject> participants = [];
    private uint? roleId;
    private bool pending, offline;
    private long battles;

    public EfficiencyTracker(Func<double>? monotonicSeconds = null) =>
        this.monotonicSeconds = monotonicSeconds ?? (() => (double)Stopwatch.GetTimestamp() / Stopwatch.Frequency);

    public EfficiencySnapshot Snapshot => new(roleId, rows, pending, dirty, participants, battles, offline);

    public void Reset()
    {
        roleId = null;
        rows.Clear(); dirty.Clear(); participants.Clear();
        pending = offline = false;
        battles = 0;
    }

    public EfficiencySnapshot Observe(EfficiencyKnowledgeSnapshot knowledge, EfficiencyEvent observation)
    {
        ArgumentNullException.ThrowIfNull(knowledge);
        ArgumentNullException.ThrowIfNull(observation);
        if (knowledge.RoleId is not { } pid || pid == 0) return Snapshot;
        if (roleId != pid) { Reset(); roleId = pid; }
        double now = observation.ObservedAt ?? monotonicSeconds();
        if (!double.IsFinite(now)) return Snapshot;
        offline = observation.Offline ?? offline;
        RefreshRow(EfficiencySubject.Player, knowledge);
        foreach (int slot in knowledge.Companions.Keys) RefreshRow(EfficiencySubject.Companion(slot), knowledge);
        foreach (var subject in rows.Keys.ToArray())
            if (!subject.IsPlayer && !knowledge.Companions.ContainsKey(subject.Slot)) rows.Remove(subject);

        if (observation is EfficiencyBattleStart start)
        {
            pending = start.Units.Any(unit => unit.Pid == pid || unit.MasterId == pid);
            dirty.Clear(); participants.Clear();
            if (pending)
                foreach (var unit in start.Units)
                {
                    if (unit.Pid == pid) participants.Add(EfficiencySubject.Player);
                    if (unit.MasterId == pid && unit.CompanionSlot is >= 1 and <= 255 && knowledge.Companions.ContainsKey(unit.CompanionSlot.Value))
                        participants.Add(EfficiencySubject.Companion(unit.CompanionSlot.Value));
                }
        }

        (EfficiencySubject Subject, long Total)? update = observation switch
        {
            EfficiencyAttributeSet { Kind: 36, Parameter: 0 } attr when attr.Subject.IsPlayer || attr.HumanKind == 4 => (attr.Subject, attr.Value),
            EfficiencyStarInfo star => (EfficiencySubject.Player, star.Experience),
            _ => null
        };
        if (update is { } exp && RefreshRow(exp.Subject, knowledge) is { } expRow)
        {
            expRow = expRow with { Experience = exp.Total };
            if (pending) { if (!dirty.Contains(exp.Subject)) dirty.Add(exp.Subject); }
            else expRow = expRow with { LastTotal = exp.Total }; // Quest reward/correction is not a battle gain.
            rows[exp.Subject] = expRow;
        }
        if (observation is not EfficiencyEventEnd || !pending) return Snapshot;
        pending = false;
        battles++;
        var sampled = dirty.ToHashSet();
        dirty.Clear();
        foreach (var (subject, original) in rows.ToArray())
        {
            var row = original;
            if (!sampled.Contains(subject))
            {
                // Only proven participants lose their baseline; idle companions retain their complete history.
                if (participants.Contains(subject)) rows[subject] = row with { LastTotal = null, LastGain = null };
                continue;
            }
            if (row.Experience is not { } total) continue;
            long? last = row.LastTotal;
            bool changed = row.SampleDegree is not null && row.SampleDegree != row.Degree;
            if (changed || total < 0 || last is not null && total < last)
            {
                row = row with { LastTotal = null, LastGain = null, Earned = 0, Count = 0,
                    History = [], FirstTime = null, LastTime = null };
                last = null;
            }
            BigInteger? gain = last is not null && row.LastTime is not null && now > row.LastTime
                ? (BigInteger)total - last.Value : null;
            row = gain is { } value
                ? row with { Earned = row.Earned + value, Count = row.Count + 1 }
                : row with { History = [] };
            var history = row.History.Add(new(row.Earned, now));
            rows[subject] = row with
            {
                LastTotal = total, LastGain = gain, LastTime = now, FirstTime = row.FirstTime ?? now,
                SampleDegree = row.Degree, History = history.Length > 31 ? history.RemoveAt(0) : history
            };
        }
        participants.Clear();
        return Snapshot;
    }

    private EfficiencyRowSnapshot? RefreshRow(EfficiencySubject subject, EfficiencyKnowledgeSnapshot knowledge)
    {
        EfficiencyStats stats;
        uint identity;
        string name;
        if (subject.IsPlayer)
        {
            stats = knowledge.PlayerStats;
            identity = knowledge.RoleId!.Value;
            name = knowledge.PlayerName;
        }
        else
        {
            if (!knowledge.Companions.TryGetValue(subject.Slot, out var companion) || companion.NpcId is not { } npcId) return null;
            stats = companion.Stats;
            identity = npcId;
            name = !string.IsNullOrEmpty(stats.Name) ? stats.Name : !string.IsNullOrEmpty(companion.CatalogName)
                ? companion.CatalogName : $"夥伴 #{subject.Slot}";
        }
        if (!rows.TryGetValue(subject, out var row) || row.Identity != identity) row = new() { Identity = identity };
        row = row with { Name = name };
        if (stats.Level is not null) row = row with { Level = stats.Level, ConfirmedLevel = stats.Level, LevelInferred = false };
        if (stats.Degree is not null) row = row with { Degree = stats.Degree, ConfirmedDegree = stats.Degree, DegreeInferred = false };
        if (stats.Experience is not null) row = row with { Experience = stats.Experience };
        if (!subject.IsPlayer && row.Experience is { } exp)
        {
            if (row.Degree is null && row.Level is not null)
            {
                int[] matches = Enumerable.Range(0, 3).Where(degree => EfficiencyRules.Progress(exp, row.Level, degree).Remaining is not null).ToArray();
                if (matches.Length == 1) row = row with { Degree = matches[0], DegreeInferred = true };
            }
            if (EfficiencyRules.MaximumLevel(row.Degree) is { } maximum &&
                (row.Level is null || EfficiencyRules.Progress(exp, row.Level, row.Degree).Remaining is null))
            {
                for (int level = 1; level <= maximum; level++)
                    if (level == maximum || EfficiencyRules.Cumulative(level, row.Degree!.Value) <= exp && exp < EfficiencyRules.Cumulative(level + 1, row.Degree.Value))
                    {
                        row = row with { Level = level, LevelInferred = true };
                        break;
                    }
            }
        }
        rows[subject] = row;
        return row;
    }
}
