using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Lala.Core.World.Eve;
using Xunit;
namespace Lala.Core.Tests.Resources;
public sealed class SceneShopPreviewTests
{
    private static ItemDataRow Item(ushort id=7,uint price=10,ushort restrict=0) => new(id,"商品",price,3,restrict,0,0,null);
    private static EveInteractionRow Shop(params EveInteractionItem[] entries) => new(9,3,0,entries.ToImmutableArray());
    [Fact]
    public void Explicit_offer_indices_order_base_prices_exit_and_restriction_follow_Python()
    {
        var products = SceneShopPreviewRequest.Build(Shop(new EveInteractionItem(8,7,2,3),new EveInteractionItem(0,0,0,4),new EveInteractionItem(2,9,2,3)),
            new Dictionary<ushort,ItemDataRow>{{7,Item()},{9,Item(9,0,16)}})!.Value;
        Assert.Equal(new byte[]{8,2},products.Select(p=>p.OfferIndex));
        Assert.Equal(10u,products[0].BasePriceGold); Assert.Equal(3u,products[0].BaseSellPriceGold);
        Assert.True(products[0].CatalogAllowsNpcSale); Assert.False(products[1].CatalogAllowsNpcSale);
        Assert.Equal(0u,products[1].BasePriceGold); Assert.All(products,p=>Assert.False(p.BuyEnabled));
    }
    [Theory][InlineData("form")][InlineData("default")][InlineData("kind")][InlineData("database")]
    [InlineData("zero-item")][InlineData("zero-offer")][InlineData("duplicate")][InlineData("empty")][InlineData("identity")][InlineData("limit")]
    public void Invalid_or_nonshop_rows_do_not_produce_partial_catalog(string mode)
    {
        var row=Shop(new EveInteractionItem(1,7,2,3)); var items=new Dictionary<ushort,ItemDataRow>{{7,Item()}};
        row=mode switch {
            "form"=>row with{FormKind=1},"default"=>row with{Items=default},"kind"=>Shop(new EveInteractionItem(1,7,2,1)),
            "database"=>Shop(new EveInteractionItem(1,7,1,3)),"zero-item"=>Shop(new EveInteractionItem(1,0,2,3)),"zero-offer"=>Shop(new EveInteractionItem(0,7,2,3)),
            "duplicate"=>Shop(new EveInteractionItem(1,7,2,3),new EveInteractionItem(1,7,2,3)),"empty"=>Shop(new EveInteractionItem(0,0,0,4)),
            "limit"=>row with{Items=Enumerable.Repeat(new EveInteractionItem(0,0,0,4),256).ToImmutableArray()},_=>row};
        if(mode=="identity")items[7]=Item(8);
        Assert.Null(SceneShopPreviewRequest.Build(row,items));
    }
    [Fact]
    public void Unknown_price_stays_unknown_and_quantity_offer_and_uint_overflow_are_rejected()
    {
        var products=SceneShopPreviewRequest.Build(Shop(new EveInteractionItem(1,7,2,3),new EveInteractionItem(2,8,2,3),new EveInteractionItem(3,9,2,3)),
            new Dictionary<ushort,ItemDataRow>{{8,Item(8,uint.MaxValue)},{9,Item(9,0)}})!.Value;
        var request=new SceneShopPreviewRequest(10,9,3,products,()=>true);
        Assert.True(request.TryPreviewPurchase(1,9999,out var unknown));Assert.Null(unknown!.BaseTotalGold);Assert.Null(unknown.TotalGold);Assert.False(unknown.Enabled);
        Assert.True(request.TryPreviewPurchase(2,1,out var max));Assert.Equal(uint.MaxValue,max!.BaseTotalGold);
        Assert.False(request.TryPreviewPurchase(2,2,out _));Assert.False(request.TryPreviewPurchase(1,0,out _));Assert.False(request.TryPreviewPurchase(1,10000,out _));
        Assert.False(request.TryPreviewPurchase(4,1,out _));Assert.True(request.TryPreviewPurchase(3,9999,out var free));Assert.Equal(0u,free!.BaseTotalGold);
        Assert.False(request.CanSendPackets);
    }
    [Fact]
    public void Stale_reads_and_revocation_during_preview_never_deliver_data()
    {
        var products=SceneShopPreviewRequest.Build(Shop(new EveInteractionItem(1,7,2,3)),new Dictionary<ushort,ItemDataRow>{{7,Item()}})!.Value;
        bool current=true;var request=new SceneShopPreviewRequest(10,9,2,products,()=>current);
        Assert.True(request.TryPreviewPurchase(1,2,out var preview));Assert.Equal(20u,preview!.BaseTotalGold);
        current=false;Assert.False(request.TryReadProducts(out var rows));Assert.Empty(rows);Assert.False(request.TryPreviewPurchase(1,1,out _));
        int checks=0;var race=new SceneShopPreviewRequest(10,9,3,products,()=>++checks<3);
        Assert.False(race.TryPreviewPurchase(1,1,out var late));Assert.Null(late);
    }
}
