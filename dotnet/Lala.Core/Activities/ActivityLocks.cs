using Lala.Core.Protocol;
using System.Collections.Frozen;

namespace Lala.Core.Activities;

public enum ActivityKind { Fishing, Gathering, Dancing, ToiletCrafting, Training, CompanionTraining }
public sealed record ActivityEvent
{
    public ActivityKind Activity { get; }
    public bool Active { get; }
    public IReadOnlyList<uint>? Roles { get; }
    public bool Initial { get; }
    public ActivityEvent(ActivityKind activity, bool active, IReadOnlyList<uint>? roles = null, bool initial = false)
    {
        Activity = activity; Active = active; Initial = initial;
        Roles = roles is null ? null : Array.AsReadOnly(roles.ToArray());
    }
}

/// <summary>Offline decoding of observed movement locks from wlre/core/activity.py.</summary>
public static class ActivityDecoder
{
    public static ActivityEvent? Decode(Packet packet)
    {
        var r = new PacketReader(packet.Payload.Span);
        ActivityEvent? result = null;
        switch (packet.Main, packet.Sub)
        {
            case (23, 122): case (23, 123):
                result = new(ActivityKind.Fishing, packet.Sub == 123, Array.AsReadOnly(new[] { r.U32() }));
                r.U8(); break;
            case (23, 138):
                result = new(ActivityKind.Gathering, true, ReadRoles(r, (uint)(r.Remaining / 4))); break;
            case (23, 137):
                result = new(ActivityKind.Gathering, false, Array.AsReadOnly(new[] { r.U32() })); break;
            case (7, 4):
                var mode = r.U8();
                if (mode == 0) result = new(ActivityKind.Dancing, true, ReadRoles(r, r.U32()), true);
                else if (mode is 1 or 3) result = new(ActivityKind.Dancing, mode == 1, Array.AsReadOnly(new[] { r.U32() }));
                else return null;
                break;
            case (62, 67): result = new(ActivityKind.ToiletCrafting, true); break;
            case (62, 84): result = new(r.U8() == 1 ? ActivityKind.Training : ActivityKind.CompanionTraining, true); break;
        }
        if (result is not null) r.End();
        return result;
    }

    private static IReadOnlyList<uint> ReadRoles(PacketReader r, uint count)
    {
        // Validate count before allocation, including hostile uint32 counts.
        if (count > r.Remaining / 4) throw new ProtocolException("activity role count exceeds payload");
        var roles = new uint[(int)count];
        for (var i = 0; i < roles.Length; i++) roles[i] = r.U32();
        return Array.AsReadOnly(roles);
    }
}

/// <summary>Single-owner session state. Does not send movement or infer permission to move.</summary>
public sealed class ActivityLocks
{
    private readonly HashSet<ActivityKind> active = [];
    public IReadOnlySet<ActivityKind> Snapshot() => active.ToFrozenSet();
    public void Apply(uint? playerRoleId, ActivityEvent activity)
    {
        if (activity.Roles is not null)
        {
            if (activity.Initial) active.Remove(activity.Activity);
            if (playerRoleId is null || !activity.Roles.Contains(playerRoleId.Value)) return;
        }
        if (activity.Active) active.Add(activity.Activity);
        else active.Remove(activity.Activity);
    }
    public void GeometryChanged(uint? playerRoleId, uint? clearActivityRole)
    {
        if (clearActivityRole != playerRoleId) return;
        active.ExceptWith([ActivityKind.ToiletCrafting, ActivityKind.Training, ActivityKind.CompanionTraining]);
    }
    public void WorldPlayerChanged() => active.Clear();
}
