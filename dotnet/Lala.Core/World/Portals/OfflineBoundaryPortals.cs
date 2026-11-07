using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.World.Portals;

public sealed record PortalConflictProjection(OfflineEventPortalProjection Portals,
    ImmutableDictionary<PortalReferenceKey, PortalLinkEvidence> LinkEvidence);

/// <summary>Physical offline joins only. Markers and link ordinals never substitute for a door ID.
/// Inputs are not authenticated and no result grants runtime admission or permission to travel.
/// Bind reproduces Python's rebuild semantics: repeated binding can return a link claim alongside
/// a prior conflicting_event_destination issue, because the event pass skips that issue. Consumers
/// must not interpret presence in the result as conflict-free or actionable.</summary>
public static class OfflineBoundaryPortals
{
    public static OfflineEventPortalProjection Bind(ReadOnlyMemory<byte>? stageRaw, ReadOnlyMemory<byte>? linkRaw,
        EveDoorProjection doors, IReadOnlyDictionary<ushort, StageDataRow> stages,
        OfflineEventPortalProjection? previous = null, PortalProjectionBudget? budget = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(doors); ArgumentNullException.ThrowIfNull(stages);
        var work = (budget ?? new()).Start(cancellationToken);
        var parsed = stageRaw is { } sr ? OfflinePortalSources.ParseStageMap(sr.Span, cancellationToken) : null;
        var links = linkRaw is { } lr ? OfflinePortalSources.ParseEveLinks(lr.Span, cancellationToken)
            : ImmutableDictionary<ushort, ImmutableArray<EvePortalLink>>.Empty;
        var counts = PortalGeometry.DoorCounts(doors, work);
        var byScene = new Dictionary<ushort, ImmutableArray<EveDoorRow>>();
        foreach (var scene in doors.Scenes) { work.Step(); byScene.Add(scene.SceneId, scene.Doors); }
        var positions = new Dictionary<EventPortalKey, EventPortalPosition>();
        var destinations = new Dictionary<EventPortalKey, EventPortalDestination?>();
        foreach (var scene in doors.Scenes)
        {
            work.Step(); if (!stages.TryGetValue(scene.SceneId, out var stage)) continue;
            var guard = PortalGeometry.Guard(stage); if (guard is null || !links.TryGetValue(scene.SceneId, out var rows)) continue;
            foreach (var link in rows)
            {
                work.Step(); var point = PortalGeometry.Point(stage, link.X, link.Y); if (point is null) continue;
                var match = PortalGeometry.Match(scene.Doors, stage, point.Value, work); if (match is null) continue;
                var (door, bounds) = match.Value; var key = new EventPortalKey(scene.SceneId, door.Index);
                if (door.Index == 0 || counts[key] != 1 || door.TouchEventIds.IsDefaultOrEmpty) continue;
                if (destinations.ContainsKey(key)) { destinations[key] = null; positions.Remove(key); continue; }
                if (!stages.ContainsKey(link.Destination)) { destinations[key] = null; continue; }
                string binding = bounds is not null ? "unique_boundary_touch_region" : "unique_door_anchor";
                positions[key] = new(scene.SceneId, door.Index, point.Value.X, point.Value.Y, true, guard,
                    "1275_eve_door_links_grid_scaled", bounds, binding, link.Index, link.X, link.Y, stage.PosXRatio, stage.PosYRatio);
                destinations[key] = new(scene.SceneId, door.Index, link.Destination, DestinationVerified:true,
                    EventX:door.X, EventY:door.Y, MatchedTouchRegion:true, BindingKind:binding, LinkIndex:link.Index,
                    MatchedStageMap:false, X:link.X, Y:link.Y, ArrivalX:link.ArrivalX, ArrivalY:link.ArrivalY);
            }
        }
        var candidates = new Dictionary<EventPortalKey, List<(StagePortalMarker Marker, EveDoorRow Door, EventPortalBounds? Bounds)>>();
        foreach (var marker in parsed is null ? [] : OfflinePortalReferences.Markers(parsed, stages, work))
        {
            work.Step(); if (marker.Kind is not (2 or 3) || !marker.PositionVerified) continue;
            if (!stages.TryGetValue(marker.Scene, out var stage) || PortalGeometry.Guard(stage) is null
                || !byScene.TryGetValue(marker.Scene, out var sceneDoors)) continue;
            var match = PortalGeometry.Match(sceneDoors, stage, (marker.X!.Value, marker.Y!.Value), work);
            if (match is null) continue;
            var (door, bounds) = match.Value; var key = new EventPortalKey(marker.Scene, door.Index);
            if (door.Index == 0 || counts[key] != 1 || door.TouchEventIds.IsDefaultOrEmpty) continue;
            if (!candidates.TryGetValue(key, out var list)) candidates.Add(key, list = []);
            list.Add((marker, door, bounds));
        }
        foreach (var pair in candidates)
        {
            work.Step(); var key = pair.Key; var rows = pair.Value; var targets = new HashSet<uint>();
            foreach (var (marker, _, _) in rows) { work.Step(); if (marker.Kind == 3 && marker.EventId > 0) targets.Add(marker.Destination!.Value); }
            if (targets.Any(t => t > ushort.MaxValue || !stages.ContainsKey((ushort)t)))
            { positions.Remove(key); destinations[key] = null; continue; }
            if (destinations.TryGetValue(key, out var prior))
            {
                if (prior is null) continue;
                if (targets.Any(t => prior.Destination != t)) { positions.Remove(key); destinations[key] = null; }
                else
                {
                    var marker = rows.OrderBy(r => r.Marker.NameId == 0).ThenBy(r => r.Marker.X).ThenBy(r => r.Marker.Y).ThenBy(r => r.Marker.EventId).First().Marker;
                    destinations[key] = prior with { StageMarkerNameId = marker.NameId, StageMarkerEventId = marker.EventId };
                }
                continue;
            }
            if (targets.Count > 1) continue;
            var chosen = rows.OrderBy(r => r.Marker.Destination is null).ThenBy(r => r.Marker.NameId == 0).ThenBy(r => r.Marker.Kind != 3)
                .ThenBy(r => r.Marker.X).ThenBy(r => r.Marker.Y).ThenBy(r => r.Marker.EventId).ThenBy(r => r.Marker.NameId).First();
            var m = chosen.Marker; string kind = chosen.Bounds is not null ? "unique_boundary_touch_region" : "unique_door_anchor";
            ushort? target = targets.Count == 0 ? null : (ushort)targets.First();
            positions[key] = new(key.Scene, key.Index, m.X!.Value, m.Y!.Value, true, PortalGeometry.Guard(stages[key.Scene]),
                "1275_stage_map_grid_scaled", chosen.Bounds, kind, null);
            destinations[key] = new(key.Scene, key.Index, target, DestinationVerified:target is not null,
                EventX:chosen.Door.X, EventY:chosen.Door.Y, MatchedTouchRegion:true, DoorBindingVerified:true,
                BindingKind:kind, MatchedStageMap:true, StageMarkerOnly:true, StageMarkerKind:m.Kind,
                StageMarkerEventId:m.EventId, StageMarkerNameId:m.NameId);
        }
        // Account for the event phase before it allocates flattened transfer arrays. Shared
        // touch-event records can be referenced by many doors, so parser input bounds alone
        // do not bound this per-door retained projection. Charge each traversal/copy/target.
        foreach (var scene in doors.Scenes) foreach (var door in scene.Doors)
        {
            work.Step();
            foreach (var touch in door.TouchEventRecords)
            {
                work.Step();
                foreach (var _ in touch.ConveyTransfers) { work.Step(); work.Step(); work.Step(); }
            }
        }
        var priorIssues = ImmutableDictionary.CreateBuilder<EventPortalKey, string>();
        if (previous is not null) foreach (var issue in previous.Issues) { work.Step(); priorIssues.Add(issue.Key, issue.Value); }
        work.Check();
        // Python retains conflict issues on Eve rows. Carry their immutable counterpart forward,
        // but rebuild all position/destination bindings instead of preserving obsolete ordinal joins.
        return OfflineEventPortalProjector.Reconcile(doors, stages,
            new(positions, destinations.Where(p => p.Value is not null).Select(p => KeyValuePair.Create(p.Key, p.Value!)), priorIssues), cancellationToken);
    }

