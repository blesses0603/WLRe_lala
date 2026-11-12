using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.World.Portals;

/// <summary>Pure port of event_portals.reconcile_event_portals. Conditions are retained, never
/// executed. No I/O, activation, admission, or transport is performed.</summary>
public static class OfflineEventPortalProjector
{
    public static OfflineEventPortalProjection Reconcile(EveDoorProjection doors,
        IReadOnlyDictionary<ushort, StageDataRow> stages, OfflineEventPortalProjection? previous = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(doors);
        ArgumentNullException.ThrowIfNull(stages);
        previous ??= new();
        var positions = previous.Positions.ToBuilder();
        var destinations = previous.Destinations.ToBuilder();
        var issues = previous.Issues.ToBuilder();
        foreach (var scene in doors.Scenes)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!stages.TryGetValue(scene.SceneId, out var stage)) continue;
            var guard = ProjectionGuard(stage);
            if (guard is null) continue;
            var counts = new Dictionary<ushort, int>();
            foreach (var door in scene.Doors)
            {
                cancellationToken.ThrowIfCancellationRequested();
                counts[door.Index] = counts.GetValueOrDefault(door.Index) + 1;
            }
            foreach (var door in scene.Doors)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var key = new EventPortalKey(scene.SceneId, door.Index);
                if (issues.TryGetValue(key, out var issue) && !string.IsNullOrEmpty(issue)) continue;
                if (door.Index == 0 || counts[door.Index] != 1) continue;
                var transfers = ImmutableArray.CreateBuilder<EveDoorTransfer>();
                bool missing = false;
                foreach (var touch in door.TouchEventRecords)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    missing |= !touch.MissingConveyIds.IsDefaultOrEmpty;
                    foreach (var transfer in touch.ConveyTransfers)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        transfers.Add(transfer);
                    }
                }
                if (missing) { Revoke(key); continue; }
                if (transfers.Count == 0) continue;
                var targets = new SortedSet<ushort>();
                bool invalid = false;
                foreach (var transfer in transfers)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                    ushort target = transfer.Convey.Destination;
                    targets.Add(target);
                    invalid |= target == 0 || !stages.ContainsKey(target);
                }
                if (invalid) { Revoke(key); continue; }
                var bounds = TouchBounds(door, stage);
                if (bounds is null && door.SignType is 1 or 4)
                {
                    var anchor = Anchor(door, stage);
                    long right = Scale(door.Right, door.SignX, stage.PosXRatio);
                    long bottom = Scale(door.Bottom, door.SignY, stage.PosYRatio);
                    if (anchor is { } a && a.X <= right && right <= ushort.MaxValue
                        && a.Y <= bottom && bottom <= ushort.MaxValue)
                        bounds = new(a.X, a.Y, right, bottom);
                }
                (long X, long Y)? point = bounds is { } b ? ((b.Left + b.Right) / 2, (b.Top + b.Bottom) / 2)
                    : door.SignType is 2 or 3 or 5 ? Anchor(door, stage) : null;
                if (point is not { } p || !InRange(p.X) || !InRange(p.Y)) continue;
                destinations.TryGetValue(key, out var prior);
                if (prior?.Destination is { } old && !targets.Contains(old))
                {
                    Revoke(key);
                    issues[key] = "conflicting_event_destination";
                    continue;
                }
                // Source preserves an existing point verbatim, even when outside the bounds.
                // Do not silently strengthen that behavior or claim a new geometric check.
                if (!positions.ContainsKey(key))
                    positions[key] = new(scene.SceneId, door.Index, p.X, p.Y, true, guard,
                        "eve_convey_door_scaled", bounds, "eve_convey", null);
                ushort? destination = targets.Count == 1 ? targets.Min : null;
                destinations[key] = (prior ?? new(scene.SceneId, door.Index, null)) with
                {
                    Scene = scene.SceneId, Index = door.Index, Destination = destination,
                    DestinationVerified = destination is not null, EventX = door.X, EventY = door.Y,
                    MatchedTouchRegion = true, DoorBindingVerified = true, TriggerVerified = false,
                    EventConveyVerified = true, EventDecidedOnly = destination is null,
                    DestinationCandidates = targets.ToImmutableArray(), ConveyTransfers = transfers.ToImmutable(),
                    BindingKind = "eve_convey"
                };
            }
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(positions, destinations, issues);
        void Revoke(EventPortalKey key) { positions.Remove(key); destinations.Remove(key); }
    }

    private static EventPortalProjectionGuard? ProjectionGuard(StageDataRow stage)
    {
        int width = stage.MapWidth == ushort.MaxValue ? 6992 : stage.MapWidth;
        int height = stage.MapHeight == ushort.MaxValue ? 6992 : stage.MapHeight;
        int maximum = Math.Max(width, height);
        return maximum <= 0 ? null : new(100.0 * (1024 - 24) / maximum,
            stage.SmallOffsetX, stage.SmallOffsetY, height);
    }
    // Convert before subtraction: uint zero must become -1, not wrap to uint.MaxValue.
    private static long Scale(uint coordinate, uint offset, byte ratio) => ((long)coordinate - 1) * 20 * ratio + (long)offset * ratio;
    private static bool InRange(long value) => value is >= 0 and <= ushort.MaxValue;
    private static (long X, long Y)? Anchor(EveDoorRow door, StageDataRow stage)
    {
        if (stage.PosXRatio == 0 || stage.PosYRatio == 0) return null;
        long x = Scale(door.X, door.SignX, stage.PosXRatio), y = Scale(door.Y, door.SignY, stage.PosYRatio);
        return InRange(x) && InRange(y) ? (x, y) : null;
    }
    private static EventPortalBounds? TouchBounds(EveDoorRow door, StageDataRow stage)
    {
        if (door.SignType is not (1 or 4) || Anchor(door, stage) is not { } a) return null;
        long right = Scale(door.Right, door.SignX, stage.PosXRatio), bottom = Scale(door.Bottom, door.SignY, stage.PosYRatio);
        return a.X < right && right <= ushort.MaxValue && a.Y < bottom && bottom <= ushort.MaxValue
            ? new(a.X, a.Y, right, bottom) : null;
    }
}
