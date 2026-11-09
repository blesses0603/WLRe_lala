using System.Text.RegularExpressions;
using System.Collections.Frozen;

namespace Lala.Core.Resources;

internal enum BundleChange { FirstBaseline, Added, Modified, Unchanged }
internal enum BundleAcquisition { Cache, UntrustedSourceDownload }

internal sealed record BundleSourceSpec
{
    internal const long MaximumBundleBytes = 256L * 1024 * 1024;
    private static readonly Regex NamePattern = new(@"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.bundle\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex Md5Pattern = new(@"\A[a-fA-F0-9]{32}\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    private static readonly Regex CrcPattern = new(@"\A[a-fA-F0-9]{8}\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    internal string DataVersion { get; }
    internal string Package { get; }
    internal string PackageVersion { get; }
    internal string Name { get; }
    internal long Size { get; }
    internal string Md5 { get; }
    internal string Crc32Le { get; }
    internal BundleSourceSpec(string dataVersion, YooAssetManifest manifest, YooBundleEntry bundle)
    {
        if (!ResourceValidation.DataVersion.IsMatch(dataVersion) || !ResourceValidation.Packages.Contains(manifest.Header.PackageName, StringComparer.Ordinal) ||
            !ResourceValidation.Manifest.IsMatch(manifest.Header.PackageVersion) || manifest.Header.OutputNameStyle != 1 ||
            !NamePattern.IsMatch(bundle.Name) || bundle.SizeInvalid() || !Md5Pattern.IsMatch(bundle.FileHash) || !CrcPattern.IsMatch(bundle.FileCrc))
            throw new BundleSourceException(BundleSourceFailure.InvalidBundle, "Manifest bundle metadata invalid or unsupported");
        DataVersion = dataVersion; Package = manifest.Header.PackageName; PackageVersion = manifest.Header.PackageVersion;
        Name = bundle.Name; Size = bundle.FileSize; Md5 = bundle.FileHash.ToLowerInvariant(); Crc32Le = bundle.FileCrc.ToLowerInvariant();
    }
    internal string Url(string host) => $"https://{OfficialResourceOrigin.SelectHost(host)}/WLN/TW/{DataVersion}/ResourcesPC/AssetBundle/{Name}";
}

internal static class BundleEntryBounds
{
    internal static bool SizeInvalid(this YooBundleEntry bundle) => bundle.FileSize is <= 0 or > BundleSourceSpec.MaximumBundleBytes;
}

internal sealed record PlannedBundleSource(BundleSourceSpec Spec, BundleChange Change, IReadOnlyList<string> Dependencies);

internal sealed class BundleSourcePlan
{
    internal static IReadOnlyList<string> RequiredTables { get; } = Array.AsReadOnly(new[]
    { "Eve", "ItemData_C", "TalkData_C", "TextData_C", "SmithData_C", "ScenesData_C", "AdventureData_C", "AdventureLvData_C", "NpcData_C", "NpcCareerData_C" });
    internal static IReadOnlyList<string> RequiredAssetPaths { get; } = Array.AsReadOnly(RequiredTables.Select(x => "Assets/ResourcesBuild/Data/" + x + ".bytes").Order(StringComparer.Ordinal).ToArray());
    internal IReadOnlyList<PlannedBundleSource> Entries { get; }
    // Each lookup is the source runtime's single-asset plan: its listed complete dependency
    // set (not recursive graph traversal), then its root. Unrelated selected roots stay out.
    internal IReadOnlyDictionary<string, IReadOnlyList<string>> AssetSourceNames { get; }
    internal int AddedCount { get; }
    internal int ModifiedCount { get; }
    internal int RemovedCount { get; }
    private BundleSourcePlan(List<PlannedBundleSource> entries, Dictionary<string, IReadOnlyList<string>> assetSources,
        int added, int modified, int removed)
    {
        Entries = entries.AsReadOnly(); AssetSourceNames = assetSources.ToFrozenDictionary(StringComparer.Ordinal);
        AddedCount = added; ModifiedCount = modified; RemovedCount = removed;
    }

    internal static BundleSourcePlan Create(YooAssetManifest current, string dataVersion,
        YooAssetManifest? previous = null, CancellationToken cancellationToken = default)
        => CreateCore(current, dataVersion, previous, RequiredAssetPaths, cancellationToken);

    internal const string SkillAssetPath = "Assets/ResourcesBuild/Data/SkillData_C.bytes";
    internal static BundleSourcePlan CreateSkill(YooAssetManifest current, string dataVersion, CancellationToken token)
        => CreateCore(current, dataVersion, null, new[] { SkillAssetPath }, token);

    internal const string DailyTaskAssetPath = "Assets/ResourcesBuild/Data/DailyTaskData_C.bytes";
    internal const string DailyRewardAssetPath = "Assets/ResourcesBuild/Data/DailyTaskRewardData_C.bytes";
    internal static BundleSourcePlan CreateDaily(YooAssetManifest current, string dataVersion, CancellationToken token)
        => CreateCore(current, dataVersion, null, new[] { DailyTaskAssetPath, DailyRewardAssetPath }, token);

    internal const string DungeonAssetPath = "Assets/ResourcesBuild/Data/DungeonData_C.bytes";
    internal const string CooperativeAssetPath = "Assets/ResourcesBuild/Data/CooperateEventData_C.bytes";
    internal static BundleSourcePlan CreateInstances(YooAssetManifest current, string dataVersion, CancellationToken token)
        => CreateCore(current, dataVersion, null, new[] { DungeonAssetPath, CooperativeAssetPath }, token);

    internal static BundleSourcePlan CreateItemImages(YooAssetManifest current, string dataVersion, CancellationToken token = default)
    {
        var paths = ItemImageMapping.Paths(current, token);
        var plan = CreateCore(current, dataVersion, null, paths.Values.ToArray(), token, "MainPackage");
        if (plan.Entries.Count is < 1 or > 4 || plan.Entries.Sum(entry => entry.Spec.Size) > 32L * 1024 * 1024)
            throw new BundleSourceException(BundleSourceFailure.Budget, "Item image source closure exceeds quota");
        return plan;
    }

    internal static BundleSourcePlan CreateEmojiData(YooAssetManifest current,string version,CancellationToken token)
        => CreateCore(current,version,null,[EmojiSourcePlan.DataPath],token);
    internal static BundleSourcePlan CreateEmojiAtlas(YooAssetManifest current,string version,CancellationToken token)
    {
        var plan=CreateCore(current,version,null,[EmojiSourcePlan.AtlasPath],token,"MainPackage");
        // Python's reviewed source budget is eight bundles. The observed exact
        // official closure contains six; this does not widen decoded-object scopes.
        if(plan.Entries.Count is <1 or >8||plan.Entries.Sum(e=>e.Spec.Size)>32L*1024*1024)
            throw new BundleSourceException(BundleSourceFailure.Budget,"Emoji atlas source closure exceeds supported quota");
        return plan;
    }

    internal static BundleSourcePlan CreateSmallMaps(YooAssetManifest current,string version,IReadOnlyList<string> paths,CancellationToken token)
    {
        var plan=CreateCore(current,version,null,paths,token,"MainPackage");
        // Keep existing Core source capacity; Python's 64 MiB family does not
        // authorize widening the Core shared download/decode budgets.
        if(plan.Entries.Count is <1 or >4||plan.Entries.Sum(e=>e.Spec.Size)>32L*1024*1024)
            throw new BundleSourceException(BundleSourceFailure.Budget,"Small map closure exceeds current Core quota");
        return plan;
    }

    // Explicit disk-backed phase plan, never the existing owned-byte download path.
    internal static BundleSourcePlan CreateStagedSmallMaps(YooAssetManifest current,string version,IReadOnlyList<string> paths,CancellationToken token)
    {
        var plan=CreateCore(current,version,null,paths,token,"MainPackage");
        if(plan.Entries.Count is <1 or >4||plan.Entries.Sum(e=>e.Spec.Size)>64L*1024*1024)
            throw new BundleSourceException(BundleSourceFailure.Budget,"Staged small map closure exceeds disk-source quota");
        return plan;
    }

    private static BundleSourcePlan CreateCore(YooAssetManifest current, string dataVersion,
        YooAssetManifest? previous, IReadOnlyList<string> assetPaths, CancellationToken cancellationToken, string package = "DataPackage")
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (current.Header.PackageName != package || (previous is not null && previous.Header.PackageName != current.Header.PackageName))
            throw new BundleSourceException(BundleSourceFailure.ManifestIdentity, "Asset plan package mismatch");
        var roots = new HashSet<int>();
        foreach (string path in assetPaths)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (!current.AssetBundles.TryGetValue(path, out int bundleId))
                throw new BundleSourceException(BundleSourceFailure.MissingRequiredAsset, "Required exact AssetPath is absent from DataPackage");
            roots.Add(bundleId);
        }
        // YooAsset DependIDs are engine-produced COMPLETE sets, not graph edges. Do not recurse.
        // In particular cycles are legitimate, and traversing dependency dependencies adds unrelated data.
        var dependencies = new HashSet<int>();
        foreach (int root in roots)
            foreach (int dependency in current.Bundles[root].DependencyIds)
            { cancellationToken.ThrowIfCancellationRequested(); dependencies.Add(dependency); }
        var ordered = dependencies.Except(roots).OrderBy(id => current.Bundles[id].Name, StringComparer.Ordinal)
            .Concat(roots.OrderBy(id => current.Bundles[id].Name, StringComparer.Ordinal));
        var old = previous?.Bundles.ToDictionary(x => x.Name, StringComparer.Ordinal) ?? new Dictionary<string, YooBundleEntry>(StringComparer.Ordinal);
        var changes = new Dictionary<string, BundleChange>(StringComparer.Ordinal);
        int added = 0, modified = 0;
        foreach (var bundle in current.Bundles)
        {
            cancellationToken.ThrowIfCancellationRequested();
            BundleChange change = previous is null ? BundleChange.FirstBaseline : !old.TryGetValue(bundle.Name, out var prior) ? BundleChange.Added :
                SameFingerprint(bundle, current, prior, previous) ? BundleChange.Unchanged : BundleChange.Modified;
            changes.Add(bundle.Name, change);
            if (change == BundleChange.Added) added++;
            if (change == BundleChange.Modified) modified++;
        }
        var names = changes.Keys.ToHashSet(StringComparer.Ordinal);
        int removed = old.Keys.Count(name => !names.Contains(name));
        var entries = new List<PlannedBundleSource>();
        foreach (int id in ordered)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var bundle = current.Bundles[id];
            entries.Add(new(new(dataVersion, current, bundle), changes[bundle.Name],
                Array.AsReadOnly(bundle.DependencyIds.Select(dep => current.Bundles[dep].Name).ToArray())));
        }
        var assetSources = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (string path in assetPaths)
        {
            cancellationToken.ThrowIfCancellationRequested();
            int root = current.AssetBundles[path];
            string[] namesForAsset = current.Bundles[root].DependencyIds.Distinct().Where(id => id != root)
                .Select(id => current.Bundles[id].Name).Order(StringComparer.Ordinal)
                .Append(current.Bundles[root].Name).ToArray();
            assetSources.Add(path, Array.AsReadOnly(namesForAsset));
        }
        return new(entries, assetSources, added, modified, removed);
    }

    private static bool SameFingerprint(YooBundleEntry a, YooAssetManifest current, YooBundleEntry b, YooAssetManifest previous) =>
        a.FileHash == b.FileHash && a.FileCrc == b.FileCrc && a.FileSize == b.FileSize && a.UnityCrc == b.UnityCrc &&
        a.Encrypted == b.Encrypted && a.Tags.SequenceEqual(b.Tags) &&
        a.DependencyIds.Select(id => current.Bundles[id].Name).SequenceEqual(b.DependencyIds.Select(id => previous.Bundles[id].Name));
}