    public static PortalConflictProjection ReconcileRouteConflicts(OfflineEventPortalProjection portals,
        IEnumerable<PortalRouteReference> routes, IReadOnlyDictionary<PortalReferenceKey, PortalLinkEvidence>? evidence = null,
        PortalProjectionBudget? budget = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(portals); ArgumentNullException.ThrowIfNull(routes);
        var work = (budget ?? new()).Start(cancellationToken);
        var targets = new Dictionary<(ushort Scene, long? X, long? Y), HashSet<ushort>>();
        foreach (var row in routes)
        {
            work.Step(); if (!row.PositionVerified) continue;
            var key = (row.Scene, row.X, row.Y);
            if (!targets.TryGetValue(key, out var list)) targets.Add(key, list = []);
            list.Add(row.Destination);
        }
        foreach (var _ in portals.Positions) work.Step();
        foreach (var _ in portals.Issues) work.Step();
        var positions = portals.Positions.ToBuilder(); var destinations = portals.Destinations.ToBuilder();
        var references = ImmutableDictionary.CreateBuilder<PortalReferenceKey, PortalLinkEvidence>();
        if (evidence is not null) foreach (var row in evidence) { work.Step(); references.Add(row.Key, row.Value); }
        foreach (var pair in portals.Destinations)
        {
            work.Step(); var key = pair.Key; var row = pair.Value; positions.TryGetValue(key, out var point);
            if (!targets.TryGetValue((key.Scene, point?.X, point?.Y), out var alternatives)) continue;
            if (row.EventConveyVerified)
            {
                var allowed = new HashSet<ushort>();
                if (!row.DestinationCandidates.IsDefault) foreach (var candidate in row.DestinationCandidates) { work.Step(); allowed.Add(candidate); }
                bool subset = true;
                foreach (var candidate in alternatives) { work.Step(); if (!allowed.Contains(candidate)) subset = false; }
                if (subset) continue;
            }
            bool conflict = row.Destination is null && alternatives.Count > 1;
            if (row.Destination is not null) foreach (var candidate in alternatives) { work.Step(); conflict |= candidate != row.Destination; }
            if (!conflict) continue;
            // An explicitly null link_index is not replaced with the event index.
            if (row.LinkIndex is { } index && index >= 0 && references.TryGetValue(new(key.Scene, (uint)index), out var reference))
            {
                var all = new SortedSet<ushort>();
                foreach (var candidate in alternatives) { work.Step(); all.Add(candidate); }
                if (row.Destination is { } destination) { work.Step(); all.Add(destination); }
                var retained = ImmutableArray.CreateBuilder<ushort>(all.Count);
                foreach (var candidate in all) { work.Step(); retained.Add(candidate); }
                var issues = ImmutableArray.CreateBuilder<string>(); var seen = new HashSet<string>(StringComparer.Ordinal);
                if (!reference.Issues.IsDefault) foreach (var issue in reference.Issues) { work.Step(); if (seen.Add(issue)) issues.Add(issue); }
                if (seen.Add("conflicting_official_destinations")) issues.Add("conflicting_official_destinations");
                references[new(key.Scene, (uint)index)] = reference with
                {
                    Issues = issues.ToImmutable(),
                    DestinationCandidates = retained.MoveToImmutable()
                };
            }
            destinations.Remove(key); positions.Remove(key);
        }
        work.Check(); return new(new(positions, destinations, portals.Issues), references.ToImmutable());
    }
}
