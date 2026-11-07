using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;

namespace Lala.Core.Battle;

/// <summary>Local player, or a confirmed companion slot. Never a remote battle-unit ID.</summary>
public readonly record struct EfficiencySubject
{
    private readonly bool isCompanion;
    public int Slot { get; }
    public bool IsPlayer => !isCompanion;
    public static EfficiencySubject Player => default;
    private EfficiencySubject(int slot) { Slot = slot; isCompanion = true; }
    public static EfficiencySubject Companion(int slot) => slot is >= 0 and <= ushort.MaxValue
        ? new(slot) : throw new ArgumentOutOfRangeException(nameof(slot));
    public override string ToString() => IsPlayer ? "self" : "follow:" + Slot.ToString(CultureInfo.InvariantCulture);
}

/// <summary>Confirmed knowledge, not curve-derived labels. Null means no new evidence.</summary>
public sealed record EfficiencyStats(long? Experience = null, long? Level = null, long? Degree = null, string? Name = null);
public sealed record EfficiencyCompanion(uint? NpcId, EfficiencyStats Stats, string? CatalogName = null);

/// <summary>Detached immutable knowledge after the event's ordinary state reducers have run.</summary>
public sealed class EfficiencyKnowledgeSnapshot
{
    public uint? RoleId { get; }
    public string PlayerName { get; }
    public EfficiencyStats PlayerStats { get; }
    public IReadOnlyDictionary<int, EfficiencyCompanion> Companions { get; }
    public EfficiencyKnowledgeSnapshot(uint? roleId, EfficiencyStats? playerStats = null,
        IEnumerable<KeyValuePair<int, EfficiencyCompanion>>? companions = null, string playerName = "玩家")
    {
        RoleId = roleId;
        PlayerName = playerName ?? throw new ArgumentNullException(nameof(playerName));
        PlayerStats = playerStats ?? new();
        var copy = (companions ?? []).ToFrozenDictionary();
        foreach (var (slot, companion) in copy)
        {
            _ = EfficiencySubject.Companion(slot);
            ArgumentNullException.ThrowIfNull(companion);
            ArgumentNullException.ThrowIfNull(companion.Stats);
        }
        Companions = copy;
    }
}

public sealed record EfficiencyBattleUnit(uint? Pid = null, uint? MasterId = null, int? CompanionSlot = null);

/// <summary>ObservedAt is monotonic seconds (or recorded offline seconds); null uses the injected clock.</summary>
public abstract record EfficiencyEvent
{
    public double? ObservedAt { get; init; }
    public bool? Offline { get; init; }
}
public sealed record EfficiencyRefresh : EfficiencyEvent;
public sealed record EfficiencyEventEnd : EfficiencyEvent;
public sealed record EfficiencyStarInfo(long Experience) : EfficiencyEvent;
public sealed record EfficiencyAttributeSet(EfficiencySubject Subject, int Kind, long Value,
    int Parameter = 0, int? HumanKind = null) : EfficiencyEvent;
public sealed record EfficiencyBattleStart : EfficiencyEvent
{
    public ImmutableArray<EfficiencyBattleUnit> Units { get; }
    public EfficiencyBattleStart(IEnumerable<EfficiencyBattleUnit> units)
    {
        ArgumentNullException.ThrowIfNull(units);
        Units = units.ToImmutableArray();
        foreach (var unit in Units) ArgumentNullException.ThrowIfNull(unit);
    }
}

public sealed record EfficiencyHistorySample(BigInteger Earned, double ObservedAt);

/// <summary>Historical state is immutable; inferred labels never replace the separate confirmed evidence.</summary>
public sealed record EfficiencyRowSnapshot
{
    public uint Identity { get; init; }
    public string Name { get; init; } = "";
    public long? Experience { get; init; }
    public long? Level { get; init; }
    public long? Degree { get; init; }
    public long? ConfirmedLevel { get; init; }
    public long? ConfirmedDegree { get; init; }
    public bool LevelInferred { get; init; }
    public bool DegreeInferred { get; init; }
    public long? LastTotal { get; init; }
    public BigInteger? LastGain { get; init; }
    public BigInteger Earned { get; init; }
    public long Count { get; init; }
    public ImmutableArray<EfficiencyHistorySample> History { get; init; } = [];
    public double? FirstTime { get; init; }
    public double? LastTime { get; init; }
    public long? SampleDegree { get; init; }
}

public sealed class EfficiencySnapshot
{
    public static EfficiencySnapshot Empty { get; } = new(null,
        new Dictionary<EfficiencySubject, EfficiencyRowSnapshot>(), false, [], [], 0, false);

    public uint? RoleId { get; }
    public IReadOnlyDictionary<EfficiencySubject, EfficiencyRowSnapshot> Rows { get; }
    public bool Pending { get; }
    public ImmutableArray<EfficiencySubject> Dirty { get; }
    public ImmutableArray<EfficiencySubject> Participants { get; }
    public long Battles { get; }
    public bool Offline { get; }
    internal EfficiencySnapshot(uint? roleId, IDictionary<EfficiencySubject, EfficiencyRowSnapshot> rows,
        bool pending, IEnumerable<EfficiencySubject> dirty, IEnumerable<EfficiencySubject> participants,
        long battles, bool offline)
    {
        RoleId = roleId;
        Rows = rows.ToFrozenDictionary();
        Pending = pending;
        Dirty = dirty.ToImmutableArray();
        Participants = participants.OrderBy(x => x.ToString(), StringComparer.Ordinal).ToImmutableArray();
        Battles = battles;
        Offline = offline;
    }
}

public sealed record EfficiencyProgress(long? Remaining, double? Percent, long? FirstRebirth190Remaining)
{
    public static EfficiencyProgress Unknown { get; } = new(null, null, null);
}
public sealed record EfficiencyRate(double? ExperiencePerMinute, long Count);
public sealed record EfficiencyRates(EfficiencyRate All, EfficiencyRate Last10, EfficiencyRate Last30);
