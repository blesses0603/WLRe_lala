using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure receive-only port of battle/party.py apply_party and expire. Decode
/// completely before applying. The caller supplies the current player role and a finite
/// monotonic timestamp when creating/expiring a request. Applying an event does not expire
/// requests implicitly. Role changes do not clear the source party state; late events can
/// recreate teams. No commands, automatic accepts, clock, scheduler, session or transport.</summary>
public static class PartyEventReducer
{
    public static PartyEventSnapshot Apply(PartyEventSnapshot state, ServerEvent observation,
        double observedAt, uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation switch
        {
            ServerSocialEvent social => Apply(state, social.Event, observedAt, ownRoleId),
            PositionSnapshotEvent position => Position(state, position, ownRoleId),
            _ => state
        };
    }

    public static PartyEventSnapshot Apply(PartyEventSnapshot state, SocialEvent observation,
        double observedAt, uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        switch (observation)
        {
            case NearbyPlayerEvent nearby:
                return state with { Nearby = state.Nearby.SetItem(nearby.Player.RoleId, nearby.Player) };
            case NearbyLeaveEvent leave:
                return state.Nearby.ContainsKey(leave.RoleId) ? state with { Nearby = state.Nearby.Remove(leave.RoleId) } : state;
            case TeamInviteEvent invite:
                return Request(state, invite.Type, invite.RoleId, observedAt);
            case TeamApplicationEvent application:
                return Request(state, application.Type, application.RoleId, observedAt);
            case TeamLeaderOfferEvent offer:
                return Request(state, offer.Type, offer.RoleId, observedAt);
            case TeamListEvent list:
                var teams = state.Teams;
                foreach (var team in list.Teams) teams = SetTeam(teams, team);
                return state with { Teams = teams, Status = "隊伍名單已更新（伺服器確認）" };
            case TeamJoinEvent join:
                var current = state.Teams.FirstOrDefault(team => team.LeaderId == join.LeaderId)
                    ?? new TeamSnapshot(join.LeaderId, [join.LeaderId]);
                if (!current.Members.Contains(join.RoleId)) current = current with { Members = current.Members.Add(join.RoleId) };
                return state with
                {
                    Teams = SetTeam(state.Teams, current), Outbound = state.Outbound.Clear(),
                    Requests = ownRoleId is { } role && current.Members.Contains(role)
                        ? RemoveRequests(state.Requests, request => request.Type == "team_invite" || request.RoleId == join.RoleId)
                        : state.Requests,
                    Status = "組隊成功（伺服器確認）"
                };
            case TeamLeaveEvent leave:
                var remaining = ImmutableArray.CreateBuilder<TeamSnapshot>();
                foreach (var team in state.Teams)
                {
                    if (!team.Members.Contains(leave.RoleId)) remaining.Add(team);
                    else if (leave.RoleId != team.LeaderId && team.Members.Length > 2)
                        remaining.Add(team with { Members = team.Members.Remove(leave.RoleId) });
                }
                return state with { Teams = remaining.ToImmutable(), Outbound = state.Outbound.Clear(), Status = "離隊／解散已由伺服器確認" };
            case TeamNewLeaderEvent change:
                var oldIndex = TeamIndex(state.Teams, change.OldLeaderId);
                var changed = state.Teams;
                if (oldIndex >= 0)
                {
                    var old = state.Teams[oldIndex];
                    var replacement = new TeamSnapshot(change.LeaderId,
                        [change.LeaderId, .. old.Members.Where(role => role != change.LeaderId)]);
                    changed = SetTeam(state.Teams.RemoveAt(oldIndex), replacement);
                }
                return state with
                {
                    Teams = changed, Outbound = state.Outbound.Clear(),
                    Requests = RemoveRequests(state.Requests, request => request.Type == "team_leader_offer"),
                    Status = "隊長已變更（伺服器確認）"
                };
            case TeamFlagEvent flag:
                return state with { Enabled = flag.Enabled, EnabledRequested = null, Status = "組隊開關：" + (flag.Enabled ? "開啟" : "關閉") };
            case TeamAnswerEvent answer:
                return Answer(state, answer.Answer, answer.RoleId);
            case TeamLeaderAnswerEvent answer:
                return Answer(state, answer.Answer, answer.RoleId);
            case TeamNoticeEvent notice:
                return state with { Status = notice.Code switch
                {
                    1 => "邀請已送達，等待對方確認", 2 => "申請已送達，等待隊長確認", _ => $"組隊通知 {notice.Code}"
                } };
            case SocialRejectedEvent rejected:
                return state with { Status = Rejection(rejected.Code), Outbound = state.Outbound.Clear() };
            default:
                return state;
        }
    }

