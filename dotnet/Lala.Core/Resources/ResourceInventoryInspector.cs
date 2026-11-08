using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Resources;

public enum ResourceInventoryInspectionStatus { Missing, SelfConsistent, Invalid, Unavailable }

/// <summary>Historical local consistency only, not official provenance, current-source equality,
/// parser compatibility, runtime admission or proof of an earlier uncertain COMMIT.</summary>
public sealed record ResourceInventoryInspection(ResourceInventoryInspectionStatus Status,
    string? CatalogIdentity, string? DataVersion, string? ExeVersion, int RequiredTables, long RequiredTableBytes)
{
    public bool HasVerifiedProvenance => false;
    public bool RuntimeAdmitted => false;
    public bool CanLogin => false;
    public bool CanSendPackets => false;
}

/// <summary>Read-only local recovery diagnostics. No source acquisition, database repair,
/// retry or runtime/account mutation. A caller may explicitly inspect after an uncertain write,
/// but must still use fresh-source preparation before admitting any resource runtime.</summary>
public static class ResourceInventoryInspector
{
    public static async Task<ResourceInventoryInspection> InspectAsync(string absoluteDataRoot,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(absoluteDataRoot);
        if (!Path.IsPathFullyQualified(absoluteDataRoot))
            throw new ArgumentException("An absolute data root is required", nameof(absoluteDataRoot));
        string path = Path.Combine(Path.GetFullPath(absoluteDataRoot), "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        cancellationToken.ThrowIfCancellationRequested();
        try
        {
            if ((File.GetAttributes(path) & FileAttributes.Directory) != 0) return Empty(ResourceInventoryInspectionStatus.Invalid);
            var connection = new SqliteConnection(new SqliteConnectionStringBuilder
            {
                DataSource = path, Mode = SqliteOpenMode.ReadOnly, Cache = SqliteCacheMode.Private,
                Pooling = false, DefaultTimeout = RuntimeDatabaseSnapshotReader.CommandTimeoutSeconds
            }.ToString());
            // Reader owns connection disposal, transaction rollback and all command/read cleanup.
            var observation = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, cancellationToken,
                OfflineBundleRuntimePreparation.MaximumExtractedTableBytes).ConfigureAwait(false);
            return InspectSnapshot(observation.Snapshot, cancellationToken);
        }
        catch (Exception error) when (ClassifyFailure(error) is { } status) { return Empty(status); }
    }

    internal static ResourceInventoryInspectionStatus? ClassifyFailure(Exception error)
    {
        ArgumentNullException.ThrowIfNull(error);
        // Cancellation keeps the reader's original exception/attached cleanup evidence.
        if (error is OperationCanceledException) return null;
        if (error.Data[RuntimeDatabaseSnapshotReader.CleanupFailuresKey] is IEnumerable<Exception> cleanup && cleanup.Any())
            return ResourceInventoryInspectionStatus.Unavailable;
        return error switch
        {
            FileNotFoundException or DirectoryNotFoundException => ResourceInventoryInspectionStatus.Missing,
            InvalidDataException or ResourceValidationException or JsonException or OverflowException => ResourceInventoryInspectionStatus.Invalid,
            SqliteException sqlite when sqlite.SqliteErrorCode is 1 or 11 or 26 => ResourceInventoryInspectionStatus.Invalid,
            IOException or UnauthorizedAccessException or SqliteException or AggregateException => ResourceInventoryInspectionStatus.Unavailable,
            _ => null
        };
    }

    private static ResourceInventoryInspection InspectSnapshot(OwnedRuntimeDatabaseSnapshot snapshot, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var active = snapshot.Active;
        if (active is null || active.VersionId <= 0 || active.CatalogKey is not { } key ||
            !ResourceValidation.Sha256.IsMatch(key) || active.IdentityJson is not { } json || json.Any(c => c > 127) ||
            ResourceValidation.Digest(Encoding.ASCII.GetBytes(json), token) != key) throw Invalid();
        using var document = ResourceValidation.Parse(Encoding.ASCII.GetBytes(json),
            OwnedRuntimeDatabaseSnapshot.MaximumIdentityCharacters, cancellationToken: token);
        var identity = document.RootElement;
        if (!ExactKeys(identity, "data_ver", "exe_version", "packages", "schema_version") ||
            !ResourceValidation.One(ResourceValidation.Property(identity, "schema_version"))) throw Invalid();
        string? data = ResourceValidation.String(identity, "data_ver"), exe = ResourceValidation.String(identity, "exe_version");
        if (data is null || !ResourceValidation.DataVersion.IsMatch(data) || exe is null || !ResourceValidation.GameVersion.IsMatch(exe)) throw Invalid();
        var packages = ResourceValidation.Property(identity, "packages");
        if (packages.ValueKind != JsonValueKind.Array || packages.GetArrayLength() != ResourceValidation.Packages.Length) throw Invalid();
        var canonicalPackages = new List<string>();
        int index = 0;
        foreach (var package in packages.EnumerateArray())
        {
            token.ThrowIfCancellationRequested();
            if (!ExactKeys(package, "full_version", "manifest_crc32_le", "manifest_sha256", "name")) throw Invalid();
            string? name = ResourceValidation.String(package, "name"), version = ResourceValidation.String(package, "full_version"),
                crc = ResourceValidation.String(package, "manifest_crc32_le"), sha = ResourceValidation.String(package, "manifest_sha256");
            if (name is null || name != ResourceValidation.Packages[index++] || version is null || !ResourceValidation.Manifest.IsMatch(version) ||
                sha is null || !ResourceValidation.Sha256.IsMatch(sha) || crc is null || crc.Length != 8 ||
                crc.Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f'))) throw Invalid();
            canonicalPackages.Add("{\"full_version\":" + ResourceValidation.Quote(version) + ",\"manifest_crc32_le\":" + ResourceValidation.Quote(crc) +
                ",\"manifest_sha256\":" + ResourceValidation.Quote(sha) + ",\"name\":" + ResourceValidation.Quote(name) + "}");
        }
        string canonical = "{\"data_ver\":" + ResourceValidation.Quote(data) + ",\"exe_version\":" + ResourceValidation.Quote(exe) +
            ",\"packages\":[" + string.Join(',', canonicalPackages) + "],\"schema_version\":1}";
        if (json != canonical) throw Invalid();
        long bytes = 0;
        foreach (string name in BundleSourcePlan.RequiredTables)
        {
            token.ThrowIfCancellationRequested();
            var row = snapshot.Table(active.VersionId, name + ".bytes");
            if (row is null || !row.HasBlob || row.RecordedSha256 is not { } sha || !ResourceValidation.Sha256.IsMatch(sha) ||
                ResourceValidation.Digest(row.Bytes, token) != sha) throw Invalid();
            bytes = checked(bytes + row.ByteLength);
            if (bytes > OfflineBundleRuntimePreparation.MaximumExtractedTableBytes) throw Invalid();
        }
        token.ThrowIfCancellationRequested();
        return new(ResourceInventoryInspectionStatus.SelfConsistent, key, data, exe, BundleSourcePlan.RequiredTables.Count, bytes);
    }

    private static bool ExactKeys(JsonElement value, params string[] keys) => value.ValueKind == JsonValueKind.Object &&
        value.EnumerateObject().Count() == keys.Length && ResourceValidation.HasKeys(value, keys);
    private static InvalidDataException Invalid() => new("Stored inventory is not locally self-consistent");
    private static ResourceInventoryInspection Empty(ResourceInventoryInspectionStatus status) => new(status, null, null, null, 0, 0);
}
