using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;
using Lala.Core.World.Portals;
using Xunit;

namespace Lala.Core.Tests.World.Eve;

public sealed class OfflineBoundaryPortalTests
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    [Theory]
    [MemberData(nameof(BoundaryPortalPythonVectors.Cases), MemberType = typeof(BoundaryPortalPythonVectors))]
    public void Matches_actual_python_parsers_bindings_conflicts_and_coverage(string name, int index)
    {
        var vector = BoundaryPortalPythonVectors.Read(index); Assert.Equal(name, vector.GetProperty("name").GetString());
        var expected = vector.GetProperty("expected"); var doors = ReadDoors(vector); var stages = ReadStages(vector);
        byte[]? stage = Bytes(vector,"stage_raw"), link = Bytes(vector,"link_raw"), route = Bytes(vector,"route_raw");
        if (stage is not null)
        {
            if (expected.TryGetProperty("stage_error",out _)) Assert.Throws<PortalProjectionException>(() => OfflinePortalSources.ParseStageMap(stage));
            else
            {
                var parsed = OfflinePortalSources.ParseStageMap(stage);
                var rows = expected.GetProperty("parsed_stage"); Assert.Equal(rows.GetArrayLength(),parsed.UniqueMarkers.Count);
                foreach (var row in rows.EnumerateArray())
                {
                    var p = parsed.UniqueMarkers[ReferenceKey(row)];
                    PortalParityJson.AssertSubset(row.GetProperty("value"),Serialize(new { p.Scene, Index=p.EventId, p.Kind,p.X,p.Y,p.NameId,p.Sorting,p.CrossScene }));
                }
            }
        }
        if (link is not null)
        {
            if (expected.TryGetProperty("link_error",out _)) Assert.Throws<PortalProjectionException>(() => OfflinePortalSources.ParseEveLinks(link));
            else PortalParityJson.AssertSubset(expected.GetProperty("parsed_links"),Serialize(OfflinePortalSources.ParseEveLinks(link)));
        }
        var references = ImmutableDictionary<PortalReferenceKey,PortalLinkEvidence>.Empty;
        if (expected.TryGetProperty("reference_error",out _))
            Assert.Throws<PortalProjectionException>(() => OfflinePortalReferences.LinkEvidence(Memory(stage),link!,doors,stages));
        else
        {
            if (link is not null) references = OfflinePortalReferences.LinkEvidence(Memory(stage),link,doors,stages);
            AssertEvidence(expected.GetProperty("references"),references);
        }
        ImmutableArray<StagePortalMarker> markers = [];
        if (expected.TryGetProperty("marker_error",out _)) Assert.Throws<PortalProjectionException>(() => OfflinePortalReferences.StageMarkers(stage!,stages));
        else
        {
            if (stage is not null) markers = OfflinePortalReferences.StageMarkers(stage,stages);
            PortalParityJson.AssertSubset(expected.GetProperty("markers"),Serialize(markers));
        }
        ImmutableArray<PortalRouteReference> routes = [];
        if (expected.TryGetProperty("route_error",out _)) Assert.Throws<PortalProjectionException>(() => OfflinePortalReferences.Routes(route!,stages));
        else
        {
            if (route is not null) routes = OfflinePortalReferences.Routes(route,stages);
            foreach (var edit in vector.GetProperty("route_edits").EnumerateObject())
            {
                int i = int.Parse(edit.Name,System.Globalization.CultureInfo.InvariantCulture);
                routes = routes.SetItem(i,routes[i] with { PositionVerified=edit.Value.GetProperty("position_verified").GetBoolean() });
            }
            PortalParityJson.AssertSubset(expected.GetProperty("routes"),Serialize(routes));
        }
        var portals = new OfflineEventPortalProjection();
        if (expected.TryGetProperty("binding_error",out _))
            Assert.Throws<PortalProjectionException>(() => OfflineBoundaryPortals.Bind(Memory(stage),Memory(link),doors,stages,portals));
        else foreach (var pass in expected.GetProperty("passes").EnumerateArray())
        {
            var prior = portals; portals = OfflineBoundaryPortals.Bind(Memory(stage),Memory(link),doors,stages,prior);
            AssertProjection(pass,portals);
        }
        var unchangedPositions = portals.Positions; var unchangedEvidence = references;
        var conflict = OfflineBoundaryPortals.ReconcileRouteConflicts(portals,routes,references);
        Assert.Same(unchangedPositions,portals.Positions); Assert.Same(unchangedEvidence,references);
        AssertProjection(expected.GetProperty("conflicts"),conflict.Portals);
        AssertEvidence(expected.GetProperty("conflicts").GetProperty("evidence"),conflict.LinkEvidence);
        var names = vector.GetProperty("names").EnumerateArray().Select(v => new PortalReferenceKey(v[0].GetUInt16(),v[1].GetUInt32())).ToHashSet();
        var report = OfflinePortalCoverage.Audit(doors,stages,Memory(stage),Memory(link),conflict.Portals,names,conflict.LinkEvidence,routes,markers);
        PortalParityJson.AssertSubset(expected.GetProperty("coverage"),Serialize(report));
    }

    [Fact]
    public void Cancellation_and_budgets_do_not_publish_partial_projections()
    {
        var v = BoundaryPortalPythonVectors.Read(3); var doors = ReadDoors(v); var stages = ReadStages(v);
        var sr = Bytes(v,"stage_raw")!; var lr = Bytes(v,"link_raw")!;
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        Assert.Throws<OperationCanceledException>(() => OfflinePortalSources.ParseStageMap(sr,cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => OfflinePortalSources.ParseEveLinks(lr,cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => OfflinePortalSources.ParseDoorRoutes(new byte[4],cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => OfflineBoundaryPortals.Bind(sr,lr,doors,stages,cancellationToken:cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => OfflinePortalCoverage.Audit(doors,stages,sr,lr,cancellationToken:cancellation.Token));
        var budget = new PortalProjectionBudget(1);
        Assert.Throws<PortalProjectionException>(() => OfflineBoundaryPortals.Bind(sr,lr,doors,stages,budget:budget));
        Assert.Throws<PortalProjectionException>(() => OfflinePortalReferences.StageMarkers(sr,stages,budget));
        Assert.Throws<PortalProjectionException>(() => OfflinePortalCoverage.Audit(doors,stages,sr,lr,budget:budget));
        Assert.Throws<ArgumentOutOfRangeException>(() => OfflinePortalCoverage.Audit(doors,stages,budget:new(0)));
        Assert.Throws<ArgumentOutOfRangeException>(() => OfflineBoundaryPortals.Bind(sr,lr,doors,stages,budget:new(10_000_001)));
    }

    [Fact]
    public void Conflict_budget_counts_each_retained_candidate_and_preserves_inputs()
    {
        var key = new EventPortalKey(60000,3); var referenceKey = new PortalReferenceKey(60000,1);
        var portals = new OfflineEventPortalProjection(new Dictionary<EventPortalKey,EventPortalPosition>
            { [key]=new(60000,3,100,200,true,null,"test",null,"test",1) },new Dictionary<EventPortalKey,EventPortalDestination>
            { [key]=new(60000,3,58001,LinkIndex:1) });
        var routes = Enumerable.Range(1,100).Select(i => new PortalRouteReference(60000,i,(ushort)i,100,200,0,0,100,200,null,null,true,false,false,null,"test")).ToArray();
        var reference = new PortalLinkEvidence(60000,1,58001,100,200,0,0,100,200,null,null,true,null,false,true,false,false,null,[],"test");
        var evidence = new Dictionary<PortalReferenceKey,PortalLinkEvidence> { [referenceKey]=reference };
        // 100 input routes + 1 evidence + 1 destination fit. Copying/comparing 100 targets must not.
        var error = Assert.Throws<PortalProjectionException>(() => OfflineBoundaryPortals.ReconcileRouteConflicts(portals,routes,evidence,new(110)));
        Assert.Contains("budget exceeded",error.Message,StringComparison.Ordinal);
        Assert.Single(portals.Positions); Assert.Single(portals.Destinations); Assert.Same(reference,evidence[referenceKey]);
    }

    [Fact]
    public void Event_flattening_is_charged_before_shared_transfer_output_is_allocated()
    {
        var vector = BoundaryPortalPythonVectors.Read(0); var parsed = EveDoorParser.ParseLayout(Convert.FromBase64String(vector.GetProperty("raw").GetString()!));
        var door = parsed.Scenes[0].Doors[0]; var touch = door.TouchEventRecords[0];
        var shared = Enumerable.Repeat(touch.ConveyTransfers[0],100).ToImmutableArray();
        door = door with { TouchEventRecords=[touch with { ConveyTransfers=shared }] };
        var doors = new EveDoorProjection([new(60000,[door,door with { Index=4 }])],2);
        // Boundary work is tiny, but the two per-door flattened copies are not.
        var error = Assert.Throws<PortalProjectionException>(() => OfflineBoundaryPortals.Bind(null,null,doors,ReadStages(vector),budget:new(50)));
        Assert.Contains("budget exceeded",error.Message,StringComparison.Ordinal);
    }

    [Fact]
    public void Cancellation_during_route_enumeration_keeps_input_state()
    {
        using var cancellation = new CancellationTokenSource(); var prior = new OfflineEventPortalProjection();
        IEnumerable<PortalRouteReference> Routes()
        {
            yield return new(1,1,2,1,2,3,4,1,2,3,4,true,true,true,null,"test");
            cancellation.Cancel();
            yield return new(1,2,3,1,2,3,4,1,2,3,4,true,true,true,null,"test");
        }
        Assert.Throws<OperationCanceledException>(() => OfflineBoundaryPortals.ReconcileRouteConflicts(prior,Routes(),cancellationToken:cancellation.Token));
        Assert.Empty(prior.Positions); Assert.Empty(prior.Destinations);
    }

    [Fact]
    public void Parsers_own_output_and_reject_declared_oversize_before_reading_rows()
    {
        var v = BoundaryPortalPythonVectors.Read(3); var raw = Bytes(v,"stage_raw")!;
        var parsed = OfflinePortalSources.ParseStageMap(raw); var expected = parsed.Rows[0]; Array.Fill(raw,(byte)0);
        Assert.Equal(expected,parsed.Rows[0]); Assert.Equal((ushort)60000,parsed.Rows[0].Scene);
        byte[] bad = [0xa1,0x86,0x01,0]; // 100001 rows
        Assert.Throws<PortalProjectionException>(() => OfflinePortalSources.ParseStageMap(bad));
        Assert.Throws<PortalProjectionException>(() => OfflinePortalSources.ParseDoorRoutes(bad));
        Assert.Throws<PortalProjectionException>(() => OfflinePortalSources.ParseEveLinks(new byte[OfflinePortalSources.MaximumLinkBytes+2]));
    }

    private static void AssertProjection(JsonElement expected, OfflineEventPortalProjection actual)
    {
        Assert.Equal(expected.GetProperty("positions").GetArrayLength(),actual.Positions.Count);
        Assert.Equal(expected.GetProperty("destinations").GetArrayLength(),actual.Destinations.Count);
        Assert.Equal(expected.GetProperty("issues").GetArrayLength(),actual.Issues.Count);
        foreach (var row in expected.GetProperty("positions").EnumerateArray()) PortalParityJson.AssertSubset(row.GetProperty("value"),PortalParityJson.Position(actual.Positions[DoorKey(row)]));
        foreach (var row in expected.GetProperty("destinations").EnumerateArray()) PortalParityJson.AssertSubset(row.GetProperty("value"),PortalParityJson.Destination(actual.Destinations[DoorKey(row)]));
        foreach (var row in expected.GetProperty("issues").EnumerateArray()) Assert.Equal(row.GetProperty("value").GetString(),actual.Issues[DoorKey(row)]);
    }
    private static void AssertEvidence(JsonElement expected, IReadOnlyDictionary<PortalReferenceKey,PortalLinkEvidence> actual)
    {
        Assert.Equal(expected.GetArrayLength(),actual.Count);
        foreach (var row in expected.EnumerateArray())
        {
            var value = actual[ReferenceKey(row)]; if (value.DestinationCandidates.IsDefault) value = value with { DestinationCandidates=[] };
            PortalParityJson.AssertSubset(row.GetProperty("value"),Serialize(value));
        }
    }
    private static JsonElement Serialize<T>(T value) => JsonSerializer.SerializeToElement(value,Json);
    private static byte[]? Bytes(JsonElement e,string name) => e.GetProperty(name).ValueKind == JsonValueKind.Null ? null : Convert.FromBase64String(e.GetProperty(name).GetString()!);
    private static ReadOnlyMemory<byte>? Memory(byte[]? raw) => raw is null ? (ReadOnlyMemory<byte>?)null : new ReadOnlyMemory<byte>(raw);
    private static EventPortalKey DoorKey(JsonElement row) => new(row.GetProperty("key")[0].GetUInt16(),row.GetProperty("key")[1].GetUInt16());
    private static PortalReferenceKey ReferenceKey(JsonElement row) => new(row.GetProperty("key")[0].GetUInt16(),row.GetProperty("key")[1].GetUInt32());
    private static EveDoorProjection ReadDoors(JsonElement v)
    {
        var baseDoor = EveDoorParser.ParseLayout(Convert.FromBase64String(v.GetProperty("raw").GetString()!)).Scenes[0].Doors[0];
        if (v.GetProperty("no_events").GetBoolean()) baseDoor = baseDoor with { TouchEventRecords=[] };
        var rows = ImmutableArray.CreateBuilder<EveDoorRow>();
        foreach (var e in v.GetProperty("door_edits").EnumerateArray())
        {
            uint U(string key,uint fallback) => e.TryGetProperty(key,out var value) ? value.GetUInt32() : fallback;
            rows.Add(baseDoor with { Index=(ushort)U("index",baseDoor.Index),X=U("x",baseDoor.X),Y=U("y",baseDoor.Y),Right=U("right",baseDoor.Right),Bottom=U("bottom",baseDoor.Bottom),
                SignType=(byte)U("sign_type",baseDoor.SignType),SignX=U("sign_x",baseDoor.SignX),SignY=U("sign_y",baseDoor.SignY),
                TouchEventIds=e.TryGetProperty("touch_event_ids",out var ids) ? ids.EnumerateArray().Select(n => n.GetByte()).ToImmutableArray() : baseDoor.TouchEventIds });
        }
        return new([new(v.GetProperty("door_scene").GetUInt16(),rows.ToImmutable())],rows.Count);
    }
    private static Dictionary<ushort,StageDataRow> ReadStages(JsonElement v) => v.GetProperty("stages").EnumerateObject().ToDictionary(
        p => ushort.Parse(p.Name,System.Globalization.CultureInfo.InvariantCulture),p =>
        {
            ushort id=ushort.Parse(p.Name,System.Globalization.CultureInfo.InvariantCulture); var x=p.Value;
            return new StageDataRow(id,0,0,0,0,0,0,0,0,0,0,x.GetProperty("pos_x_ratio").GetByte(),x.GetProperty("pos_y_ratio").GetByte(),x.GetProperty("map_width").GetUInt16(),
                x.GetProperty("map_height").GetUInt16(),x.GetProperty("small_offset_x").GetUInt16(),x.GetProperty("small_offset_y").GetUInt16());
        });
}
