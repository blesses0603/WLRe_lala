using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static ushort CraftTool(ServiceStateSnapshot s, ushort itemId)
    {
        var room = s.Crafting.Furniture;
        Require(room.Ready && room.Owner == s.Player!.RoleId && room.CurrentOwner == s.Player.RoleId, "請先進入自家小屋並等待設備同步。");
        var tools = room.ItemOrder.Where(room.Items.ContainsKey).Select(i => room.Items[i]).Where(i => i.ItemId == itemId && i.Status == 0).ToArray();
        Require(tools.Length > 0, "小屋沒有可用的製作設備。");
        return tools[^1].Index;
    }

    private static GameActionPlan CraftFull(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c, double now)
    {
        var craft = s.Crafting.Crafting;
        Require(craft.Ready && !craft.Uncertain && craft.Pending is null, "製作排程未同步，或前次操作尚未確認。");
        if (a.Operation == "add")
        {
            Require(a.Target is > 0 and <= ushort.MaxValue, "請選擇目前官方配方。");
            var preflight = CraftingMaterialPreflight.Evaluate(CraftingPreflightContext.FromRuntime(c.Recipes), (ushort)a.Target, a.Count,
                s.Player!.RoleId, s.Crafting, s.Bag, s.Storage.Storage);
            Require(preflight.Success, $"製作條件未滿足：{preflight.Blocker}；缺少材料 {preflight.MissingItemId} × {preflight.MissingCount}。");
            var recipe = preflight.Recipe!.Recipe;
            _ = CraftTool(s, recipe.ToolId);
            var bag = preflight.Allocations.Where(r => r.Source == CraftingMaterialSource.Bag).ToArray();
            var cupboard = preflight.Allocations.Where(r => r.Source == CraftingMaterialSource.Materials).ToArray();
            var w = new PacketWriter().U16(preflight.ToolIndex!.Value);
            if (recipe.RecipeId is {} id) w.U16(id);
            w.U16(recipe.ItemId).U8(a.Count).U8(bag.Length);
            foreach (var row in bag) w.U8(row.Index).U8(row.Count);
            w.U16(cupboard.Length);
            foreach (var row in cupboard) w.U16(row.Index).U16(row.Count);
            w.U8(0);
            bool queueAck = false, completeAck = false; long productReceived = 0;
            bool Consumed(ServiceStateSnapshot next) => preflight.Allocations.All(allocation =>
            {
                var remaining = allocation.Before - allocation.Count;
                if (allocation.Source == CraftingMaterialSource.Bag)
                {
                    var row = next.Bag.Items.GetValueOrDefault(checked((byte)allocation.Index));
                    return next.Bag.Reliable && (row is null ? remaining == 0 : row.ItemId == allocation.ItemId && row.OriginalRecord.Serial == allocation.Serial && row.Count == remaining);
                }
                var stored = next.Storage.Storage.Materials.Items.GetValueOrDefault(allocation.Index);
                return next.Storage.Storage.Materials.Reliable && (stored is null ? remaining == 0 : stored.ItemId == allocation.ItemId && stored.Count == remaining);
            });
            return new(new(64, 1, w.Build()), "inventory", "新增製作排程", next => next,
                next => (queueAck || recipe.Seconds == 0 && completeAck && productReceived >= (long)recipe.Output * a.Count) && Consumed(next))
            {
                ObserveReceipt = receipt =>
                {
                    if (receipt.Type == "craft_added" && receipt.ItemId == recipe.ItemId && receipt.Count == a.Count) queueAck = true;
                    if (receipt.Type == "craft_completed") completeAck = true;
                    if (receipt.Type == "bag_add" && receipt.ItemId == recipe.ItemId) productReceived += receipt.Count ?? 0;
                    if (receipt.Type == "craft_failed") throw new ProtocolException("伺服器拒絕製作，請確認設備或空間。");
                }
            };
        }
        if (a.Operation == "start")
        {
            Require(!craft.Running && craft.Queue.TryGetValue(1, out var first), "製作中，或首項排程尚未同步。");
            var row = craft.Queue[1];
            Require(c.Recipes.Products.TryGetValue(row.ItemId, out var selected), "此排程的配方不明，請重新同步。");
            ushort tool = CraftTool(s, c.Recipes.Products[row.ItemId].Recipe.ToolId);
            var w = new PacketWriter().U16(tool).U8(row.Index).U8(craft.HumanIndex).U32(craft.HumanId);
            return Simple(new(64, 2, w.Build()), "craft", "開始製作", next => next.Crafting.Crafting.Running && next.Crafting.Crafting.Active == row.Index);
        }
        if (a.Operation == "complete")
        {
            Require(craft.Running && craft.Queue.TryGetValue(craft.Active, out var current), "目前沒有可完成的製作。");
            var row = craft.Queue[craft.Active];
            // Base time is the slowest supported duration. Waiting for it is conservative
            // and avoids inventing speed bonuses from missing furniture/partner metadata.
            Require(CraftingReducer.Elapsed(craft, row, now) >= Math.Max(1, row.BaseTime), "製作時間尚未到達。");
            Require(s.Bag.Ready && s.Bag.Reliable, "請等待背包同步。");
            bool done = false; long received = 0;
            Require(c.Recipes.Products.TryGetValue(row.ItemId, out var recipe), "產物數量未知，不能接續製作。");
            long required = (long)c.Recipes.Products[row.ItemId].Recipe.Output * row.Count;
            return new(new(64, 10), "craft", "領取製作產物", next => next, next => done && received >= required)
            {
                ObserveReceipt = receipt =>
                {
                    if (receipt.Type == "craft_completed" && receipt.Index == row.Index) done = true;
                    if (receipt.Type == "bag_add" && receipt.ItemId == row.ItemId) received += receipt.Count ?? 0;
                    if (receipt.Type == "craft_failed") throw new ProtocolException("製作產物尚未收取，請確認背包或住宅空間。");
                }
            };
        }
        Require(!craft.Running || a.Operation == "pause", "請先暫停製作再調整排程。");
        return Craft(a, s, c);
    }
}
