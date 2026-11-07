using System.Collections.Frozen;
using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Xunit;

namespace Lala.Core.Tests.Social;

public sealed class GuildEventContractTests
{
    private static GuildRosterEvent Roster(params GuildMember[] members) =>
        new("private guild", "discarded chief", 72, members.ToFrozenDictionary(member => member.RoleId), 3);
    private static GuildEventSnapshot Ready(params GuildMember[] members) =>
        GuildEventReducer.Apply(GuildEventSnapshot.Empty, Roster(members));

    [Fact]
    public void DefaultsAndEmptyRosterHaveDistinctReadinessWithoutAssumedMembership()
    {
        var empty = GuildEventSnapshot.Empty;
        Assert.False(empty.Ready); Assert.Null(empty.Serial); Assert.Empty(empty.Members);
        var ready = GuildEventReducer.Apply(empty, Roster() with { Serial = 0, Level = 0, Name = "" });
        Assert.True(ready.Ready); Assert.Equal(0u, ready.Serial); Assert.Equal((byte)0, ready.Level);
        Assert.Equal("", ready.Name); Assert.Empty(ready.Members);
        Assert.False(empty.Ready);
    }

    [Fact]
    public void ProfilesAndAddsBeforeRosterAreIgnoredRatherThanBuffered()
    {
        var empty = GuildEventSnapshot.Empty;
        Assert.Same(empty, GuildEventReducer.Apply(empty, new GuildMemberProfileEvent(1, "early")));
        Assert.Same(empty, GuildEventReducer.Apply(empty, new GuildMemberAddedEvent(1)));
        Assert.Same(empty, GuildEventReducer.Apply(empty, new GuildMemberRemovedEvent(1)));
        var ready = GuildEventReducer.Apply(empty, Roster());
        var added = GuildEventReducer.Apply(ready, new GuildMemberAddedEvent(1));
        Assert.Equal("", added.Members[1].Name);
    }

    [Fact]
    public void AddIsSetDefaultAndProfileDoesNotCreateMembers()
    {
        var ready = Ready(new GuildMember(1, "retained"));
        Assert.Same(ready, GuildEventReducer.Apply(ready, new GuildMemberAddedEvent(1)));
        Assert.Same(ready, GuildEventReducer.Apply(ready, new GuildMemberProfileEvent(2, "unknown")));
        var zero = GuildEventReducer.Apply(ready, new GuildMemberAddedEvent(0));
        Assert.Equal(new GuildMember(0, ""), zero.Members[0]);
        var named = GuildEventReducer.Apply(zero, new GuildMemberProfileEvent(0, "renamed"));
        Assert.Equal("", zero.Members[0].Name); Assert.Equal("renamed", named.Members[0].Name);
        Assert.Equal("retained", named.Members[1].Name);
    }

    [Fact]
    public void SelfRemovalDoesNotImplyLeavingOrClearReadiness()
    {
        var state = Ready(new GuildMember(1, "self"), new(2, "other"));
        var removed = GuildEventReducer.Apply(state, new GuildMemberRemovedEvent(1), 1);
        Assert.True(removed.Ready); Assert.Equal(state.Serial, removed.Serial);
        Assert.Single(removed.Members); Assert.True(removed.Members.ContainsKey(2));
        Assert.Equal(2, state.Members.Count);
    }

    [Theory]
    [InlineData(null, 0u, false)]
    [InlineData(null, 1u, false)]
    [InlineData(0u, 0u, true)]
    [InlineData(1u, 0u, false)]
    [InlineData(1u, 1u, true)]
    [InlineData(1u, 2u, false)]
    [InlineData(uint.MaxValue, uint.MaxValue, true)]
    public void SuccessfulLeaveMatchesOnlyTheExplicitCurrentRole(uint? ownRoleId, uint leaving, bool cleared)
    {
        var state = Ready(new GuildMember(1, "self"));
        var result = GuildEventReducer.Apply(state, new GuildLeaveResultEvent(0, leaving), ownRoleId);
        Assert.Same(cleared ? GuildEventSnapshot.Empty : state, result);
    }

