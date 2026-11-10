using System.Collections.Immutable;
using Lala.Core.Resources;
using Lala.Core.World.Portals;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class ScenePortalObservationTests
{
    [Fact]
    public void Scene_filter_order_conflicts_and_event_coordinates_are_preserved_without_authority()
    {
        var destination = new EventPortalDestination(10, 2, null, EventX: uint.MaxValue, DestinationCandidates: [20, 30]);
        var source = new OfflineEventPortalProjection(
            destinations: new Dictionary<EventPortalKey, EventPortalDestination> { [new(10,2)] = destination, [new(11,1)] = new(11,1,20) },
            issues: new Dictionary<EventPortalKey,string> { [new(10,3)] = "conflict", [new(10,2)] = "ambiguous" });
        var rows = ScenePortalObservationRequest.Build(10, source);
        Assert.Equal(new ushort[] { 2, 3 }, rows.Select(x => x.Index));
        Assert.Same(destination, rows[0].Destination); Assert.Null(rows[0].Position);
        Assert.Equal("ambiguous", rows[0].Issue); Assert.Equal("conflict", rows[1].Issue);
        Assert.Null(rows[1].Destination); Assert.All(rows, x => Assert.False(x.CanTravel));
    }
    [Fact]
    public void Mismatched_identity_and_excess_rows_are_rejected()
    {
        var bad = new OfflineEventPortalProjection(destinations: new Dictionary<EventPortalKey,EventPortalDestination> { [new(10,1)] = new(11,1,20) });
        Assert.Throws<ResourceValidationException>(() => ScenePortalObservationRequest.Build(10,bad));
        var large = new OfflineEventPortalProjection(issues: Enumerable.Range(0,4097).Select(i => new KeyValuePair<EventPortalKey,string>(new(10,(ushort)i),"unknown")));
        Assert.Throws<ResourceValidationException>(() => ScenePortalObservationRequest.Build(10,large));
    }
    [Fact]
    public void Known_empty_missing_sources_and_revocation_remain_distinct()
    {
        bool active = true;
        var request = new ScenePortalObservationRequest(10,"test",ScenePortalObservationRequest.Build(10,new()),["StageMapData_C"],()=>active);
        Assert.True(request.TryReadRows(out var rows)); Assert.Empty(rows);
        Assert.Single(request.UnavailableOptionalSources); Assert.False(request.CanSendPackets);
        active = false; Assert.False(request.TryReadRows(out _));
        int reads = 0;
        var racing = new ScenePortalObservationRequest(10,"test",[],[],()=>++reads == 1);
        Assert.False(racing.TryReadRows(out var stale)); Assert.Empty(stale);
    }
}
