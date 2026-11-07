using Lala.Core.Protocol;

namespace Lala.Core.Automation;

public abstract record TimeCubeEvent;
public sealed record CubeInfo(byte Kind, byte Count, ushort CheckMinutes, ushort KeepMinutes) : TimeCubeEvent;
public sealed record CubeItem(ushort ItemId) : TimeCubeEvent;
public sealed record CubeLegacyResult : TimeCubeEvent;

/// <summary>Exact S122 layouts. S122-2 remains intentionally opaque and is not a receipt.</summary>
public static class TimeCubeProtocol
{
    public static TimeCubeEvent? Decode(Packet packet)
    {
        if (packet.Main != 122 || packet.Sub is not (1 or 2 or 3)) return null;
        var r = new PacketReader(packet.Payload.Span);
        if (packet.Sub == 2) return new CubeLegacyResult();
        if (packet.Sub == 3)
        {
            ushort item = r.U16(); r.End();
            if (item == 0) throw new ProtocolException("時間魔方福袋 ID 無效");
            return new CubeItem(item);
        }
        var info = new CubeInfo(r.U8(), r.U8(), r.U16(), r.U16()); r.End();
        if (info.Kind > 1 || info.Count > 3) throw new ProtocolException("時間魔方狀態格式無效");
        return info;
    }
}
public sealed record CubePending(byte Count, long BagRevision, bool CountUpdated, double Due);
public sealed record TimeCubeState
{
    public bool Enabled { get; init; } = true;
    public bool Ready { get; init; }
    public byte? Count { get; init; }
    public double? Deadline { get; init; }
    public ushort? CheckMinutes { get; init; }
    public ushort? ItemId { get; init; }
    public uint? RoleId { get; init; }
    public CubePending? Pending { get; init; }
    public bool Uncertain { get; init; }
    public long Revision { get; init; }
    public string Status { get; init; } = "等待伺服器同步時間魔方";
}

/// <summary>Offline port of services/time_cube.py; countdowns never manufacture eligibility.</summary>
public static class TimeCubeService
{
    public static TimeCubeState RoleListAvailable() => new();
    public static TimeCubeState WorldPlayer(TimeCubeState state, uint role) =>
        (state.RoleId is not null && state.RoleId != role ? new TimeCubeState() : state) with { RoleId = role };
    public static TimeCubeState Apply(TimeCubeState state, TimeCubeEvent value, uint? role, double now)
    {
        AutomationChecks.Clock(now);
        return value switch
        {
            CubeItem item when item.ItemId != 0 => state with { ItemId = item.ItemId },
            CubeInfo info when info.Kind <= 1 && info.Count <= 3 => state with
            {
                Ready = true, Count = info.Count, Revision = checked(state.Revision + 1), RoleId = role,
                Deadline = info.Kind == 0 ? now + Math.Max(0, info.CheckMinutes - info.KeepMinutes) * 60 : state.Deadline,
                CheckMinutes = info.Kind == 0 ? info.CheckMinutes : state.CheckMinutes,
                Pending = state.Pending is { } p && info.Count < p.Count ? p with { CountUpdated = true } : state.Pending,
                Status = state.Pending is null && !state.Uncertain ? "伺服器已同步魔方狀態" : state.Status
            },
            CubeLegacyResult => state,
            _ => throw new ProtocolException("時間魔方狀態格式無效")
        };
    }
    public static string Problem(TimeCubeState state, AutomationContext context)
    {
        if (!context.WorldReady || !context.InitialDataComplete || context.RoleId is null or 0) return "等待角色與世界同步";
        if (!state.Ready || state.RoleId != context.RoleId) return "等待伺服器同步魔方次數";
        if (state.Uncertain) return "魔方開啟結果不明，請重新登入同步";
        if (state.Pending is not null) return "等待魔方次數與背包更新，不重複送出";
        if (state.Count is null or 0) return "分析中，等待伺服器確認可開啟次數";
        var pause = context.CoordinationProblem(true); if (pause.Length != 0) return pause;
        if (context.BagOperationsBusy(true)) return "等待其他背包操作結束";
        if (context.InstanceRewardActive) return "等待副本領獎確認";
        return context.Bag.Problem(state.Count.Value);
    }
    public static TimeCubeState SetAutomatic(TimeCubeState state, bool enabled, bool resourceHeld)
    {
        AutomationChecks.Resource(resourceHeld, !enabled);
        return state with { Enabled = enabled, Status = enabled ? "已啟用自動開啟" : "已關閉自動開啟" };
    }
    public static AutomationPlan<TimeCubeState> RequestOpen(TimeCubeState state, AutomationContext context, double now)
    {
        AutomationChecks.Clock(now); AutomationChecks.Resource(context.ResourceHeld);
        if (!context.WorldAcknowledged) throw new ProtocolException("等待世界初始化確認");
        var issue = Problem(state, context); if (issue.Length != 0) throw new ProtocolException(issue);
        return new(state with
        {
            Pending = new(state.Count!.Value, context.Bag.Revision, false, now + 15),
            Status = "已送出開啟要求，等待伺服器次數及背包更新"
        }, new Packet(122, 2));
    }
    public static AutomationPlan<TimeCubeState> Tick(TimeCubeState state, AutomationContext context, double now)
    {
        AutomationChecks.Clock(now);
        if (state.Pending is { } p)
        {
            if (p.CountUpdated && context.Bag.Reliable && context.Bag.Revision > p.BagRevision)
                state = state with { Pending = null, Status = "已收到次數及背包更新；實際獎勵以背包為準" };
            else if (now >= p.Due)
                state = state with { Pending = null, Uncertain = true, Status = "魔方開啟結果不明，停止重送；請重新登入同步" };
            return new(state);
        }
        if (!context.WorldAcknowledged || !state.Enabled || !context.AutomationEnabled || context.ResourceHeld) return new(state);
        var issue = Problem(state, context);
        return issue.Length != 0 ? new(state with { Status = issue }) : RequestOpen(state, context, now);
    }
    // Stop intent must not discard outstanding receipts/holds. Disconnect marks an outstanding result uncertain.
    public static TimeCubeState Disconnect(TimeCubeState state) => state with
    {
        Enabled = false, Ready = false, Uncertain = state.Pending is not null || state.Uncertain,
        Pending = null, Status = "連線結束，魔方自動開啟已停止"
    };
}
