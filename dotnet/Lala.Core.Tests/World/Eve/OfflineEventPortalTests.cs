using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;
using Lala.Core.World.Portals;
using Xunit;

namespace Lala.Core.Tests.World.Eve;

public sealed class OfflineEventPortalTests
{
    [Theory]
    [MemberData(nameof(EventPortalPythonVectors.Cases), MemberType = typeof(EventPortalPythonVectors))]
    public void Matches_actual_python_reconciliation(string name, int index)
    {
        Assert.False(string.IsNullOrEmpty(name));
        var vector = EventPortalPythonVectors.Read(index);
        Assert.Equal(name, vector.GetProperty("name").GetString());
        var doors = ReadDoors(vector);
        var stages = ReadStages(vector);
        var state = ReadPrior(vector);
        var original = state;
        foreach (var expected in vector.GetProperty("expected").EnumerateArray())
        {
            state = OfflineEventPortalProjector.Reconcile(doors, stages, state);
            Assert.Equal(expected.GetProperty("positions").GetArrayLength(), state.Positions.Count);
            Assert.Equal(expected.GetProperty("destinations").GetArrayLength(), state.Destinations.Count);
            Assert.Equal(expected.GetProperty("issues").GetArrayLength(), state.Issues.Count);
            foreach (var row in expected.GetProperty("positions").EnumerateArray())
                AssertSubset(row.GetProperty("value"), Position(state.Positions[Key(row)]));
            foreach (var row in expected.GetProperty("destinations").EnumerateArray())
                AssertSubset(row.GetProperty("value"), Destination(state.Destinations[Key(row)]));
            foreach (var row in expected.GetProperty("issues").EnumerateArray())
                Assert.Equal(row.GetProperty("value").GetString(), state.Issues[Key(row)]);
        }
        Assert.Equal(ReadPrior(vector).Positions, original.Positions);
        Assert.Equal(ReadPrior(vector).Destinations, original.Destinations);
        Assert.Equal(ReadPrior(vector).Issues, original.Issues);
    }

    [Fact]
    public void Cancellation_and_null_inputs_publish_nothing()
    {
        var vector = EventPortalPythonVectors.Read(0);
        using var cts = new CancellationTokenSource(); cts.Cancel();
        var prior = new OfflineEventPortalProjection();
        Assert.Throws<OperationCanceledException>(() => OfflineEventPortalProjector.Reconcile(ReadDoors(vector), ReadStages(vector), prior, cts.Token));
        Assert.Empty(prior.Positions); Assert.Empty(prior.Destinations); Assert.Empty(prior.Issues);
        Assert.Throws<ArgumentNullException>(() => OfflineEventPortalProjector.Reconcile(null!, ReadStages(vector)));
        Assert.Throws<ArgumentNullException>(() => OfflineEventPortalProjector.Reconcile(ReadDoors(vector), null!));
    }

    [Fact]
    public void Cancel_during_traversal_does_not_change_prior_or_publish_partial_state()
    {
        var vector = EventPortalPythonVectors.Read(0);
        using var cts = new CancellationTokenSource();
        var stages = new CancellingStages(ReadStages(vector), cts);
        var prior = ReadPrior(EventPortalPythonVectors.Read(38));
        var positions = prior.Positions; var destinations = prior.Destinations;
        Assert.Throws<OperationCanceledException>(() => OfflineEventPortalProjector.Reconcile(ReadDoors(vector), stages, prior, cts.Token));
        Assert.Same(positions, prior.Positions); Assert.Same(destinations, prior.Destinations);
    }

    [Fact]
    public void Snapshot_copies_mutable_collections_and_retains_immutable_records()
    {
        var key = new EventPortalKey(60000, 3);
        var positions = new Dictionary<EventPortalKey, EventPortalPosition> { [key] = new(60000, 3, 1, 2, false, null, "seed", null, "seed", 9) };
        var destinations = new Dictionary<EventPortalKey, EventPortalDestination> { [key] = new(60000, 3, 58001) };
        var issues = new Dictionary<EventPortalKey, string> { [key] = "conflict" };
        var snapshot = new OfflineEventPortalProjection(positions, destinations, issues);
        positions.Clear(); destinations.Clear(); issues.Clear();
        Assert.Single(snapshot.Positions); Assert.Single(snapshot.Destinations); Assert.Single(snapshot.Issues);
    }

