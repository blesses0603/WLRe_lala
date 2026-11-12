using System.Data.Common;
using System.Text.Json;

namespace Lala.Core.Resources;

// Internal offline cache. A dedicated, closed, exclusively supplied SQLite connection is consumed.
// The caller must independently rebuild current candidates; this store confers no provenance.
internal static class SpritePngStore
{
    private const string Schema = "CREATE TABLE sprite_png_v1 (asset TEXT PRIMARY KEY NOT NULL, identity TEXT NOT NULL, png_sha TEXT NOT NULL, png BLOB NOT NULL)";
    private const int MaximumImages = 8192, MaximumTotalBytes = 96 * 1024 * 1024;

    internal static Task WriteAsync(DbConnection connection, IReadOnlyList<SpritePixelCandidate> current,
        Action revalidateSources, CancellationToken token = default) => RunAsync(connection, current, revalidateSources, true, token);

    // Returned PNGs are private copies and remain offline data, not revocable production publication.
    internal static Task<IReadOnlyDictionary<string, byte[]>> ReadAsync(DbConnection connection,
        IReadOnlyList<SpritePixelCandidate> current, Action revalidateSources, CancellationToken token = default) =>
        RunAsync(connection, current, revalidateSources, false, token);

    private static async Task<IReadOnlyDictionary<string, byte[]>> RunAsync(DbConnection connection,
        IReadOnlyList<SpritePixelCandidate> current, Action revalidateSources, bool write, CancellationToken token)
    {
        var db = new ResourceInventoryDatabase(connection, token);
        Exception? primary = null; var result = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        try
        {
            ArgumentNullException.ThrowIfNull(revalidateSources);
            token.ThrowIfCancellationRequested();
            BoundedSpritePixels.Check(current.Count is > 0 and <= MaximumImages, "Image cache count exceeds bounds");
            var candidates = current.ToArray();
            BoundedSpritePixels.Check(candidates.All(c => c.Context.VersionIdentity == candidates[0].Context.VersionIdentity),
                "Image cache candidates have different source sets or versions");
            BoundedSpritePixels.Check(candidates.Select(c => c.Context.AssetPath).Distinct(StringComparer.Ordinal).Count() == candidates.Length,
                "Image cache asset paths are duplicated");
            long budget = 0;
            foreach (var candidate in candidates)
            {
                // Check total before creating any PNGs or opening the database.
                budget += (long)(candidate.Width * 4 + 1) * candidate.Height + 160;
                BoundedSpritePixels.Check(budget <= MaximumTotalBytes, "Image cache aggregate size exceeds bounds");
            }
            await db.OpenAsync(write).ConfigureAwait(false);
            var schema = await db.ReadAsync("SELECT " + ResourceInventoryDatabase.BoundedTextSql("sql", 4096) + " FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'", 1).ConfigureAwait(false);
            if (schema.Count == 0 && write) await db.ExecuteAsync(Schema).ConfigureAwait(false);
            else BoundedSpritePixels.Check(schema.Count == 1 && schema[0][0] as string == Schema, "Unexpected image cache schema");
            if (write)
            {
                await db.ExecuteAsync("DELETE FROM sprite_png_v1").ConfigureAwait(false);
                foreach (var candidate in candidates)
                {
                    byte[] png = SpritePng.Encode(candidate, token);
                    await db.ExecuteAsync("INSERT INTO sprite_png_v1 VALUES(CAST(@asset AS TEXT),CAST(@identity AS TEXT),CAST(@hash AS TEXT),@png)",
                        ("@asset", candidate.Context.AssetPath), ("@identity", Identity(candidate)), ("@hash", SpritePng.Hash(png)), ("@png", png)).ConfigureAwait(false);
                }
            }
            var count = await db.ReadAsync("SELECT count(*) FROM sprite_png_v1", 1).ConfigureAwait(false);
            BoundedSpritePixels.Check(ResourceInventoryDatabase.Number(count[0][0]) == candidates.Length, "Image cache index changed");
            foreach (var candidate in candidates)
            {
                token.ThrowIfCancellationRequested();
                var rows = await db.ReadAsync("SELECT " + ResourceInventoryDatabase.BoundedTextSql("identity", 65536) + "," +
                    ResourceInventoryDatabase.BoundedTextSql("png_sha", 64) +
                    $",CASE WHEN typeof(png)='blob' AND length(png)<={SpritePng.MaximumBytes} THEN png ELSE NULL END FROM sprite_png_v1 WHERE asset=CAST(@asset AS TEXT)",
                    1, ("@asset", candidate.Context.AssetPath)).ConfigureAwait(false);
                BoundedSpritePixels.Check(rows.Count == 1, "Image cache asset missing");
                var row = rows[0];
                BoundedSpritePixels.Check(row[0] as string == Identity(candidate) && row[2] is byte[], "Image cache identity or storage mismatch");
                byte[] png = (byte[])row[2]!;
                BoundedSpritePixels.Check(row[1] as string == SpritePng.Hash(png) && png.AsSpan().SequenceEqual(SpritePng.Encode(candidate, token)),
                    "Image cache PNG or pixel mismatch");
                result.Add(candidate.Context.AssetPath, png);
            }
            await db.CommitAsync(() => { revalidateSources(); token.ThrowIfCancellationRequested(); }).ConfigureAwait(false);
        }
        catch (Exception error) { primary = error; }
        await db.FinishAsync(primary).ConfigureAwait(false);
        return result;
    }
    private static string Identity(SpritePixelCandidate candidate) => JsonSerializer.Serialize(new
    {
        candidate.Context, candidate.TextureLayout, candidate.Rectangle, candidate.Width, candidate.Height,
        candidate.TexturePayloadSha256, candidate.PixelSha256
    });
}
