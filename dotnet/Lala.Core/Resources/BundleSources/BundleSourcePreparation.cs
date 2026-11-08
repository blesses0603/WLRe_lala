using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace Lala.Core.Resources;

// Internal acquisition seam. Implementations and checksums establish observations and byte
// integrity, NOT official provenance. No production authority factory or startup registration.
internal interface IResourceSource
{
    // Optional origin binding only, never proof of provenance. Scripts have no bound host.
    string? SelectedHost => null;
    ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken cancellationToken);
    ValueTask<ResourceResponse> OpenAsync(string exactUrl, CancellationToken cancellationToken);
}
internal sealed record ResourceResponse(string FinalUrl, int Status, string? ContentLength, Stream Body) : IDisposable
{
    public void Dispose() => Body.Dispose();
}
// Planned/reserved acquisition totals, including optional attempts that later fail.
internal sealed class BundleDownloadTotals(int count, long bytes)
{
    internal int Count = count;
    internal long Bytes = bytes;
    internal RequiredBundleSources? Context;
    internal Dictionary<string, VerifiedBundleSource> Owned { get; } = new(StringComparer.Ordinal);
}
internal interface IBundleSourceCacheReader
{
    ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken cancellationToken);
}

/// <summary>Owns the exact verified bytes. No path, writeable memory or unchecked reopen escapes.</summary>
internal sealed class VerifiedBundleSource
{
    private readonly byte[] _bytes;
    internal BundleSourceSpec Spec { get; }
    internal string Sha256 { get; }
    internal BundleAcquisition Acquisition { get; }
    private VerifiedBundleSource(BundleSourceSpec spec, byte[] bytes, BundleAcquisition acquisition, CancellationToken token)
    { Spec = spec; _bytes = bytes; Acquisition = acquisition; Sha256 = ResourceValidation.Digest(bytes, token); }
    internal Stream OpenRead() => new MemoryStream(_bytes, 0, _bytes.Length, writable: false, publiclyVisible: false);
    internal static VerifiedBundleSource Verify(BundleSourceSpec spec, ReadOnlySpan<byte> input, BundleAcquisition acquisition,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (input.Length != spec.Size) throw new BundleSourceException(BundleSourceFailure.ResponseLength, "Bundle length differs from manifest");
        byte[] bytes = input.ToArray();
        if (Convert.ToHexStringLower(MD5.HashData(bytes)) != spec.Md5 || ManifestIdentity.Crc32LittleEndian(bytes, cancellationToken) != spec.Crc32Le)
            throw new BundleSourceException(BundleSourceFailure.Checksum, "Bundle MD5 or little-endian CRC32 differs from manifest");
        cancellationToken.ThrowIfCancellationRequested();
        return new(spec, bytes, acquisition, cancellationToken);
    }
}

internal sealed record BundleSourceBudget(int MaximumDownloads = 24, long MaximumDownloadBytes = 32L * 1024 * 1024)
{
    internal void Validate()
    {
        if (MaximumDownloads is < 0 or > 24 || MaximumDownloadBytes is < 0 or > 32L * 1024 * 1024)
            throw new BundleSourceException(BundleSourceFailure.Budget, "Invalid runtime download budget");
    }
}

internal sealed class RequiredBundleSources
{
    internal string Status => "required bundle sources verified; no runtime candidate built";
    internal string Provenance => "source observations; official provenance unavailable";
    internal string ManifestContentIdentity { get; }
    internal long Attempt { get; }
    internal object Owner { get; }
    internal OfficialVersionSnapshot Snapshot { get; }
    internal IReadOnlyList<YooAssetManifest> Manifests { get; }
    internal string Host { get; }
    internal BundleSourcePlan Plan { get; }
    internal IReadOnlyList<VerifiedBundleSource> Sources { get; }
    internal int DownloadCount { get; }
    internal long DownloadBytes { get; }
    internal RequiredBundleSources(string identity, long attempt, BundleSourcePlan plan, List<VerifiedBundleSource> sources, int count, long bytes,
        object owner, OfficialVersionSnapshot snapshot, IReadOnlyList<YooAssetManifest> manifests, string host)
    {
        ManifestContentIdentity = identity; Attempt = attempt; Plan = plan; Sources = sources.AsReadOnly();
        DownloadCount = count; DownloadBytes = bytes; Owner = owner; Snapshot = snapshot;
        Manifests = Array.AsReadOnly(manifests.ToArray()); Host = host;
    }
}

