using Lala.Core.Gameplay;

namespace Lala.Core.Resources;

/// <summary>Optional, owner-issued same-version data acquisition. It never reruns login
/// preparation or changes the startup activation. Raw sources are released after parsing.</summary>
internal sealed class VerifiedSocialSource(string root, ManifestIdentity identity, YooAssetManifest manifest, Func<bool> current)
{
    internal string Identity => identity.Key;
    internal bool IsCurrent => current();
    private void Check(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (!current() || manifest.Sha256 != identity.Packages.Single(p => p.Name == "DataPackage").ManifestSha256)
            throw new ResourceValidationException("社交資料來源已失效。");
    }
    internal async Task<GameSocialCatalog> LoadAsync(CancellationToken token)
    {
        Check(token);
        var plan = BundleSourcePlan.CreateSocial(manifest, identity.DataVersion, token);
        if (plan.Entries.Count > 24 || plan.Entries.Sum(e => e.Spec.Size) > 32L * 1024 * 1024)
            throw new ResourceValidationException("社交資料來源超過 24 檔／32 MiB 配額。");
        var cache = new RuntimeBundleCacheReader(root); var writer = new RuntimeBundleCacheWriter(root);
        using var source = new HttpOfficialResourceSource();
        var handles = new Dictionary<string, VerifiedBundleSource>();
        await CheckVersionsAsync(source, token).ConfigureAwait(false);
        foreach (var entry in plan.Entries)
        {
            Check(token); var spec = entry.Spec;
            byte[]? bytes = null;
            await using (var input = await cache.OpenReadAsync(spec, token).ConfigureAwait(false))
                if (input is not null)
                {
                    try
                    {
                        await BundleStreamVerifier.VerifyAsync(spec, input, token: token).ConfigureAwait(false);
                        input.Position = 0; bytes = new byte[checked((int)spec.Size)];
                        await input.ReadExactlyAsync(bytes, token).ConfigureAwait(false);
                    }
                    catch (BundleSourceException) { bytes = null; }
                }
            if (bytes is null)
            {
                using var response = await source.OpenBundleStreamAsync(spec, token).ConfigureAwait(false);
                Check(token);
                if (response.Status != 200 || response.FinalUrl != spec.Url(OfficialResourceOrigin.DefaultHost)) throw new ResourceValidationException("社交資料下載來源不符。");
                await writer.StoreStreamAsync(spec, response.Body, token).ConfigureAwait(false);
                await using var read = await cache.OpenReadAsync(spec, token).ConfigureAwait(false) ?? throw new ResourceValidationException("社交資料快取遺失。");
                bytes = new byte[checked((int)spec.Size)]; await read.ReadExactlyAsync(bytes, token).ConfigureAwait(false);
            }
            handles.Add(spec.Name, VerifiedBundleSource.Verify(spec, bytes, BundleAcquisition.Cache, token));
        }
        var tables = new Dictionary<string, byte[]>(); long total = 0;
        foreach (var (path, names) in plan.AssetSourceNames)
        {
            Check(token);
            var raw = UnityTextAssetExtractor.Extract(path, names.Select(n => handles[n]).ToArray(), cancellationToken: token);
            total += raw.Length;
            if (total > 16 * 1024 * 1024) throw new ResourceValidationException("社交資料表超過保留額度。");
            tables.Add(Path.GetFileNameWithoutExtension(path), raw);
        }
        var result = GameSocialCatalog.Parse(tables, identity.Key, token);
        await CheckVersionsAsync(source, token).ConfigureAwait(false);
        Check(token); return result;
    }
    private async Task CheckVersionsAsync(IResourceSource source, CancellationToken token)
    {
        Check(token); var observed = await source.ObserveAsync(token).ConfigureAwait(false); Check(token);
        if (observed.DataVersion != identity.DataVersion || observed.ExeVersion != identity.ExeVersion || identity.Packages.Any(p => !observed.Packages.TryGetValue(p.Name, out var v) || v != p.FullVersion))
            throw new ResourceValidationException("官方版本已改變，請回版本檢查頁。");
    }
}
