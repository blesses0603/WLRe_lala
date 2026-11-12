using System.Text.Json;
using Lala.Core.Resources;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class SpritePngStoreTests : IDisposable
{
    private readonly string path = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "lala-owned-png-" + Guid.NewGuid() + ".sqlite");
    private SqliteConnection Connection() => new(new SqliteConnectionStringBuilder { DataSource = path, Pooling = false }.ToString());
    public void Dispose() { System.IO.File.Delete(path); System.IO.File.Delete(path + "-journal"); }
    private static SpritePixelCandidate Candidate(int width = 2, int height = 3, string version = "owned", string asset = "Assets/owned.png", int seed = 11) =>
        BoundedSpritePixels.Decode(new(version, new string('a', 64), "CAB-owned", asset, 1, 2), new(width, height, 4), new(0, 0, width, height),
            Enumerable.Range(0, width * height * 4).Select(i => (byte)(i * 37 + seed)).ToArray());
    private void Execute(string sql, params (string, object)[] parameters)
    {
        using var c = Connection(); c.Open(); using var cmd = c.CreateCommand(); cmd.CommandText = sql;
        foreach (var (name, value) in parameters) cmd.Parameters.AddWithValue(name, value);
        cmd.ExecuteNonQuery();
    }
    private static void CheckSource() { }
    public static IEnumerable<object[]> Vectors()
    {
        using var stream = typeof(SpritePngStoreTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.png_vectors.json")!;
        using var json = JsonDocument.Parse(stream);
        foreach (var v in json.RootElement.GetProperty("vectors").EnumerateArray())
            yield return [v.GetProperty("width").GetInt32(), v.GetProperty("height").GetInt32(), v.GetProperty("bytes").GetInt32(), v.GetProperty("sha256").GetString()!];
    }
    [Theory, MemberData(nameof(Vectors))]
    public void Canonical_png_matches_Pillow_and_zlib_verified_vectors(int width, int height, int size, string hash)
    {
        byte[] png = SpritePng.Encode(Candidate(width, height)); Assert.Equal(size, png.Length); Assert.Equal(hash, SpritePng.Hash(png));
    }
    [Fact]
    public async Task Owned_bundle_extracts_to_durable_png_and_reads_with_rebuilt_candidate()
    {
        using var stream = typeof(SpritePngStoreTests).Assembly.GetManifestResourceStream("Lala.Core.Tests.Resources.UnityImages.SerializedFixtures.owned.bundle")!;
        using var memory = new MemoryStream(); stream.CopyTo(memory); byte[] bytes = memory.ToArray();
        SpritePixelCandidate Rebuild() => UnitySpriteExtractor.Extract("Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png", "owned", [UnityFixtures.Source(bytes)]);
        int checks = 0;
        await SpritePngStore.WriteAsync(Connection(), [Rebuild()], () => checks++);
        var result = await SpritePngStore.ReadAsync(Connection(), [Rebuild()], () => checks++);
        Assert.Equal(2, checks); Assert.Equal(SpritePng.Encode(Rebuild()), result.Single().Value);
        Array.Fill(result.Single().Value, (byte)0);
        Assert.Equal(SpritePng.Encode(Rebuild()), (await SpritePngStore.ReadAsync(Connection(), [Rebuild()], CheckSource)).Single().Value);
        Assert.False(Rebuild().HasVerifiedProvenance);
    }
    [Theory, InlineData("png"), InlineData("hash"), InlineData("identity"), InlineData("missing"), InlineData("extra"), InlineData("type"), InlineData("oversize"), InlineData("forged-png")]
    public async Task Corrupt_cache_cannot_authorize_its_own_pixels(string mutation)
    {
        var candidate = Candidate(); await SpritePngStore.WriteAsync(Connection(), [candidate], CheckSource);
        switch (mutation)
        {
            case "png": Execute("UPDATE sprite_png_v1 SET png=zeroblob(length(png))"); break;
            case "hash": Execute("UPDATE sprite_png_v1 SET png_sha='wrong'"); break;
            case "identity": Execute("UPDATE sprite_png_v1 SET identity='{}'"); break;
            case "missing": Execute("DELETE FROM sprite_png_v1"); break;
            case "extra": Execute("INSERT INTO sprite_png_v1 SELECT 'extra',identity,png_sha,png FROM sprite_png_v1"); break;
            case "type": Execute("UPDATE sprite_png_v1 SET png='text'"); break;
            case "oversize": Execute("UPDATE sprite_png_v1 SET png=zeroblob(4194305)"); break;
            case "forged-png":
                var other = SpritePng.Encode(Candidate(seed: 12));
                Execute("UPDATE sprite_png_v1 SET png=@png,png_sha=@hash", ("@png", other), ("@hash", SpritePng.Hash(other))); break;
        }
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.ReadAsync(Connection(), [candidate], CheckSource));
    }
    [Fact]
    public async Task Source_change_with_identical_pixels_is_rejected()
    {
        await SpritePngStore.WriteAsync(Connection(), [Candidate()], CheckSource);
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.ReadAsync(Connection(), [Candidate(version: "new")], CheckSource));
    }
    [Theory, InlineData(false), InlineData(true)]
    public async Task Precommit_failure_or_cancellation_preserves_previous_catalog(bool cancel)
    {
        var old = Candidate(); await SpritePngStore.WriteAsync(Connection(), [old], CheckSource);
        using var cts = new CancellationTokenSource();
        Exception error = await Assert.ThrowsAnyAsync<Exception>(() => SpritePngStore.WriteAsync(Connection(), [Candidate(version: "replacement")], () =>
        {
            if (cancel) cts.Cancel(); else throw new InvalidDataException("Owned source changed");
        }, cts.Token));
        Assert.Equal(ResourceInventoryWriteOutcome.NotCommitted, error.Data[ResourceInventoryDatabase.OutcomeKey]);
        Assert.Equal(true, error.Data[ResourceInventoryDatabase.RollbackKey]);
        Assert.Equal(SpritePng.Encode(old), (await SpritePngStore.ReadAsync(Connection(), [old], CheckSource)).Single().Value);
    }
    [Fact]
    public async Task Duplicate_and_aggregate_oversize_inputs_are_rejected_before_open()
    {
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.WriteAsync(Connection(), [Candidate(), Candidate()], CheckSource));
        Assert.False(System.IO.File.Exists(path));
        var large = Candidate(512, 512);
        var candidates = Enumerable.Range(0, 96).Select(i => new SpritePixelCandidate(large.Context with { AssetPath = $"Assets/{i}.png" },
            large.TextureLayout, large.Rectangle, large.Width, large.Height, large.CopyPixels(), large.TexturePayloadSha256)).ToArray();
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.WriteAsync(Connection(), candidates, CheckSource));
        Assert.False(System.IO.File.Exists(path));
    }
    [Fact]
    public async Task Mixed_source_sets_and_versions_are_rejected_before_open()
    {
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.WriteAsync(Connection(),
            [Candidate(asset: "Assets/a.png"), Candidate(version: "other", asset: "Assets/b.png")], CheckSource));
        Assert.False(System.IO.File.Exists(path));
    }
    [Fact]
    public async Task Readonly_write_failure_preserves_the_existing_database()
    {
        await SpritePngStore.WriteAsync(Connection(), [Candidate()], CheckSource);
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
        await Assert.ThrowsAsync<SqliteException>(() => SpritePngStore.WriteAsync(connection, [Candidate(version: "new")], CheckSource));
        Assert.Single(await SpritePngStore.ReadAsync(Connection(), [Candidate()], CheckSource));
    }
    [Fact]
    public async Task Foreign_schema_and_triggers_are_rejected_without_mutating_existing_rows()
    {
        await SpritePngStore.WriteAsync(Connection(), [Candidate()], CheckSource);
        Execute("CREATE TRIGGER extra BEFORE DELETE ON sprite_png_v1 BEGIN SELECT RAISE(FAIL,'unexpected'); END");
        await Assert.ThrowsAsync<InvalidDataException>(() => SpritePngStore.WriteAsync(Connection(), [Candidate(version: "new")], CheckSource));
        Execute("DROP TRIGGER extra");
        Assert.Single(await SpritePngStore.ReadAsync(Connection(), [Candidate()], CheckSource));
    }
    [Fact]
    public async Task Read_rechecks_sources_before_returning_any_pngs()
    {
        await SpritePngStore.WriteAsync(Connection(), [Candidate()], CheckSource);
        await Assert.ThrowsAsync<InvalidDataException>(() => SpritePngStore.ReadAsync(Connection(), [Candidate()], () => throw new InvalidDataException("changed")));
    }
    [Fact]
    public async Task Replacement_is_atomic_and_order_independent()
    {
        var a = Candidate(asset: "Assets/a.png"); var b = Candidate(asset: "Assets/b.png");
        await SpritePngStore.WriteAsync(Connection(), [a, b], CheckSource);
        Assert.Equal(2, (await SpritePngStore.ReadAsync(Connection(), [b, a], CheckSource)).Count);
        await SpritePngStore.WriteAsync(Connection(), [b], CheckSource);
        Assert.Single(await SpritePngStore.ReadAsync(Connection(), [b], CheckSource));
        await Assert.ThrowsAsync<SpritePixelException>(() => SpritePngStore.ReadAsync(Connection(), [a, b], CheckSource));
    }
}