/// <summary>Uninstalled resource preparation. Does not consume or issue resource/session admission.</summary>
internal sealed class BundleSourcePreparation
{
    // Independent fail-closed cap on all owned sources, including cache hits. Download budgets below
    // keep the original runtime 24 / 32 MiB ceilings. No huge cached closure may exhaust memory.
    internal const long MaximumRetainedBytes = 32L * 1024 * 1024;
    private readonly object _gate = new();
    private readonly object _owner = new();
    private long _attempt;
    internal void Invalidate() { lock (_gate) { _attempt = checked(_attempt + 1); } }
    private void Check(long attempt, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        lock (_gate)
            if (_attempt != attempt) throw new BundleSourceException(BundleSourceFailure.StaleAttempt, "Resource preparation attempt was replaced");
    }

    internal async Task<RequiredBundleSources> PrepareAsync(IResourceSource source,
        IBundleSourceCacheReader? cache = null, BundleSourceBudget? budget = null,
        string host = OfficialResourceOrigin.DefaultHost, YooAssetManifest? previous = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(source);
        cancellationToken.ThrowIfCancellationRequested();
        budget ??= new(); budget.Validate();
        host = OfficialResourceOrigin.SelectHost(host);
        if (source.SelectedHost is { } selected && selected != host)
            throw new BundleSourceException(BundleSourceFailure.ResponseSource, "Source host differs from preparation host");
        long attempt; lock (_gate) { attempt = _attempt = checked(_attempt + 1); }
        Check(attempt, cancellationToken);
        var before = await source.ObserveAsync(cancellationToken).ConfigureAwait(false);
        Check(attempt, cancellationToken);
        var manifests = await ReadManifestsAsync(source, before, host, attempt, cancellationToken).ConfigureAwait(false);
        var plan = BundleSourcePlan.Create(manifests[0], before.DataVersion, previous, cancellationToken);
        long retained = 0;
        foreach (var row in plan.Entries)
        {
            Check(attempt, cancellationToken);
            retained = checked(retained + row.Spec.Size);
            if (retained > MaximumRetainedBytes)
                throw new BundleSourceException(BundleSourceFailure.Budget, "Required source closure exceeds owned-byte bound");
        }
        bool[] cached = new bool[plan.Entries.Count];
        int downloadCount = 0; long downloadBytes = 0;
        for (int i = 0; i < plan.Entries.Count; i++)
        {
            Check(attempt, cancellationToken);
            cached[i] = cache is not null && await CacheMatchesAsync(cache, plan.Entries[i].Spec, cancellationToken).ConfigureAwait(false);
            Check(attempt, cancellationToken);
            if (!cached[i]) { downloadCount++; downloadBytes += plan.Entries[i].Spec.Size; }
        }
        if (downloadCount > budget.MaximumDownloads || downloadBytes > budget.MaximumDownloadBytes)
            throw new BundleSourceException(BundleSourceFailure.Budget, "Planned downloads exceed explicit byte/file quota");
        await CheckVersionsAsync(source, before, attempt, cancellationToken).ConfigureAwait(false);
        var handles = new List<VerifiedBundleSource>();
        for (int i = 0; i < plan.Entries.Count; i++)
        {
            Check(attempt, cancellationToken);
            var spec = plan.Entries[i].Spec;
            byte[] bytes;
            if (cached[i])
            {
                using var stream = await cache!.OpenReadAsync(spec, cancellationToken).ConfigureAwait(false);
                Check(attempt, cancellationToken);
                if (stream is null) throw new BundleSourceException(BundleSourceFailure.CacheChanged, "Bundle cache disappeared since planning");
                try
                {
                    bytes = await ReadBoundedAsync(stream, spec.Size, spec.Size, cancellationToken).ConfigureAwait(false);
                    handles.Add(VerifiedBundleSource.Verify(spec, bytes, BundleAcquisition.Cache, cancellationToken));
                }
                catch (BundleSourceException)
                { throw new BundleSourceException(BundleSourceFailure.CacheChanged, "Bundle cache changed since planning"); }
            }
            else
            {
                bytes = await FetchAsync(source, spec.Url(host), spec.Size, spec.Size, attempt, cancellationToken).ConfigureAwait(false);
                handles.Add(VerifiedBundleSource.Verify(spec, bytes, BundleAcquisition.UntrustedSourceDownload, cancellationToken));
            }
            Check(attempt, cancellationToken);
        }
        await CheckVersionsAsync(source, before, attempt, cancellationToken).ConfigureAwait(false);
        // Re-read both complete manifest responses, not just metadata or old cached receipts. A same
        // version replacement with its own matching CRC still changes the SHA-256 content identity.
        var afterManifests = await ReadManifestsAsync(source, before, host, attempt, cancellationToken).ConfigureAwait(false);
        for (int i = 0; i < manifests.Count; i++)
            if (manifests[i].Sha256 != afterManifests[i].Sha256)
                throw new BundleSourceException(BundleSourceFailure.ManifestChanged, "Manifest bytes changed during preparation");
        await CheckVersionsAsync(source, before, attempt, cancellationToken).ConfigureAwait(false);
        string identity = ContentIdentity(before, manifests, cancellationToken);
        lock (_gate)
        {
            Check(attempt, cancellationToken);
            return new(identity, attempt, plan, handles, downloadCount, downloadBytes, _owner, before, manifests, host);
        }
    }

