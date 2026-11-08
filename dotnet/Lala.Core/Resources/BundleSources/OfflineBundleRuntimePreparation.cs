using System.Collections.Immutable;
using Lala.Core.Catalogs;

namespace Lala.Core.Resources;

/// <summary>Historical structural result from untrusted source observations. No official origin,
/// database admission or runtime installation is established by checksums or reobservation.</summary>
internal sealed class OfflinePreparedRuntimeCandidate
{
    internal OfflineRuntimeCandidate Candidate { get; }
    internal ManifestIdentity Identity { get; }
    internal ResourceInventoryInput InventoryInput { get; }
    internal RequiredBundleSources RecheckContext { get; }
    internal string ManifestContentIdentity { get; }
    internal long Attempt { get; }
    internal int DownloadCount { get; }
    internal long DownloadBytes { get; }
    internal ImmutableArray<string> ExtractedTables { get; }
    internal string SourceStability => "observed versions and manifest bytes reobserved after decoding";
    internal string OfficialProvenance => "unavailable";
    internal string DatabaseAdmission => "unavailable";
    internal string RuntimeInstallation => "unavailable";
    internal string Static1275Admission => "unavailable";
    internal OfflinePreparedRuntimeCandidate(OfflineRuntimeCandidate candidate, RequiredBundleSources sources,
        ResourceInventoryInput inventory, ManifestIdentity identity)
    {
        RecheckContext = sources;
        Identity = identity; InventoryInput = inventory;
        Candidate = candidate; ManifestContentIdentity = sources.ManifestContentIdentity; Attempt = sources.Attempt;
        DownloadCount = sources.DownloadCount; DownloadBytes = sources.DownloadBytes;
        ExtractedTables = OfflineRuntimeCandidateDecoder.Sources;
    }
}

/// <summary>Uninstalled composition of source preparation, native bounded extraction and all ten
/// required table decoders. No injected parser/decompressor, filesystem, HTTP implementation or
/// callback can replace those checks. The internal source seam cannot grant authority.</summary>
internal sealed class OfflineBundleRuntimePreparation
{
    // Conservative aggregate ownership bound in addition to the existing 16 MiB per-table limit.
    // This may reject source-valid unusually large catalogs; it does not relax any parser limit.
    internal const long MaximumExtractedTableBytes = 32L * 1024 * 1024;
    private readonly BundleSourcePreparation _preparation = new();
    internal void Invalidate() => _preparation.Invalidate();
    internal Task ConfirmUnchangedAsync(IResourceSource source, OfflinePreparedRuntimeCandidate prepared, CancellationToken token)
        => _preparation.ConfirmUnchangedAsync(source, prepared.RecheckContext, token);

    internal async Task<OfflinePreparedRuntimeCandidate> PrepareAsync(IResourceSource source,
        IBundleSourceCacheReader? cache = null, BundleSourceBudget? budget = null,
        string host = OfficialResourceOrigin.DefaultHost, YooAssetManifest? previous = null,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var prepared = await _preparation.PrepareAsync(source, cache, budget, host, previous, cancellationToken).ConfigureAwait(false);
        _preparation.EnsureCurrent(prepared, cancellationToken);
        var handles = prepared.Sources.ToDictionary(handle => handle.Spec.Name, StringComparer.Ordinal);
        var tables = new Dictionary<string, ReadOnlyMemory<byte>>(StringComparer.Ordinal);
        long extractedBytes = 0;
        foreach (string name in OfflineRuntimeCandidateDecoder.Sources)
        {
            _preparation.EnsureCurrent(prepared, cancellationToken);
            string path = "Assets/ResourcesBuild/Data/" + name + ".bytes";
            // Use only this exact asset's real manifest-selected root + complete dependency set.
            // Passing the union of all ten roots would invent relationships and change duplicates.
            var selected = prepared.Plan.AssetSourceNames[path].Select(bundle => handles[bundle]).ToArray();
            byte[] raw = UnityTextAssetExtractor.Extract(path, selected, cancellationToken: cancellationToken);
            _preparation.EnsureCurrent(prepared, cancellationToken);
            extractedBytes = checked(extractedBytes + raw.Length);
            if (extractedBytes > MaximumExtractedTableBytes)
                throw new BundleSourceException(BundleSourceFailure.Budget, "Extracted required tables exceed owned-byte bound");
            tables.Add(name, raw);
        }
        _preparation.EnsureCurrent(prepared, cancellationToken);
        string packageVersion = prepared.Snapshot.Packages["DataPackage"];
        var candidate = OfflineRuntimeCandidateDecoder.Decode(tables, packageVersion, cancellationToken);
        var identity = ManifestIdentity.FromParsed(prepared.Snapshot, prepared.Manifests, cancellationToken);
        // Persist precisely the native-extracted arrays, not reserialized decoded rows or
        // caller-provided hashes. Capture detaches every payload under the original limits.
        var inventory = ResourceInventoryInput.Capture(identity.Key, OfflineRuntimeCandidateDecoder.Sources
            .Select(name => new ResourceInventoryMember("tables/" + name + ".bytes", tables[name])).ToArray(),
            identity, cancellationToken);
        foreach (var table in inventory.Tables)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (candidate.SourceSha256[table.Name[..^6]] != table.Sha256)
                throw new ResourceValidationException("Decoded runtime differs from the owned extracted inventory");
        }
        // No readiness, provenance, active state, persisted receipt or partial result is published.
        _preparation.EnsureCurrent(prepared, cancellationToken);
        await _preparation.ConfirmUnchangedAsync(source, prepared, cancellationToken).ConfigureAwait(false);
        return _preparation.ReturnCurrent(prepared, new OfflinePreparedRuntimeCandidate(candidate, prepared, inventory, identity), cancellationToken);
    }
}
