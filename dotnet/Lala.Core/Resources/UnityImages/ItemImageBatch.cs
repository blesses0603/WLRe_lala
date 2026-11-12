using System.Collections.Immutable;
using System.Text.Json;
using Lala.Core.Catalogs;

namespace Lala.Core.Resources;

// Exact complete batch; source matching is checked before extraction and fingerprint normalization.
internal sealed class ItemImageBatch
{
    internal ItemImageMapping Mapping { get; }
    internal ImmutableArray<SpritePixelCandidate> Pixels { get; }
    internal string Fingerprint { get; }
    private ItemImageBatch(ItemImageMapping mapping, ImmutableArray<SpritePixelCandidate> pixels, string fingerprint)
        => (Mapping, Pixels, Fingerprint) = (mapping, pixels, fingerprint);
    internal static ItemImageBatch Create(YooAssetManifest manifest, string dataVersion, string versionIdentity,
        IReadOnlyDictionary<ushort, ItemDataRow> items, IReadOnlyDictionary<string, IReadOnlyList<VerifiedBundleSource>> selected,
        CancellationToken token = default)
    {
        var mapping = ItemImageMapping.Create(manifest, items, token);
        var plan = BundleSourcePlan.CreateItemImages(manifest, dataVersion, token);
        BoundedSpritePixels.Check(selected.Count == mapping.Assets.Count, "Item image batch index mismatch");
        var specs = plan.Entries.ToDictionary(e => e.Spec.Name, e => e.Spec, StringComparer.Ordinal);
        var owned = new Dictionary<string, VerifiedBundleSource>(StringComparer.Ordinal);
        foreach (var (path, names) in plan.AssetSourceNames)
        {
            token.ThrowIfCancellationRequested();
            BoundedSpritePixels.Check(selected.TryGetValue(path, out var sources) && sources.Count == names.Count &&
                sources.Select(s => s.Spec.Name).ToHashSet(StringComparer.Ordinal).SetEquals(names), "Item image dependency closure mismatch");
            foreach (var source in sources!)
            {
                BoundedSpritePixels.Check(source.Spec == specs[source.Spec.Name], "Item image source differs from exact manifest");
                if (owned.TryGetValue(source.Spec.Name, out var previous))
                    BoundedSpritePixels.Check(source.Sha256 == previous.Sha256, "Item image source changed within batch");
                else owned.Add(source.Spec.Name, source);
            }
        }
        string fingerprint = SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new
        {
            VersionIdentity = versionIdentity, manifest.Sha256, mapping.InputSha256,
            Sources = owned.Values.OrderBy(s => s.Spec.Name, StringComparer.Ordinal).Select(s => new
            { s.Spec.DataVersion, s.Spec.Package, s.Spec.PackageVersion, s.Spec.Name, s.Spec.Size, s.Spec.Md5, s.Spec.Crc32Le, s.Sha256 }),
            Closures = plan.AssetSourceNames.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => new { Path = p.Key, Names = p.Value })
        }));
        // Original per-image selection is preserved in the manifest/closure fingerprint. A common
        // batch identity permits different exact closures without weakening SpritePngStore's gate.
        var decoded = UnitySpriteExtractor.ExtractMany(selected, fingerprint, token);
        var pixels = decoded.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p =>
            new SpritePixelCandidate(p.Value.Context with { VersionIdentity = fingerprint }, p.Value.TextureLayout,
                p.Value.Rectangle, p.Value.Width, p.Value.Height, p.Value.CopyPixels(), p.Value.TexturePayloadSha256)).ToImmutableArray();
        token.ThrowIfCancellationRequested(); return new(mapping, pixels, fingerprint);
    }
}

internal sealed class ItemImageReadback(ItemImageBatch batch, IReadOnlyDictionary<string, byte[]> verifiedPngs)
{
    // SpritePngStore has already compared every byte to independent current candidates.
    private readonly Dictionary<string, byte[]> pngs = verifiedPngs.ToDictionary(p => p.Key, p => p.Value.ToArray(), StringComparer.Ordinal);
    internal byte[] CopyPng(ushort itemId) => pngs[batch.Mapping.Assets[batch.Mapping.Icon(itemId)]].ToArray();
}
