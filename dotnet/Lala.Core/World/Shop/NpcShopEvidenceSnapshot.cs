using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Sessions;
using Lala.Core.State;

namespace Lala.Core.World.Shop;

/// <summary>Independent scalar receive facts, never an order ID or a settled transaction.
/// S27GoldField is deliberately retained separately from authoritative S26 balance evidence.</summary>
public sealed record NpcShopEvidenceEntry(BigInteger Packet, string Type,
    BigInteger InventoryRevision, bool InventoryReliable, BigInteger GoldRevision, bool GoldReliable)
{
    public ushort? ItemId { get; init; }
    public byte? Count { get; init; }
    public byte? Index { get; init; }
    public uint? S27GoldField { get; init; }
    public byte? Capacity { get; init; }
    public uint? Amount { get; init; }
    public long? Delta { get; init; }
    public byte? Result { get; init; }
    public override string ToString() => nameof(NpcShopEvidenceEntry);

    internal StateValue ToData()
    {
        var data = new Dictionary<string, StateValue>(StringComparer.Ordinal);
        void Put(string key, object? value) => data[key] = StateValue.Scalar(value);
        Put("packet", Packet); Put("type", Type); Put("inventory_revision", InventoryRevision);
        Put("inventory_reliable", InventoryReliable); Put("gold_revision", GoldRevision); Put("gold_reliable", GoldReliable);
        switch (Type)
        {
            case "bag_add": Put("item_id", ItemId); Put("count", Count); Put("index", Index); break;
            case "bag_delete": Put("index", Index); Put("count", Count); break;
            case "bag_sell": Put("index", Index); Put("count", Count); Put("s27_gold_field", S27GoldField); break;
            case "bag_snapshot": Put("capacity", Capacity); break;
            case "gold_snapshot": Put("amount", Amount); break;
            case "gold_delta": Put("delta", Delta); break;
            case "shop_purchase_result": case "sale_notice": Put("result", Result); break;
        }
        return StateValue.Map(data);
    }
}

/// <summary>Immutable source defaults and bounded observation history. No payment is enabled.</summary>
public sealed record NpcShopEvidenceSnapshot
{
    public static NpcShopEvidenceSnapshot Empty { get; } = new();
    public ImmutableArray<NpcShopEvidenceEntry> Events { get; init; } = [];
    public BigInteger Revision { get; init; }
    public string Status { get; init; } = "無交易觀測資料（未啟用付款）";
    public override string ToString() => nameof(NpcShopEvidenceSnapshot);

    public StateValue ToOfflineData() => StateValue.Map(
        ("events", StateValue.List((Events.IsDefault ? [] : Events).Select(entry => entry.ToData()))),
        ("revision", StateValue.Scalar(Revision)), ("status", StateValue.Scalar(Status)));
}

/// <summary>Explicit post-local-handler state for this exact packet. The caller must finish
/// normal inventory/gold reducers first, even when they mark a packet unreliable. No defaults,
/// clock, revision inference or verification of provenance are supplied here.</summary>
public sealed record NpcShopObservationContext(BigInteger PacketCount,
    BagReceiveSnapshot Inventory, SessionGoldSnapshot Gold);

/// <summary>Caller-provided historical description recorded when one command was sent.
/// This type neither creates a command nor verifies this assertion. No live command currently
/// produces it. Retrospective guesses and overlapping operations cannot establish settlement.</summary>
public sealed record NpcShopOfflineOrder(string Kind, BigInteger StartPacket, BigInteger ItemId,
    BigInteger Count, BigInteger ExpectedGoldDelta, BigInteger? BagSlot = null)
{
    internal StateValue ToData() => StateValue.Map(("kind", StateValue.Scalar(Kind)),
        ("start_packet", StateValue.Scalar(StartPacket)), ("item_id", StateValue.Scalar(ItemId)),
        ("count", StateValue.Scalar(Count)), ("expected_gold_delta", StateValue.Scalar(ExpectedGoldDelta)),
        ("bag_slot", StateValue.Scalar(BagSlot)));
    public override string ToString() => nameof(NpcShopOfflineOrder);
}

/// <summary>Offline correlation only. Even observed_consistent is not payment authorization,
/// confirmation of settlement, permission to retry, or permission to send another command.</summary>
public sealed record NpcShopOfflineClassification(string Status, string Reason);
