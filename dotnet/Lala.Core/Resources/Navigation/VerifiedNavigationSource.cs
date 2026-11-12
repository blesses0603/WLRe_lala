using System.Security.Cryptography;
using Microsoft.Data.Sqlite;
using Lala.Core.World;

namespace Lala.Core.Resources;

/// <summary>Resource-owner-issued navigation source. No public API accepts a claimed
/// manifest, URL, file path, raw mesh or authority flag for movement.</summary>
internal sealed class VerifiedNavigationSource(string root, ManifestIdentity identity, YooAssetManifest manifest, Func<bool> current)
{
    internal string Identity => identity.Key;
    internal string DataVersion => identity.DataVersion;
    internal bool IsCurrent => current();
    private string Database => Path.Combine(root, "official_sync", "derived_catalogs", "navigation.sqlite3");
    private void Check(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (!current() || manifest.Sha256 != ReviewedNavigationCache.MainSha256 || manifest.Sha256 != identity.Packages.Single(p => p.Name == "MainPackage").ManifestSha256)
            throw new NavigationException("目前導航來源已失效或尚未核對此版本。");
    }
    internal async Task<OfflineNavigationCacheEntry> LoadAsync(ushort model, string mode, bool download, CancellationToken token)
    {
        Check(token);
        if (!ReviewedNavigationCache.Models.TryGetValue(model, out var review)) throw new NavigationException("此地圖導航格式尚未核對。");
        byte[]? raw = await ReadCacheAsync(review, token).ConfigureAwait(false);
        if (raw is null)
        {
            var assets = manifest.Assets.Where(a => a.Address == "M" + model.ToString("D5") && a.Path.EndsWith("/M" + model.ToString("D5") + ".unity", StringComparison.Ordinal)).ToArray();
            if (assets.Length != 1 || review.Bundles.Length != 2 || manifest.Bundles[assets[0].BundleId].Name != review.Bundles[0]) throw new NavigationException("導航場景與官方清單不符。");
            var bundle = manifest.Bundles[assets[0].BundleId];
            if (!bundle.DependencyIds.Any(i => manifest.Bundles[i].Name == review.Bundles[1])) throw new NavigationException("導航來源依賴不符。");
            var specs = review.Bundles.Select(name => new BundleSourceSpec(identity.DataVersion, manifest, manifest.Bundles.Single(b => b.Name == name))).ToArray();
            if (specs.Sum(spec => spec.Size) > 32L * 1024 * 1024) throw new NavigationException("導航來源超過 2 檔案／32 MiB 配額。");
            var cache = new RuntimeBundleCacheReader(root); var writer = new RuntimeBundleCacheWriter(root);
            using var source = new HttpOfficialResourceSource();
            if (download) await CheckVersionsAsync(source, token).ConfigureAwait(false);
            var candidates = new List<byte[]>(); var budget = new UnityExtractionBudget();
            foreach (var spec in specs)
            {
                Check(token);
                bool cached = false;
                var input = await cache.OpenReadAsync(spec, token).ConfigureAwait(false);
                if (input is not null)
                {
                    await using (input)
                    {
                        try { await BundleStreamVerifier.VerifyAsync(spec, input, token: token).ConfigureAwait(false); cached = true; }
                        catch (BundleSourceException error) when (error.Failure is BundleSourceFailure.Checksum or BundleSourceFailure.ResponseLength) { }
                    }
                }
                if (!cached)
                {
                    if (!download) throw new NavigationException("此地圖尚未快取，請先按「同步導航」。");
                    var response = await source.OpenBundleStreamAsync(spec, token).ConfigureAwait(false);
                    try
                    {
                        Check(token);
                        if (response.Status != 200 || response.FinalUrl != spec.Url(OfficialResourceOrigin.DefaultHost)) throw new NavigationException("導航下載來源不符。");
                        if (response.ContentLength is {} length && length != spec.Size.ToString(System.Globalization.CultureInfo.InvariantCulture)) throw new NavigationException("導航下載長度不符。");
                        await writer.StoreStreamAsync(spec, response.Body, token).ConfigureAwait(false);
                    }
                    finally { response.Dispose(); }
                }
                var reopened = await cache.OpenReadAsync(spec, token).ConfigureAwait(false) ?? throw new NavigationException("導航快取已被移除。");
                byte[] bytes = new byte[checked((int)spec.Size)];
                await using (reopened)
                {
                    await reopened.ReadExactlyAsync(bytes, token).ConfigureAwait(false);
                    if (await reopened.ReadAsync(new byte[1], token).ConfigureAwait(false) != 0) throw new NavigationException("導航 Bundle 長度已改變。");
                }
                _ = VerifiedBundleSource.Verify(spec, bytes, cached ? BundleAcquisition.Cache : BundleAcquisition.UntrustedSourceDownload, token);
                foreach (var entry in BoundedUnityBundle.ReadImageArchive(bytes, budget, token))
                {
                    // The reviewed ZIP's exact full SHA-256 binds it to this model. No scene
                    // script, MonoBehaviour or unrelated Unity object is interpreted/executed.
                    var data = entry.Bytes;
                    int signatures = 0;
                    for (int offset = 0; offset <= data.Length - review.Length; offset++)
                    {
                        if ((offset & 65535) == 0) Check(token);
                        if (data.Span[offset] != 0x50 || data.Span[offset + 1] != 0x4b || data.Span[offset + 2] != 3 || data.Span[offset + 3] != 4) continue;
                        if (++signatures > 256) throw new NavigationException("導航封存搜尋超過配額。");
                        var candidate = data.Slice(offset, review.Length);
                        if (Convert.ToHexStringLower(SHA256.HashData(candidate.Span)) == review.Sha256) candidates.Add(candidate.ToArray());
                    }
                }
            }
            Check(token);
            if (candidates.Count != 1) throw new NavigationException("導航快取內容缺失或不唯一。");
            raw = candidates[0];
            if (download)
            {
                await CheckVersionsAsync(source, token).ConfigureAwait(false);
                _ = ReviewedNavigationCache.Decode(raw, review, mode, token);
                await WriteCacheAsync(review, raw, token).ConfigureAwait(false);
            }
        }
        Check(token);
        var geometry = ReviewedNavigationCache.Decode(raw, review, mode, token);
        Check(token);
        return new(new(identity.Key, identity.DataVersion), model, geometry.Origin, geometry.Mesh);
    }
    private async Task CheckVersionsAsync(IResourceSource source, CancellationToken token)
    {
        Check(token); var observed = await source.ObserveAsync(token).ConfigureAwait(false); Check(token);
        if (observed.DataVersion != identity.DataVersion || observed.ExeVersion != identity.ExeVersion || identity.Packages.Any(p => !observed.Packages.TryGetValue(p.Name, out var v) || v != p.FullVersion))
            throw new NavigationException("官方版本已改變，請回資源準備頁。");
    }
    private async Task<byte[]?> ReadCacheAsync(ReviewedNavigationModel review, CancellationToken token)
    {
        if (!File.Exists(Database)) return null;
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = Database, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        await connection.OpenAsync(token).ConfigureAwait(false);
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT raw, digest FROM lala_navigation_v1 WHERE version=$version AND model=$model";
        command.Parameters.AddWithValue("$version", identity.Key); command.Parameters.AddWithValue("$model", review.Model);
        try
        {
            using var rows = await command.ExecuteReaderAsync(token).ConfigureAwait(false);
            if (!await rows.ReadAsync(token).ConfigureAwait(false)) return null;
            if (rows.GetString(1) != review.Sha256 || rows.GetBytes(0, 0, null, 0, 0) != review.Length) throw new NavigationException("導航資料庫指紋或長度不符。");
            var raw = new byte[review.Length]; rows.GetBytes(0, 0, raw, 0, raw.Length); Check(token); return raw;
        }
        catch (SqliteException error) when (error.SqliteErrorCode == 1 && error.Message.Contains("no such table: lala_navigation_v1", StringComparison.Ordinal)) { return null; }
    }
    private async Task WriteCacheAsync(ReviewedNavigationModel review, byte[] raw, CancellationToken token)
    {
        Check(token); Directory.CreateDirectory(Path.GetDirectoryName(Database)!);
        using var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = Database, Mode = SqliteOpenMode.ReadWriteCreate, Pooling = false }.ToString());
        await connection.OpenAsync(token).ConfigureAwait(false);
        using var transaction = connection.BeginTransaction(); using var command = connection.CreateCommand(); command.Transaction = transaction;
        command.CommandText = "CREATE TABLE IF NOT EXISTS lala_navigation_v1(version TEXT NOT NULL, model INTEGER NOT NULL, digest TEXT NOT NULL, raw BLOB NOT NULL CHECK(length(raw)<=8388608), PRIMARY KEY(version,model))";
        await command.ExecuteNonQueryAsync(token).ConfigureAwait(false);
        command.CommandText = "INSERT OR REPLACE INTO lala_navigation_v1 VALUES($version,$model,$digest,$raw)";
        command.Parameters.AddWithValue("$version", identity.Key); command.Parameters.AddWithValue("$model", review.Model);
        command.Parameters.AddWithValue("$digest", review.Sha256); command.Parameters.AddWithValue("$raw", raw);
        await command.ExecuteNonQueryAsync(token).ConfigureAwait(false); Check(token); transaction.Commit();
    }
}
