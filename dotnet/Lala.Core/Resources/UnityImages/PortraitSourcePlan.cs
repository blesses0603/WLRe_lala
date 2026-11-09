using System.Collections.Frozen;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lala.Core.Resources;

internal sealed record PortraitMaterialKey(string Kind, string Icon);
// Exact data-only projection from Python portrait_assets.py. NOT the material bundle's
// complete Unity dependency closure; no object parsing, renderer input or activation yet.
internal sealed class PortraitSourcePlan
{
    internal const string DataVersion = "1.3.23", MainVersion = "1296_2026_11_04_13_36_07_72";
    private static readonly FrozenDictionary<string, (long Size, string Sha256)> Pins = new Dictionary<string, (long, string)>
    {
        ["mainpackage_material.bundle"] = (1903222, "4940712f0a4aa16c71959fe3b315b2b85eef23144feb90a4b70db22046a1fc94"),
        ["mainpackage_texture_a.bundle"] = (21442774, "a7dc6325bc73f8e5083cde9143e60a87b393ce84719814d1349142893141d3ca"),
        ["mainpackage_unityshaders.bundle"] = (1226061, "4e756561fa3d8b77f439b0b3e969a01f573b451ac9d14ac662d8c8bedf443a47")
    }.ToFrozenDictionary(StringComparer.Ordinal);
    private static readonly Regex Pattern = new(@"\AAssets/ResourcesBuild/Other/(?:Avatar2DMaterial/([0-9]{4})/PhotoAvatar_([0-9]{4})|Avatar2DNPCMaterial/([0-9]{4}(?:_[0-9]+)?)/PhotoAvatarNPC_([0-9]{4}(?:_[0-9]+)?))\.mat\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    internal IReadOnlyDictionary<PortraitMaterialKey, string> Materials { get; }
    internal IReadOnlyList<BundleSourceSpec> Specs { get; }
    internal string Fingerprint { get; }
    private PortraitSourcePlan(YooAssetManifest manifest, Dictionary<PortraitMaterialKey,string> materials, BundleSourceSpec[] specs)
    {
        Materials = materials.ToFrozenDictionary(); Specs = Array.AsReadOnly(specs);
        Fingerprint = SpritePng.Hash(JsonSerializer.SerializeToUtf8Bytes(new
        {
            DataVersion, MainVersion, manifest.Sha256,
            Materials = materials.OrderBy(p => p.Key.Kind, StringComparer.Ordinal).ThenBy(p => p.Key.Icon, StringComparer.Ordinal)
                .Select(p => new { p.Key.Kind, p.Key.Icon, Path = p.Value }),
            Sources = specs.Select(s => new { s.Name, s.Size, s.Md5, s.Crc32Le, Pins[s.Name].Sha256 })
        }));
    }
    internal static PortraitSourcePlan Create(YooAssetManifest manifest, string dataVersion, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        BoundedSpritePixels.Check(dataVersion == DataVersion && manifest.Header.PackageName == "MainPackage" &&
            manifest.Header.PackageVersion == MainVersion, "Portrait source version is not reviewed");
        var specs = new List<BundleSourceSpec>();
        foreach (var name in Pins.Keys.Order(StringComparer.Ordinal))
        {
            var bundle = manifest.Bundles.SingleOrDefault(b => b.Name == name);
            BoundedSpritePixels.Check(bundle is not null && bundle.FileSize == Pins[name].Size, "Portrait source bundle missing or changed size");
            specs.Add(new(dataVersion, manifest, bundle!));
        }
        var materials = new Dictionary<PortraitMaterialKey,string>();
        foreach (var asset in manifest.Assets)
        {
            token.ThrowIfCancellationRequested();
            if (!asset.Path.Contains("/PhotoAvatar_", StringComparison.Ordinal) && !asset.Path.Contains("/PhotoAvatarNPC_", StringComparison.Ordinal)) continue;
            var match = Pattern.Match(asset.Path);
            BoundedSpritePixels.Check(match.Success && manifest.Bundles[asset.BundleId].Name == "mainpackage_material.bundle", "Unreviewed portrait material path or bundle");
            bool player = match.Groups[1].Success;
            string directory = match.Groups[player ? 1 : 3].Value, icon = match.Groups[player ? 2 : 4].Value;
            BoundedSpritePixels.Check(directory == icon && materials.TryAdd(new(player ? "player" : "companion", icon), asset.Path), "Portrait material identity mismatch or duplicate");
            BoundedSpritePixels.Check(materials.Count <= 778, "Portrait material count exceeds reviewed set");
        }
        BoundedSpritePixels.Check(materials.Count == 778 && materials.Keys.Where(k => k.Kind == "player").Select(k => k.Icon)
            .ToHashSet(StringComparer.Ordinal).SetEquals(Enumerable.Range(1,15).Select(i => i.ToString("D4", System.Globalization.CultureInfo.InvariantCulture))), "Incomplete portrait material set");
        return new(manifest, materials, specs.ToArray());
    }
    internal VerifiedPortraitSources Verify(IReadOnlyList<VerifiedBundleSource> sources, CancellationToken token = default)
        => VerifiedPortraitSources.Capture(this, sources, token);
    private void ValidateSources(IReadOnlyList<VerifiedBundleSource> sources, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        BoundedSpritePixels.Check(sources.Count == Specs.Count && sources.Select(s => s.Spec.Name).Distinct(StringComparer.Ordinal).Count() == Specs.Count,
            "Portrait source set mismatch");
        foreach (var spec in Specs)
        {
            token.ThrowIfCancellationRequested();
            var source = sources.SingleOrDefault(s => s.Spec.Name == spec.Name);
            BoundedSpritePixels.Check(source is not null && source.Spec == spec && source.Sha256 == Pins[spec.Name].Sha256, "Portrait source fingerprint is not reviewed");
        }

    }
    // Construction validates the plan and all immutable bytes against both
    // manifest checksums and the reviewed SHA pins. It still carries no currentness/authority.
    internal sealed class VerifiedPortraitSources
    {
        internal PortraitSourcePlan Plan { get; }
        internal IReadOnlyDictionary<string, VerifiedBundleSource> Sources { get; }
        private VerifiedPortraitSources(PortraitSourcePlan plan, IReadOnlyList<VerifiedBundleSource> sources)
        { Plan = plan; Sources = sources.ToFrozenDictionary(s => s.Spec.Name, StringComparer.Ordinal); }
        internal static VerifiedPortraitSources Capture(PortraitSourcePlan plan, IReadOnlyList<VerifiedBundleSource> sources, CancellationToken token)
        { var owned = sources.ToArray(); plan.ValidateSources(owned, token); return new(plan, owned); }
    }
}