    private static EveDoorProjection ReadDoors(JsonElement vector)
    {
        var parsed = EveDoorParser.ParseLayout(Convert.FromBase64String(vector.GetProperty("raw").GetString()!));
        var d = parsed.Scenes[0].Doors[0]; var e = vector.GetProperty("edit");
        uint U(string k, uint value) => e.TryGetProperty(k, out var v) ? v.GetUInt32() : value;
        d = d with { Index = (ushort)U("index", d.Index), X = U("x", d.X), Y = U("y", d.Y), Right = U("right", d.Right), Bottom = U("bottom", d.Bottom),
            SignType = (byte)U("sign_type", d.SignType), SignX = U("sign_x", d.SignX), SignY = U("sign_y", d.SignY) };
        if (vector.GetProperty("no_events").GetBoolean()) d = d with { TouchEventRecords = [] };
        ImmutableArray<EveDoorRow> rows = vector.GetProperty("duplicate").GetBoolean() ? [d, d] : [d];
        return new([new(60000, rows)], rows.Length);
    }
    private static Dictionary<ushort, StageDataRow> ReadStages(JsonElement vector) => vector.GetProperty("stages").EnumerateObject().ToDictionary(
        p => ushort.Parse(p.Name, System.Globalization.CultureInfo.InvariantCulture), p =>
        {
            ushort id = ushort.Parse(p.Name, System.Globalization.CultureInfo.InvariantCulture); var v = p.Value;
            return new StageDataRow(id, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, (byte)Number(v,"pos_x_ratio"), (byte)Number(v,"pos_y_ratio"),
                (ushort)Number(v,"map_width"), (ushort)Number(v,"map_height"), (ushort)Number(v,"small_offset_x"), (ushort)Number(v,"small_offset_y"));
        });
    private static OfflineEventPortalProjection ReadPrior(JsonElement vector)
    {
        var p = vector.GetProperty("prior"); if (p.ValueKind == JsonValueKind.Null) return new();
        var key = new EventPortalKey(60000, 3);
        var positions = new Dictionary<EventPortalKey, EventPortalPosition>();
        var destinations = new Dictionary<EventPortalKey, EventPortalDestination>();
        var issues = new Dictionary<EventPortalKey, string>();
        if (p.TryGetProperty("position", out var pos)) positions[key] = new(60000, 3, Number(pos,"x"), Number(pos,"y"), pos.GetProperty("position_verified").GetBoolean(),
            null, pos.GetProperty("source_kind").GetString()!, null, pos.GetProperty("binding_kind").GetString()!, (int)Number(pos,"link_index"), Number(pos,"raw_link_x"), Number(pos,"raw_link_y"), (byte)Number(pos,"pos_x_ratio"), (byte)Number(pos,"pos_y_ratio"));
        if (p.TryGetProperty("destination", out var dest)) destinations[key] = new(60000, 3, (ushort)Number(dest,"destination"), LinkIndex:(int)Number(dest,"link_index"),
            MatchedStageMap:true, StageMarkerOnly:true, StageMarkerKind:(byte)Number(dest,"stage_marker_kind"), StageMarkerEventId:(uint)Number(dest,"stage_marker_event_id"), StageMarkerNameId:(uint)Number(dest,"stage_marker_name_id"), X:Number(dest,"x"), Y:Number(dest,"y"), ArrivalX:Number(dest,"arrival_x"), ArrivalY:Number(dest,"arrival_y"));
        if (p.TryGetProperty("issue", out var issue)) issues[key] = issue.GetString()!;
        return new(positions, destinations, issues);
    }
    private static long Number(JsonElement e, string name) => e.TryGetProperty(name, out var v) ? v.GetInt64() : 0;
    private static EventPortalKey Key(JsonElement row) => new(row.GetProperty("key")[0].GetUInt16(), row.GetProperty("key")[1].GetUInt16());
    private static JsonElement Position(EventPortalPosition p) => JsonSerializer.SerializeToElement(new
    {
        scene=p.Scene,index=p.Index,x=p.X,y=p.Y,position_verified=p.PositionVerified,
        projection_guard=p.ProjectionGuard is { } g ? new { rate=g.Rate,offset_x=g.OffsetX,offset_y=g.OffsetY,height=g.Height } : null,
        source_kind=p.SourceKind,trigger_bounds=p.TriggerBounds is { } b ? new[] { b.Left,b.Top,b.Right,b.Bottom } : null,
        binding_kind=p.BindingKind,link_index=p.LinkIndex,raw_link_x=p.RawLinkX,raw_link_y=p.RawLinkY,pos_x_ratio=p.PosXRatio,pos_y_ratio=p.PosYRatio
    });
    private static JsonElement Destination(EventPortalDestination d) => JsonSerializer.SerializeToElement(new
    {
        scene=d.Scene,index=d.Index,destination=d.Destination,destination_verified=d.DestinationVerified,event_x=d.EventX,event_y=d.EventY,
        matched_touch_region=d.MatchedTouchRegion,door_binding_verified=d.DoorBindingVerified,trigger_verified=d.TriggerVerified,
        event_convey_verified=d.EventConveyVerified,event_decided_only=d.EventDecidedOnly,
        destination_candidates=d.DestinationCandidates.IsDefault ? [] : d.DestinationCandidates.ToArray(),
        convey_transfers=d.ConveyTransfers.IsDefault ? [] : d.ConveyTransfers.Select(t => new
        {
            convey_id=t.Convey.ConveyId,destination=t.Convey.Destination,arrival_x=t.Convey.ArrivalX,arrival_y=t.Convey.ArrivalY,
            name=t.Convey.Name.Name,name_bytes=t.Convey.Name.NameBytes,name_valid=t.Convey.Name.NameValid,
            condition=new { id=t.Condition.Id,para_main=t.Condition.ParaMain,para_kind=t.Condition.ParaKind,para_style=t.Condition.ParaStyle,
                para_type=t.Condition.ParaType,para_operator=t.Condition.ParaOperator,para_value=t.Condition.ParaValue,
                group_number=t.Condition.GroupNumber,para_class1=t.Condition.ParaClass1,para_class2=t.Condition.ParaClass2 }
        }).ToArray(),binding_kind=d.BindingKind,link_index=d.LinkIndex,matched_stage_map=d.MatchedStageMap,stage_marker_only=d.StageMarkerOnly,
        stage_marker_kind=d.StageMarkerKind,stage_marker_event_id=d.StageMarkerEventId,stage_marker_name_id=d.StageMarkerNameId,x=d.X,y=d.Y,arrival_x=d.ArrivalX,arrival_y=d.ArrivalY
    });
    private static void AssertSubset(JsonElement expected, JsonElement actual)
    {
        Assert.Equal(expected.ValueKind, actual.ValueKind);
        if (expected.ValueKind == JsonValueKind.Object)
            foreach (var p in expected.EnumerateObject()) { Assert.True(actual.TryGetProperty(p.Name, out var value), p.Name); AssertSubset(p.Value,value); }
        else if (expected.ValueKind == JsonValueKind.Array)
        {
            Assert.Equal(expected.GetArrayLength(),actual.GetArrayLength());
            for (int i=0;i<expected.GetArrayLength();i++) AssertSubset(expected[i],actual[i]);
        }
        else if (expected.ValueKind == JsonValueKind.Number) Assert.Equal(expected.GetDouble(),actual.GetDouble());
        else if (expected.ValueKind == JsonValueKind.String) Assert.Equal(expected.GetString(),actual.GetString());
        else Assert.Equal(expected.GetRawText(),actual.GetRawText());
    }
    private sealed class CancellingStages(Dictionary<ushort, StageDataRow> rows, CancellationTokenSource cancellation) : IReadOnlyDictionary<ushort, StageDataRow>
    {
        public StageDataRow this[ushort key] => rows[key];
        public IEnumerable<ushort> Keys => rows.Keys;
        public IEnumerable<StageDataRow> Values => rows.Values;
        public int Count => rows.Count;
        public bool ContainsKey(ushort key) { cancellation.Cancel(); return rows.ContainsKey(key); }
        public bool TryGetValue(ushort key, out StageDataRow value) => rows.TryGetValue(key,out value!);
        public IEnumerator<KeyValuePair<ushort,StageDataRow>> GetEnumerator() => rows.GetEnumerator();
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
