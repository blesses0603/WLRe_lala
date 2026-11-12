using System.Collections.Immutable;
using System.Globalization;
using Lala.Core.Protocol;

namespace Lala.Core.Social;

public sealed record PartyRequest(string Key, string Type, uint RoleId, double Expires, string Status);
public sealed record PartyOutboundRequest(uint RoleId, double Expires);

/// <summary>Immutable receive-side projection of battle/party.py party_defaults.
/// Teams retain Python dictionary insertion order because own_team selects the first
/// matching team, even when conflicting or late observations contain the same player.
/// There is no source readiness flag, role/session binding or stale-event rejection.
/// Requests, Enabled and membership are observations, never permission to act.</summary>
public sealed record PartyEventSnapshot
{
    public static PartyEventSnapshot Empty { get; } = new();
    public ImmutableArray<TeamSnapshot> Teams { get; init; } = [];
    public ImmutableDictionary<uint, NearbyPlayer> Nearby { get; init; } = ImmutableDictionary<uint, NearbyPlayer>.Empty;
    public ImmutableDictionary<string, PartyRequest> Requests { get; init; } = ImmutableDictionary<string, PartyRequest>.Empty;
    // Receive/expiry can clear caller-supplied pending evidence; this slice never creates
    // outbound requests or changes EnabledRequested to a non-null value.
    public ImmutableDictionary<string, PartyOutboundRequest> Outbound { get; init; } = ImmutableDictionary<string, PartyOutboundRequest>.Empty;
    public bool? Enabled { get; init; }
    public bool? EnabledRequested { get; init; }
    public string Status { get; init; } = "尚無隊伍資料";

    public TeamSnapshot? OwnTeam(uint? ownRoleId) => ownRoleId is { } role
        ? Teams.FirstOrDefault(team => team.Members.Contains(role)) : null;

    public string PlayerName(uint roleId, uint? ownRoleId = null, string? ownName = null) =>
        roleId == ownRoleId ? ownName ?? roleId.ToString(CultureInfo.InvariantCulture)
        : Nearby.TryGetValue(roleId, out var player) ? player.Name : roleId.ToString(CultureInfo.InvariantCulture);

    // Avoid incidental disclosure of nearby names, role IDs or request contents.
    public override string ToString() => $"PartyEventSnapshot (teams={Teams.Length}, nearby={Nearby.Count}, requests={Requests.Count})";
}
