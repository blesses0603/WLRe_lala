using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.World.Portals;

public sealed record PortalCoverageDetail(uint Index, uint? LinkIndex, uint? StageMarkerEventId,
    string DestinationStatus, uint? DirectDoorIndex, string Category, ImmutableArray<string> Issues,
    int ConveyTransferCount, ImmutableArray<ushort> DestinationCandidates, bool Named,
    ushort? OfficialLinkDestination, ImmutableArray<long>? OfficialLinkPosition,
    ImmutableArray<long>? OfficialArrivalPosition, bool ReferenceOnly);
public sealed record PortalSceneCoverage(ushort Scene, bool InSceneTable, int HiddenStageMarkers,
    int CrossSceneStageMarkers, int EveDoors, int OrdinaryPortals, int Unresolved, ImmutableArray<PortalCoverageDetail> Details);
public sealed record OfflinePortalCoverageReport(int SourceRevision, ImmutableDictionary<string, string> SourceStatus,
    bool AllSourcesAvailable, int SceneCount, int SceneTableCount, ImmutableArray<PortalSceneCoverage> Scenes,
    int UnresolvedPortals, int OfficialLinkReferenceCount, int ReferenceSourceXyCount, int ReferenceArrivalXyCount,
    int ReferenceMissingStageMarkerCount, int ReferenceMissingEveEventCount, int ReferenceUnknownTargetCount,
    int DoorLinkDataRouteCount, int StageHiddenMarkerCount, int StageCrossSceneMarkerCount, int StageHiddenNoTargetCount);

