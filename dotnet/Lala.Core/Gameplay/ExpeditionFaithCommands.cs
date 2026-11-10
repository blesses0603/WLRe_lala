using Lala.Core.Catalogs;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static GameActionPlan ExpeditionFaith(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        var e = s.Expedition;
        Require(e.Ready && e.OutpostReady && !e.Uncertain && e.Pending is null && a.Index is >= 1 and <= 255 && e.Roles.ContainsKey((byte)a.Index) && a.Target <= 65535,
            "遠征夥伴或恢復物品資料尚未確認。");
        var role = e.Roles[(byte)a.Index]; long? gain = ExpeditionTaskInspection.FaithGain(c.Items.GetValueOrDefault((ushort)a.Target));
        Require(role.State == 0 && a.Count > role.Faith && a.Count <= 100 && gain > 0 && s.Bag.Ready && s.Bag.Reliable, "夥伴忙碌、目標好友度無效，或恢復物品效果未知。");
        int need = checked((int)((a.Count - role.Faith + gain!.Value - 1) / gain.Value));
        var allocations = new List<(byte Index, int Count, int Before, uint Serial)>();
        foreach (var row in s.Bag.Items.Values.OrderBy(i => i.Index))
        {
            if (row.ItemId != a.Target || row.OriginalRecord.Locked || row.OriginalRecord.AvailableTime != 0 || row.OriginalRecord.LimitedTime != 0) continue;
            int use = (int)System.Numerics.BigInteger.Min(need, BagReceiveReducer.Available(s.Bag, row.Index));
            if (use > 0) { allocations.Add((row.Index, use, row.Count, row.OriginalRecord.Serial)); need -= use; }
            if (need == 0) break;
        }
        Require(need == 0 && allocations.Count <= 255, "好友度恢復物品數量不足。");
        var w = new PacketWriter().U8(a.Index).U8(allocations.Count);
        foreach (var row in allocations) w.U8(1).U16(row.Index).U16(a.Target).U16(row.Count);
        return Simple(new(31, 27, w.Build()), "inventory", "恢復遠征夥伴好友度", next =>
            next.Expedition.Roles.GetValueOrDefault((byte)a.Index) is {} current && current.NpcId == role.NpcId && current.Faith >= a.Count && next.Bag.Reliable &&
            allocations.All(row => next.Bag.Items.TryGetValue(row.Index, out var item) ? item.ItemId == a.Target && item.OriginalRecord.Serial == row.Serial && item.Count == row.Before - row.Count : row.Before == row.Count));
    }
}
