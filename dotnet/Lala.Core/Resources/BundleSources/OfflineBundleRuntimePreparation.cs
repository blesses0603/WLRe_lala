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
    // Immutable references to private verified snapshots, never cache paths or source buffers.
    // Failed optional decodes do not retain extra bundles solely for cache population.
    internal ImmutableArray<VerifiedBundleSource> VerifiedSources { get; }
    internal string SourceStability => "observed versions and manifest bytes reobserved after decoding";
    internal string OfficialProvenance => "unavailable";
    internal string DatabaseAdmission => "unavailable";
    internal string RuntimeInstallation => "unavailable";
    internal string Static1275Admission => "unavailable";
    internal OfflinePreparedRuntimeCandidate(OfflineRuntimeCandidate candidate, RequiredBundleSources sources,
        ResourceInventoryInput inventory, ManifestIdentity identity, BundleDownloadTotals? downloads = null,
        IEnumerable<VerifiedBundleSource>? verifiedSources = null)
    {
        RecheckContext = sources;
        Identity = identity; InventoryInput = inventory;
        Candidate = candidate; ManifestContentIdentity = sources.ManifestContentIdentity; Attempt = sources.Attempt;
        DownloadCount = downloads?.Count ?? sources.DownloadCount; DownloadBytes = downloads?.Bytes ?? sources.DownloadBytes;
        ExtractedTables = inventory.Tables.Select(table => table.Name[..^6]).ToImmutableArray();
        VerifiedSources = (verifiedSources ?? sources.Sources).ToImmutableArray();
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
        var downloads = new BundleDownloadTotals(prepared.DownloadCount, prepared.DownloadBytes);
        // Optional acquisition/decoding failures leave required preparation intact. It uses
        // the same manifest/attempt and remaining quota; unknown digests never become rows.
        if (prepared.Manifests[0].AssetBundles.ContainsKey(BundleSourcePlan.SkillAssetPath))
        {
            try
            {
                var skillSources = await _preparation.PrepareSkillAsync(source, prepared, cache, budget, downloads, cancellationToken).ConfigureAwait(false);
                byte[] skillRaw = UnityTextAssetExtractor.Extract(BundleSourcePlan.SkillAssetPath, skillSources,
                    cancellationToken: cancellationToken);
                if (skillRaw.Length > SkillDataParser.MaxBytes || extractedBytes + skillRaw.Length > MaximumExtractedTableBytes)
                    throw new CatalogDecodeException("Optional skill payload exceeds retained table budget");
                candidate = candidate.WithOptionalSkills(skillRaw, cancellationToken);
                tables.Add("SkillData_C", skillRaw);
                extractedBytes += skillRaw.Length;
                foreach (var handle in skillSources) handles.TryAdd(handle.Spec.Name, handle);
            }
            catch (Exception error) when (IsOptionalFailure(error))
            {
                // No optional row is persisted or exposed. Cancellation, stale attempt and
                // final source drift are still checked outside this optional failure boundary.
            }
            _preparation.EnsureCurrent(prepared, cancellationToken);
        }
        if (prepared.Manifests[0].AssetBundles.ContainsKey(BundleSourcePlan.DungeonAssetPath) &&
            prepared.Manifests[0].AssetBundles.ContainsKey(BundleSourcePlan.CooperativeAssetPath))
        {
            try
            {
                var instanceSources = await _preparation.PrepareInstancesAsync(source, prepared, cache, budget, downloads, cancellationToken).ConfigureAwait(false);
                byte[] dungeonRaw = UnityTextAssetExtractor.Extract(BundleSourcePlan.DungeonAssetPath,
                    instanceSources[BundleSourcePlan.DungeonAssetPath], cancellationToken: cancellationToken);
                byte[] cooperativeRaw = UnityTextAssetExtractor.Extract(BundleSourcePlan.CooperativeAssetPath,
                    instanceSources[BundleSourcePlan.CooperativeAssetPath], cancellationToken: cancellationToken);
                if (extractedBytes + dungeonRaw.Length + cooperativeRaw.Length > MaximumExtractedTableBytes)
                    throw new CatalogDecodeException("Optional instance payloads exceed retained table budget");
                candidate = candidate.WithOptionalInstances(dungeonRaw, cooperativeRaw, cancellationToken);
                tables.Add("DungeonData_C", dungeonRaw);
                tables.Add("CooperateEventData_C", cooperativeRaw);
                extractedBytes += dungeonRaw.Length + cooperativeRaw.Length;
                foreach (var handle in instanceSources.Values.SelectMany(group => group))
                    handles.TryAdd(handle.Spec.Name, handle);
            }
            catch (Exception error) when (IsOptionalFailure(error)) { }
            _preparation.EnsureCurrent(prepared, cancellationToken);
        }
        if (prepared.Manifests[0].AssetBundles.ContainsKey(BundleSourcePlan.DailyTaskAssetPath) &&
            prepared.Manifests[0].AssetBundles.ContainsKey(BundleSourcePlan.DailyRewardAssetPath))
        {
            try
            {
                var dailySources = await _preparation.PrepareDailyAsync(source, prepared, cache, budget, downloads, cancellationToken).ConfigureAwait(false);
                byte[] taskRaw = UnityTextAssetExtractor.Extract(BundleSourcePlan.DailyTaskAssetPath,
                    dailySources[BundleSourcePlan.DailyTaskAssetPath], cancellationToken: cancellationToken);
                byte[] rewardRaw = UnityTextAssetExtractor.Extract(BundleSourcePlan.DailyRewardAssetPath,
                    dailySources[BundleSourcePlan.DailyRewardAssetPath], cancellationToken: cancellationToken);
                if (taskRaw.Length > DailyTaskDataParser.MaxTaskBytes || rewardRaw.Length > DailyTaskDataParser.MaxRewardBytes ||
                    extractedBytes + taskRaw.Length + rewardRaw.Length > MaximumExtractedTableBytes)
                    throw new CatalogDecodeException("Optional daily payloads exceed retained table budget");
                candidate = candidate.WithOptionalDailyCatalog(taskRaw, rewardRaw, cancellationToken);
                // The two tables are a single feature: no partial pair or cross-reference
                // failure enters inventory input or an exposed catalog.
                tables.Add("DailyTaskData_C", taskRaw);
                tables.Add("DailyTaskRewardData_C", rewardRaw);
                extractedBytes += taskRaw.Length + rewardRaw.Length;
                foreach (var handle in dailySources.Values.SelectMany(group => group))
                    handles.TryAdd(handle.Spec.Name, handle);
            }
            catch (Exception error) when (IsOptionalFailure(error)) { }
            _preparation.EnsureCurrent(prepared, cancellationToken);
        }
        var identity = ManifestIdentity.FromParsed(prepared.Snapshot, prepared.Manifests, cancellationToken);
        // Persist precisely the native-extracted arrays, not reserialized decoded rows or
        // caller-provided hashes. Capture detaches every payload under the original limits.
        var inventory = ResourceInventoryInput.Capture(identity.Key, tables.Keys
            .Select(name => new ResourceInventoryMember("tables/" + name + ".bytes", tables[name])).ToArray(),
            identity, cancellationToken);
        foreach (var table in inventory.Tables)
        {
            cancellationToken.ThrowIfCancellationRequested();
            string expected = table.Name switch
            {
                "SkillData_C.bytes" => SkillDataParser.ReviewedSha256,
                "DailyTaskData_C.bytes" or "DailyTaskRewardData_C.bytes" or "DungeonData_C.bytes" or "CooperateEventData_C.bytes" => ResourceValidation.Digest(tables[table.Name[..^6]].Span, cancellationToken),
                _ => candidate.SourceSha256[table.Name[..^6]]
            };
            if (expected != table.Sha256)
                throw new ResourceValidationException("Decoded runtime differs from the owned extracted inventory");
        }
        // No readiness, provenance, active state, persisted receipt or partial result is published.
        _preparation.EnsureCurrent(prepared, cancellationToken);
        await _preparation.ConfirmUnchangedAsync(source, prepared, cancellationToken).ConfigureAwait(false);
        return _preparation.ReturnCurrent(prepared, new OfflinePreparedRuntimeCandidate(candidate, prepared, inventory, identity,
            downloads, handles.Values), cancellationToken);
    }
    private static bool IsOptionalFailure(Exception error) => !error.Data.Contains(ResourceCleanup.FailureMarker) &&
        error is not ResourceTransportException { Failure: ResourceTransportFailure.Cleanup } &&
        error is (BundleSourceException or UnityTextAssetException or CatalogDecodeException or IOException or
            UnauthorizedAccessException or HttpRequestException);

}
