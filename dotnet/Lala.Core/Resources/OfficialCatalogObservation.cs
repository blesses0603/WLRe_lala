using System.Collections.Frozen;
using System.Text;
using System.Text.Json;

namespace Lala.Core.Resources;

/// <summary>Pure identity selection from catalog_runtime.py. Never an approval token.</summary>
public sealed record CatalogSelectionDecision(string? CatalogKey, string Status, string Reason)
{
    public IReadOnlyList<string> VerifiedFeatures => Array.Empty<string>();
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
}

/// <summary>
/// Observed identity, not authenticated origin. Retains Python's nonempty string rules rather than
/// guessing a revision format. The stricter persisted snapshot schema is OfficialVersionSnapshot.
/// </summary>
public sealed class OfficialCatalogObservation
{
    public const int MaximumBytes = ResourceValidation.MaximumMetadataBytes;
    public string DataVersion { get; }
    public string ExeVersion { get; }
    public bool NewerOfficialClient { get; }
    public IReadOnlyDictionary<string, string> Packages { get; }
    public string CatalogKey { get; }
    private OfficialCatalogObservation(string data, string exe, bool newer, Dictionary<string, string> packages, CancellationToken cancellationToken)
    {
        DataVersion = data; ExeVersion = exe; NewerOfficialClient = newer;
        Packages = packages.ToFrozenDictionary(StringComparer.Ordinal);
        string identity = "{\"data_ver\":" + ResourceValidation.Quote(data) + ",\"exe_version\":" + ResourceValidation.Quote(exe) +
            ",\"packages\":{\"DataPackage\":" + ResourceValidation.Quote(packages["DataPackage"]) +
            ",\"MainPackage\":" + ResourceValidation.Quote(packages["MainPackage"]) + "}}";
        CatalogKey = ResourceValidation.Digest(Encoding.ASCII.GetBytes(identity), cancellationToken);
    }
    public static OfficialCatalogObservation Parse(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        using var doc = ResourceValidation.Parse(raw, MaximumBytes, cancellationToken: cancellationToken);
        return Parse(doc.RootElement, cancellationToken);
    }
    internal static OfficialCatalogObservation Parse(JsonElement remote, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var newer = ResourceValidation.Property(remote, "newer_official_client");
        if (!ResourceValidation.IsObject(remote) || newer.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            throw new ResourceValidationException("Official client identity is not verified");
        var packages = ResourceValidation.Property(remote, "packages");
        if (!ResourceValidation.HasKeys(packages, ResourceValidation.Packages))
            throw new ResourceValidationException("Missing or unexpected official package");
        var versions = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string name in ResourceValidation.Packages)
        {
            var row = packages.GetProperty(name);
            string? revision = ResourceValidation.String(row, "remote");
            if (!ResourceValidation.IsObject(row) || string.IsNullOrEmpty(revision) || ResourceValidation.TextLength(revision) > 100)
                throw new ResourceValidationException("Invalid official package revision");
            versions.Add(name, revision);
        }
        string? data = ResourceValidation.String(remote, "resource_path"), exe = ResourceValidation.String(remote, "official_exe_version");
        if (string.IsNullOrEmpty(data) || string.IsNullOrEmpty(exe))
            throw new ResourceValidationException("Missing official client identifiers");
        return new(data, exe, newer.GetBoolean(), versions, cancellationToken);
    }
    public static CatalogSelectionDecision Select(ReadOnlySpan<byte> raw, IReadOnlyDictionary<string, string>? packageVersions = null, CancellationToken cancellationToken = default)
    {
        try
        {
            var observation = Parse(raw, cancellationToken);
            if (packageVersions is not null && (packageVersions.Count != 2 ||
                ResourceValidation.Packages.Any(name => !packageVersions.TryGetValue(name, out string? version) || version != observation.Packages[name])))
                return new(null, "blocked", "official_package_pair_mismatch");
            cancellationToken.ThrowIfCancellationRequested();
            return new(observation.CatalogKey, "verification_required", "source_validation_required");
        }
        catch (ResourceValidationException) { return new(null, "blocked", "invalid_official_identity"); }
    }
}

public sealed record CatalogSourceMetadata(string SourceName, string SchemaId, string Sha256, int RecordCount);

/// <summary>
/// Display-only metadata checks from active_official_catalog/load_dynamic_runtime_metadata.
/// A syntactically valid digest/count is not a verified payload. No input can set readiness or packet permission.
/// </summary>
public sealed class CatalogMetadataView
{
    public const int MaximumBytes = ResourceValidation.MaximumMetadataBytes;
    public string CatalogKey { get; }
    public IReadOnlyDictionary<string, string> PackageVersions { get; }
    public IReadOnlyDictionary<string, CatalogSourceMetadata> Sources { get; }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
    private CatalogMetadataView(OfficialCatalogObservation observation, Dictionary<string, CatalogSourceMetadata> sources)
    { CatalogKey = observation.CatalogKey; PackageVersions = observation.Packages; Sources = sources.ToFrozenDictionary(StringComparer.Ordinal); }

    // Input is the metadata projection, not SQLite or parsed game records. No persistence here.
    public static CatalogMetadataView Inspect(OfficialCatalogObservation observation, ReadOnlySpan<byte> metadata, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(observation);
        using var doc = ResourceValidation.Parse(metadata, MaximumBytes, cancellationToken: cancellationToken);
        var root = doc.RootElement;
        if (!ResourceValidation.IsObject(root) || ResourceValidation.String(root, "catalog_key") != observation.CatalogKey)
            throw new ResourceValidationException("Current-version catalog metadata unavailable");
        var sources = ResourceValidation.Property(root, "sources");
        if (!ResourceValidation.HasKeys(sources, ResourceValidation.Features))
            throw new ResourceValidationException("Official source set incomplete");
        var result = new Dictionary<string, CatalogSourceMetadata>(StringComparer.Ordinal);
        foreach (string feature in ResourceValidation.Features)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var row = sources.GetProperty(feature);
            string? source = ResourceValidation.String(row, "source_name"), schema = ResourceValidation.String(row, "schema_id"), digest = ResourceValidation.String(row, "sha256");
            if (string.IsNullOrEmpty(source) || ResourceValidation.TextLength(source) > 120 || string.IsNullOrEmpty(schema) ||
                digest is null || !ResourceValidation.Sha256.IsMatch(digest) ||
                !ResourceValidation.Integer(ResourceValidation.Property(row, "record_count"), out int count) || count is < 0 or > 20000)
                throw new ResourceValidationException("Invalid official source metadata");
            result.Add(feature, new(source, schema, digest, count));
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(observation, result);
    }
}
