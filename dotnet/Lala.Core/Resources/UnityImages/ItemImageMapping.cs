using System.Collections.Frozen;
using System.Globalization;
using System.Text.Json;
using Lala.Core.Catalogs;

namespace Lala.Core.Resources;

internal sealed record ItemImageMetadata(byte Width, byte Height, byte OpenUsed);

// Pure mapping from reviewed item fields and the exact MainPackage manifest.
// No arbitrary model guesses, image bytes, currentness or production authority.
internal sealed class ItemImageMapping
{
    internal const string Prefix = "Assets/ResourcesBuild/Sprite/Sprite_Item/";
    internal IReadOnlyDictionary<int, string> Assets { get; }
    internal IReadOnlyDictionary<ushort, ushort> Icons { get; }
    internal IReadOnlyDictionary<ushort, ItemImageMetadata> Metadata { get; }
    internal string InputSha256 { get; }
    private ItemImageMapping(YooAssetManifest manifest, IReadOnlyDictionary<int, string> assets,
        Dictionary<ushort, ushort> icons, Dictionary<ushort, ItemImageMetadata> metadata)
    {
        Assets = assets; Icons = icons.ToFrozenDictionary(); Metadata = metadata.ToFrozenDictionary();
        InputSha256 = SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new
        {
            manifest.Sha256, Assets = assets.OrderBy(x => x.Key), Icons = icons.OrderBy(x => x.Key), Metadata = metadata.OrderBy(x => x.Key)
        }));
    }
    internal static IReadOnlyDictionary<int, string> Paths(YooAssetManifest manifest, CancellationToken token = default)
    {
        BoundedSpritePixels.Check(manifest.Header.PackageName == "MainPackage", "Item images require MainPackage");
        var paths = new Dictionary<int, string>();
        foreach (var asset in manifest.Assets)
        {
            token.ThrowIfCancellationRequested();
            if (!asset.Path.StartsWith(Prefix, StringComparison.Ordinal)) continue;
            string name = asset.Path[Prefix.Length..];
            BoundedSpritePixels.Check(name.Length is 9 or 10 && name[0] == 's' && name.EndsWith(".png", StringComparison.Ordinal), "Invalid item image path");
            var digits = name.AsSpan(1, name.Length - 5);
            foreach (char c in digits) BoundedSpritePixels.Check(c is >= '0' and <= '9', "Invalid item image model");
            int model = int.Parse(digits, NumberStyles.None, CultureInfo.InvariantCulture);
            BoundedSpritePixels.Check(model is > 0 and <= 65535 && paths.TryAdd(model, asset.Path), "Duplicate or invalid item image model");
            BoundedSpritePixels.Check(paths.Count <= 8192, "Item image count exceeds quota");
        }
        BoundedSpritePixels.Check(paths.TryGetValue(1000, out var fallback) && fallback == Prefix + "s1000.png", "Default item image s1000 missing");
        return paths.ToFrozenDictionary();
    }
    internal static ItemImageMapping Create(YooAssetManifest manifest, IReadOnlyDictionary<ushort, ItemDataRow> items, CancellationToken token = default)
    {
        var paths = Paths(manifest, token);
        BoundedSpritePixels.Check(items.Count is > 0 and <= ItemDataParser.MaxItems, "Item image mapping is empty or oversized");
        var icons = new Dictionary<ushort, ushort>(); var metadata = new Dictionary<ushort, ItemImageMetadata>();
        foreach (var (id, row) in items)
        {
            token.ThrowIfCancellationRequested();
            BoundedSpritePixels.Check(id == row.ItemId && row.ReviewedDetails is not null, "Item image fields are not reviewed");
            var details = row.ReviewedDetails!;
            icons.Add(id, details.IconId); metadata.Add(id, new(details.ItemW, details.ItemH, row.OpenUsed));
        }
        return new(manifest, paths, icons, metadata);
    }
    internal int Icon(ushort itemId)
    {
        int icon = Icons.TryGetValue(itemId, out var value) ? value : 1000;
        return Assets.ContainsKey(icon) ? icon : 1000;
    }
}
