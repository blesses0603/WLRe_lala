using System.Collections.Immutable;
using Lala.Core.World.Portals;

namespace Lala.Core.Catalogs;

/// <summary>Detached observations derived only from this candidate's decoded Eve and ScenesData.
/// Reconciliation includes the event-only path even when all optional portal assets are absent.
/// Coverage and geometric cross-checks are not source authentication or permission to travel.</summary>
public sealed class OfflineRuntimePortalObservations
{
    internal OfflineRuntimePortalObservations(OfflineEventPortalProjection reconciled, OfflinePortalCoverageReport coverage)
        => (Reconciled, Coverage) = (reconciled, coverage);
    public OfflineEventPortalProjection Reconciled { get; }
    public OfflinePortalCoverageReport Coverage { get; }
    public ImmutableArray<string> UnavailableOptionalSources => ["StageMapData_C", "EveDoorLinks", "DoorLinkData_C"];
}
