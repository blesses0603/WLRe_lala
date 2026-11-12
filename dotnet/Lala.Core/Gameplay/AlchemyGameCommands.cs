using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    internal static bool AlchemyMaterial(BagItemSnapshot row, ItemDataRow? data)
    {
        var item = row.OriginalRecord; var meta = data?.ReviewedDetails;
        return meta is not null && !item.Locked && item.LimitedTime == 0 && item.AvailableTime == 0 &&
            item.BeatLevel == 0 && item.EnhanceLevel == 0 && item.MagicSpar == 0 && item.DesignId == 0 && item.SaddleBeatLevel == 0 &&
            item.StarSoulLevel == 0 && item.StarSoulKind == 0 && item.Modeling == 0 && item.Plugins.All(p => p.Value == 0) &&
            (data!.Restrict & 4) == 0 && meta.Kind is not (52 or 54) && meta.Spares.Count > 0 && meta.Spares[0] != 0 &&
            meta.Special is not (142 or 162 or 163 or 197) && (meta.Special != 149 || meta.Spares[0] == 73);
    }
    private static string AlchemyCategory(ReviewedItemDetails m) => m.Special == 141 ? "book" : m.Special == 149 && m.Spares[0] == 73 ? "partner" :
        m.Kind == 20 ? "pet" : m.Special == 213 && m.Spares[0] is 4 or 5 ? m.Spares[0] == 4 ? "design" : "recipe" : "normal";
    private static GameActionPlan Alchemy(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        Require(!a.Ingredients.IsDefault && a.Ingredients.Length is >= 2 and <= 5 && a.Count is >= 1 and <= 999, "煉金需要 2～5 欄材料，次數須為 1～999。");
        Require(s.Bag.Ready && s.Bag.Reliable && s.Bag.Capacity - s.Bag.Items.Count >= 5 && s.Bag.Holds.IsEmpty && s.Bag.Reserved.Count == 0, "背包尚未可靠同步、仍有保留物品，或不足五個空位。");
        int skill = a.Operation switch { "none" => 0, "basic" => 15997, "intermediate" => 15998, "advanced" => 15999, _ => throw new ProtocolException("未知煉金模式。") };
        Require(skill == 0 || s.PlayerKnowledge.Ready && s.PlayerKnowledge.Skills.TryGetValue((uint)skill, out var learned) && learned.Level > 0, "尚未確認學會所選煉金術。");
        var categories = new List<string>();
        foreach (var ingredient in a.Ingredients)
        {
            Require(ingredient.Index > 0 && ingredient.Count is >= 1 and <= 50 && s.Bag.Items.TryGetValue(ingredient.Index, out var row) &&
                row.ItemId == ingredient.ItemId && row.OriginalRecord.Serial == ingredient.Serial && row.OriginalRecord.SerialVersion == ingredient.SerialVersion,
                "材料格位、身分或數量已改變。");
            var material = s.Bag.Items[ingredient.Index];
            Require(AlchemyMaterial(material, c.Items.GetValueOrDefault(material.ItemId)), "所選物品不是已核對且無附加屬性的可用煉金材料。");
            categories.Add(AlchemyCategory(c.Items[material.ItemId].ReviewedDetails!));
        }
        Require(categories.Count(kind => kind == "book") <= 1 && categories.Count(kind => kind != "book") >= 2 && categories.Where(kind => kind != "book").Distinct().Count() == 1,
            "煉金至少需要兩個同類型的非百科材料欄位，最多一本百科。");
        Require(!categories.Contains("book") || categories[^1] == "book" && a.Ingredients[^1].Count == 1 && categories[0] == "normal", "百科必須放在最後一欄、每次一本，且只搭配一般材料。");
        var used = a.Ingredients.GroupBy(i => i.Index).ToDictionary(g => g.Key, g => g.Sum(i => (int)i.Count));
        foreach (var (index, amount) in used) Require(BagReceiveReducer.Available(s.Bag, index) >= amount * (long)a.Count, "材料可用數量不足以執行設定次數。");
        var beforeTotals = s.Bag.Items.Values.GroupBy(i => i.ItemId).ToDictionary(g => g.Key, g => g.Sum(i => (long)i.Count));
        var consumedItems = a.Ingredients.GroupBy(i => i.ItemId).ToDictionary(g => g.Key, g => g.Sum(i => (long)i.Count));
        var deleted = new Dictionary<int, int>(); var added = new Dictionary<ushort, int>();
        ushort? output = null; int outputCount = 0; bool snapshot = false;
        var writer = new PacketWriter().U8(a.Ingredients.Length);
        foreach (var row in a.Ingredients) writer.U8(row.Index).U8(row.Count);
        int sub = categories[0] != "normal" ? 115 : a.Operation switch { "none" => 150, "basic" => 14, "intermediate" => 87, _ => 101 };
        bool Confirmed(ServiceStateSnapshot next)
        {
            if (output is not {} result || outputCount <= 0 || !next.Bag.Reliable) return false;
            var totals = next.Bag.Items.Values.GroupBy(i => i.ItemId).ToDictionary(g => g.Key, g => g.Sum(i => (long)i.Count));
            bool materialAck = used.All(pair => deleted.GetValueOrDefault(pair.Key) >= pair.Value) || snapshot && consumedItems.All(pair =>
                totals.GetValueOrDefault(pair.Key) == beforeTotals.GetValueOrDefault(pair.Key) - pair.Value + (pair.Key == result ? outputCount : 0));
            bool outputAck = added.GetValueOrDefault(result) >= outputCount || snapshot && totals.GetValueOrDefault(result) >= beforeTotals.GetValueOrDefault(result) - consumedItems.GetValueOrDefault(result) + outputCount;
            return materialAck && outputAck;
        }
        return new(new(23, sub, writer.Build()), "alchemy", "煉金", next => next, Confirmed)
        {
            ObserveReceipt = receipt =>
            {
                if (receipt.Type == "alchemy_space_error") throw new ProtocolException("伺服器拒絕煉金：空間或條件不足。");
                if (receipt.Type == "alchemy_result")
                {
                    if (receipt.ItemId is not > 0 || receipt.Count is not > 0) throw new ProtocolException("伺服器未回覆有效煉金產物。");
                    if (output is null) { output = receipt.ItemId; outputCount = receipt.Count.Value; }
                }
                else if (receipt.Type == "bag_delete" && receipt.Index is {} index && receipt.Count is {} count) deleted[index] = deleted.GetValueOrDefault(index) + count;
                else if (receipt.Type == "bag_add" && receipt.Source == 3 && receipt.ItemId is {} id && receipt.Count is {} addedCount) added[id] = added.GetValueOrDefault(id) + addedCount;
                else if (receipt.Type == "bag_snapshot") snapshot = true;
            }
        };
    }
}