    /// <summary>Explicit expiry only. Reference equality indicates whether anything expired,
    /// corresponding to Python expire's boolean result. No timer or send is scheduled.</summary>
    public static PartyEventSnapshot Expire(PartyEventSnapshot state, double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        RequireFiniteTime(observedAt);
        var requests = RemoveRequests(state.Requests, request => observedAt >= request.Expires);
        var outbound = state.Outbound.RemoveRange(state.Outbound.Where(pair => observedAt >= pair.Value.Expires).Select(pair => pair.Key));
        return requests.Count == state.Requests.Count && outbound.Count == state.Outbound.Count ? state
            : state with { Requests = requests, Outbound = outbound, Status = "組隊請求已逾時，請重新確認" };
    }

    private static PartyEventSnapshot Position(PartyEventSnapshot state, PositionSnapshotEvent position, uint? ownRoleId)
    {
        if (position.RoleId == ownRoleId)
            return state with { Nearby = state.Nearby.RemoveRange(state.Nearby.Where(pair => pair.Value.Scene != position.Scene).Select(pair => pair.Key)) };
        return state.Nearby.TryGetValue(position.RoleId, out var nearby) ? state with
        {
            Nearby = state.Nearby.SetItem(position.RoleId, nearby with { Scene = position.Scene, X = position.X, Y = position.Y })
        } : state;
    }

    private static PartyEventSnapshot Request(PartyEventSnapshot state, string type, uint roleId, double observedAt)
    {
        RequireFiniteTime(observedAt);
        var key = $"{type}:{roleId}";
        return state with
        {
            Requests = state.Requests.SetItem(key, new(key, type, roleId, observedAt + 60, "pending")),
            Status = "收到組隊請求，請選擇接受或拒絕"
        };
    }

    private static PartyEventSnapshot Answer(PartyEventSnapshot state, byte answer, uint? roleId) => state with
    {
        Status = answer switch
        {
            1 => "對方同意，等待隊伍名單", 2 => "對方拒絕", 3 => "對方忙碌／未回應", _ => $"組隊回覆 {answer}"
        },
        // Python treats both an omitted role and role zero as false, clearing all outbound.
        Outbound = roleId is null or 0 ? state.Outbound.Clear()
            : state.Outbound.RemoveRange(state.Outbound.Where(pair => pair.Value.RoleId == roleId).Select(pair => pair.Key))
    };

    private static ImmutableDictionary<string, PartyRequest> RemoveRequests(ImmutableDictionary<string, PartyRequest> requests,
        Func<PartyRequest, bool> predicate) => requests.RemoveRange(requests.Where(pair => predicate(pair.Value)).Select(pair => pair.Key));

    private static int TeamIndex(ImmutableArray<TeamSnapshot> teams, uint leaderId)
    {
        for (var i = 0; i < teams.Length; i++) if (teams[i].LeaderId == leaderId) return i;
        return -1;
    }

    private static ImmutableArray<TeamSnapshot> SetTeam(ImmutableArray<TeamSnapshot> teams, TeamSnapshot team)
    {
        var index = TeamIndex(teams, team.LeaderId);
        return index < 0 ? teams.Add(team) : teams.SetItem(index, team);
    }

    private static void RequireFiniteTime(double observedAt)
    {
        if (!double.IsFinite(observedAt)) throw new ArgumentOutOfRangeException(nameof(observedAt), "A finite monotonic timestamp is required.");
    }

    private static string Rejection(byte code) => code switch
    {
        5 => "釣魚中無法組隊", 6 => "採集中無法組隊", 8 or 19 => "對方忙碌", 10 => "對方未開啟組隊邀請",
        15 => "對方已離線", 16 => "不在相同地圖", 17 => "對方戰鬥中", 20 or 21 => "對方已有隊伍",
        22 => "隊伍已滿", 24 => "請先解除騎乘", 27 => "配對中無法變更隊伍", 28 => "對方配對中",
        30 => "二轉條件不符", _ => $"伺服器拒絕操作（代碼{code}）"
    };
}
