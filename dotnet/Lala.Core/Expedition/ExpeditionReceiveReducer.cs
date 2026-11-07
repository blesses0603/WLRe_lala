using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Expedition;

/// <summary>Pure offline port of expedition.manager.apply_expedition and with_deadline.
/// The caller provides one finite monotonic timestamp per observation. Only S31 evidence
/// changes this domain, and no service observer, lifecycle, packet count or clock is invoked.
/// Decoding must complete before Apply: malformed packets cannot partly update prior state.</summary>
public static class ExpeditionReceiveReducer
{
    public static ExpeditionReceiveSnapshot Apply(ExpeditionReceiveSnapshot state, ServerEvent observation,
        double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation is ServerExpeditionEvent expedition ? Apply(state, expedition.Event, observedAt) : state;
    }

    public static ExpeditionReceiveSnapshot Apply(ExpeditionReceiveSnapshot state, ExpeditionEvent observation,
        double observedAt)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ExpeditionReceiveSnapshot next;
        switch (observation)
        {
            case OutpostSnapshotEvent snapshot:
                if (snapshot.Roles.IsDefault || snapshot.Roles.Length > byte.MaxValue)
                    throw new ProtocolException("Invalid outpost role snapshot length.");
                var roles = ImmutableDictionary<byte, ExpeditionOutpostState>.Empty;
                foreach (var role in snapshot.Roles) roles = roles.SetItem(role.Index, ExpeditionOutpostState.From(role));
                next = state with { OutpostReady = true, Roles = roles };
                break;
            case OutpostRoleEvent role:
                next = state with { Roles = state.Roles.SetItem(role.Role.Index, ExpeditionOutpostState.From(role.Role)) };
                break;
            case OutpostRemoveEvent remove:
                next = state with { Roles = state.Roles.Remove(remove.Index) };
                break;
            case OutpostStatusEvent status:
                next = UpdateRole(state, status.Index, role => role with { State = status.State });
                break;
            case OutpostFaithEvent faith:
                next = UpdateRole(state, faith.Index, role => role with { Faith = faith.Faith });
                break;
            case OutpostAttributeEvent attribute:
                next = UpdateRole(state, attribute.Index, role => Attribute(role, attribute.Kind, attribute.Value));
                break;
            case ExpeditionSnapshotEvent snapshot:
                if (snapshot.Teams.IsDefault || snapshot.Teams.Length != 10 || snapshot.Quests.IsDefault || snapshot.Quests.Length != 50)
                    throw new ProtocolException("Invalid expedition snapshot length.");
                var teams = ImmutableDictionary<byte, ExpeditionTeamState>.Empty;
                var quests = ImmutableDictionary<byte, ushort>.Empty;
                // The source uses ordinal slots, not the ten indices embedded in the packet.
                for (var i = 0; i < snapshot.Teams.Length; i++)
                {
                    var index = (byte)(i + 1);
                    teams = teams.SetItem(index, WithDeadline(snapshot.Teams[i], index, observedAt));
                }
                for (var i = 0; i < snapshot.Quests.Length; i++) quests = quests.SetItem((byte)(i + 1), snapshot.Quests[i]);
                next = state with { Ready = true, Teams = teams, Quests = quests, Level = snapshot.Level };
                break;
            case ExpeditionTeamEvent team:
                next = state with { Teams = state.Teams.SetItem(team.Team.Index, WithDeadline(team.Team, team.Team.Index, observedAt)) };
                break;
            case ExpeditionTimeEvent time:
                next = state.Teams.TryGetValue(time.Index, out var current) ? state with
                {
                    Teams = state.Teams.SetItem(time.Index, current with
                    { Minutes = time.Minutes, Due = Deadline(observedAt, time.Minutes) })
                } : state;
                break;
            case ExpeditionQuestsEvent questUpdate:
                // Complete replacement, not a merge. Duplicate keys were already resolved by the decoder.
                next = state with { Quests = questUpdate.Quests.ToImmutableDictionary() };
                break;
            case ExpeditionLevelEvent level:
                next = state with { Level = level.Level };
                break;
            case ExpeditionResultEvent result:
                // Result/award bytes are not inventory evidence or confirmation of a pending claim.
                next = state with { Teams = state.Teams.SetItem(result.Index, new(result.Index, 0, [0, 0, 0, 0], null, 0, null)) };
                break;
            case ExpeditionRejectedEvent rejection:
                next = state with
                {
                    Enabled = false,
                    Status = $"伺服器拒絕遠征操作（S31-{rejection.Source} 代碼 {rejection.Code}）",
                    Uncertain = state.Uncertain || !string.IsNullOrEmpty(state.Pending)
                };
                break;
            default:
                // Start acknowledgments, unrelated and future event types do not establish state.
                return state;
        }
        // Missing-slot updates and duplicates still count as recognized observations in Python.
        return next with { Revision = state.Revision + 1 };
    }

    private static ExpeditionReceiveSnapshot UpdateRole(ExpeditionReceiveSnapshot state, byte index,
        Func<ExpeditionOutpostState, ExpeditionOutpostState> update) =>
        state.Roles.TryGetValue(index, out var role) ? state with { Roles = state.Roles.SetItem(index, update(role)) } : state;

    private static ExpeditionOutpostState Attribute(ExpeditionOutpostState role, byte kind, int value) => kind switch
    {
        64 => role with { Faith = value },
        27 => role with { Stats = role.Stats with { Int = value } },
        28 => role with { Stats = role.Stats with { Str = value } },
        29 => role with { Stats = role.Stats with { Con = value } },
        30 => role with { Stats = role.Stats with { Agi = value } },
        33 => role with { Stats = role.Stats with { Wis = value } },
        35 => role with { Stats = role.Stats with { Level = value } },
        _ => role
    };

    private static ExpeditionTeamState WithDeadline(ExpeditionTeam team, byte index, double observedAt) =>
        new(index, team.Minutes, [.. team.Members], [.. team.Items], team.Quest, Deadline(observedAt, team.Minutes));

    private static double Deadline(double observedAt, ushort minutes)
    {
        if (!double.IsFinite(observedAt)) throw new ArgumentOutOfRangeException(nameof(observedAt), "A finite monotonic timestamp is required.");
        return observedAt + minutes * 60;
    }
}
