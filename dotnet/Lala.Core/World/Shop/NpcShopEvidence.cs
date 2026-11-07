using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.World.Shop;

/// <summary>Pure offline port of npc_shop_evidence.py. Does not send, schedule, mutate inventory,
/// confirm settlement, create order descriptors, or connect to a session/service coordinator.</summary>
public static class NpcShopEvidence
{
    public const int MaxEvents = 96;
    private const string InvalidOrder = "離線交易對帳的項目、數量或金額非法";
    private const string InvalidEvidence = "離線交易事件來源不合法";

    public static NpcShopEvidenceSnapshot Observe(NpcShopEvidenceSnapshot state, ServerEvent observation,
        NpcShopObservationContext context)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        ArgumentNullException.ThrowIfNull(context);
        if (observation is LoginResultEvent or ServerLayoutEvent { Event: RoleListAvailableEvent })
            return NpcShopEvidenceSnapshot.Empty;
        if (observation is not (GoldSnapshotEvent or GoldDeltaEvent or GoldLimitEvent or
            ServerLiveDataEvent { Event: BagSnapshotEvent or BagAddEvent or BagDeleteEvent or BagSellEvent or ShopPurchaseResultEvent or SaleNoticeEvent }))
            return state;
        ArgumentNullException.ThrowIfNull(context.Inventory);
        ArgumentNullException.ThrowIfNull(context.Gold);
        var entry = new NpcShopEvidenceEntry(context.PacketCount, observation.Type,
            context.Inventory.Revision, context.Inventory.Ready && context.Inventory.Reliable,
            context.Gold.Revision, context.Gold.Ready && context.Gold.Reliable);
        entry = observation switch
        {
            ServerLiveDataEvent { Event: BagAddEvent added } => entry with { ItemId = added.Item.ItemId, Count = added.Item.Count, Index = added.Item.Index },
            ServerLiveDataEvent { Event: BagDeleteEvent deleted } => entry with { Index = deleted.Index, Count = deleted.Count },
            ServerLiveDataEvent { Event: BagSellEvent sold } => entry with { Index = sold.Index, Count = sold.Count, S27GoldField = sold.Gold },
            ServerLiveDataEvent { Event: BagSnapshotEvent bag } => entry with { Capacity = bag.Capacity },
            GoldSnapshotEvent gold => entry with { Amount = gold.Amount },
            GoldDeltaEvent gold => entry with { Delta = gold.Delta },
            ServerLiveDataEvent { Event: ShopPurchaseResultEvent result } => entry with { Result = result.Result },
            ServerLiveDataEvent { Event: SaleNoticeEvent result } => entry with { Result = result.Result },
            _ => entry
        };
        var events = (state.Events.IsDefault ? ImmutableArray<NpcShopEvidenceEntry>.Empty : state.Events).Add(entry);
        if (events.Length > MaxEvents) events = events.RemoveRange(0, events.Length - MaxEvents);
        return new() { Events = events, Revision = state.Revision + 1, Status = "已記錄 S23／S26／S27 封包；並非交易已完成" };
    }

    public static NpcShopOfflineClassification ClassifyOffline(NpcShopEvidenceSnapshot evidence, NpcShopOfflineOrder order)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        ArgumentNullException.ThrowIfNull(order);
        return ClassifyOfflineData(evidence.ToOfflineData(), order.ToData());
    }

    /// <summary>Narrow immutable boundary for externally retained source-shaped evidence and
    /// order fields. It preserves Python's exact-int descriptor checks and absent/null values.
    /// It is not a general Python serializer or a trusted order/provenance validator. Explicit
    /// source validation uses ProtocolException; malformed object shapes/missing required row
    /// keys throw InvalidOperationException/KeyNotFoundException, never a reassuring result.</summary>
    public static NpcShopOfflineClassification ClassifyOfflineData(StateValue evidence, StateValue order)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        ArgumentNullException.ThrowIfNull(order);
        var kind = Text(Get(order, "kind"));
        if (kind is not ("buy" or "sell") || !TryInteger(Get(order, "start_packet"), out var start) || start < 0 ||
            !TryInteger(Get(order, "item_id"), out var itemId) || itemId < 1 || itemId > 65535 ||
            !TryInteger(Get(order, "count"), out var count) || count < 1 || count > 255 ||
            !TryInteger(Get(order, "expected_gold_delta"), out var delta) || delta < -new BigInteger(uint.MaxValue) || delta > uint.MaxValue ||
            (kind == "buy" ? delta >= 0 : delta <= 0) ||
            (kind == "sell" && (!TryInteger(Get(order, "bag_slot"), out var slot) || slot < 0 || slot > 255)))
            throw new ProtocolException(InvalidOrder);
        var entries = evidence.MapValue.GetValueOrDefault("events", StateValue.List());
        if (entries.Kind != StateValueKind.List || entries.SequenceValue.Length > MaxEvents)
            throw new ProtocolException(InvalidEvidence);
        var rows = entries.SequenceValue;
        if (rows.Length > 0 && TryInteger(Get(rows[0], "packet"), out var first) && first > start + 1)
            return Uncertain("事件已超出保留窗口，無法對帳");
        var records = rows.Where(row => TryInteger(Get(row, "packet"), out var packet) && packet > start).ToArray();
        if (records.Length == 0) return new("pending", "未觀測到付款、背包或結果回覆");
        var resultKind = kind == "buy" ? "shop_purchase_result" : "sale_notice";
        if (records.Any(row => Text(Get(row, "type")) is "shop_purchase_result" or "sale_notice" && Text(Get(row, "type")) != resultKind))
            return Uncertain("觀測窗口包含其他種類交易結果，無法唯一歸屬");
        var results = records.Where(row => Text(row["type"]) == resultKind).ToArray();
        if (results.Length > 1) return Uncertain("交易結果可能重複或包含其他交易");
        if (results.Length != 0 && !NumericEquals(Get(results[0], "result"), kind == "buy" ? 0 : 1))
        {
            var conflicting = records.Any(row => Text(row["type"]) is "gold_delta" or "bag_add" or "bag_delete" or "bag_sell");
            return new(conflicting ? "uncertain" : "rejected", conflicting
                ? "伺服器宣告失敗但另有背包／金幣異動，無法安全判定" : "伺服器拒絕交易，未觀察到這筆交易的相關異動");
        }
        var currencies = records.Where(row => Text(row["type"]) == "gold_delta").ToArray();
        var items = records.Where(row => Text(row["type"]) is "bag_add" or "bag_delete" or "bag_sell").ToArray();
        if (records.Any(row => Text(row["type"]) is "gold_snapshot" or "gold_limit" or "bag_snapshot") || currencies.Length > 1 ||
            currencies.Concat(items).Any(row => !Truth(Get(row, "gold_reliable")) || !Truth(Get(row, "inventory_reliable"))))
            return Uncertain("資料重新初始化、其他金幣異動或同步失效");
        if (currencies.Length != 0 && !NumericEquals(Get(currencies[0], "delta"), delta))
            return Uncertain("S26 金幣變更與預期金額不同，可能有折扣或其他交易");
        bool itemsDone;
        if (kind == "buy")
        {
            if (items.Any(row => Text(row["type"]) != "bag_add" || !NumericEquals(Get(row, "item_id"), itemId) ||
                !TryInteger(Get(row, "count"), out var quantity) || quantity <= 0))
                return Uncertain("S23 背包異動不屬於這筆商品");
            var total = items.Aggregate(BigInteger.Zero, (sum, row) => sum + Integer(row["count"]));
            if (total > count) return Uncertain("S23 入袋數量超過本筆預期");
            itemsDone = total == count;
        }
        else
        {
            if (items.Length > 1 || items.Any(row => Text(row["type"]) != "bag_sell" ||
                !NumericEquals(Get(row, "index"), Integer(Get(order, "bag_slot"))) || !NumericEquals(Get(row, "count"), count)))
                return Uncertain("S27-6 販售格位或數量與預期不同");
            itemsDone = items.Length == 1;
        }
        return results.Length != 0 && currencies.Length != 0 && itemsDone
            ? new("observed_consistent", "S23/S26/S27 觀測一致；因缺少伺服器交易識別碼，仍待實機人工對帳")
            : new("pending", "等待缺少的 S23、S26 或 S27 證據；禁止重送");
    }

    private static NpcShopOfflineClassification Uncertain(string reason) => new("uncertain", reason);
    private static StateValue Get(StateValue map, string key) => map.MapValue.GetValueOrDefault(key, StateValue.Null);
    private static string? Text(StateValue value) => value.Kind == StateValueKind.Scalar ? value.ScalarValue as string : null;
    private static bool TryInteger(StateValue value, out BigInteger number)
    {
        if (value.Kind == StateValueKind.Scalar && value.ScalarValue is sbyte or byte or short or ushort or int or uint or long or ulong or BigInteger)
        { number = Integer(value); return true; }
        number = default; return false;
    }
    private static BigInteger Integer(StateValue value) => value.ScalarValue is BigInteger big ? big :
        BigInteger.Parse(Convert.ToString(value.ScalarValue, CultureInfo.InvariantCulture)!, CultureInfo.InvariantCulture);
    // Python numeric equality accepts bool/float in observation fields, unlike type(x) is int.
    // Compare integral floats as exact integers, never round a large expected integer to double.
    private static bool NumericEquals(StateValue value, BigInteger expected)
    {
        if (TryInteger(value, out var integer)) return integer == expected;
        if (value.Kind != StateValueKind.Scalar) return false;
        return value.ScalarValue switch
        {
            bool boolean => (boolean ? BigInteger.One : BigInteger.Zero) == expected,
            double real => double.IsFinite(real) && real == Math.Truncate(real) && new BigInteger(real) == expected,
            float real => float.IsFinite(real) && real == MathF.Truncate(real) && new BigInteger(real) == expected,
            decimal real => real == decimal.Truncate(real) && new BigInteger(real) == expected,
            _ => false
        };
    }
    private static bool Truth(StateValue value) => value.Kind switch
    {
        StateValueKind.Map => value.MapValue.Count != 0,
        StateValueKind.List or StateValueKind.Tuple => value.SequenceValue.Length != 0,
        _ => value.ScalarValue switch
        {
            null => false, bool boolean => boolean, string text => text.Length != 0,
            double real => real != 0, float real => real != 0, decimal real => real != 0,
            _ => !TryInteger(value, out var integer) || integer != 0
        }
    };
}
