using System.Collections.Immutable;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Xunit;

namespace Lala.Core.Tests.Social.Party;

public sealed class PartyEventContractTests
{
    private static PartyEventSnapshot Apply(PartyEventSnapshot state, SocialEvent observation, uint? own = null, double now = 100) =>
        PartyEventReducer.Apply(state, observation, now, own);
    private static TeamListEvent List(params TeamSnapshot[] teams) => new([.. teams]);
    private static PartyEventSnapshot Roster(params TeamSnapshot[] teams) => Apply(PartyEventSnapshot.Empty, List(teams));
    private static PartyEventSnapshot Pending() => PartyEventSnapshot.Empty with
    {
        Outbound = new Dictionary<string, PartyOutboundRequest>
        {
            ["invite:1"] = new(1, 115), ["apply:2"] = new(2, 116), ["invite:0"] = new(0, 117)
        }.ToImmutableDictionary(), EnabledRequested = true
    };

    [Fact]
    public void DefaultsDoNotInventReadinessMembershipOrPermission()
    {
        var state = PartyEventSnapshot.Empty;
        Assert.Empty(state.Teams); Assert.Empty(state.Nearby); Assert.Empty(state.Requests); Assert.Empty(state.Outbound);
        Assert.Null(state.Enabled); Assert.Null(state.EnabledRequested); Assert.Null(state.OwnTeam(null));
        Assert.Null(state.OwnTeam(0)); Assert.Equal("尚無隊伍資料", state.Status);
        Assert.Equal("隊伍名單已更新（伺服器確認）", Apply(state, List()).Status);
    }

    [Fact]
    public void RostersMergeAndKeepFirstInsertionOrderIncludingDuplicateLeaderRows()
    {
        var first = Roster(new(7, [7, 42]), new(1, [1, 42]));
        var second = Apply(first, List(new(7, [7, 2]), new(3, [3, 42]), new(7, [7, 42, 2])));
        Assert.Equal(new uint[] { 7, 1, 3 }, second.Teams.Select(t => t.LeaderId));
        Assert.Equal(new uint[] { 7, 42, 2 }, second.Teams[0].Members);
        Assert.Equal(7u, second.OwnTeam(42)!.LeaderId);
        Assert.Equal(7u, Apply(second, List()).OwnTeam(42)!.LeaderId);
        Assert.Equal(new uint[] { 7, 42 }, first.Teams[0].Members);
    }

    [Fact]
    public void RepeatedJoinDoesNotDuplicateButCanExceedRosterLimitAndRecreateLateTeam()
    {
        var state = PartyEventSnapshot.Empty;
        foreach (var role in new uint[] { 1, 2, 3, 4, 5, 5 }) state = Apply(state, new TeamJoinEvent(1, role));
        Assert.Equal(new uint[] { 1, 2, 3, 4, 5 }, state.Teams[0].Members);
        var left = Apply(state, new TeamLeaveEvent(1));
        Assert.Empty(left.Teams);
        var late = Apply(left, new TeamJoinEvent(1, 5));
        Assert.Equal(new uint[] { 1, 5 }, late.Teams[0].Members);
        Assert.Equal(5, state.Teams[0].Members.Length);
    }

    [Fact]
    public void LeaveTouchesEveryContainingTeamAndDisbandsLeaderOrTwoMemberTeams()
    {
        var state = Roster(new(1, [1, 2, 42]), new(7, [7, 2]), new(3, [3, 1, 42]));
        var member = Apply(state, new TeamLeaveEvent(2));
        Assert.Equal(new uint[] { 1, 3 }, member.Teams.Select(t => t.LeaderId));
        Assert.Equal(new uint[] { 1, 42 }, member.Teams[0].Members);
        var leader = Apply(member, new TeamLeaveEvent(1));
        Assert.Equal(new uint[] { 3, 42 }, Assert.Single(leader.Teams).Members);
    }

    [Fact]
    public void SameLeaderTransferMovesKeyToEndAndChangesFirstOwnTeam()
    {
        var state = Roster(new(7, [7, 42]), new(1, [1, 42]));
        var next = Apply(state, new TeamNewLeaderEvent(7, 7));
        Assert.Equal(new uint[] { 1, 7 }, next.Teams.Select(t => t.LeaderId));
        Assert.Equal(1u, next.OwnTeam(42)!.LeaderId);
        Assert.Equal(7u, state.OwnTeam(42)!.LeaderId);
    }

