using System.Collections.Immutable;
using Lala.Core.World.Portals;

namespace Lala.Core.Resources;

/// <summary>Event-only source observations, not a complete portal roster or travel authority.</summary>
public sealed record ScenePortalObservation(ushort Index, EventPortalPosition? Position,
    EventPortalDestination? Destination, string? Issue)
{
    public bool CanTravel => false;
}

/// <summary>Revocable view of the current account scene's immutable resource observations.</summary>
public sealed class ScenePortalObservationRequest
{
    private readonly ImmutableArray<ScenePortalObservation> rows;
    private readonly Func<bool> current;
    public ushort Scene { get; }
    public string Identity { get; }
    public bool IsCurrent => current();
    public bool CanSendPackets => false;
    public ImmutableArray<string> UnavailableOptionalSources { get; }
    internal ScenePortalObservationRequest(ushort scene, string identity,
        ImmutableArray<ScenePortalObservation> rows, ImmutableArray<string> unavailable, Func<bool> current)
        => (Scene, Identity, this.rows, UnavailableOptionalSources, this.current) = (scene, identity, rows, unavailable, current);
    public bool TryReadRows(out ImmutableArray<ScenePortalObservation> result)
    {
        result = [];
        if (!IsCurrent) return false;
        var captured = rows;
        if (!IsCurrent) return false;
        result = captured;
        return true;
    }
    internal static ImmutableArray<ScenePortalObservation> Build(ushort scene, OfflineEventPortalProjection source)
    {
        var keys = source.Positions.Keys.Concat(source.Destinations.Keys).Concat(source.Issues.Keys)
            .Where(k => k.Scene == scene).Distinct().Take(4097).ToArray();
        if (keys.Length > 4096) throw new ResourceValidationException("Scene portal observation limit exceeded");
        var result = ImmutableArray.CreateBuilder<ScenePortalObservation>(keys.Length);
        foreach (var key in keys.OrderBy(k => k.Index))
        {
            var position = source.Positions.GetValueOrDefault(key);
            var destination = source.Destinations.GetValueOrDefault(key);
            if (position is not null && (position.Scene != scene || position.Index != key.Index) ||
                destination is not null && (destination.Scene != scene || destination.Index != key.Index))
                throw new ResourceValidationException("Scene portal observation key mismatch");
            // Keep issue-only tombstones and all evidence; never promote raw event coordinates.
            result.Add(new(key.Index, position, destination, source.Issues.GetValueOrDefault(key)));
        }
        return result.MoveToImmutable();
    }
}
