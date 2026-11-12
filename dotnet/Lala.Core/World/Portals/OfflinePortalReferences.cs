using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.World.Portals;

public sealed record StagePortalMarker(ushort Scene, byte Kind, uint EventId, ushort? CrossSceneReference,
    uint? Destination, bool DestinationDefined, ushort SourceGridX, ushort SourceGridY,
    long? X, long? Y, uint NameId, byte Sorting, bool PositionVerified,
    EventPortalProjectionGuard? ProjectionGuard, string SourceKind);
public sealed record PortalLinkEvidence(ushort Scene, int Index, ushort Destination,
    ushort SourceGridX, ushort SourceGridY, ushort ArrivalGridX, ushort ArrivalGridY,
    long? X, long? Y, long? ArrivalX, long? ArrivalY, bool PositionVerified,
    EventPortalProjectionGuard? ProjectionGuard, bool ArrivalVerified, bool DestinationDefined,
    bool StageMarkerMatched, bool EveEventMatched, uint? NameId, ImmutableArray<string> Issues,
    string SourceKind, ImmutableArray<ushort> DestinationCandidates = default);
public sealed record PortalRouteReference(ushort Scene, int RouteOrdinal, ushort Destination,
    ushort SourceGridX, ushort SourceGridY, ushort ArrivalGridX, ushort ArrivalGridY,
    long? X, long? Y, long? ArrivalX, long? ArrivalY, bool PositionVerified, bool ArrivalVerified,
    bool DestinationDefined, EventPortalProjectionGuard? ProjectionGuard, string SourceKind);

/// <summary>Offline references only. Link ordinals and marker event IDs are never converted to
/// door identity. Field names retain Python's geometric cross-check terminology, not provenance.</summary>
public static class OfflinePortalReferences
{
    public static ImmutableArray<StagePortalMarker> StageMarkers(ReadOnlySpan<byte> raw,
        IReadOnlyDictionary<ushort, StageDataRow> stages, PortalProjectionBudget? budget = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(stages);
        var work = (budget ?? new()).Start(cancellationToken);
        return Markers(OfflinePortalSources.ParseStageMap(raw, cancellationToken), stages, work);
    }
    internal static ImmutableArray<StagePortalMarker> Markers(ParsedStagePortals parsed,
        IReadOnlyDictionary<ushort, StageDataRow> stages, PortalWork work)
    {
        // inspect_stage_map is stricter than parse_stage_map_portals: all scene IDs must be nonzero.
        foreach (var row in parsed.Rows) { work.Step(); if (row.Scene == 0) throw new PortalProjectionException("Zero StageMap scene"); }
        var result = ImmutableArray.CreateBuilder<StagePortalMarker>();
        foreach (var row in parsed.Rows)
        {
            work.Step(); if (row.Kind is not (2 or 3 or 4)) continue;
            stages.TryGetValue(row.Scene, out var stage);
            var point = row.Kind is 2 or 3 ? PortalGeometry.Point(stage, row.X, row.Y) : null;
            uint? destination = row.Kind == 3 && row.EventId > 0 ? row.EventId : null;
            result.Add(new(row.Scene, row.Kind, row.EventId, row.Kind == 4 ? row.CrossScene : null,
                destination, destination is > 0 and <= ushort.MaxValue && stages.ContainsKey((ushort)destination.Value),
                row.X, row.Y, point?.X, point?.Y, row.NameId, row.Sorting, point is not null,
                row.Kind is 2 or 3 ? PortalGeometry.Guard(stage) : null,
                row.Kind == 3 ? "1275_hidden_stage_marker" : row.Kind == 4 ? "1275_other_scene_marker" : "1275_normal_stage_marker"));
        }
        work.Check(); return result.ToImmutable();
    }
    public static ImmutableDictionary<PortalReferenceKey, PortalLinkEvidence> LinkEvidence(ReadOnlyMemory<byte>? stageRaw,
        ReadOnlySpan<byte> linkRaw, EveDoorProjection doors, IReadOnlyDictionary<ushort, StageDataRow> stages,
        PortalProjectionBudget? budget = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(doors); ArgumentNullException.ThrowIfNull(stages);
        var work = (budget ?? new()).Start(cancellationToken);
        var markers = stageRaw is { } raw ? OfflinePortalSources.ParseStageMap(raw.Span, cancellationToken).UniqueMarkers
            : ImmutableDictionary<PortalReferenceKey, StagePortalRow>.Empty;
        var links = OfflinePortalSources.ParseEveLinks(linkRaw, cancellationToken);
        var counts = PortalGeometry.DoorCounts(doors, work);
        var result = ImmutableDictionary.CreateBuilder<PortalReferenceKey, PortalLinkEvidence>();
        foreach (var pair in links)
            foreach (var link in pair.Value)
            {
                work.Step(); var key = new PortalReferenceKey(link.Scene, (uint)link.Index);
                markers.TryGetValue(key, out var marker);
                stages.TryGetValue(link.Scene, out var stage); stages.TryGetValue(link.Destination, out var target);
                var src = PortalGeometry.Point(stage, link.X, link.Y); var dst = PortalGeometry.Point(target, link.ArrivalX, link.ArrivalY);
                int count = link.Index <= ushort.MaxValue ? counts.GetValueOrDefault(new(link.Scene, (ushort)link.Index)) : 0;
                bool eventUnique = count == 1, markerMatched = marker?.Kind == 2;
                var issues = ImmutableArray.CreateBuilder<string>();
                if (!eventUnique) issues.Add(count == 0 ? "missing_eve_door" : "duplicate_eve_door");
                if (!markerMatched) issues.Add("missing_normal_stage_marker");
                if (stage is null) issues.Add("source_scene_undefined");
                if (target is null) issues.Add("destination_scene_undefined");
                if (src is null) issues.Add("source_coordinate_uncalibrated");
                if (dst is null) issues.Add("arrival_coordinate_uncalibrated");
                result.Add(key, new(link.Scene, link.Index, link.Destination, link.X, link.Y, link.ArrivalX, link.ArrivalY,
                    src?.X, src?.Y, dst?.X, dst?.Y, src is not null, PortalGeometry.Guard(stage), dst is not null,
                    target is not null, markerMatched, eventUnique, markerMatched ? marker!.NameId : null,
                    issues.ToImmutable(), "1275_eve_door_links_reference"));
            }
        work.Check(); return result.ToImmutable();
    }
    public static ImmutableArray<PortalRouteReference> Routes(ReadOnlySpan<byte> raw,
        IReadOnlyDictionary<ushort, StageDataRow> stages, PortalProjectionBudget? budget = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(stages); var work = (budget ?? new()).Start(cancellationToken);
        var result = ImmutableArray.CreateBuilder<PortalRouteReference>(); var counts = new Dictionary<ushort, int>();
        foreach (var row in OfflinePortalSources.ParseDoorRoutes(raw, cancellationToken))
        {
            work.Step(); int index = counts.GetValueOrDefault(row.Scene) + 1; counts[row.Scene] = index;
            stages.TryGetValue(row.Scene, out var stage); stages.TryGetValue(row.Destination, out var target);
            var src = PortalGeometry.Point(stage, row.X, row.Y); var dst = PortalGeometry.Point(target, row.ArrivalX, row.ArrivalY);
            result.Add(new(row.Scene, index, row.Destination, row.X, row.Y, row.ArrivalX, row.ArrivalY,
                src?.X, src?.Y, dst?.X, dst?.Y, src is not null, dst is not null, target is not null,
                PortalGeometry.Guard(stage), "1275_door_link_data_reference"));
        }
        work.Check(); return result.ToImmutable();
    }
}

