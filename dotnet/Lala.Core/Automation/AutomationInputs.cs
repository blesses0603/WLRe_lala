using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Automation;

/// <summary>Caller-owned, immutable observations. No service here fetches resources or transmits packets.</summary>
public sealed record ServiceActivity(bool Pending = false, bool Uncertain = false, bool Enabled = false,
    bool AutoContinue = false, bool Checking = false)
{
    public bool Active => Pending || Uncertain;
}
public sealed record BagSlot(int Index, int ItemId, int Count);
public sealed record RewardBag
{
    public bool Ready { get; init; }
    public bool Reliable { get; init; }
    public int Capacity { get; init; }
    public long Revision { get; init; }
    public ImmutableArray<BagSlot> Items { get; init; } = [];
    public bool HasHolds { get; init; }
    public bool HasReservedItems { get; init; }
    public bool SupplyPending { get; init; }

    public string Problem(long requiredSlots)
    {
        if (!Ready) return "尚未收到 S23-5 背包完整快照";
        if (!Reliable) return "S23 背包資料未通過一致性驗證，請重新登入同步";
        if (Capacity is < 1 or > 255 || Items.IsDefault) return "背包容量或格位資料未確認";
        var occupied = new HashSet<int>();
        foreach (var item in Items)
            if (item.Index < 1 || item.Index > Capacity || !occupied.Add(item.Index)) return "背包格位索引超出容量或重複";
        int empty = Capacity - occupied.Count;
        if (empty < requiredSlots) return $"背包剩餘 {empty} 格，保守領獎需要至少 {requiredSlots} 格";
        if (HasHolds) return "背包仍有其他功能保留的物品或格位";
        if (HasReservedItems) return "背包仍有未完成的物品數量保留";
        return SupplyPending ? "補給正在使用背包，待伺服器確認" : "";
    }

    public ImmutableDictionary<int, long>? ItemTotals()
    {
        if (!Ready || !Reliable || Items.IsDefault) return null;
        var totals = ImmutableDictionary.CreateBuilder<int, long>();
        var occupied = new HashSet<int>();
        foreach (var item in Items)
        {
            if (item.ItemId is < 1 or > 65535 || item.Count is < 1 or > 255 ||
                item.Index < 1 || item.Index > Capacity || !occupied.Add(item.Index)) return null;
            totals[item.ItemId] = totals.GetValueOrDefault(item.ItemId) + item.Count;
        }
        return totals.ToImmutable();
    }
}

public sealed record AutomationContext
{
    public bool WorldReady { get; init; }
    public bool InitialDataComplete { get; init; }
    public uint? RoleId { get; init; }
    public bool WorldAcknowledged { get; init; }
    public bool AutomationEnabled { get; init; }
    // Resource admission is separate from world readiness. Unknown/unverified is held by default.
    public bool ResourceHeld { get; init; } = true;
    public bool BattleActive { get; init; }
    public bool EventBlocked { get; init; }
    public bool PostBattleIncomplete { get; init; }
    public bool HasActivities { get; init; }
    public bool SupplyActive { get; init; }
    public bool InstanceRewardActive { get; init; }
    public ServiceActivity StarArk { get; init; } = new();
    public ServiceActivity Guild { get; init; } = new();
    public ServiceActivity TimeCube { get; init; } = new();
    public ServiceActivity DailyTasks { get; init; } = new();
    public ServiceActivity RoomStorage { get; init; } = new();
    public ServiceActivity Maintenance { get; init; } = new();
    public ServiceActivity Expedition { get; init; } = new();
    public ServiceActivity Alchemy { get; init; } = new();
    public ServiceActivity Crafting { get; init; } = new();
    public RewardBag Bag { get; init; } = new();

    internal string CoordinationProblem(bool cube)
    {
        if (StarArk.Active) return "等待方舟操作確認";
        if (Guild.Active) return "等待組織簽到／捐獻確認";
        if (cube && DailyTasks.Active) return "等待每日任務領獎確認";
        if (!cube && TimeCube.Active) return "等待魔方開啟確認";
        if (BattleActive || EventBlocked) return "等待戰鬥／伺服器事件結束";
        if (PostBattleIncomplete) return "等待戰後事件完成";
        if (HasActivities) return "請先結束目前活動";
        return SupplyActive || Bag.SupplyPending ? "請先等待補給結果確認" : "";
    }
    internal bool BagOperationsBusy(bool cube) => new[] { Maintenance, RoomStorage, Crafting, Alchemy, Expedition }
        .Any(s => s.Active || s.Enabled || s.AutoContinue || (!cube && s.Checking)) ||
        !cube && (TimeCube.Active || TimeCube.AutoContinue || TimeCube.Checking);
}

/// <summary>A pure proposed transition and candidate packet, never permission or a transport receipt.</summary>
public sealed record AutomationPlan<T>(T State, Packet? Candidate = null);
internal static class AutomationChecks
{
    internal static void Clock(double now)
    {
        if (!double.IsFinite(now)) throw new ProtocolException("monotonic time must be finite");
    }
    internal static void Resource(bool held, bool disabling = false)
    {
        if (held && !disabling) throw new ProtocolException("官方資源尚未確認，已暫停操作");
    }
}
