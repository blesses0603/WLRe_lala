using Lala.Core.Activities;
using Lala.Core.Protocol;
using Xunit;
namespace Lala.Core.Tests.Activities;

public sealed class ActivityLocksTests
{
    public static IEnumerable<object[]> PythonCases() => System.Text.Json.JsonDocument.Parse(PythonActivityVectors.Json).RootElement.EnumerateArray().Select(x => new object[] { x.Clone() });
    [Theory, MemberData(nameof(PythonCases))]
    public void PythonParity(System.Text.Json.JsonElement sample)
    {
        var state = new ActivityLocks();
        foreach (var initial in sample.GetProperty("initial").EnumerateArray())
            state.Apply(null, new(Enum.Parse<ActivityKind>(initial.GetString()!), true));
        var pid = sample.GetProperty("pid");
        var activity = ActivityDecoder.Decode(new(sample.GetProperty("main").GetInt32(), sample.GetProperty("sub").GetInt32(), Convert.FromHexString(sample.GetProperty("hex").GetString()!)));
        state.Apply(pid.ValueKind == System.Text.Json.JsonValueKind.Null ? null : pid.GetUInt32(), activity!);
        Assert.Equal(sample.GetProperty("expected").EnumerateArray().Select(x=>x.GetString()).Order(), state.Snapshot().Select(x=>x.ToString()).Order());
    }
    public static IEnumerable<object[]> Packets()
    {
        yield return [23, 122, "0700000000", ActivityKind.Fishing, false, new uint[] {7}, false];
        yield return [23, 123, "07000000FF", ActivityKind.Fishing, true, new uint[] {7}, false];
        yield return [23, 138, "0700000008000000", ActivityKind.Gathering, true, new uint[] {7,8}, false];
        yield return [23, 138, "", ActivityKind.Gathering, true, Array.Empty<uint>(), false];
        yield return [23, 137, "07000000", ActivityKind.Gathering, false, new uint[] {7}, false];
        yield return [7, 4, "00020000000700000008000000", ActivityKind.Dancing, true, new uint[] {7,8}, true];
        yield return [7, 4, "0107000000", ActivityKind.Dancing, true, new uint[] {7}, false];
        yield return [7, 4, "0307000000", ActivityKind.Dancing, false, new uint[] {7}, false];
        yield return [62, 67, "", ActivityKind.ToiletCrafting, true, null!, false];
        yield return [62, 84, "01", ActivityKind.Training, true, null!, false];
        yield return [62, 84, "00", ActivityKind.CompanionTraining, true, null!, false];
        yield return [62, 84, "FF", ActivityKind.CompanionTraining, true, null!, false];
    }
    [Theory, MemberData(nameof(Packets))]
    public void DecodeKnown(int main, int sub, string hex, ActivityKind kind, bool active, uint[]? roles, bool initial)
    {
        var e = Assert.IsType<ActivityEvent>(ActivityDecoder.Decode(new(main, sub, Convert.FromHexString(hex))));
        Assert.Equal(kind, e.Activity); Assert.Equal(active, e.Active); Assert.Equal(initial, e.Initial);
        Assert.Equal(roles, e.Roles);
    }
    [Theory, MemberData(nameof(Packets))]
    public void RejectTruncationAndTrailing(int main, int sub, string hex, ActivityKind kind, bool active, uint[]? roles, bool initial)
    {
        DecodeKnown(main, sub, hex, kind, active, roles, initial);
        var bytes = Convert.FromHexString(hex);
        Assert.Throws<ProtocolException>(() => ActivityDecoder.Decode(new(main, sub, bytes.Concat(new byte[]{0}).ToArray())));
        // Gathering lists accept any complete count, so truncated four-byte boundaries are valid.
        if (main == 23 && sub == 138) return;
        for (var n = 0; n < bytes.Length; n++)
            Assert.Throws<ProtocolException>(() => ActivityDecoder.Decode(new(main, sub, bytes.AsSpan(0,n))));
    }
    [Fact] public void CallerCannotMutateRoleEvidence()
    {
        var roles = new uint[] {7}; var activity = new ActivityEvent(ActivityKind.Fishing, true, roles);
        roles[0] = 8;
        var state = new ActivityLocks(); state.Apply(7, activity);
        Assert.Contains(ActivityKind.Fishing, state.Snapshot());
        Assert.Throws<NotSupportedException>(()=>((IList<uint>)activity.Roles!)[0] = 9);
    }
    [Fact] public void UnknownAndHostile()
    {
        Assert.Null(ActivityDecoder.Decode(new(255,255,new byte[]{1})));
        Assert.Null(ActivityDecoder.Decode(new(7,4,new byte[]{2,99})));
        Assert.Throws<ProtocolException>(()=>ActivityDecoder.Decode(new(7,4,Convert.FromHexString("00FFFFFFFF"))));
    }
    [Fact] public void NullableGeometryClearsAllSelfActivitiesOnly()
    {
        var state = new ActivityLocks();
        foreach (var kind in Enum.GetValues<ActivityKind>()) state.Apply(null, new(kind, true));
        state.GeometryChanged(null, null);
        Assert.Equal(new[] { ActivityKind.Fishing, ActivityKind.Gathering, ActivityKind.Dancing }, state.Snapshot().Order());
    }
    [Fact] public void OwnershipInitialResetAndLifecycle()
    {
        var state = new ActivityLocks();
        state.Apply(7,new(ActivityKind.Dancing,true,new uint[]{8})); Assert.Empty(state.Snapshot());
        state.Apply(7,new(ActivityKind.Dancing,true,new uint[]{7}));
        state.Apply(7,new(ActivityKind.Dancing,true,new uint[]{8},true)); Assert.Empty(state.Snapshot());
        state.Apply(null,new(ActivityKind.Fishing,true,new uint[]{7})); Assert.Empty(state.Snapshot());
        state.Apply(7,new(ActivityKind.Fishing,true,new uint[]{7}));
        state.Apply(7,new(ActivityKind.Training,true));
        state.GeometryChanged(7,8); Assert.Equal(2,state.Snapshot().Count);
        state.GeometryChanged(7,7); Assert.Equal(new[]{ActivityKind.Fishing},state.Snapshot());
        state.Apply(7,new(ActivityKind.Fishing,false,new uint[]{7})); Assert.Empty(state.Snapshot());
        state.Apply(7,new(ActivityKind.Training,true)); var copy = state.Snapshot();
        state.WorldPlayerChanged(); Assert.Empty(state.Snapshot()); Assert.Single(copy);
    }
}