    // Optional acquisition shares the required attempt, exact manifest and remaining budget.
    // Already owned dependencies are reused; no second plan can reset the download quota.
    internal async Task<IReadOnlyList<VerifiedBundleSource>> PrepareSkillAsync(IResourceSource source,
        RequiredBundleSources required, IBundleSourceCacheReader? cache, BundleSourceBudget? budget,
        BundleDownloadTotals totals, CancellationToken token)
    {
        var plan = BundleSourcePlan.CreateSkill(required.Manifests[0], required.Snapshot.DataVersion, token);
        var result = await PrepareOptionalAsync(source, required, cache, budget, totals, plan, token).ConfigureAwait(false);
        return result[BundleSourcePlan.SkillAssetPath];
    }

    internal Task<IReadOnlyDictionary<string, IReadOnlyList<VerifiedBundleSource>>> PrepareDailyAsync(IResourceSource source,
        RequiredBundleSources required, IBundleSourceCacheReader? cache, BundleSourceBudget? budget,
        BundleDownloadTotals totals, CancellationToken token)
        => PrepareOptionalAsync(source, required, cache, budget, totals,
            BundleSourcePlan.CreateDaily(required.Manifests[0], required.Snapshot.DataVersion, token), token);

    private async Task<IReadOnlyDictionary<string, IReadOnlyList<VerifiedBundleSource>>> PrepareOptionalAsync(IResourceSource source,
        RequiredBundleSources required, IBundleSourceCacheReader? cache, BundleSourceBudget? budget,
        BundleDownloadTotals totals, BundleSourcePlan plan, CancellationToken token)
    {
        EnsureCurrent(required, token);
        budget ??= new(); budget.Validate();
        if (totals.Context is null) totals.Context = required;
        else if (!ReferenceEquals(totals.Context, required))
            throw new BundleSourceException(BundleSourceFailure.StaleAttempt, "Optional acquisition belongs to another preparation");
        var owned = totals.Owned;
        foreach (var handle in required.Sources) owned.TryAdd(handle.Spec.Name, handle);
        var needed = plan.Entries.Where(x => !owned.ContainsKey(x.Spec.Name)).ToArray();
        long retained = owned.Values.Sum(x => x.Spec.Size) + needed.Sum(x => x.Spec.Size);
        if (retained > MaximumRetainedBytes)
            throw new BundleSourceException(BundleSourceFailure.Budget, "Optional closure exceeds owned-byte bound");
        var hits = new Dictionary<string, bool>(StringComparer.Ordinal);
        int downloads = Math.Max(totals.Count, required.DownloadCount);
        long bytes = Math.Max(totals.Bytes, required.DownloadBytes);
        foreach (var entry in needed)
        {
            EnsureCurrent(required, token);
            bool hit = false;
            if (cache is not null)
            {
                try { hit = await ReadOptionalCacheAsync(cache, entry.Spec, token).ConfigureAwait(false) is not null; }
                catch (BundleSourceException error) when (!error.Data.Contains(ResourceCleanup.FailureMarker)) { }
            }
            hits.Add(entry.Spec.Name, hit);
            if (!hit) { downloads++; bytes += entry.Spec.Size; }
        }
        if (downloads > budget.MaximumDownloads || bytes > budget.MaximumDownloadBytes)
            throw new BundleSourceException(BundleSourceFailure.Budget, "Optional downloads exceed remaining quota");
        totals.Count = downloads; totals.Bytes = bytes;
        foreach (var entry in needed)
        {
            EnsureCurrent(required, token);
            var spec = entry.Spec;
            if (hits[spec.Name])
            {
                var handle = await ReadOptionalCacheAsync(cache!, spec, token).ConfigureAwait(false);
                if (handle is null) throw new BundleSourceException(BundleSourceFailure.CacheChanged, "Optional cache disappeared");
                owned.Add(spec.Name, handle);
            }
            else
            {
                byte[] raw = await FetchAsync(source, spec.Url(required.Host), spec.Size, spec.Size, required.Attempt, token).ConfigureAwait(false);
                owned.Add(spec.Name, VerifiedBundleSource.Verify(spec, raw, BundleAcquisition.UntrustedSourceDownload, token));
            }
        }
        EnsureCurrent(required, token);
        return plan.AssetSourceNames.ToDictionary(pair => pair.Key,
            pair => (IReadOnlyList<VerifiedBundleSource>)pair.Value.Select(name => owned[name]).ToArray(), StringComparer.Ordinal);
    }

