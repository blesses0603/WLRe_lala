using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Resources;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

public sealed record GameShopMenu(ushort Scene, ushort Interaction, string EffectKey, string Title,
    ImmutableArray<SceneShopProduct> Products);

public static class GameInventoryOperations
{
    public static GameShopMenu? Shop(ServiceStateSnapshot state, OfflineRuntimeCandidate catalog)
    {
        var d = state.Local.Session.NpcDialogue;
        if (!d.Active || d.Phase != "choice_unavailable" || d.EffectType != 6 || d.Scene != state.Player?.Scene ||
            d.Scene is not {} scene || d.OptionIndex is not {} index || d.EffectPacket is null ||
            state.Local.Session.EventFlow.AwaitingResponse || catalog.EveIndexes.Scenes.IsDefault) return null;
        var rows = catalog.EveIndexes.Scenes.Where(s => s.SceneId == scene).SelectMany(s => s.Interactions).Where(r => r.Index == index).Take(2).ToArray();
        if (rows.Length != 1 || SceneShopPreviewRequest.Build(rows[0], catalog.Items) is not {} products) return null;
        return new(scene, index, d.EffectPacket.Value.ToString(System.Globalization.CultureInfo.InvariantCulture),
            rows[0].FormKind == 2 ? "武器商店" : "道具商店", products);
    }

    // Ordinary consumables only. Equipment and items opening a dedicated official UI
    // must never fall through to C23-15 simply because their packet shape looks similar.
    public static bool IsOrdinaryConsumable(ItemDataRow data) => data.OpenUsed == 0 &&
        data.ReviewedDetails is { FitType: 7 or 8 or 10, Kind: 23 or 25 or 32, Gender: 0 or 3 or 8 } m &&
        m.Special is 0 or 4 or 25 or 54 or 113 or 114 or 118 or 123 &&
        // Food is classified before item-ID-specific branches in official Bag.lua.
        // A kind-25 item with special=0 may instead be a gift/key/special UI object.
        (m.Special != 0 || m.Kind is 23 or 32);

    public static string UseDescription(ItemDataRow? data) => data is null ? "等待同版道具資料" :
        IsOrdinaryConsumable(data) ? "可選擇角色或夥伴使用；送出前會重新檢查限制。" :
        data.ReviewedDetails?.FitType is >= 1 and <= 6 or 11 ? "裝備穿脫暫不開放。" : "此道具需專屬功能，不能以一般使用指令代替。";
}

internal static partial class ManualGameCommands
{
    private static GameActionPlan Shop(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        Require(s.Local.Battle.Active != true && !s.Local.Session.PostBattle.Pending && s.Activities.Count == 0,
            "請先結束戰鬥或目前活動。");
        var shop = GameInventoryOperations.Shop(s, c);
        Require(shop is not null && a.Scene == shop.Scene && a.X == shop.Interaction && a.Key == shop.EffectKey,
            "商店已關閉或選單已改變，請重新選擇。");
        if (a.Operation == "sell") return InventoryItem(a, s, c);
        Require(a.Operation == "buy" && a.Count is > 0 and <= 9999, "購買數量請輸入 1～9999。");
        var product = shop!.Products.FirstOrDefault(p => p.OfferIndex == a.Index && p.ItemId == a.Target);
        Require(product is not null && c.Items.TryGetValue(product.ItemId, out var metadata) && metadata.ReviewedDetails is not null,
            "商品或同版物品資料已改變。");
        var item = c.Items[product!.ItemId];
        Require(a.ExpectedPrice == item.Price, "商品價格已變更，請重新確認。");
        Require(s.Bag.Ready && s.Bag.Reliable && s.Bag.Capacity is > 0 && s.Bag.Holds.IsEmpty && s.Bag.Reserved.Count == 0,
            "請等待可靠背包資料，並結束物品保留。");
        // Shop.GetMaxPurchaseCount uses empty slots, rather than assuming existing stacks accept new goods.
        int slots = item.ReviewedDetails!.Stackable ? (a.Count + 199) / 200 : a.Count;
        Require(s.Bag.Capacity - s.Bag.Items.Count >= slots, "背包空間不足。");
        ulong total = (ulong)item.Price * (uint)a.Count;
        var gold = s.Local.Session.Gold;
        Require(total <= uint.MaxValue && gold is { Ready: true, Reliable: true, Amount: not null } && gold.Amount >= total,
            "金幣不足或餘額尚未可靠同步。");
        long before = ItemTotal(s.Bag, product.ItemId); bool receipt = false; long added = 0;
        return new(new(27, 1, new PacketWriter().U8(product.OfferIndex).U32(a.Count).Build()), "shop", "購買商品",
            next => next, next => receipt && added == a.Count && next.Bag.Ready && next.Bag.Reliable &&
                ItemTotal(next.Bag, product.ItemId) == before + a.Count && next.Local.Session.Gold is { Ready: true, Reliable: true, Amount: {} balance } &&
                balance == gold.Amount!.Value - total)
        {
            RefusalUnchanged = next => InventoryUnchanged(s, next),
            ObserveReceipt = e =>
            {
                if (e.Type == "shop_purchase_result")
                {
                    if (e.Code is >= 1 and <= 4) throw new GameActionRefusedException(e.Code switch
                    { 1 => "金幣不足。", 2 => "背包空間不足。", 3 => "購買數量超出限制。", _ => "伺服器拒絕購買。" });
                    Require(e.Code == 0, "未知購買結果，請重新同步。");
                    receipt = true;
                }
                if (e.Type == "bag_add" && e.ItemId == product.ItemId && e.Count is {} count)
                { added += count; Require(added <= a.Count, "商品入包數量不符，請重新同步。"); }
            }
        };
    }

