using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.World.Eve;

namespace Lala.Core.Resources;

/// <summary>Catalog base prices only, never a live quote or a purchase permit.</summary>
public sealed record SceneShopProduct(byte OfferIndex, ushort ItemId, string Name,
    uint? BasePriceGold, uint? BaseSellPriceGold, bool CatalogAllowsNpcSale)
{
    public bool BuyEnabled => false;
}
public sealed record SceneShopPurchasePreview(ushort ItemId, int Count, uint? BaseUnitGold, uint? BaseTotalGold)
{
    public uint? TotalGold => null;
    public bool Enabled => false;
}

/// <summary>Current-scene catalog preview. The interaction index is not an NPC index;
/// this does not assert a live S20 shop context, discounts, currency, stock or settlement.</summary>
public sealed class SceneShopPreviewRequest
{
    private readonly ImmutableArray<SceneShopProduct> products;
    private readonly Func<bool> current;
    public ushort Scene { get; }
    public ushort InteractionIndex { get; }
    public byte FormKind { get; }
    public string Title => FormKind == 2 ? "武器商店" : "道具商店";
    public bool IsCurrent => current();
    public bool CanSendPackets => false;
    internal SceneShopPreviewRequest(ushort scene, ushort index, byte formKind,
        ImmutableArray<SceneShopProduct> products, Func<bool> current)
        => (Scene, InteractionIndex, FormKind, this.products, this.current) = (scene, index, formKind, products, current);
    public bool TryReadProducts(out ImmutableArray<SceneShopProduct> result)
    {
        result = [];
        if (!IsCurrent) return false;
        var captured = products;
        if (!IsCurrent) return false;
        result = captured; return true;
    }
    public bool TryPreviewPurchase(byte offerIndex, int count, out SceneShopPurchasePreview? preview)
    {
        preview = null;
        if (count is < 1 or > 9999 || !TryReadProducts(out var rows)) return false;
        var row = rows.FirstOrDefault(p => p.OfferIndex == offerIndex);
        if (row is null) return false;
        ulong? total = row.BasePriceGold is { } price ? (ulong)price * (uint)count : null;
        if (total > uint.MaxValue || !IsCurrent) return false;
        preview = new(row.ItemId, count, row.BasePriceGold, total is { } value ? (uint)value : null);
        return true;
    }
    internal static ImmutableArray<SceneShopProduct>? Build(EveInteractionRow interaction,
        IReadOnlyDictionary<ushort, ItemDataRow> items)
    {
        // Python npc_shop.shop_catalog: form 2/3, exit kind 4, offer kind 3/database 2.
        if (interaction.FormKind is not (2 or 3) || interaction.Items.IsDefault || interaction.Items.Length > 255) return null;
        var rows = ImmutableArray.CreateBuilder<SceneShopProduct>();
        var indices = new HashSet<byte>();
        foreach (var entry in interaction.Items)
        {
            if (entry.Kind == 4) continue;
            if (entry.Kind != 3 || entry.DatabaseKind != 2 || entry.TextId == 0 || entry.Id == 0 || !indices.Add(entry.Id)) return null;
            items.TryGetValue(entry.TextId, out var item);
            if (item is not null && item.ItemId != entry.TextId) return null;
            rows.Add(new(entry.Id, entry.TextId, item?.Name ?? "物品 #" + entry.TextId.ToString(System.Globalization.CultureInfo.InvariantCulture),
                item?.Price, item?.SellPrice, item is not null && (item.Restrict & 16) == 0));
        }
        return rows.Count == 0 ? null : rows.ToImmutable();
    }
}
