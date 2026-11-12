using Xunit;
using System.Text.Json;
using Lala.Core.World.Portals;
namespace Lala.Core.Tests.World.Eve;
internal static class PortalParityJson
{
    internal static JsonElement Position(EventPortalPosition p) => JsonSerializer.SerializeToElement(new
    {
        scene=p.Scene,index=p.Index,x=p.X,y=p.Y,position_verified=p.PositionVerified,
        projection_guard=p.ProjectionGuard is { } g ? new { rate=g.Rate,offset_x=g.OffsetX,offset_y=g.OffsetY,height=g.Height } : null,
        source_kind=p.SourceKind,trigger_bounds=p.TriggerBounds is { } b ? new[] { b.Left,b.Top,b.Right,b.Bottom } : null,
        binding_kind=p.BindingKind,link_index=p.LinkIndex,raw_link_x=p.RawLinkX,raw_link_y=p.RawLinkY,pos_x_ratio=p.PosXRatio,pos_y_ratio=p.PosYRatio
    });
    internal static JsonElement Destination(EventPortalDestination d) => JsonSerializer.SerializeToElement(new
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
    internal static void AssertSubset(JsonElement expected, JsonElement actual)
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
}