    [Fact]
    public void ResetDoesNotInventGenerationProtectionAgainstLateRoster()
    {
        var initial = Ready(new GuildMember(1, "old"));
        var cleared = GuildEventReducer.Apply(initial, new GuildDisbandResultEvent(0));
        Assert.Same(GuildEventSnapshot.Empty, cleared);
        Assert.Same(cleared, GuildEventReducer.Apply(cleared, new GuildMemberAddedEvent(1)));
        var late = GuildEventReducer.Apply(cleared, Roster(new GuildMember(2, "late")));
        Assert.True(late.Ready); Assert.Equal("late", late.Members[2].Name);
        Assert.Equal("old", initial.Members[1].Name);
    }

    [Fact]
    public void RoleAndActionEventsAreNoopsWithoutLifecycleOrActionsIntegration()
    {
        var state = Ready(new GuildMember(1, "self"));
        ServerEvent[] observations =
        [
            new ServerLayoutEvent(new RoleListAvailableEvent([])),
            new ServerLayoutEvent(new WorldPlayerEvent(new(2, 0, 1, 2, 3, 0, 0, 0, 0, 0, 0, false, [], "other", 0))),
            new ServerSocialEvent(new GuildSignStateEvent(2)),
            new ServerSocialEvent(new GuildSignResultEvent(0)),
            new ServerSocialEvent(new GuildDonateStateEvent(3, true)),
            new ServerSocialEvent(new GuildActionErrorEvent(1)),
            new ServerSocialEvent(new UiSellNoticeEvent()),
            new ServerSocialEvent(new UiSellUpdateEvent(1, 2)),
            new ServerSocialEvent(new UiSellSnapshotEvent(new Dictionary<byte, byte>().ToFrozenDictionary())),
            new ServerSocialEvent(new UiSellDayResetEvent()),
            new ServerSocialEvent(new TeamLeaveEvent(1)),
            new ServerSocialEvent(new ChatResultEvent(0, "success"))
        ];
        foreach (var observation in observations) Assert.Same(state, GuildEventReducer.Apply(state, observation, 2));
    }

    [Fact]
    public void RosterReplacementAndIndependentBranchesNeverMutatePublishedStateOrInput()
    {
        var source = new Dictionary<uint, GuildMember> { [1] = new(1, "original") };
        var roster = Roster() with { Members = source.ToFrozenDictionary() };
        var initial = GuildEventReducer.Apply(GuildEventSnapshot.Empty, roster);
        source[1] = new(1, "changed outside");
        var renamed = GuildEventReducer.Apply(initial, new GuildMemberProfileEvent(1, "renamed"));
        var removed = GuildEventReducer.Apply(initial, new GuildMemberRemovedEvent(1));
        var replacement = GuildEventReducer.Apply(renamed, Roster(new GuildMember(2, "replacement")) with { Serial = 99 });
        Assert.Equal("original", initial.Members[1].Name); Assert.Equal("original", roster.Members[1].Name);
        Assert.Equal("renamed", renamed.Members[1].Name); Assert.Empty(removed.Members);
        Assert.Single(replacement.Members); Assert.False(replacement.Members.ContainsKey(1));
        Assert.Equal(99u, replacement.Serial); Assert.Equal(72u, initial.Serial);
        Assert.IsType<ImmutableDictionary<uint, GuildMember>>(initial.Members);
    }

    [Fact]
    public void DiagnosticsDoNotExposeNamesAndNoRankOrChiefIsInvented()
    {
        var state = Ready(new GuildMember(1, "private member"));
        Assert.DoesNotContain("private", state.ToString());
        Assert.DoesNotContain("private", state.Members[1].ToString());
        Assert.Null(typeof(GuildEventSnapshot).GetProperty("Chief"));
        Assert.Null(typeof(GuildMember).GetProperty("Rank"));
    }

    [Fact]
    public void NullInputsAreRejectedAtBothTypedBoundaries()
    {
        Assert.Throws<ArgumentNullException>(() => GuildEventReducer.Apply(null!, new GuildDisbandResultEvent(0)));
        Assert.Throws<ArgumentNullException>(() => GuildEventReducer.Apply(null!, new ServerSocialEvent(new GuildDisbandResultEvent(0))));
        Assert.Throws<ArgumentNullException>(() => GuildEventReducer.Apply(GuildEventSnapshot.Empty, (SocialEvent)null!));
        Assert.Throws<ArgumentNullException>(() => GuildEventReducer.Apply(GuildEventSnapshot.Empty, (ServerEvent)null!));
    }
}