    private static async Task<VerifiedBundleSource?> ReadOptionalCacheAsync(IBundleSourceCacheReader cache,
        BundleSourceSpec spec, CancellationToken token)
    {
        var stream = await cache.OpenReadAsync(spec, token).ConfigureAwait(false);
        if (stream is null) return null;
        Exception? primary = null;
        try
        {
            byte[] raw = await ReadBoundedAsync(stream, spec.Size, spec.Size, token).ConfigureAwait(false);
            return VerifiedBundleSource.Verify(spec, raw, BundleAcquisition.Cache, token);
        }
        catch (Exception error) { primary = error; throw; }
        finally { ResourceCleanup.DisposePreservingFailure(stream, primary); }
    }

    // Reobserve AFTER extraction/table decoding. Preparing owned bytes alone does not establish
    // that the observed source remained stable while the structural candidate was built.
    internal async Task ConfirmUnchangedAsync(IResourceSource source, RequiredBundleSources prepared,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(source);
        EnsureCurrent(prepared, cancellationToken);
        await CheckVersionsAsync(source, prepared.Snapshot, prepared.Attempt, cancellationToken).ConfigureAwait(false);
        var manifests = await ReadManifestsAsync(source, prepared.Snapshot, prepared.Host, prepared.Attempt, cancellationToken).ConfigureAwait(false);
        for (int i = 0; i < prepared.Manifests.Count; i++)
            if (prepared.Manifests[i].Sha256 != manifests[i].Sha256)
                throw new BundleSourceException(BundleSourceFailure.ManifestChanged, "Manifest bytes changed during runtime candidate construction");
        await CheckVersionsAsync(source, prepared.Snapshot, prepared.Attempt, cancellationToken).ConfigureAwait(false);
        EnsureCurrent(prepared, cancellationToken);
    }

    internal void EnsureCurrent(RequiredBundleSources prepared, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(prepared);
        if (!ReferenceEquals(prepared.Owner, _owner))
            throw new BundleSourceException(BundleSourceFailure.StaleAttempt, "Resource preparation belongs to another attempt owner");
        Check(prepared.Attempt, token);
    }

    // Linearization point for returning a historical offline observation. Not installation,
    // activation or a promise that a server will remain unchanged after this point.
    internal T ReturnCurrent<T>(RequiredBundleSources prepared, T result, CancellationToken token)
    {
        lock (_gate) { EnsureCurrent(prepared, token); return result; }
    }

