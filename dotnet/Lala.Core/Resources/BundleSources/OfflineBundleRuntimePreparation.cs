using System.Collections.Immutable;
using Lala.Core.Catalogs;

namespace Lala.Core.Resources;

/// <summary>Historical structural result from a scripted in-memory source. No official origin,
/// database admission or runtime installation is established by checksums or reobservation.</summary>
internal sealed class OfflinePreparedRuntimeCandidate
{
    internal OfflineRuntimeCandidate Candidate { get; }
    internal string ManifestContentIdentity { get; }
    internal long Attempt { get; }
    internal int DownloadCount { get; }
    internal long DownloadBytes { get; }
    internal ImmutableArray<string> ExtractedTables { get; }
    internal string SourceStability => "scripted versions and manifest bytes reobserved after decoding";
    internal string OfficialProvenance => "unavailable";
    internal string DatabaseAdmission => "unavailable";
    internal string RuntimeInstallation => "unavailable";
    internal string Static1275Admission => "unavailable";
    internal OfflinePreparedRuntimeCandidate(OfflineRuntimeCandidate candidate, RequiredBundleSources sources)
    {
        Candidate = candidate; ManifestContentIdentity = sources.ManifestContentIdentity; Attempt = sources.Attempt;
        DownloadCount = sources.DownloadCount; DownloadBytes = sources.DownloadBytes;
        ExtractedTables = OfflineRuntimeCandidateDecoder.Sources;
    }
}

/// <summary>Actual offline composition of source preparation, native bounded extraction and all ten
/// required table decoders. No injected parser/decompressor, filesystem, HTTP implementation or
/// callback can replace those checks. The only source implementation is an internal scripted seam.</summary>
internal sealed class OfflineBundleRuntimePreparation
{
    // Conservative aggregate ownership bound in addition to the existing 16 MiB per-table limit.
    // This may reject source-valid unusually large catalogs; it does not relax any parser limit.
    internal const long MaximumExtractedTableBytes = 32L * 1024 * 1024;
    private readonly BundleSourcePreparation _preparation = new();
    internal void Invalidate() => _preparation.Invalidate();

    internal async Task<OfflinePreparedRuntimeCandidate> PrepareAsync(IScriptedResourceSource source,
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
        // No readiness, provenance, active state, persisted receipt or partial result is published.
        _preparation.EnsureCurrent(prepared, cancellationToken);
        await _preparation.ConfirmUnchangedAsync(source, prepared, cancellationToken).ConfigureAwait(false);
        return _preparation.ReturnCurrent(prepared, new OfflinePreparedRuntimeCandidate(candidate, prepared), cancellationToken);
    }
}
