using System.Collections.Frozen;
using System.Text;

namespace Lala.Core.Resources;

public sealed record PackageBaseline(string Revision, string Manifest);
public sealed record PackageCompatibility(string Baseline, string BaselineManifest, string? Remote, string Comparison);

/// <summary>Comparison only, not source integrity, runtime readiness, login or packet permission.</summary>
public sealed class ResourceCompatibilityResult
{
    public string Status { get; }
    public IReadOnlyDictionary<string, PackageCompatibility> Packages { get; }
    public string ProtocolCompatibility => "unverified";
    public bool ReadOnly => true;
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    internal ResourceCompatibilityResult(string status, Dictionary<string, PackageCompatibility> packages)
    { Status = status; Packages = packages.ToFrozenDictionary(StringComparer.Ordinal); }
}

/// <summary>Release-owned resource policy from configuration.py. Network observations cannot replace it.</summary>
public sealed class ResourceCompatibility
{
    public const int MaximumBaselineBytes = 4096;
    public string OfficialGameExeVersion { get; }
    public IReadOnlyDictionary<string, PackageBaseline> Packages { get; }
    public string Label => Packages["DataPackage"].Revision == Packages["MainPackage"].Revision
        ? Packages["DataPackage"].Revision
        : "DataPackage " + Packages["DataPackage"].Revision + "／MainPackage " + Packages["MainPackage"].Revision;

    public static ResourceCompatibility Shipped { get; } = ParseBaseline(Encoding.UTF8.GetBytes("""
        {"schema_version":1,"official_game_exe_version":"1.3.0","packages":{
        "DataPackage":{"revision":"1275","manifest":"1275_2026_10_21_18_27_33_84"},
        "MainPackage":{"revision":"1275","manifest":"1275_2026_10_21_18_29_38_49"}}}
        """));

    private ResourceCompatibility(string exeVersion, Dictionary<string, PackageBaseline> packages)
    { OfficialGameExeVersion = exeVersion; Packages = packages.ToFrozenDictionary(StringComparer.Ordinal); }

    // Test-only baseline injection, matching Python's optional offline path. No production policy setter.
    internal static ResourceCompatibility ParseBaseline(ReadOnlySpan<byte> raw)
    {
        using var document = ResourceValidation.Parse(raw, MaximumBaselineBytes, allowBom: true);
        var root = document.RootElement;
        string? exe = ResourceValidation.String(root, "official_game_exe_version");
        if (!ResourceValidation.HasKeys(root, "schema_version", "official_game_exe_version", "packages") ||
            !ResourceValidation.One(ResourceValidation.Property(root, "schema_version")) || exe is null || !ResourceValidation.GameVersion.IsMatch(exe))
            throw new ResourceValidationException("Invalid release-owned resource baseline");
        var packages = ResourceValidation.Property(root, "packages");
        if (!ResourceValidation.HasKeys(packages, ResourceValidation.Packages))
            throw new ResourceValidationException("Incomplete baseline package set");
        var result = new Dictionary<string, PackageBaseline>(StringComparer.Ordinal);
        foreach (string name in ResourceValidation.Packages)
        {
            var entry = packages.GetProperty(name);
            string? revision = ResourceValidation.String(entry, "revision"), manifest = ResourceValidation.String(entry, "manifest");
            if (!ResourceValidation.HasKeys(entry, "revision", "manifest") || revision is null || manifest is null ||
                !ResourceValidation.Revision.IsMatch(revision) || !ResourceValidation.Manifest.IsMatch(manifest) ||
                ResourceValidation.Manifest.Match(manifest).Groups[1].Value != revision)
                throw new ResourceValidationException("Invalid baseline package revision or Manifest identity");
            result.Add(name, new(revision, manifest));
        }
        return new(exe, result);
    }

    /// <summary>Strict full-Manifest comparison from check_official_versions, with no fetch or fallback.</summary>
    public ResourceCompatibilityResult Compare(IReadOnlyDictionary<string, string?>? observedVersions)
    {
        var result = new Dictionary<string, PackageCompatibility>(StringComparer.Ordinal);
        foreach (string name in ResourceValidation.Packages)
        {
            PackageBaseline baseline = Packages[name];
            string? remote = observedVersions is not null && observedVersions.TryGetValue(name, out string? value) ? value : null;
            string comparison = remote is null ? "unverified" : ResourceValidation.CompareRevision(baseline.Revision, remote);
            if (remote == baseline.Manifest) comparison = "same";
            else if (remote == baseline.Revision) comparison = "unverified";
            else if (comparison == "same") comparison = "different";
            result.Add(name, new(baseline.Revision, baseline.Manifest, remote, comparison));
        }
        string[] states = result.Values.Select(p => p.Comparison).ToArray();
        return new(states.Contains("unverified") ? "unverified" : states.All(s => s == "same") ? "same_resources" : "resources_changed", result);
    }
}
