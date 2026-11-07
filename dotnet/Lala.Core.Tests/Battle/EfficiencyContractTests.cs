using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class EfficiencyContractTests
{
    private static readonly EfficiencySubject Pet = EfficiencySubject.Companion(2);
    private static EfficiencyKnowledgeSnapshot Knowledge(long total = 10000, uint? identity = 8002, int? level = 12, int? degree = 0) =>
        new(71, new(20000, 15, 0), new Dictionary<int, EfficiencyCompanion> { [2] = new(identity, new(total, level, degree, "Pet")) });
    private static EfficiencySnapshot Battle(EfficiencyTracker tracker, long total, double end, bool pet = true)
    {
        var knowledge = Knowledge(total);
        tracker.Observe(knowledge, new EfficiencyBattleStart(pet ? [new(71), new(8002, 71, 2)] : [new(71)]) { ObservedAt = end - 2 });
        tracker.Observe(knowledge, new EfficiencyAttributeSet(pet ? Pet : EfficiencySubject.Player, 36, total, HumanKind: pet ? 4 : null) { ObservedAt = end - 1 });
        return tracker.Observe(knowledge, new EfficiencyEventEnd { ObservedAt = end });
    }

    [Fact]
    public void InjectedClockIsUsedOnlyWhenAnEligibleObservationHasNoRecordedTime()
    {
        int calls = 0;
        var tracker = new EfficiencyTracker(() => { calls++; return 0; });
        tracker.Observe(new(null), new EfficiencyRefresh());
        tracker.Observe(Knowledge(), new EfficiencyRefresh { ObservedAt = 42 });
        Assert.Equal(0, calls);
        tracker.Observe(Knowledge(), new EfficiencyBattleStart([new(71)]));
        tracker.Observe(Knowledge(), new EfficiencyStarInfo(100));
        var snapshot = tracker.Observe(Knowledge(), new EfficiencyEventEnd());
        Assert.Equal(3, calls);
        Assert.Equal(0, snapshot.Rows[EfficiencySubject.Player].FirstTime);
        Assert.Equal(0, snapshot.Rows[EfficiencySubject.Player].LastTime);
        Assert.Null(snapshot.Rows[EfficiencySubject.Player].LastGain);
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void InvalidClockCannotConsumePendingBattleOrSetOffline(double time)
    {
        var tracker = new EfficiencyTracker(() => time);
        Battle(tracker, 10000, 10);
        tracker.Observe(Knowledge(), new EfficiencyBattleStart([new(71)]) { ObservedAt = 20 });
        var result = tracker.Observe(Knowledge(), new EfficiencyEventEnd { Offline = true });
        Assert.True(result.Pending);
        Assert.False(result.Offline);
        Assert.Equal(1, result.Battles);
    }

    [Fact]
    public void InferredLevelDoesNotOverwriteConfirmedEvidenceAndMatchingConfirmationClearsMarker()
    {
        var tracker = new EfficiencyTracker();
        long total = EfficiencyRules.Cumulative(16, 0)!.Value + 5;
        var row = tracker.Observe(Knowledge(total), new EfficiencyRefresh { ObservedAt = 0 }).Rows[Pet];
        Assert.Equal(16, row.Level);
        Assert.Equal(12, row.ConfirmedLevel);
        Assert.True(row.LevelInferred);
        Assert.Equal(0, row.ConfirmedDegree);
        row = tracker.Observe(Knowledge(total, level: 16), new EfficiencyRefresh { ObservedAt = 1 }).Rows[Pet];
        Assert.Equal(16, row.ConfirmedLevel);
        Assert.False(row.LevelInferred);
    }

    [Fact]
    public void UniqueDegreeInferenceRemainsDistinctFromConfirmation()
    {
        var tracker = new EfficiencyTracker();
        long total = EfficiencyRules.Cumulative(12, 0)!.Value + 5;
        var row = tracker.Observe(Knowledge(total, degree: null), new EfficiencyRefresh { ObservedAt = 0 }).Rows[Pet];
        Assert.Equal(0, row.Degree);
        Assert.True(row.DegreeInferred);
        Assert.Null(row.ConfirmedDegree);
        row = tracker.Observe(Knowledge(total), new EfficiencyRefresh { ObservedAt = 1 }).Rows[Pet];
        Assert.False(row.DegreeInferred);
        Assert.Equal(0, row.ConfirmedDegree);
    }

    [Fact]
    public void AmbiguousDegreeAndPlayerLevelAreNeverInvented()
    {
        var tracker = new EfficiencyTracker();
        var snapshot = tracker.Observe(new(71, new(10000), new Dictionary<int, EfficiencyCompanion>
            { [2] = new(8002, new(0, 1)) }), new EfficiencyRefresh { ObservedAt = 0 });
        Assert.Null(snapshot.Rows[Pet].Degree);
        Assert.False(snapshot.Rows[Pet].DegreeInferred);
        Assert.Null(snapshot.Rows[EfficiencySubject.Player].Level);
        Assert.Null(snapshot.Rows[EfficiencySubject.Player].Degree);
    }

    [Fact]
    public void MissingParticipantEvidenceKeepsConfirmedRatesButBreaksNextGain()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10);
        var before = Battle(tracker, 10120, 30).Rows[Pet];
        tracker.Observe(Knowledge(10120), new EfficiencyBattleStart([new(71), new(8002, 71, 2)]) { ObservedAt = 40 });
        var missing = tracker.Observe(Knowledge(10120), new EfficiencyEventEnd { ObservedAt = 50 }).Rows[Pet];
        Assert.Null(missing.LastTotal);
        Assert.Null(missing.LastGain);
        Assert.Equal(EfficiencyRules.Rates(before), EfficiencyRules.Rates(missing));
        var resumed = Battle(tracker, 10250, 70).Rows[Pet];
        Assert.Equal(new BigInteger(120), resumed.Earned);
        Assert.Equal(1, resumed.Count);
        Assert.Null(resumed.LastGain);
        Assert.Single(resumed.History);
    }

    [Fact]
    public void IdleParticipantHistoryIsUntouchedByPlayerOnlyBattle()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10);
        var before = Battle(tracker, 10120, 30).Rows[Pet];
        tracker.Observe(Knowledge(10120), new EfficiencyBattleStart([new(71)]) { ObservedAt = 40 });
        var after = tracker.Observe(Knowledge(10120), new EfficiencyEventEnd { ObservedAt = 50 }).Rows[Pet];
        Assert.Equal(before, after);
    }

    [Fact]
    public void QuestRewardRebasesWithoutIncreasingEarned()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10);
        tracker.Observe(Knowledge(10500), new EfficiencyAttributeSet(Pet, 36, 10500, HumanKind: 4) { ObservedAt = 20 });
        var row = Battle(tracker, 10540, 40).Rows[Pet];
        Assert.Equal(new BigInteger(40), row.Earned);
        Assert.Equal(new BigInteger(40), row.LastGain);
    }

    [Fact]
    public void ExplicitZeroGainIsValidSample()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10);
        var row = Battle(tracker, 10000, 20).Rows[Pet];
        Assert.Equal(BigInteger.Zero, row.LastGain);
        Assert.Equal(1, row.Count);
        Assert.Equal(0, EfficiencyRules.Rates(row).All.ExperiencePerMinute);
    }

    [Fact]
    public void UnconfirmedCompanionCannotCreateOrUpdateRow()
    {
        var tracker = new EfficiencyTracker();
        var result = tracker.Observe(Knowledge(identity: null), new EfficiencyAttributeSet(Pet, 36, 42, HumanKind: 4) { ObservedAt = 0 });
        Assert.False(result.Rows.ContainsKey(Pet));
        result = tracker.Observe(Knowledge(), new EfficiencyAttributeSet(EfficiencySubject.Companion(5), 36, 42, HumanKind: 4) { ObservedAt = 1 });
        Assert.False(result.Rows.ContainsKey(EfficiencySubject.Companion(5)));
    }

    [Fact]
    public void CompanionReplacementCannotInheritIdentityHistory()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10);
        Battle(tracker, 10120, 30);
        var replaced = tracker.Observe(Knowledge(10120, identity: 9002), new EfficiencyRefresh { ObservedAt = 40 }).Rows[Pet];
        Assert.Equal(9002u, replaced.Identity);
        Assert.Equal(BigInteger.Zero, replaced.Earned);
        Assert.Empty(replaced.History);
        Assert.Null(replaced.LastTotal);
    }

    [Fact]
    public void RowNamesUseStatsThenInjectedCatalogThenSlotFallback()
    {
        var tracker = new EfficiencyTracker();
        var knowledge = new EfficiencyKnowledgeSnapshot(71, companions: new Dictionary<int, EfficiencyCompanion>
        {
            [1] = new(9001, new(Name: "Confirmed"), "Catalog"),
            [2] = new(9002, new(Name: ""), "Catalog"),
            [3] = new(9003, new(), "")
        });
        var rows = tracker.Observe(knowledge, new EfficiencyRefresh { ObservedAt = 0 }).Rows;
        Assert.Equal("Confirmed", rows[EfficiencySubject.Companion(1)].Name);
        Assert.Equal("Catalog", rows[Pet].Name);
        Assert.Equal("夥伴 #3", rows[EfficiencySubject.Companion(3)].Name);
    }

    [Fact]
    public void DetachedKnowledgeUnitsAndPublishedSnapshotsCannotBeMutatedByCaller()
    {
        var companions = new Dictionary<int, EfficiencyCompanion> { [2] = new(8002, new(10000, 12, 0)) };
        var knowledge = new EfficiencyKnowledgeSnapshot(71, companions: companions);
        var units = new List<EfficiencyBattleUnit> { new(71), new(8002, 71, 2) };
        var start = new EfficiencyBattleStart(units) { ObservedAt = 0 };
        companions.Clear(); units.Clear();
        var tracker = new EfficiencyTracker();
        var snapshot = tracker.Observe(knowledge, start);
        Assert.Equal(2, start.Units.Length);
        Assert.Single(knowledge.Companions);
        Assert.True(snapshot.Pending);
        tracker.Reset();
        Assert.Equal(2, snapshot.Rows.Count);
        Assert.Equal(2, snapshot.Participants.Length);
        Assert.True(snapshot.Pending);
        Assert.Empty(tracker.Snapshot.Rows);
        var mutableRows = Assert.IsAssignableFrom<IDictionary<EfficiencySubject, EfficiencyRowSnapshot>>(snapshot.Rows);
        Assert.Throws<NotSupportedException>(() => mutableRows.Clear());
    }

    [Fact]
    public void HistoryIsBoundedButAllTimeCountersRemainComplete()
    {
        var tracker = new EfficiencyTracker();
        EfficiencyRowSnapshot? row = null;
        for (int i = 0; i < 40; i++) row = Battle(tracker, 10000 + i * 10, i * 10).Rows[Pet];
        Assert.NotNull(row);
        Assert.Equal(31, row.History.Length);
        Assert.Equal(39, row.Count);
        Assert.Equal(new BigInteger(390), row.Earned);
        Assert.Equal(10, EfficiencyRules.Rates(row).Last10.Count);
        Assert.Equal(30, EfficiencyRules.Rates(row).Last30.Count);
    }

    [Fact]
    public void ResetClearsRoleAndEveryMeasurement()
    {
        var tracker = new EfficiencyTracker();
        Battle(tracker, 10000, 10); Battle(tracker, 10120, 30);
        tracker.Reset();
        var snapshot = tracker.Snapshot;
        Assert.Null(snapshot.RoleId);
        Assert.False(snapshot.Offline);
        Assert.False(snapshot.Pending);
        Assert.Empty(snapshot.Dirty); Assert.Empty(snapshot.Participants); Assert.Empty(snapshot.Rows);
        Assert.Equal(0, snapshot.Battles);
        Assert.Null(Battle(tracker, 10200, 50).Rows[Pet].LastGain);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(0)]
    [InlineData(256)]
    public void InvalidCompanionSlotsAreRejectedAtTypedInputBoundary(int slot) =>
        Assert.Throws<ArgumentOutOfRangeException>(() => EfficiencySubject.Companion(slot));

    [Theory]
    [InlineData(0, 0)]
    [InlineData(401, 0)]
    [InlineData(1, -1)]
    [InlineData(1, 3)]
    public void UnsupportedCurveInputsHaveNoInventedValues(int level, int degree)
    {
        Assert.Null(EfficiencyRules.Need(level, degree));
        Assert.Null(EfficiencyRules.Cumulative(level, degree));
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(0, level, degree));
    }

    [Fact]
    public void MissingProgressEvidenceRemainsUnknown()
    {
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(null, 1, 0));
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(0, null, 0));
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(0, 1, null));
    }

    [Fact]
    public void RatesDoNotInventIntervalsFromEmptySingleOrReversedHistory()
    {
        var empty = EfficiencyRules.Rates(new());
        Assert.Null(empty.All.ExperiencePerMinute);
        Assert.Null(empty.Last10.ExperiencePerMinute);
        var reversed = EfficiencyRules.Rates(new()
        {
            Earned = 100, Count = 1, FirstTime = 10, LastTime = 0,
            History = ImmutableArray.Create(new EfficiencyHistorySample(0, 10), new EfficiencyHistorySample(100, 0))
        });
        Assert.Null(reversed.All.ExperiencePerMinute);
        Assert.Null(reversed.Last10.ExperiencePerMinute);
        Assert.Equal(1, reversed.Last10.Count);
    }
}