    private static long ItemTotal(BagReceiveSnapshot bag, ushort item) => bag.Items.Values.Where(i => i.ItemId == item).Sum(i => (long)i.Count);
    private static bool InventoryUnchanged(ServiceStateSnapshot before, ServiceStateSnapshot next) => next.Bag.Ready && next.Bag.Reliable &&
        next.Bag.Items.Count == before.Bag.Items.Count && before.Bag.Items.All(p => next.Bag.Items.GetValueOrDefault(p.Key) == p.Value) &&
        next.Local.Session.Gold.Ready == before.Local.Session.Gold.Ready && next.Local.Session.Gold.Reliable == before.Local.Session.Gold.Reliable &&
        next.Local.Session.Gold.Amount == before.Local.Session.Gold.Amount;

    private static GameActionPlan InventoryItem(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        Require(a.Operation is "use" or "discard" or "sell" && a.Index is > 0 and <= 255 && a.Count is > 0 and <= 255,
            "道具操作、格位或數量無效。");
        Require(s.Bag.Ready && s.Bag.Reliable && s.Bag.Items.TryGetValue((byte)a.Index, out var present) && present.ItemId == a.Target &&
            present.Count >= a.Count && MaintenanceKnowledge.SlotAvailable(s.Bag, (byte)a.Index) && s.Bag.Holds.IsEmpty &&
            s.Bag.AlchemySlots?.Contains((ushort)a.Index) != true && s.Bag.ExpeditionSlots?.Contains((ushort)a.Index) != true,
            "道具已改變、鎖定或仍被其他功能保留。");
        var source = s.Bag.Items[(byte)a.Index];
        Require(a.ItemSerial == source.OriginalRecord.Serial && a.ItemSerialVersion == source.OriginalRecord.SerialVersion,
            "道具身分已更新，請重新選擇。");
        Require(c.Items.TryGetValue(source.ItemId, out var data) && data.ReviewedDetails is not null, "缺少同版道具資料。");
        Packet packet; string label; uint expectedGold = 0; bool receipt = false;
        if (a.Operation == "use")
        {
            Require(GameInventoryOperations.IsOrdinaryConsumable(data!), GameInventoryOperations.UseDescription(data));
            Require(a.Count == 1 && a.Y is >= 0 and <= 255, "一般道具請逐次使用，並選擇目前角色或夥伴。");
            var m = data!.ReviewedDetails!; long? level; long? hp;
            if (a.Y == 0)
            {
                Require(a.RecipientId == s.Player!.RoleId && m.Gender != 8, "此道具或對象不適用角色。");
                Require(s.PlayerKnowledge.Ready, "請等待角色屬性同步。");
                level = s.PlayerKnowledge.Stats.GetValueOrDefault("level");
                hp = s.PlayerKnowledge.Stats.TryGetValue("hp", out var currentHp) ? currentHp : null;
                Require(!m.Attributes.Any(v => v.Kind == 64), "友好度物品只能對夥伴使用。");
            }
            else
            {
                Require(s.Companions.Ready && s.Companions.Companions.TryGetValue((ushort)a.Y, out var target) &&
                    a.RecipientId == target.Data.NpcId && m.Gender != 3 && (data.Restrict & 64) == 0, "夥伴身分已變更或道具不適用。");
                var companion = s.Companions.Companions[(ushort)a.Y];
                level = companion.StatOverrides.GetValueOrDefault("level", companion.Data.Level);
                hp = companion.StatOverrides.TryGetValue("hp", out var currentHp) ? currentHp : companion.Data.Hp;
                if (m.Attributes.Any(v => v.Kind == 64))
                    Require(companion.StatOverrides.GetValueOrDefault("faith", companion.Data.Faith) < 100, "夥伴友好度已滿。");
            }
            Require(level is > 0 && (m.Special is 113 or 114 ? data.NeedLevel == 0 || level <= data.NeedLevel : level >= data.NeedLevel), "使用等級條件不符或尚未同步。");
            Require(hp is not null && (m.Special == 118 ? hp == 0 : hp > 0), "對象狀態不符合道具用途。");
            packet = new(23, 15, new PacketWriter().U8(a.Index).U16(source.ItemId).U32(1).U8(a.Y).Build()); label = "使用道具";
        }
        else if (a.Operation == "discard")
        {
            Require((data!.Restrict & 128) == 0, "此道具不可丟棄。");
            packet = new(23, 124, [(byte)a.Index, (byte)a.Count, 2]); label = "丟棄道具";
        }
        else
        {
            Require((data!.Restrict & 16) == 0 && a.ExpectedPrice == data.SellPrice, "此道具不可販售或價格已更新。");
            var gold = s.Local.Session.Gold; ulong total = (ulong)data.SellPrice * (uint)a.Count;
            Require(gold is { Ready: true, Reliable: true, Amount: not null } && total + gold.Amount <= uint.MaxValue, "金幣餘額未同步或超出上限。");
            expectedGold = (uint)(total + gold.Amount!.Value);
            packet = new(27, 3, [(byte)a.Index, (byte)a.Count]); label = "販售道具";
        }
        return new(packet, a.Kind == "shop" ? "shop" : "inventory_manual", label, next => next, next =>
        {
            Require(next.Bag.Ready && next.Bag.Reliable, "道具操作期間背包資料失效。");
            var after = next.Bag.Items.GetValueOrDefault((byte)a.Index);
            Require(after is null || after.ItemId == source.ItemId && after.OriginalRecord.Serial == source.OriginalRecord.Serial &&
                after.OriginalRecord.SerialVersion == source.OriginalRecord.SerialVersion, "格位已替換，操作結果無法核對。");
            bool spent = after is null ? source.Count == a.Count : after.Count == source.Count - a.Count;
            return receipt && spent && (a.Operation != "sell" || next.Local.Session.Gold is { Ready: true, Reliable: true, Amount: {} balance } && balance == expectedGold);
        })
        {
            RefusalUnchanged = next => InventoryUnchanged(s, next),
            ObserveReceipt = e =>
            {
                if (a.Operation == "use" && e.Type == "item_use_result")
                {
                    if (e.Code is 3 or 4) throw new GameActionRefusedException(e.Code == 4 ? "背包空間不足，無法使用。" : "伺服器拒絕使用道具。");
                    if (e.Code == 1 || e.Code == 2 && e.ItemId == source.ItemId && e.Index == a.Y) receipt = true;
                }
                if (a.Operation == "sell" && e.Type == "sale_notice" && e.Code == 0) throw new GameActionRefusedException("伺服器拒絕販售。");
                if (a.Operation is "discard" or "sell" && e.Type == (a.Operation == "sell" ? "bag_sell" : "bag_delete") && e.Index == a.Index)
                { Require(e.Count == a.Count, "道具扣除數量不符。"); receipt = true; }
            }
        };
    }
}

// A definitive negative result is different from a timeout or unknown settlement.
internal sealed class GameActionRefusedException(string message) : Exception(message);