    [Fact]
    public void TransferCollisionReplacesExistingTeamAtItsPositionAndAddsAbsentLeader()
    {
        var state = Roster(new(7, [7, 42]), new(1, [1, 2]), new(3, [3, 2]));
        var next = Apply(state, new TeamNewLeaderEvent(3, 7));
        Assert.Equal(new uint[] { 1, 3 }, next.Teams.Select(t => t.LeaderId));
        Assert.Equal(new uint[] { 3, 7, 42 }, next.Teams[1].Members);
        var unknown = Apply(next, new TeamNewLeaderEvent(2, 99));
        Assert.Equal(next.Teams, unknown.Teams);
        Assert.Equal("隊長已變更（伺服器確認）", unknown.Status);
    }

    [Theory]
    [InlineData(null, false)]
    [InlineData(7u, true)]
    [InlineData(1u, true)]
    [InlineData(2u, false)]
    public void JoinFiltersRequestsOnlyWhenOwnRoleBelongsToTheUpdatedTeam(uint? ownRole, bool filters)
    {
        var state = Pending();
        foreach (var role in new uint[] { 1, 2 })
        {
            state = Apply(state, new TeamInviteEvent(role));
            state = Apply(state, new TeamApplicationEvent(role));
            state = Apply(state, new TeamLeaderOfferEvent(role));
        }
        var next = Apply(state, new TeamJoinEvent(7, 1), ownRole);
        Assert.Empty(next.Outbound);
        Assert.Equal(filters ? 2 : 6, next.Requests.Count);
        if (filters) Assert.Equal(new[] { "team_application:2", "team_leader_offer:2" }, next.Requests.Keys.Order());
        Assert.Equal(6, state.Requests.Count); Assert.Equal(3, state.Outbound.Count);
    }

    [Fact]
    public void MissingLeaderTransferStillClearsOffersAndOutboundNotOtherRequests()
    {
        var state = Apply(Apply(Pending(), new TeamLeaderOfferEvent(1)), new TeamInviteEvent(2));
        var next = Apply(state, new TeamNewLeaderEvent(2, 99));
        Assert.Empty(next.Outbound); Assert.Equal("team_invite:2", Assert.Single(next.Requests).Key);
    }

    [Theory]
    [InlineData(null, 0)]
    [InlineData(0u, 0)]
    [InlineData(1u, 2)]
    [InlineData(99u, 3)]
    public void AnswerClearsByTruthyRoleWithoutConfirmingMembership(uint? roleId, int remaining)
    {
        var state = Apply(Pending(), new TeamInviteEvent(1));
        var next = Apply(state, new TeamLeaderAnswerEvent(1, roleId));
        Assert.Equal(remaining, next.Outbound.Count); Assert.Empty(next.Teams); Assert.Single(next.Requests);
        Assert.Equal("對方同意，等待隊伍名單", next.Status);
    }

    [Fact]
    public void DuplicateRequestRefreshesDeadlineAndPendingStatusWithoutAutoAcceptOrAutoExpiry()
    {
        var first = Apply(PartyEventSnapshot.Empty, new TeamInviteEvent(1), now: 0);
        var sent = first with { Requests = first.Requests.SetItem("team_invite:1", first.Requests["team_invite:1"] with { Status = "sent" }) };
        var received = Apply(sent, new TeamInviteEvent(1), now: 30);
        Assert.Equal("pending", received.Requests["team_invite:1"].Status);
        Assert.Equal(90, received.Requests["team_invite:1"].Expires);
        Assert.Empty(received.Teams); Assert.Empty(received.Outbound);
        var unrelated = Apply(received, new TeamNoticeEvent(1), now: 1000);
        Assert.Single(unrelated.Requests);
        Assert.Same(unrelated, PartyEventReducer.Expire(unrelated, 89.999));
        var expired = PartyEventReducer.Expire(unrelated, 90);
        Assert.Empty(expired.Requests); Assert.Equal("組隊請求已逾時，請重新確認", expired.Status);
        Assert.Same(expired, PartyEventReducer.Expire(expired, 1000));
        Assert.Single(received.Requests);
    }

    [Fact]
    public void ExpiryCoversCallerPendingEvidenceAtInclusiveBoundary()
    {
        var state = Pending();
        Assert.Same(state, PartyEventReducer.Expire(state, 114.999));
        var one = PartyEventReducer.Expire(state, 115);
        Assert.Equal(2, one.Outbound.Count); Assert.True(one.EnabledRequested);
        Assert.Empty(PartyEventReducer.Expire(one, 117).Outbound);
    }