internal static class PortalGeometry
{
    internal static Dictionary<EventPortalKey, int> DoorCounts(EveDoorProjection doors, PortalWork work)
    {
        var counts = new Dictionary<EventPortalKey, int>();
        foreach (var scene in doors.Scenes) foreach (var door in scene.Doors)
        { work.Step(); var key = new EventPortalKey(scene.SceneId, door.Index); counts[key] = counts.GetValueOrDefault(key) + 1; }
        return counts;
    }
    internal static EventPortalProjectionGuard? Guard(StageDataRow? stage)
    {
        if (stage is null) return null;
        int width = stage.MapWidth == ushort.MaxValue ? 6992 : stage.MapWidth;
        int height = stage.MapHeight == ushort.MaxValue ? 6992 : stage.MapHeight;
        return Math.Max(width, height) <= 0 ? null : new(100000.0 / Math.Max(width, height), stage.SmallOffsetX, stage.SmallOffsetY, height);
    }
    internal static (long X, long Y)? Point(StageDataRow? stage, long x, long y)
    {
        if (stage is null || stage.PosXRatio == 0 || stage.PosYRatio == 0 || x < 0 || y < 0
            || x > ushort.MaxValue / stage.PosXRatio || y > ushort.MaxValue / stage.PosYRatio) return null;
        return (x * stage.PosXRatio, y * stage.PosYRatio);
    }
    private static long Scale(uint coordinate, uint offset, byte ratio) => ((long)coordinate - 1) * 20 * ratio + (long)offset * ratio;
    internal static (long X, long Y)? Anchor(EveDoorRow door, StageDataRow stage)
    {
        if (stage.PosXRatio == 0 || stage.PosYRatio == 0) return null;
        long x = Scale(door.X, door.SignX, stage.PosXRatio), y = Scale(door.Y, door.SignY, stage.PosYRatio);
        return x is >= 0 and <= ushort.MaxValue && y is >= 0 and <= ushort.MaxValue ? (x, y) : null;
    }
    internal static EventPortalBounds? Bounds(EveDoorRow door, StageDataRow stage)
    {
        if (door.SignType is not (1 or 4) || Anchor(door, stage) is not { } a) return null;
        long right = Scale(door.Right, door.SignX, stage.PosXRatio), bottom = Scale(door.Bottom, door.SignY, stage.PosYRatio);
        return a.X < right && right <= ushort.MaxValue && a.Y < bottom && bottom <= ushort.MaxValue ? new(a.X, a.Y, right, bottom) : null;
    }
    internal static (EveDoorRow Door, EventPortalBounds? Bounds)? Match(ImmutableArray<EveDoorRow> doors,
        StageDataRow stage, (long X, long Y) point, PortalWork work)
    {
        (EveDoorRow, EventPortalBounds?)? result = null;
        foreach (var door in doors)
        {
            work.Step(); var bounds = Bounds(door, stage);
            bool matches = bounds is { } b ? b.Left <= point.X && point.X <= b.Right && b.Top <= point.Y && point.Y <= b.Bottom
                : door.SignType is 2 or 3 or 5 && Anchor(door, stage) == point;
            if (!matches) continue;
            if (result is not null) return null;
            result = (door, bounds);
        }
        return result;
    }
}
