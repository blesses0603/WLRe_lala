using System.Collections.Frozen;
using System.Text.Json;

namespace Lala.Core.Resources;

public sealed class OfficialSnapshotComparison
{
    public bool? DataVersionChanged { get; }
    public bool? ExeVersionChanged { get; }
    public IReadOnlyDictionary<string, string> PackageChanges { get; }
    public string ResourceInstallation => "not_implemented";
    public bool CanStartAssetDependentFeatures => false;
    internal OfficialSnapshotComparison(bool? data, bool? exe, Dictionary<string, string> changes)
    { DataVersionChanged = data; ExeVersionChanged = exe; PackageChanges = changes.ToFrozenDictionary(StringComparer.Ordinal); }
}

/// <summary>Validated metadata only. Origin text is not proof of a fetch, freshness or installed assets.</summary>
public sealed class OfficialVersionSnapshot
{
    public const int MaximumBytes = 4096;
    public string DataVersion { get; }
    public string ExeVersion { get; }
    public IReadOnlyDictionary<string, string> Packages { get; }
    public string CheckedAtUtc { get; }
    public bool AssetsReady => false;
    private OfficialVersionSnapshot(string data, string exe, Dictionary<string, string> packages, string checkedAt)
    { DataVersion = data; ExeVersion = exe; Packages = packages.ToFrozenDictionary(StringComparer.Ordinal); CheckedAtUtc = checkedAt; }

    public static OfficialVersionSnapshot Parse(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        using var doc = ResourceValidation.Parse(raw, MaximumBytes, cancellationToken: cancellationToken);
        return Parse(doc.RootElement);
    }
    internal static OfficialVersionSnapshot Parse(JsonElement value)
    {
        string? data = ResourceValidation.String(value, "data_ver"), exe = ResourceValidation.String(value, "exe_version"), checkedAt = ResourceValidation.String(value, "checked_at_utc");
        var packages = ResourceValidation.Property(value, "packages");
        if (!ResourceValidation.HasKeys(value, "schema_version", "origin", "data_ver", "exe_version", "packages", "checked_at_utc", "assets_ready") ||
            !ResourceValidation.One(ResourceValidation.Property(value, "schema_version")) ||
            ResourceValidation.String(value, "origin") != "official_pc_version_endpoint" ||
            data is null || !ResourceValidation.DataVersion.IsMatch(data) || exe is null || !ResourceValidation.GameVersion.IsMatch(exe) ||
            !ResourceValidation.HasKeys(packages, ResourceValidation.Packages) ||
            ResourceValidation.Property(value, "assets_ready").ValueKind != JsonValueKind.False || checkedAt is null || ResourceValidation.TextLength(checkedAt) > 40)
            throw new ResourceValidationException("Invalid official version metadata");
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string name in ResourceValidation.Packages)
        {
            string? revision = ResourceValidation.String(packages, name);
            if (revision is null || !ResourceValidation.Manifest.IsMatch(revision))
                throw new ResourceValidationException("Invalid official package version metadata");
            result.Add(name, revision);
        }
        return new(data, exe, result, checkedAt);
    }

    public OfficialSnapshotComparison Compare(OfficialVersionSnapshot? previous = null) => new(
        previous is null ? null : DataVersion != previous.DataVersion,
        previous is null ? null : ExeVersion != previous.ExeVersion,
        ResourceValidation.Packages.ToDictionary(name => name,
            name => previous is null ? "first_observation" : Packages[name] == previous.Packages[name] ? "unchanged" : "changed", StringComparer.Ordinal));

    /// <summary>Identity stability only, equivalent to runtime before/after version checks. Does not infer a timestamp TTL.</summary>
    public bool HasSameIdentity(OfficialVersionSnapshot other)
    {
        ArgumentNullException.ThrowIfNull(other);
        return DataVersion == other.DataVersion && ExeVersion == other.ExeVersion && ResourceValidation.Packages.All(name => Packages[name] == other.Packages[name]);
    }
}