    [Fact]
    public void TeamFlagAloneClearsRequestedFlagAndPreservesRequestsAndPending()
    {
        var state = Apply(Pending(), new TeamInviteEvent(1));
        var next = Apply(state, new TeamFlagEvent(false));
        Assert.False(next.Enabled); Assert.Null(next.EnabledRequested); Assert.Single(next.Requests); Assert.Equal(3, next.Outbound.Count);
        Assert.True(state.EnabledRequested); Assert.Null(state.Enabled);
    }

    [Fact]
    public void PositionFiltersOwnSceneButOnlyUpdatesKnownOtherPlayers()
    {
        var player = new NearbyPlayer(1, 2, 3, 4, 100, 5, 6, 7, 8, "private name");
        var state = Apply(Apply(PartyEventSnapshot.Empty, new NearbyPlayerEvent(player)), new NearbyPlayerEvent(player with { RoleId = 42, Scene = 200 }));
        var position = new PositionSnapshotEvent(7, 99, 200, 65535, 0, 0, new(false));
        Assert.Same(state, PartyEventReducer.Apply(state, position, 100, 42));
        var other = PartyEventReducer.Apply(state, position with { RoleId = 1 }, 100, 42);
        Assert.Equal((ushort)200, other.Nearby[1].Scene); Assert.Equal((ushort)65535, other.Nearby[1].X);
        var own = PartyEventReducer.Apply(state, position with { RoleId = 42, Scene = 100 }, 100, 42);
        Assert.Equal(1u, Assert.Single(own.Nearby).Key); Assert.Equal((ushort)5, own.Nearby[1].X);
        Assert.Equal((ushort)100, state.Nearby[1].Scene);
        Assert.DoesNotContain("private name", state.ToString());
    }

    [Fact]
    public void PlayerNamePrefersExplicitOwnNameIncludingEmptyAndOtherwiseNearbyOrId()
    {
        var state = Apply(PartyEventSnapshot.Empty, new NearbyPlayerEvent(new(42, 0, 0, 0, 0, 0, 0, 0, 0, "nearby")));
        Assert.Equal("nearby", state.PlayerName(42)); Assert.Equal("own", state.PlayerName(42, 42, "own"));
        Assert.Equal("", state.PlayerName(42, 42, "")); Assert.Equal("42", state.PlayerName(42, 42));
        Assert.Equal("4294967295", state.PlayerName(uint.MaxValue));
    }

    [Fact]
    public void RoleListAndOtherDomainsDoNotImplicitlyResetParty()
    {
        var state = Apply(Roster(new TeamSnapshot(1, [1, 42])), new TeamInviteEvent(2));
        Assert.Same(state, PartyEventReducer.Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent([])), 100, 42));
        Assert.Same(state, Apply(state, new AlchemyResultEvent(1, 2)));
        Assert.Same(state, PartyEventReducer.Apply(state, new InitialDataCompleteEvent(), 100, 42));
        Assert.Equal(1u, state.OwnTeam(42)!.LeaderId); Assert.Null(state.OwnTeam(7));
    }

    [Theory]
    [InlineData(double.NaN)]
    [InlineData(double.PositiveInfinity)]
    [InlineData(double.NegativeInfinity)]
    public void ExplicitClockContractRejectsNonfiniteRequestAndExpiryTimes(double now)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => Apply(PartyEventSnapshot.Empty, new TeamInviteEvent(1), now: now));
        Assert.Throws<ArgumentOutOfRangeException>(() => PartyEventReducer.Expire(PartyEventSnapshot.Empty, now));
        // Unrelated observations do not require or consult a clock.
        Assert.Same(PartyEventSnapshot.Empty, Apply(PartyEventSnapshot.Empty, new AlchemyResultEvent(1, 1), now: now));
    }

    [Fact]
    public void NullInputsAreRejected()
    {
        Assert.Throws<ArgumentNullException>(() => PartyEventReducer.Apply(null!, new TeamInviteEvent(1), 0));
        Assert.Throws<ArgumentNullException>(() => PartyEventReducer.Apply(PartyEventSnapshot.Empty, (SocialEvent)null!, 0));
        Assert.Throws<ArgumentNullException>(() => PartyEventReducer.Apply(null!, new InitialDataCompleteEvent(), 0));
        Assert.Throws<ArgumentNullException>(() => PartyEventReducer.Apply(PartyEventSnapshot.Empty, (ServerEvent)null!, 0));
        Assert.Throws<ArgumentNullException>(() => PartyEventReducer.Expire(null!, 0));
    }
}