    private async Task CheckVersionsAsync(IResourceSource source, OfficialVersionSnapshot before, long attempt, CancellationToken token)
    {
        Check(attempt, token);
        var after = await source.ObserveAsync(token).ConfigureAwait(false);
        Check(attempt, token);
        if (!before.HasSameIdentity(after)) throw new BundleSourceException(BundleSourceFailure.VersionsChanged, "Observed versions changed during preparation");
    }
    private async Task<IReadOnlyList<YooAssetManifest>> ReadManifestsAsync(IResourceSource source,
        OfficialVersionSnapshot snapshot, string host, long attempt, CancellationToken token)
    {
        var result = new List<YooAssetManifest>();
        foreach (string package in ResourceValidation.Packages)
        {
            Check(attempt, token);
            string prefix = $"https://{host}/WLN/TW/{snapshot.DataVersion}/ResourcesPC/AssetBundle/{package}";
            byte[] hash = await FetchAsync(source, prefix + ".hash", 8, null, attempt, token).ConfigureAwait(false);
            if (hash.Length != 8 || hash.Any(b => !((b >= '0' && b <= '9') || (b >= 'a' && b <= 'f') || (b >= 'A' && b <= 'F'))))
                throw new BundleSourceException(BundleSourceFailure.Checksum, "Manifest .hash must contain exactly eight ASCII hex bytes");
            string expected = Encoding.ASCII.GetString(hash).ToLowerInvariant();
            byte[] bytes = await FetchAsync(source, prefix + ".bytes", ManifestIdentity.MaximumManifestBytes, null, attempt, token).ConfigureAwait(false);
            if (ManifestIdentity.Crc32LittleEndian(bytes, token) != expected)
                throw new BundleSourceException(BundleSourceFailure.Checksum, "Manifest bytes differ from response CRC32");
            var manifest = YooAssetManifest.Parse(bytes, token);
            manifest.ValidateIdentity(snapshot, package);
            result.Add(manifest);
        }
        return result.AsReadOnly();
    }
    private async Task<byte[]> FetchAsync(IResourceSource source, string url, long maximum, long? exact, long attempt, CancellationToken token)
    {
        Check(attempt, token);
        var response = await source.OpenAsync(url, token).ConfigureAwait(false);
        Exception? primary = null;
        try
        {
            Check(attempt, token);
            // Source rejection must precede declared length and any body read, including redirects/status.
            if (response.FinalUrl != url || response.Status != 200)
                throw new BundleSourceException(BundleSourceFailure.ResponseSource, "Response location or status differs from requested source");
            long? declared = null;
            if (response.ContentLength is { } text)
            {
                if (text.Length is 0 or > 20 || text.Any(c => c is < '0' or > '9') ||
                    !long.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out long value) || value > maximum || (exact.HasValue && value != exact))
                    throw new BundleSourceException(BundleSourceFailure.ResponseLength, "Invalid response Content-Length");
                declared = value;
            }
            byte[] bytes = await ReadBoundedAsync(response.Body, maximum, exact ?? declared, token).ConfigureAwait(false);
            Check(attempt, token);
            return bytes;
        }
        catch (Exception ex) { primary = ex; throw; }
        finally { ResourceCleanup.DisposePreservingFailure(response, primary); }
    }

    private static async Task<bool> CacheMatchesAsync(IBundleSourceCacheReader cache, BundleSourceSpec spec, CancellationToken token)
    {
        using var stream = await cache.OpenReadAsync(spec, token).ConfigureAwait(false);
        if (stream is null) return false;
        try
        {
            byte[] bytes = await ReadBoundedAsync(stream, spec.Size, spec.Size, token).ConfigureAwait(false);
            _ = VerifiedBundleSource.Verify(spec, bytes, BundleAcquisition.Cache, token);
            return true;
        }
        catch (BundleSourceException) { return false; } // Corrupt initial cache is a miss, never authority.
    }
    private static async Task<byte[]> ReadBoundedAsync(Stream stream, long maximum, long? exact, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        using var output = new MemoryStream();
        byte[] chunk = new byte[64 * 1024];
        long length = 0;
        while (true)
        {
            token.ThrowIfCancellationRequested();
            int requested = (int)Math.Min(chunk.Length, maximum - length + 1);
            int read = await stream.ReadAsync(chunk.AsMemory(0, requested), token).ConfigureAwait(false);
            token.ThrowIfCancellationRequested();
            if (read < 0 || read > requested) throw new BundleSourceException(BundleSourceFailure.ResponseLength, "Invalid stream read length");
            if (read == 0) break;
            length += read;
            if (length > maximum) throw new BundleSourceException(BundleSourceFailure.ResponseLength, "Stream exceeds bounded length");
            output.Write(chunk, 0, read);
        }
        if (length == 0 || (exact.HasValue && length != exact))
            throw new BundleSourceException(BundleSourceFailure.ResponseLength, "Stream empty or truncated");
        return output.ToArray();
    }
    private static string ContentIdentity(OfficialVersionSnapshot snapshot, IReadOnlyList<YooAssetManifest> manifests, CancellationToken token)
    {
        // Same canonical structure as ManifestIdentity, but every field now comes from actual parsed bytes.
        string text = "{\"data_ver\":" + ResourceValidation.Quote(snapshot.DataVersion) + ",\"exe_version\":" + ResourceValidation.Quote(snapshot.ExeVersion) + ",\"packages\":[" +
            string.Join(',', manifests.Select(m => "{\"full_version\":" + ResourceValidation.Quote(m.Header.PackageVersion) + ",\"manifest_crc32_le\":" + ResourceValidation.Quote(m.Crc32Le) +
            ",\"manifest_sha256\":" + ResourceValidation.Quote(m.Sha256) + ",\"name\":" + ResourceValidation.Quote(m.Header.PackageName) + "}")) + "],\"schema_version\":1}";
        return ResourceValidation.Digest(Encoding.ASCII.GetBytes(text), token);
    }
}
