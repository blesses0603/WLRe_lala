using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class ItemImageMappingTests
{
    private static YooAssetManifest Manifest(params string[] names)
    {
        var index = BundleSourceFixtures.Index("main-valid"); var original = index["assets"]![0]!;
        var assets = new JsonArray();
        foreach (string name in names) { var row = original.DeepClone(); row["path"] = ItemImageMapping.Prefix + name; assets.Add(row); }
        index["assets"] = assets; return YooAssetManifest.Parse(BundleSourceFixtures.Encode(index));
    }
    private static ItemDataRow Row(ushort id, ushort icon) => new(id, "owned", 0, 0, 0, 1, 0,
        new ReviewedItemDetails { IconId = icon, ItemW = 2, ItemH = 3 });
    [Fact]
    public void Paths_and_fallback_match_actual_Python_function_vectors()
    {
        using var stream = typeof(ItemImageMappingTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.item_mapping_vectors.json")!;
        using var json = System.Text.Json.JsonDocument.Parse(stream);
        foreach (var row in json.RootElement.GetProperty("cases").EnumerateArray())
        {
            var manifest = Manifest(row.GetProperty("names").EnumerateArray().Select(x => x.GetString()!).ToArray());
            if (row.GetProperty("valid").GetBoolean()) Assert.NotEmpty(ItemImageMapping.Paths(manifest));
            else Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(manifest));
        }
        var map = ItemImageMapping.Create(Manifest("s1000.png", "s0020.png"), new Dictionary<ushort, ItemDataRow> { [1] = Row(1, 20), [2] = Row(2, 0), [3] = Row(3, 9999) });
        foreach (var icon in json.RootElement.GetProperty("icons").EnumerateObject())
            Assert.Equal(icon.Value.GetInt32(), map.Icon(ushort.Parse(icon.Name, System.Globalization.CultureInfo.InvariantCulture)));
    }
    [Fact]
    public void Exact_model_mapping_and_fallback_match_Python_rules()
    {
        var items = new Dictionary<ushort, ItemDataRow> { [1] = Row(1, 20), [2] = Row(2, 0), [3] = Row(3, 9999) };
        var map = ItemImageMapping.Create(Manifest("s1000.png", "s0020.png"), items);
        Assert.Equal(20, map.Icon(1)); Assert.Equal(1000, map.Icon(2)); Assert.Equal(1000, map.Icon(3)); Assert.Equal(1000, map.Icon(65535));
        Assert.Equal(new ItemImageMetadata(2, 3, 1), map.Metadata[1]);
        items[1] = Row(1, 1000); Assert.Equal(20, map.Icon(1));
        Assert.NotEqual(map.InputSha256, ItemImageMapping.Create(Manifest("s1000.png", "s0020.png"), items).InputSha256);
    }
    [Theory]
    [InlineData("s0000.png")][InlineData("s65536.png")][InlineData("s100.png")][InlineData("s100000.png")]
    [InlineData("s１２３４.png")][InlineData("s1001.PNG")][InlineData("../s1001.png")][InlineData("s+100.png")]
    public void Unreviewed_paths_are_rejected(string name) => Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(Manifest("s1000.png", name)));
    [Fact]
    public void Duplicate_numeric_model_and_noncanonical_fallback_are_rejected()
    {
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(Manifest("s1000.png", "s01000.png")));
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(Manifest("s01000.png")));
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(Manifest("s0020.png")));
    }
    [Fact]
    public void Legacy_unreviewed_item_fields_and_wrong_keys_cannot_map_icons()
    {
        var manifest = Manifest("s1000.png");
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Create(manifest, new Dictionary<ushort, ItemDataRow> { [1] = Row(1, 1000) with { ReviewedDetails = null } }));
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Create(manifest, new Dictionary<ushort, ItemDataRow> { [2] = Row(1, 1000) }));
        Assert.Throws<SpritePixelException>(() => ItemImageMapping.Paths(YooAssetManifest.Parse(BundleSourceFixtures.Bytes("data-valid"))));
    }
    [Fact]
    public void Image_plan_has_exact_MainPackage_closure_and_four_bundle_limit()
    {
        var manifest = Manifest("s1000.png"); var plan = BundleSourcePlan.CreateItemImages(manifest, "1.3.21");
        Assert.Equal(new[] { "dep-a.bundle", "dep-b.bundle", "root-a.bundle" }, plan.Entries.Select(x => x.Spec.Name));
        var index = BundleSourceFixtures.Index("main-valid"); index["assets"]![0]!["path"] = ItemImageMapping.Prefix + "s1000.png";
        index["bundles"]![0]!["dependency_ids"] = new JsonArray(1, 2, 3, 4);
        Assert.Throws<BundleSourceException>(() => BundleSourcePlan.CreateItemImages(YooAssetManifest.Parse(BundleSourceFixtures.Encode(index)), "1.3.21"));
    }
    [Fact]
    public void Cancellation_rejects_mapping_and_plan()
    {
        using var cts = new CancellationTokenSource(); cts.Cancel();
        Assert.ThrowsAny<OperationCanceledException>(() => ItemImageMapping.Paths(Manifest("s1000.png"), cts.Token));
        Assert.ThrowsAny<OperationCanceledException>(() => BundleSourcePlan.CreateItemImages(Manifest("s1000.png"), "1.3.21", cts.Token));
    }
}
