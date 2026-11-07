using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class EfficiencyKnowledgeProjectorTests
{
    private static WorldPlayer Player(uint role = 71, string name = "Current local name") =>
        new(role, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], name, 0);
    private static CompanionProfileSnapshot Profile(byte slot = 0, uint npc = 8000, string? name = "Confirmed name") =>
        new(new(slot, npc, 10000, 12, 300, 50, 10, 11, 12, 13, 14, 0, 100, 1, 0, name,
            [], [], 0, 0, 0, 0, 0, 0, 0), ImmutableDictionary<uint, CompanionLearnedSkill>.Empty,
            ImmutableDictionary<string, long>.Empty);
    private static CompanionReceiveSnapshot Companions(CompanionProfileSnapshot? profile = null) =>
        new() { Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(0, profile ?? Profile()) };
    private static PlayerKnowledgeSnapshot Stats(long exp = 20000, long level = 15, long degree = 0) =>
        new() { Stats = new Dictionary<string, long> { ["exp"] = exp, ["level"] = level, ["degree"] = degree }.ToImmutableDictionary() };

    [Fact]
    public void DefaultPlayerAndCompanionZeroHaveDistinctIdentityAndDictionaryKeys()
    {
        var zero = EfficiencySubject.Companion(0);
        Assert.Equal(default, EfficiencySubject.Player);
        Assert.True(EfficiencySubject.Player.IsPlayer);
        Assert.False(zero.IsPlayer);
        Assert.NotEqual(EfficiencySubject.Player, zero);
        Assert.Equal("self", EfficiencySubject.Player.ToString());
        Assert.Equal("follow:0", zero.ToString());
        var knowledge = EfficiencyKnowledgeProjector.Project(Stats(), Companions(), Player());
        var snapshot = EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge, new EfficiencyRefresh { ObservedAt = 0 });
        Assert.Equal(2, snapshot.Rows.Count);
        Assert.Equal(71u, snapshot.Rows[EfficiencySubject.Player].Identity);
        Assert.Equal(8000u, snapshot.Rows[zero].Identity);
        Assert.Equal(20000, snapshot.Rows[EfficiencySubject.Player].Experience);
        Assert.Equal(10000, snapshot.Rows[zero].Experience);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(256)]
    [InlineData(65535)]
    public void FullWireSubjectRangeIsPreservedButOnlySlotsOneThrough255AreParticipants(int slot)
    {
        var subject = EfficiencySubject.Companion(slot);
        var knowledge = new EfficiencyKnowledgeSnapshot(71, companions:
            new Dictionary<int, EfficiencyCompanion> { [slot] = new(8000, new(10000, 12, 0)) });
        var snapshot = EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge,
            new EfficiencyBattleStart([new(8000, 71, slot)]) { ObservedAt = 0 });
        Assert.True(snapshot.Pending);
        Assert.Empty(snapshot.Participants);
        Assert.True(snapshot.Rows.ContainsKey(subject));
        var attribute = new AttributeSetEvent(2, $"follow:{slot}", 4, (ushort)slot, 36, "exp", 1, 123, 0);
        snapshot = EfficiencyReceiveReducer.Apply(snapshot, knowledge, attribute, 1);
        Assert.Equal(subject, Assert.Single(snapshot.Dirty));
        Assert.Equal(123, snapshot.Rows[subject].Experience);
        Assert.Null(snapshot.Rows[EfficiencySubject.Player].Experience);
    }

    [Theory]
    [InlineData(256)]
    [InlineData(65535)]
    public void UnknownWireSlotsRefreshWithoutCreatingOrBorrowingAProfile(int slot)
    {
        var value = new AttributeSetEvent(2, $"follow:{slot}", 4, (ushort)slot, 36, "exp", 1, 123, 0);
        var result = EfficiencyReceiveReducer.Apply(EfficiencySnapshot.Empty,
            EfficiencyKnowledgeProjector.Project(Stats(), Companions(), Player()), value, 0);
        Assert.Equal(2, result.Rows.Count);
        Assert.False(result.Rows.ContainsKey(EfficiencySubject.Companion(slot)));
        Assert.Equal(10000, result.Rows[EfficiencySubject.Companion(0)].Experience);
    }

    [Theory]
    [InlineData(long.MinValue)]
    [InlineData(-4294967295L)]
    [InlineData(4294967295L)]
    [InlineData(long.MaxValue)]
    public void FullInt64EvidenceAndSampleDegreeNeverNarrowOrBecomeInventedCurveValues(long value)
    {
        var profile = Profile() with { StatOverrides = new Dictionary<string, long>
            { ["exp"] = -7, ["level"] = value, ["degree"] = value }.ToImmutableDictionary() };
        var knowledge = EfficiencyKnowledgeProjector.Project(Stats(level: value, degree: value), Companions(profile), Player());
        Assert.Equal(value, knowledge.PlayerStats.Level);
        Assert.Equal(value, knowledge.Companions[0].Stats.Degree);
        var snapshot = EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge,
            new EfficiencyBattleStart([new(71)]) { ObservedAt = 0 });
        snapshot = EfficiencyReducer.Apply(snapshot, knowledge,
            new EfficiencyAttributeSet(EfficiencySubject.Player, 36, 20000) { ObservedAt = 1 });
        snapshot = EfficiencyReducer.Apply(snapshot, knowledge, new EfficiencyEventEnd { ObservedAt = 2 });
        foreach (var row in snapshot.Rows.Values)
        {
            Assert.Equal(value, row.Level); Assert.Equal(value, row.Degree);
            Assert.Equal(value, row.ConfirmedLevel); Assert.Equal(value, row.ConfirmedDegree);
            Assert.False(row.LevelInferred); Assert.False(row.DegreeInferred);
        }
        Assert.Equal(value, snapshot.Rows[EfficiencySubject.Player].SampleDegree);
        Assert.Null(EfficiencyRules.Need(value, 0L));
        Assert.Null(EfficiencyRules.Need(1L, value));
        Assert.Null(EfficiencyRules.Cumulative(value, 0L));
        Assert.Null(EfficiencyRules.Cumulative(1L, value));
        Assert.Null(EfficiencyRules.MaximumLevel(value));
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(20000, value, 0L));
        Assert.Equal(EfficiencyProgress.Unknown, EfficiencyRules.Progress(20000, 15L, value));
    }

    [Fact]
    public void ReadinessIsNotRequiredAndMissingStatsStayUnknownWhileExplicitZeroOverridesWin()
    {
        var profile = Profile() with { StatOverrides = new Dictionary<string, long>
            { ["exp"] = 0, ["level"] = 0, ["degree"] = -1 }.ToImmutableDictionary() };
        var player = new PlayerKnowledgeSnapshot { Stats = ImmutableDictionary<string, long>.Empty.Add("exp", 0) };
        var companions = Companions(profile);
        Assert.False(player.Ready); Assert.False(companions.Ready);
        var knowledge = EfficiencyKnowledgeProjector.Project(player, companions, null);
        Assert.Null(knowledge.RoleId);
        Assert.Equal("玩家", knowledge.PlayerName);
        Assert.Equal(new EfficiencyStats(0), knowledge.PlayerStats);
        Assert.Equal(new EfficiencyStats(0, 0, -1, "Confirmed name"), knowledge.Companions[0].Stats);
        Assert.Single(knowledge.Companions);
        Assert.Empty(EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge, new EfficiencyRefresh()).Rows);
        Assert.Equal(10000, profile.Data.Exp);
        Assert.Equal(12, profile.Data.Level);
    }

    [Fact]
    public void CompanionInferenceKeepsAnOutOfInt32ConfirmedLevelSeparate()
    {
        var profile = Profile() with { StatOverrides = ImmutableDictionary<string, long>.Empty.Add("level", uint.MaxValue) };
        var knowledge = EfficiencyKnowledgeProjector.Project(Stats(), Companions(profile), Player());
        var row = EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge, new EfficiencyRefresh { ObservedAt = 0 })
            .Rows[EfficiencySubject.Companion(0)];
        Assert.Equal((long)uint.MaxValue, row.ConfirmedLevel);
        Assert.InRange(row.Level!.Value, 1, 199);
        Assert.True(row.LevelInferred);
        Assert.Equal(0, row.ConfirmedDegree);
    }

    [Fact]
    public void CompleteMembershipPostLocalIdentityAndDetachedNamesAreExplicit()
    {
        var names = new Dictionary<uint, string> { [8000] = "Catalog name" };
        var source = Companions(Profile(name: null));
        var knowledge = EfficiencyKnowledgeProjector.Project(Stats(), source, Player(72, "Post local"), names);
        names[8000] = "Later catalog";
        var refreshed = EfficiencyKnowledgeProjector.Project(Stats(), source with
            { Companions = source.Companions.Remove(0) }, Player(0));
        Assert.Equal(72u, knowledge.RoleId);
        Assert.Equal("Post local", knowledge.PlayerName);
        Assert.Single(knowledge.Companions);
        Assert.Equal("Catalog name", knowledge.Companions[0].CatalogName);
        Assert.Empty(refreshed.Companions);
        Assert.Equal(0u, refreshed.RoleId);
        var snapshot = EfficiencyReducer.Apply(EfficiencySnapshot.Empty, knowledge, new EfficiencyRefresh { ObservedAt = 0 });
        Assert.Equal("Catalog name", snapshot.Rows[EfficiencySubject.Companion(0)].Name);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<int, EfficiencyCompanion>)knowledge.Companions).Clear());
    }

    [Fact]
    public void InvalidRequiredSnapshotsAndNestedValuesAreRejectedWithoutReplacingPreviousKnowledge()
    {
        var previous = EfficiencyKnowledgeProjector.Project(Stats(), Companions(), Player());
        Assert.Throws<ArgumentNullException>(() => EfficiencyKnowledgeProjector.Project(null!, Companions(), Player()));
        Assert.Throws<ArgumentNullException>(() => EfficiencyKnowledgeProjector.Project(Stats(), null!, Player()));
        Assert.Throws<ArgumentNullException>(() => EfficiencyKnowledgeProjector.Project(Stats() with { Stats = null! }, Companions(), Player()));
        Assert.Throws<ArgumentNullException>(() => EfficiencyKnowledgeProjector.Project(Stats(), new() { Companions = null! }, Player()));
        foreach (var profile in new CompanionProfileSnapshot[] { null!, Profile() with { Data = null! }, Profile() with { StatOverrides = null! } })
        {
            var invalid = new CompanionReceiveSnapshot
                { Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(0, profile) };
            Assert.Throws<ArgumentNullException>(() => EfficiencyKnowledgeProjector.Project(Stats(), invalid, Player()));
        }
        Assert.Equal(71u, previous.RoleId);
        Assert.Equal(10000, previous.Companions[0].Stats.Experience);
    }
}
