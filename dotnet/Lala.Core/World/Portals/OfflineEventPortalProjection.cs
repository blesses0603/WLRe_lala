using System.Collections.Immutable;
using Lala.Core.World.Eve;

namespace Lala.Core.World.Portals;

public readonly record struct EventPortalKey(ushort Scene, ushort Index);
public readonly record struct EventPortalBounds(long Left, long Top, long Right, long Bottom);
public sealed record EventPortalProjectionGuard(double Rate, ushort OffsetX, ushort OffsetY, int Height);

/// <summary>Detached geometric observations only. Verified field names describe source cross-checks,
/// not official provenance, a current runtime, successful transfers, or permission to travel.</summary>
public sealed record EventPortalPosition(ushort Scene, ushort Index, long X, long Y,
    bool PositionVerified, EventPortalProjectionGuard? ProjectionGuard, string SourceKind,
    EventPortalBounds? TriggerBounds, string BindingKind, int? LinkIndex,
    long? RawLinkX = null, long? RawLinkY = null, byte? PosXRatio = null, byte? PosYRatio = null);

public sealed record EventPortalDestination(ushort Scene, ushort Index, ushort? Destination,
    bool DestinationVerified = false, uint EventX = 0, uint EventY = 0,
    bool MatchedTouchRegion = false, bool DoorBindingVerified = false, bool TriggerVerified = false,
    bool EventConveyVerified = false, bool EventDecidedOnly = false,
    ImmutableArray<ushort> DestinationCandidates = default,
    ImmutableArray<EveDoorTransfer> ConveyTransfers = default,
    string BindingKind = "", int? LinkIndex = null,
    bool? MatchedStageMap = null, bool? StageMarkerOnly = null, byte? StageMarkerKind = null,
    uint? StageMarkerEventId = null, uint? StageMarkerNameId = null,
    long? X = null, long? Y = null, long? ArrivalX = null, long? ArrivalY = null);

/// <summary>Immutable projection state. Issues are persistent tombstones: retain this state when
/// reconciling again, rather than discarding a conflict and resurrecting an earlier claim.</summary>
public sealed class OfflineEventPortalProjection
{
    public ImmutableDictionary<EventPortalKey, EventPortalPosition> Positions { get; }
    public ImmutableDictionary<EventPortalKey, EventPortalDestination> Destinations { get; }
    public ImmutableDictionary<EventPortalKey, string> Issues { get; }

    public OfflineEventPortalProjection(
        IEnumerable<KeyValuePair<EventPortalKey, EventPortalPosition>>? positions = null,
        IEnumerable<KeyValuePair<EventPortalKey, EventPortalDestination>>? destinations = null,
        IEnumerable<KeyValuePair<EventPortalKey, string>>? issues = null)
    {
        Positions = positions?.ToImmutableDictionary() ?? ImmutableDictionary<EventPortalKey, EventPortalPosition>.Empty;
        Destinations = destinations?.ToImmutableDictionary() ?? ImmutableDictionary<EventPortalKey, EventPortalDestination>.Empty;
        Issues = issues?.ToImmutableDictionary() ?? ImmutableDictionary<EventPortalKey, string>.Empty;
    }
}