/// <summary>All-scene offline cross-reference audit. SourceRevision preserves the Python report's
/// legacy literal 1275, not a verified current release. Completeness is never authorization.</summary>
public static class OfflinePortalCoverage
{
    public static OfflinePortalCoverageReport Audit(EveDoorProjection doors, IReadOnlyDictionary<ushort, StageDataRow> stages,
        ReadOnlyMemory<byte>? stageRaw = null, ReadOnlyMemory<byte>? linkRaw = null,
        OfflineEventPortalProjection? portals = null, IReadOnlySet<PortalReferenceKey>? names = null,
        IReadOnlyDictionary<PortalReferenceKey, PortalLinkEvidence>? linkEvidence = null,
        IEnumerable<PortalRouteReference>? extraRoutes = null, IEnumerable<StagePortalMarker>? stageMarkers = null,
        PortalProjectionBudget? budget = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(doors); ArgumentNullException.ThrowIfNull(stages);
        var work = (budget ?? new()).Start(cancellationToken); portals ??= new();
        ParsedStagePortals? parsed = null; var links = ImmutableDictionary<ushort, ImmutableArray<EvePortalLink>>.Empty;
        string stageStatus = "missing", linkStatus = "missing";
        if (stageRaw is { } sr)
        {
            try { parsed = OfflinePortalSources.ParseStageMap(sr.Span, cancellationToken); stageStatus = "parsed"; }
            catch (PortalProjectionException) { stageStatus = "invalid"; }
        }
        if (linkRaw is { } lr)
        {
            try { links = OfflinePortalSources.ParseEveLinks(lr.Span, cancellationToken); linkStatus = "parsed"; }
            catch (PortalProjectionException) { linkStatus = "invalid"; }
        }
        var markers = parsed?.UniqueMarkers ?? ImmutableDictionary<PortalReferenceKey, StagePortalRow>.Empty;
        var markerCounts = new Dictionary<PortalReferenceKey, int>();
        var markerIndices = new Dictionary<ushort, HashSet<uint>>();
        if (parsed is not null) foreach (var row in parsed.Rows)
        {
            work.Step(); if (row.Kind is not (2 or 3) || row.Scene == 0 || row.EventId == 0) continue;
            var key = new PortalReferenceKey(row.Scene, row.EventId); markerCounts[key] = markerCounts.GetValueOrDefault(key) + 1;
            if (!markerIndices.TryGetValue(row.Scene, out var indices)) markerIndices.Add(row.Scene, indices = []);
            indices.Add(row.EventId);
        }
        var counts = PortalGeometry.DoorCounts(doors, work);
        var scenes = new SortedSet<ushort>();
        foreach (var stage in stages) { work.Step(); scenes.Add(stage.Key); }
        var byScene = new Dictionary<ushort, ImmutableArray<EveDoorRow>>();
        foreach (var scene in doors.Scenes) { work.Step(); scenes.Add(scene.SceneId); byScene.Add(scene.SceneId, scene.Doors); }
        foreach (var scene in markerIndices.Keys) { work.Step(); scenes.Add(scene); }
        foreach (var scene in links)
        {
            work.Step(); scenes.Add(scene.Key);
            foreach (var row in scene.Value) { work.Step(); scenes.Add(row.Destination); }
        }
        var hiddenCounts = new Dictionary<ushort, int>(); var crossCounts = new Dictionary<ushort, int>();
        int hidden = 0, cross = 0, noTarget = 0, routeCount = 0;
        if (stageMarkers is not null) foreach (var marker in stageMarkers)
        {
            work.Step(); scenes.Add(marker.Scene);
            if (marker.Kind == 3) { hidden++; hiddenCounts[marker.Scene] = hiddenCounts.GetValueOrDefault(marker.Scene) + 1; if (marker.Destination is null) noTarget++; }
            if (marker.Kind == 4) { cross++; crossCounts[marker.Scene] = crossCounts.GetValueOrDefault(marker.Scene) + 1; }
        }
        if (extraRoutes is not null) foreach (var _ in extraRoutes) { work.Step(); routeCount++; }
        var resolved = new Dictionary<ushort, HashSet<uint>>();
        foreach (var row in portals.Destinations)
        {
            work.Step(); if (!row.Value.MatchedTouchRegion || row.Value.LinkIndex is not { } index || index < 0) continue;
            if (!resolved.TryGetValue(row.Key.Scene, out var indices)) resolved.Add(row.Key.Scene, indices = []);
            indices.Add((uint)index);
        }
        var results = ImmutableArray.CreateBuilder<PortalSceneCoverage>(); int totalUnresolved = 0;
        foreach (ushort scene in scenes)
        {
            work.Step(); var events = byScene.GetValueOrDefault(scene, []);
            var firstDoors = new Dictionary<ushort, EveDoorRow>(); var indices = new SortedSet<uint>();
            foreach (var door in events) { work.Step(); indices.Add(door.Index); firstDoors.TryAdd(door.Index, door); }
            var sceneLinks = new Dictionary<uint, EvePortalLink>();
            if (links.TryGetValue(scene, out var l)) foreach (var link in l) { work.Step(); sceneLinks.Add((uint)link.Index, link); }
            var resolvedLinks = resolved.GetValueOrDefault(scene);
            if (markerIndices.TryGetValue(scene, out var mi)) foreach (uint index in mi) { work.Step(); if (resolvedLinks?.Contains(index) != true) indices.Add(index); }
            foreach (uint index in sceneLinks.Keys) { work.Step(); if (resolvedLinks?.Contains(index) != true) indices.Add(index); }
            int gaps = 0, ordinary = 0; var details = ImmutableArray.CreateBuilder<PortalCoverageDetail>();
            foreach (uint index in indices)
            {
                work.Step(); var referenceKey = new PortalReferenceKey(scene, index);
                EventPortalKey? key = index <= ushort.MaxValue ? new(scene, (ushort)index) : null;
                EventPortalDestination? binding = key is { } k ? portals.Destinations.GetValueOrDefault(k) : null;
                bool positioned = key is { } pk && portals.Positions.ContainsKey(pk);
                bool boundary = binding?.MatchedTouchRegion == true && positioned
                    && binding.BindingKind is "unique_boundary_touch_region" or "unique_door_anchor" or "eve_convey";
                uint? linkIndex = binding is null ? index : binding.LinkIndex is { } li && li >= 0 ? (uint)li : null;
                markers.TryGetValue(referenceKey, out var marker); int markerCount = markerCounts.GetValueOrDefault(referenceKey);
                int doorCount = key is { } dk ? counts.GetValueOrDefault(dk) : 0;
                var reasons = ImmutableArray.CreateBuilder<string>();
                if (!boundary && markerCount > 1) reasons.Add("duplicate_stage_marker");
                string category;
                if (marker?.Kind == 3 && !boundary) category = "hidden_portal";
                else if (!boundary && markerCount == 0 && !sceneLinks.ContainsKey(index)) category = stageStatus == "parsed" ? "event_container_only" : "source_incomplete";
                else
                {
                    category = boundary ? binding!.EventConveyVerified ? "event_convey_portal" : binding.StageMarkerOnly == true ? "stage_marker_portal" : "boundary_portal" : "ordinary_portal";
                    ordinary++;
                    if (markerCount == 0 && !boundary) reasons.Add("missing_stage_marker");
                    if (doorCount == 0) reasons.Add("missing_eve_door"); else if (doorCount != 1) reasons.Add("duplicate_eve_door");
                    var link = linkIndex is { } idx ? sceneLinks.GetValueOrDefault(idx) : null;
                    if (link is null && binding?.StageMarkerOnly != true && binding?.EventConveyVerified != true) reasons.Add("missing_door_link");
                    else if (link is not null && !stages.ContainsKey(link.Destination)) reasons.Add("unknown_destination_scene");
                    if (!positioned) reasons.Add("position_unverified");
                    if (binding is null) reasons.Add("destination_unverified");
                }
                int transfers = 0; bool missing = false;
                if (index <= ushort.MaxValue && firstDoors.TryGetValue((ushort)index, out var first))
                    foreach (var touch in first.TouchEventRecords) { work.Step(); transfers += touch.ConveyTransfers.Length; missing |= !touch.MissingConveyIds.IsDefaultOrEmpty; }
                if (!boundary && transfers != 0)
                {
                    string? issue = key is { } ik ? portals.Issues.GetValueOrDefault(ik) : null;
                    reasons.Add(string.IsNullOrEmpty(issue) ? "event_convey_unbound" : issue);
                }
                if (missing) reasons.Add("missing_convey");
                if (reasons.Count != 0) gaps++;
                PortalLinkEvidence? evidence = linkIndex is { } ri && linkEvidence is not null ? linkEvidence.GetValueOrDefault(new(scene, ri)) : null;
                uint? nameIndex = binding?.StageMarkerOnly == true ? binding.StageMarkerEventId : linkIndex;
                details.Add(new(index, linkIndex, binding?.StageMarkerEventId,
                    (binding?.StageMarkerOnly == true || binding?.EventDecidedOnly == true) && binding.Destination is null ? "server_decided"
                        : binding?.DestinationVerified == true ? "verified" : "unverified",
                    boundary ? index : null, category, reasons.ToImmutable(), transfers,
                    binding is null || binding.DestinationCandidates.IsDefault ? [] : binding.DestinationCandidates,
                    nameIndex is { } ni && names?.Contains(new(scene, ni)) == true, evidence?.Destination,
                    evidence?.PositionVerified == true && evidence.X is { } x && evidence.Y is { } y ? [x, y] : null,
                    evidence?.ArrivalVerified == true && evidence.ArrivalX is { } ax && evidence.ArrivalY is { } ay ? [ax, ay] : null,
                    evidence is not null));
            }
            totalUnresolved += gaps;
            results.Add(new(scene, stages.ContainsKey(scene), hiddenCounts.GetValueOrDefault(scene), crossCounts.GetValueOrDefault(scene),
                events.Length, ordinary, gaps, details.ToImmutable()));
        }
        int references = 0, sourceXY = 0, arrivalXY = 0, missingMarker = 0, missingEvent = 0, unknown = 0;
        if (linkEvidence is not null) foreach (var row in linkEvidence.Values)
        {
            work.Step(); references++; if (row.PositionVerified) sourceXY++; if (row.ArrivalVerified) arrivalXY++;
            if (!row.StageMarkerMatched) missingMarker++; if (!row.EveEventMatched) missingEvent++; if (!row.DestinationDefined) unknown++;
        }
        work.Check(); return new(1275, new Dictionary<string, string> { ["StageMapData_C"] = stageStatus, ["EveDoorLinks"] = linkStatus }.ToImmutableDictionary(),
            stageStatus == "parsed" && linkStatus == "parsed", results.Count, stages.Count, results.ToImmutable(), totalUnresolved,
            references, sourceXY, arrivalXY, missingMarker, missingEvent, unknown, routeCount, hidden, cross, noTarget);
    }
}
