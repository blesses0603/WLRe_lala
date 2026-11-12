using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

/// <summary>Pure receive-only port of social/guild.py apply_guild. Decode completely before
/// applying; malformed packets never supply partial observations. The caller supplies the
/// current player role for self-leave matching. No epoch, role or guild binding is inferred:
/// role-list/world-player updates leave the roster intact in retained Python, and a late
/// roster/add/profile can still affect it. Session/lifecycle invalidation remains separate.
/// This snapshot alone must not authorize guild actions or chat. guild_actions.py pending,
/// sign-in, donation, catalog, budget and day-reset state are deliberately not migrated here.
/// No transport, command construction, service scheduling or AccountSession integration.</summary>
public static class GuildEventReducer
{
    public static GuildEventSnapshot Apply(GuildEventSnapshot state, ServerEvent observation,
        uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation is ServerSocialEvent social ? Apply(state, social.Event, ownRoleId) : state;
    }

    public static GuildEventSnapshot Apply(GuildEventSnapshot state, SocialEvent observation,
        uint? ownRoleId = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation switch
        {
            GuildRosterEvent roster => new()
            {
                Ready = true, Name = roster.Name, Serial = roster.Serial, Level = roster.Level,
                Members = roster.Members.ToImmutableDictionary()
            },
            GuildMemberProfileEvent profile when state.Members.TryGetValue(profile.RoleId, out var member) =>
                state with { Members = state.Members.SetItem(profile.RoleId, member with { Name = profile.Name }) },
            GuildMemberAddedEvent added when state.Ready && !state.Members.ContainsKey(added.RoleId) =>
                state with { Members = state.Members.Add(added.RoleId, new(added.RoleId, "")) },
            GuildMemberRemovedEvent removed when state.Members.ContainsKey(removed.RoleId) =>
                state with { Members = state.Members.Remove(removed.RoleId) },
            GuildLeaveResultEvent { Result: 0 } leave when leave.RoleId == ownRoleId => GuildEventSnapshot.Empty,
            GuildDisbandResultEvent { Result: 0 } => GuildEventSnapshot.Empty,
            _ => state
        };
    }
}
