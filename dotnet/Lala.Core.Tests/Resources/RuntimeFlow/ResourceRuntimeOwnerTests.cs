using System.Globalization;
using System.Text;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Microsoft.Data.Sqlite;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class ResourceRuntimeOwnerTests
{
    private static readonly TimeSpan TestTimeout = TimeSpan.FromSeconds(15);

    private class Source : IResourceSource, IDisposable
    {
        internal byte[] Bundle = RuntimeFlowFixtures.Read("all-ten.bundle");
        internal byte[] Main = BundleSourceFixtures.Bytes("main-valid");
        internal byte[] Data;
        internal int Observations;
        internal int Disposals;
        internal Action<CancellationToken>? OnToken;
        internal Func<int, OfficialVersionSnapshot> Snapshot = _ => RuntimeFlowFixtures.Snapshot();
        internal Action? OnDispose;
        public void Dispose() { Interlocked.Increment(ref Disposals); OnDispose?.Invoke(); }
        internal Func<int, Task>? BeforeObserve;
        internal Source() => Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]> { ["all-ten.bundle"] = Bundle });
        public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
        {
            int n = ++Observations;
            OnToken?.Invoke(token);
            if (BeforeObserve is not null) await BeforeObserve(n);
            token.ThrowIfCancellationRequested(); return Snapshot(n);
        }
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            byte[] bytes = url[(url.LastIndexOf('/') + 1)..] switch
            {
                "DataPackage.bytes" => Data, "MainPackage.bytes" => Main,
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                "all-ten.bundle" => Bundle,
                _ => throw new InvalidOperationException("Unexpected offline target")
            };
            return ValueTask.FromResult(new ResourceResponse(url, 200, bytes.Length.ToString(CultureInfo.InvariantCulture), new MemoryStream(bytes, false)));
        }
    }
    private sealed class AsyncSource : Source, IAsyncDisposable
    {
        public async ValueTask DisposeAsync() { await Task.Yield(); Dispose(); }
    }
    private static IEnumerable<Exception> Failures(Exception error)
        => error is AggregateException aggregate ? aggregate.Flatten().InnerExceptions : new[] { error };
    private static void Register(CancellationToken token, int mode, Action callback)
    {
        if (mode == 0) token.Register(callback);
        else if (mode == 1) token.UnsafeRegister(_ => callback(), null);
        else { using (ExecutionContext.SuppressFlow()) token.Register(callback); }
    }
    private sealed class Fixture : IDisposable
    {
        internal string Root = Path.Combine(Path.GetTempPath(), "lala-owner-" + Guid.NewGuid().ToString("N"));
        internal string Inventory => Path.Combine(Root, "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        internal async Task PopulateAsync(Source source)
        {
            var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
            using var db = new DatabaseReadTestDatabase();
            db.Execute("DELETE FROM resources; DELETE FROM version_identities; DELETE FROM sync_state; DELETE FROM versions;");
            db.Execute("INSERT INTO versions VALUES(1,@p0)", prepared.Identity.Key);
            db.Execute("INSERT INTO version_identities VALUES(1,@p0)", prepared.Identity.CanonicalJson);
            db.Execute("INSERT INTO sync_state VALUES(1,1)");
            foreach (string name in BundleSourcePlan.RequiredTables)
            {
                string path = RuntimeFlowFixtures.AssetRoot + name + ".bytes";
                var selected = prepared.RecheckContext.Plan.AssetSourceNames[path];
                byte[] raw = UnityTextAssetExtractor.Extract(path, prepared.RecheckContext.Sources.Where(s => selected.Contains(s.Spec.Name)).ToArray());
                db.Execute("INSERT INTO resources VALUES(1,@p0,@p1,@p2)", name + ".bytes", prepared.Candidate.SourceSha256[name], raw);
            }
            Directory.CreateDirectory(Path.GetDirectoryName(Inventory)!);
            File.Copy(db.FileName, Inventory);
            source.Observations = 0;
        }
        public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }
    [Fact]
    public async Task Portrait_batch_writes_independently_reads_and_offline_owner_cannot_admit()
    {
        using var fixture = new Fixture();
        int builds = 0;
        var hooks = new ResourceRuntimeBootstrapTestHooks { PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch(() => { builds++; return 255; }) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Null(result.Failure); Assert.Equal(AccountResourceStorageOutcome.Committed, result.PortraitStorageOutcome);
        Assert.NotNull(result.Publication!.Portraits); Assert.Equal(3, builds);
        Assert.False(owner.TryActivate(result.Publication, out _));
        var refresh = await owner.RefreshWithResultAsync();
        Assert.Null(refresh.Failure); Assert.NotNull(refresh.Publication!.Portraits);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, refresh.PortraitStorageOutcome); Assert.Equal(5, builds);
    }
    [Fact]
    public async Task Missing_portrait_cache_refresh_is_readonly_and_unreviewed_sources_are_absent()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source()); Assert.Null(prepared.Portraits);
        var hooks = new ResourceRuntimeBootstrapTestHooks { PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch() };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks);
        var result = await owner.RefreshWithResultAsync();
        Assert.Null(result.Failure); Assert.Null(result.Publication!.Portraits);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.PortraitStorageOutcome);
        Assert.False(File.Exists(Path.Combine(fixture.Root,"official_sync","derived_catalogs","core_portraits_v1.sqlite3")));
    }
    [Theory, InlineData(false), InlineData(true)]
    public async Task Portrait_retirement_or_source_drift_preserves_exact_storage_outcome(bool drift)
    {
        using var fixture = new Fixture(); var source = new Source(); ResourceRuntimeOwner? owner = null;
        var hooks = new ResourceRuntimeBootstrapTestHooks
        {
            PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch(),
            BeforePortraitCommitAdmission = () =>
            {
                if (drift) { var main = BundleSourceFixtures.Index("main-valid"); main["header"]!["package_note"] = "changed"; source.Main = BundleSourceFixtures.Encode(main); }
                else owner!.Invalidate();
            }
        };
        await using (owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks))
        {
            var result = await owner.BootstrapAndRefreshAsync(); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
            Assert.Equal(drift ? AccountResourceStorageOutcome.Committed : AccountResourceStorageOutcome.NotCommitted, result.PortraitStorageOutcome);
        }
    }
    [Fact]
    public async Task Portrait_pixel_drift_between_preparation_and_write_blocks_publication()
    {
        using var fixture = new Fixture(); int calls = 0;
        var hooks = new ResourceRuntimeBootstrapTestHooks { PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch(() => ++calls) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.NotNull(result.Failure); Assert.Null(result.Publication);
        Assert.Equal(AccountResourceStorageOutcome.NotCommitted, result.PortraitStorageOutcome);
    }
    [Theory, InlineData("invalidate"), InlineData("dispose"), InlineData("refresh")]
    public async Task Portrait_reads_require_exact_activation_and_revoke(string retirement)
    {
        using var fixture = new Fixture();
        var hooks = new ResourceRuntimeBootstrapTestHooks { PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch() };
        await using var offline = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await offline.BootstrapAndRefreshAsync(); Assert.Null(result.Failure);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var portraits = result.Publication!.Portraits! with { Mapping = PortraitMapping.ParseLayoutForOfflineTests(PortraitMappingTests.Raw()) };
        var publication = new ResourceRuntimePublication(owner, 0, prepared, portraits: portraits);
        // White-box lifetime fixture only; this does not assert official acquisition or acceptance.
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        Assert.True(owner.TryActivate(publication, out var active)); Assert.True(active!.HasPortraits);
        Assert.True(active.TryReadPortrait(PortraitRuntimeFixtures.Key, out var image)); Assert.NotNull(image);
        var player = new Lala.Core.Protocol.WorldPlayer(1,2,1,0,0,0,0,0,444444444,444444444,0,false,[],"owned",0);
        Assert.True(active.TrySelectPortrait(player,Lala.Core.Inventory.CompanionReceiveSnapshot.Empty,false,out var selection,out var selected));
        Assert.Equal(PortraitRuntimeFixtures.Key,selection!.Key); Assert.Same(image,selected);
        Assert.False(new ResourceRuntimeActivation(owner,publication).TrySelectPortrait(player,Lala.Core.Inventory.CompanionReceiveSnapshot.Empty,false,out _,out _));
        Assert.False(active.TryReadPortrait(new("player","9999"), out _));
        Assert.False(new ResourceRuntimeActivation(owner, publication).TryReadPortrait(PortraitRuntimeFixtures.Key, out _));
        var first = image!.CopyBasePng(); Array.Fill(first,(byte)0); Assert.NotEqual(first,image.CopyBasePng());
        if (retirement == "invalidate") owner.Invalidate();
        else if (retirement == "dispose") await owner.DisposeAsync();
        else await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(new(true)));
        Assert.False(active.HasPortraits); Assert.False(active.TryReadPortrait(PortraitRuntimeFixtures.Key, out image)); Assert.Null(image);
        Assert.False(active.TrySelectPortrait(player,Lala.Core.Inventory.CompanionReceiveSnapshot.Empty,false,out selection,out selected));
        Assert.Null(selection); Assert.Null(selected);
    }
    [Fact]
    public async Task Corrupt_portrait_cache_is_not_repaired_by_refresh()
    {
        using var fixture = new Fixture();
        var hooks = new ResourceRuntimeBootstrapTestHooks { PortraitsForOfflineTest = _ => PortraitRuntimeFixtures.Batch() };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        Assert.Null((await owner.BootstrapAndRefreshAsync()).Failure);
        string path = Path.Combine(fixture.Root,"official_sync","derived_catalogs","core_portraits_v1.sqlite3");
        using (var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource=path,Pooling=false }.ToString()))
        { db.Open(); using var command=db.CreateCommand(); command.CommandText="UPDATE portrait_png_v1 SET base_png=zeroblob(16)"; command.ExecuteNonQuery(); }
        byte[] before = File.ReadAllBytes(path);
        var result = await owner.RefreshWithResultAsync(); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted,result.PortraitStorageOutcome); Assert.Equal(before,File.ReadAllBytes(path));
    }

    [Fact]
    public async Task Emoji_batch_writes_independently_reads_and_offline_owner_cannot_admit()
    {
        using var fixture = new Fixture();
        int builds = 0;
        var hooks = new ResourceRuntimeBootstrapTestHooks { EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch(() => { builds++; return 255; }) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Null(result.Failure); Assert.Equal(AccountResourceStorageOutcome.Committed, result.EmojiStorageOutcome);
        Assert.NotNull(result.Publication!.Emojis); Assert.Equal(3, builds);
        Assert.False(owner.TryActivate(result.Publication, out _));
        var refresh = await owner.RefreshWithResultAsync();
        Assert.Null(refresh.Failure); Assert.NotNull(refresh.Publication!.Emojis);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, refresh.EmojiStorageOutcome); Assert.Equal(5, builds);
    }
    [Fact]
    public async Task Missing_emoji_cache_refresh_is_readonly_and_unreviewed_sources_are_absent()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var hooks = new ResourceRuntimeBootstrapTestHooks { EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch() };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks);
        var result = await owner.RefreshWithResultAsync();
        Assert.Null(result.Failure); Assert.Null(result.Publication!.Emojis);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.EmojiStorageOutcome);
        Assert.False(File.Exists(Path.Combine(fixture.Root,"official_sync","derived_catalogs","core_emojis_v1.sqlite3")));
    }
    [Theory, InlineData(false), InlineData(true)]
    public async Task Emoji_retirement_or_source_drift_preserves_exact_storage_outcome(bool drift)
    {
        using var fixture = new Fixture(); var source = new Source(); ResourceRuntimeOwner? owner = null;
        var hooks = new ResourceRuntimeBootstrapTestHooks
        {
            EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch(),
            BeforeEmojiCommitAdmission = () =>
            {
                if (drift) { var main = BundleSourceFixtures.Index("main-valid"); main["header"]!["package_note"] = "changed"; source.Main = BundleSourceFixtures.Encode(main); }
                else owner!.Invalidate();
            }
        };
        await using (owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks))
        {
            var result = await owner.BootstrapAndRefreshAsync(); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
            Assert.Equal(drift ? AccountResourceStorageOutcome.Committed : AccountResourceStorageOutcome.NotCommitted, result.EmojiStorageOutcome);
        }
    }
    [Fact]
    public async Task Emoji_pixel_drift_between_preparation_and_write_blocks_publication()
    {
        using var fixture = new Fixture(); int calls = 0;
        var hooks = new ResourceRuntimeBootstrapTestHooks { EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch(() => ++calls) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.NotNull(result.Failure); Assert.Null(result.Publication);
        Assert.Equal(AccountResourceStorageOutcome.NotCommitted, result.EmojiStorageOutcome);
    }
    [Theory, InlineData("invalidate"), InlineData("dispose"), InlineData("refresh")]
    public async Task Emoji_reads_require_exact_activation_and_revoke(string retirement)
    {
        using var fixture = new Fixture();
        var hooks = new ResourceRuntimeBootstrapTestHooks { EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch() };
        await using var offline = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        var result = await offline.BootstrapAndRefreshAsync(); Assert.Null(result.Failure);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var emojis = result.Publication!.Emojis!;
        var publication = new ResourceRuntimePublication(owner, 0, prepared, emojis: emojis);
        // White-box lifetime fixture only; this does not assert official acquisition or acceptance.
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        Assert.True(owner.TryActivate(publication, out var active)); Assert.True(active!.HasEmojis);
        Assert.True(active.TryReadEmoji(1, out var image)); Assert.NotNull(image);
        var session=new AccountSession();var snapshot=session.Begin("owned","offline");
        Assert.True(AccountResourceBinding.TryBind(session,snapshot.Generation,owner,publication,out var binding));
        Assert.True(binding!.TryReadEmoji(1,out _));Assert.False(binding.CanSendPackets);
        session.Hold(snapshot.Generation);Assert.False(binding.TryReadEmoji(1,out var retired));Assert.Null(retired);
        Assert.True(active.TryReadEmoji(1,out _)); // Account replacement does not revoke unrelated owner readers.

        Assert.False(active.TryReadEmoji(0, out _));
        Assert.False(new ResourceRuntimeActivation(owner, publication).TryReadEmoji(1, out _));
        image![0]=0; Assert.True(active.TryReadEmoji(1,out var fresh)); Assert.Equal(137,fresh![0]);
        if (retirement == "invalidate") owner.Invalidate();
        else if (retirement == "dispose") await owner.DisposeAsync();
        else await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(new(true)));
        Assert.False(active.HasEmojis); Assert.False(active.TryReadEmoji(1, out image)); Assert.Null(image);
    }
    [Fact]
    public async Task Corrupt_emoji_cache_is_not_repaired_by_refresh()
    {
        using var fixture = new Fixture();
        var hooks = new ResourceRuntimeBootstrapTestHooks { EmojisForOfflineTest = _ => EmojiRuntimeFixtures.Batch() };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source(), bootstrapHooks: hooks);
        Assert.Null((await owner.BootstrapAndRefreshAsync()).Failure);
        string path = Path.Combine(fixture.Root,"official_sync","derived_catalogs","core_emojis_v1.sqlite3");
        using (var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource=path,Pooling=false }.ToString()))
        { db.Open(); using var command=db.CreateCommand(); command.CommandText="UPDATE emoji_frames_v1 SET png=zeroblob(16)"; command.ExecuteNonQuery(); }
        byte[] before = File.ReadAllBytes(path);
        var result = await owner.RefreshWithResultAsync(); Assert.NotNull(result.Failure); Assert.Null(owner.Current);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted,result.EmojiStorageOutcome); Assert.Equal(before,File.ReadAllBytes(path));
    }

    [Fact]
    public async Task Readonly_refresh_does_not_create_a_missing_item_image_cache()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var hooks = new ResourceRuntimeBootstrapTestHooks { ItemImagesForOfflineTest = p => ImageBatchFixtures.Batch(p.Identity.Key) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks);
        var result = await owner.RefreshWithResultAsync();
        Assert.Null(result.Failure); Assert.Null(result.Publication!.ItemImages);
        Assert.Equal(AccountResourceStorageOutcome.NotAttempted, result.ItemImageStorageOutcome);
        Assert.False(File.Exists(Path.Combine(fixture.Root, "official_sync", "derived_catalogs", "core_item_images_v1.sqlite3")));
    }
    [Fact]
    public async Task Unreviewed_item_fields_do_not_fetch_or_publish_image_candidates()
    {
        var source = new Source(); var main = BundleSourceFixtures.Index("main-valid");
        main["assets"]![0]!["path"] = ItemImageMapping.Prefix + "s1000.png";
        source.Main = BundleSourceFixtures.Encode(main);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Null(prepared.ItemImages);
        Assert.All(prepared.VerifiedSources, handle => Assert.Equal("DataPackage", handle.Spec.Package));
    }
    [Fact]
    public async Task Owned_image_batch_is_written_read_back_but_offline_owner_never_admits()
    {
        using var fixture = new Fixture(); var source = new Source();
        var hooks = new ResourceRuntimeBootstrapTestHooks { ItemImagesForOfflineTest = p => ImageBatchFixtures.Batch(p.Identity.Key) };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks);
        var result = await owner.BootstrapAndRefreshAsync();
        Assert.Null(result.Failure); Assert.Equal(AccountResourceStorageOutcome.Committed, result.ItemImageStorageOutcome);
        Assert.NotNull(result.Publication!.ItemImages); Assert.False(result.Publication.ResourceAdmitted);
        Assert.False(owner.TryActivate(result.Publication, out _));
        var refreshed = await owner.RefreshWithResultAsync();
        Assert.Null(refreshed.Failure); Assert.Equal(AccountResourceStorageOutcome.NotAttempted, refreshed.ItemImageStorageOutcome);
        Assert.NotNull(refreshed.Publication!.ItemImages);
    }
    [Theory, InlineData(false), InlineData(true)]
    public async Task Image_retirement_or_source_change_prevents_publication_and_preserves_write_outcome(bool changeAfterCommit)
    {
        using var fixture = new Fixture(); var source = new Source(); ResourceRuntimeOwner? owner = null;
        var hooks = new ResourceRuntimeBootstrapTestHooks
        {
            ItemImagesForOfflineTest = p => ImageBatchFixtures.Batch(p.Identity.Key),
            BeforeImageCommitAdmission = () =>
            {
                if (changeAfterCommit)
                {
                    var main = BundleSourceFixtures.Index("main-valid"); main["header"]!["package_note"] = "changed";
                    source.Main = BundleSourceFixtures.Encode(main);
                }
                else owner!.Invalidate();
            }
        };
        await using (owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, bootstrapHooks: hooks))
        {
            var result = await owner.BootstrapAndRefreshAsync();
            Assert.NotNull(result.Failure); Assert.Null(owner.Current);
            Assert.Equal(changeAfterCommit ? AccountResourceStorageOutcome.Committed : AccountResourceStorageOutcome.NotCommitted, result.ItemImageStorageOutcome);
        }
    }
    [Fact]
    public async Task Item_image_reads_require_exact_activation_and_revoke_with_owner()
    {
        using var fixture = new Fixture(); var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        var batch = ImageBatchFixtures.Batch();
        var readback = new ItemImageReadback(batch, batch.Pixels.ToDictionary(p => p.Context.AssetPath, p => SpritePng.Encode(p)));
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared, itemImages: readback);
        // Existing white-box admission seam tests lifetime only, not official provenance.
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        Assert.True(owner.TryActivate(publication, out var active)); Assert.True(active!.HasItemImages);
        Assert.True(active.TryReadItemImage(1, out var png)); Assert.NotNull(png);
        Assert.False(new ResourceRuntimeActivation(owner, publication).TryReadItemImage(1, out _));
        owner.Invalidate(); Assert.False(active.HasItemImages); Assert.False(active.TryReadItemImage(1, out png)); Assert.Null(png);
    }

    [Fact]
    public async Task Real_database_match_is_published_but_offline_success_never_admits()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var publication = await owner.RefreshAsync();
        Assert.Same(publication, owner.Current);
        Assert.Equal(8, source.Observations); // Six preparation observations plus two after DB read.
        Assert.False(publication.ResourceAdmitted); Assert.False(publication.TlsOriginObserved);
        Assert.False(publication.CanLogin); Assert.False(publication.CanSendPackets);
        Assert.False(publication.Candidate.RuntimeAdmitted);
        owner.Invalidate(); Assert.Null(owner.Current);
        var next = await owner.RefreshAsync(); Assert.True(next.Generation > publication.Generation);
    }
    [Fact]
    public async Task Missing_inventory_fails_without_creating_database_or_publication()
    {
        using var fixture = new Fixture();
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, new Source());
        await Assert.ThrowsAnyAsync<Exception>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.False(File.Exists(fixture.Inventory));
    }
    [Theory]
    [InlineData("Eve.bytes")]
    [InlineData("NpcData_C.bytes")]
    [InlineData("ItemData_C.bytes")]
    public async Task Stored_blob_tampering_is_rejected_even_when_recorded_hash_is_unchanged(string table)
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        { DataSource = fixture.Inventory, Pooling = false }.ToString()))
        {
            connection.Open(); using var command = connection.CreateCommand();
            command.CommandText = "UPDATE resources SET data=x'00000000' WHERE name=@name";
            command.Parameters.AddWithValue("@name", table);
            Assert.Equal(1, command.ExecuteNonQuery());
        }
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        await Assert.ThrowsAsync<ResourceValidationException>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.Equal(6, source.Observations);
    }
    [Fact]
    public async Task Same_version_manifest_replacement_after_database_read_is_rejected()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        source.BeforeObserve = n =>
        {
            if (n == 7) source.Data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]>
                { ["replacement.bundle"] = source.Bundle });
            return Task.CompletedTask;
        };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => owner.RefreshAsync());
        Assert.Equal(BundleSourceFailure.ManifestChanged, error.Failure); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Cancellation_after_database_read_prevents_publication()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        using var cancel = new CancellationTokenSource();
        source.BeforeObserve = n => { if (n == 7) cancel.Cancel(); return Task.CompletedTask; };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancel.Token));
        Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Already_cancelled_caller_cannot_enter_source_or_admission_hook()
    {
        using var fixture = new Fixture(); var source = new Source();
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        int hooks = 0;
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            () => { hooks++; return Task.CompletedTask; });
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancellation.Token).WaitAsync(TestTimeout));
        Assert.Equal(0, hooks); Assert.Equal(0, source.Observations); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Refresh_flood_is_rejected_until_cancelled_operation_finishes_retirement()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.BeforeObserve = async n => { if (n == 1) { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); } };
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var first = owner.RefreshAsync();
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            owner.Invalidate(); Assert.Null(owner.Current);
            for (int i = 0; i < 100; i++)
                await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            Assert.Equal(1, source.Observations);
        }
        finally { release.TrySetResult(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first.WaitAsync(TestTimeout));
        source.BeforeObserve = null;
        var next = await owner.RefreshAsync().WaitAsync(TestTimeout); Assert.Same(next, owner.Current);
    }
    [Fact]
    public async Task Disposal_waits_for_retirement_and_never_publishes_late_results()
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        source.BeforeObserve = async _ => { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); };
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var first = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask(); Assert.False(disposal.IsCompleted);
            Assert.Null(owner.Current);
        }
        finally { release.TrySetResult(); disposal ??= owner.DisposeAsync().AsTask(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => first.WaitAsync(TestTimeout));
        await disposal.WaitAsync(TestTimeout); Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Disposal_joins_admitted_attempt_before_first_source_operation()
    {
        using var fixture = new Fixture(); var source = new Source();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source, async () =>
        { entered.TrySetResult(); await release.Task.WaitAsync(TestTimeout); });
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await entered.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask();
            Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals); Assert.Equal(0, source.Observations);
        }
        finally { release.TrySetResult(); disposal ??= owner.DisposeAsync().AsTask(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => refresh.WaitAsync(TestTimeout));
        await disposal.WaitAsync(TestTimeout); Assert.Equal(1, source.Disposals); Assert.Equal(0, source.Observations);
    }
    [Fact]
    public async Task Blocked_reentrant_throwing_callback_is_joined_before_retirement_and_disposal()
    {
        using var fixture = new Fixture(); var source = new Source();
        using var callbackRelease = new ManualResetEventSlim();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntered = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            cleanupEntered: () => cleanupEntered.TrySetResult());
        source.OnToken = token => token.Register(() =>
        {
            bool revoked = owner.Current is null;
            owner.Invalidate();
            callbackEntered.TrySetResult(revoked);
            if (!callbackRelease.Wait(TestTimeout)) throw new TimeoutException("Callback release timed out");
            throw new InvalidOperationException("callback failure");
        });
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            owner.Invalidate(); Assert.True(await callbackEntered.Task.WaitAsync(TestTimeout));
            observeRelease.TrySetResult(); await cleanupEntered.Task.WaitAsync(TestTimeout);
            await Assert.ThrowsAsync<InvalidOperationException>(() => owner.RefreshAsync());
            disposal = owner.DisposeAsync().AsTask();
            Assert.Same(disposal, owner.DisposeAsync().AsTask());
            Assert.False(refresh.IsCompleted); Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        finally { callbackRelease.Set(); observeRelease.TrySetResult(); }
        var refreshFailure = await Assert.ThrowsAnyAsync<Exception>(() => refresh.WaitAsync(TestTimeout));
        var disposalFailure = await Assert.ThrowsAnyAsync<Exception>(() => disposal!.WaitAsync(TestTimeout));
        Assert.Contains(Failures(refreshFailure), e => e is InvalidOperationException && e.Message == "callback failure");
        Assert.Contains(Failures(disposalFailure), e => e is InvalidOperationException && e.Message == "callback failure");
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData(0, false)]
    [InlineData(1, false)]
    [InlineData(2, false)]
    [InlineData(0, true)]
    [InlineData(1, true)]
    [InlineData(2, true)]
    public async Task Callback_self_disposal_rejects_join_while_external_disposal_waits_for_retirement(int registration, bool externalFirst)
    {
        using var fixture = new Fixture(); var source = new Source();
        using var callbackRelease = new ManualResetEventSlim();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackObserved = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var cleanupEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source,
            cleanupEntered: () => cleanupEntered.TrySetResult());
        source.OnToken = token => Register(token, registration, () =>
        {
            Exception? failure = null;
            try { owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult(); }
            catch (Exception error) { failure = error; }
            callbackObserved.TrySetResult(failure);
            if (!callbackRelease.Wait(TestTimeout)) throw new TimeoutException("Callback release timed out");
        });
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            if (externalFirst) disposal = owner.DisposeAsync().AsTask();
            else owner.Invalidate();
            var failure = Assert.IsType<InvalidOperationException>(await callbackObserved.Task.WaitAsync(TestTimeout));
            Assert.Contains("own active operation", failure.Message);
            disposal ??= owner.DisposeAsync().AsTask();
            var joins = await Task.WhenAll(Enumerable.Range(0, 8)
                .Select(_ => Task.Run(() => (object)owner.DisposeAsync().AsTask()))).WaitAsync(TestTimeout);
            Assert.All(joins, join => Assert.Same(disposal, join));
            Assert.Null(owner.Current);
            observeRelease.TrySetResult(); await cleanupEntered.Task.WaitAsync(TestTimeout);
            Assert.False(refresh.IsCompleted); Assert.False(disposal.IsCompleted); Assert.Equal(0, source.Disposals);
        }
        finally { callbackRelease.Set(); observeRelease.TrySetResult(); }
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => refresh.WaitAsync(TestTimeout));
        await disposal!.WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
        await Assert.ThrowsAsync<ObjectDisposedException>(() => owner.RefreshAsync());
    }
    [Fact]
    public async Task Uncaught_callback_self_disposal_failure_is_reported_after_cleanup()
    {
        using var fixture = new Fixture(); var source = new Source();
        var observing = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var observeRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        source.OnToken = token => token.Register(() =>
            owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult());
        source.BeforeObserve = async _ => { observing.TrySetResult(); await observeRelease.Task.WaitAsync(TestTimeout); };
        var refresh = owner.RefreshAsync();
        Task? disposal = null;
        try
        {
            await observing.Task.WaitAsync(TestTimeout);
            disposal = owner.DisposeAsync().AsTask();
        }
        finally { observeRelease.TrySetResult(); }
        var refreshFailure = await Assert.ThrowsAnyAsync<Exception>(() => refresh.WaitAsync(TestTimeout));
        var disposalFailure = await Assert.ThrowsAnyAsync<Exception>(() => disposal!.WaitAsync(TestTimeout));
        Assert.Contains(Failures(refreshFailure), e => e is InvalidOperationException && e.Message.Contains("own active operation"));
        Assert.Contains(Failures(disposalFailure), e => e is InvalidOperationException && e.Message.Contains("own active operation"));
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Source_self_disposal_rejects_join_without_completing_external_cleanup(bool asynchronous)
    {
        using var fixture = new Fixture(); Source source = asynchronous ? new AsyncSource() : new Source();
        using var sourceRelease = new ManualResetEventSlim();
        var reentry = new TaskCompletionSource<Exception?>(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        source.OnDispose = () =>
        {
            Exception? failure = null;
            try { owner.DisposeAsync().AsTask().WaitAsync(TestTimeout).GetAwaiter().GetResult(); }
            catch (Exception error) { failure = error; }
            reentry.TrySetResult(failure);
            if (!sourceRelease.Wait(TestTimeout)) throw new TimeoutException("Source release timed out");
        };
        var firstDisposal = Task.Run(async () => await owner.DisposeAsync());
        Task? disposal = null;
        try
        {
            var failure = Assert.IsType<InvalidOperationException>(await reentry.Task.WaitAsync(TestTimeout));
            Assert.Contains("own active operation", failure.Message);
            disposal = owner.DisposeAsync().AsTask();
            Assert.Same(disposal, owner.DisposeAsync().AsTask());
            Assert.False(firstDisposal.IsCompleted); Assert.False(disposal.IsCompleted);
            Assert.Equal(1, source.Disposals);
        }
        finally { sourceRelease.Set(); }
        await firstDisposal.WaitAsync(TestTimeout); await disposal!.WaitAsync(TestTimeout);
        await owner.DisposeAsync().AsTask().WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals);
    }
    [Fact]
    public async Task Captured_operation_context_can_join_disposal_after_real_retirement()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        Task? lateDisposal = null;
        source.BeforeObserve = n =>
        {
            if (n == 1) lateDisposal = Task.Run(async () =>
            {
                await release.Task.WaitAsync(TestTimeout);
                await owner.DisposeAsync();
            });
            return Task.CompletedTask;
        };
        try { await owner.RefreshAsync().WaitAsync(TestTimeout); }
        finally { release.TrySetResult(); }
        await lateDisposal!.WaitAsync(TestTimeout);
        Assert.Equal(1, source.Disposals); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Failed_retry_revokes_prior_publication_and_fabricated_publications_never_admit()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var prior = await owner.RefreshAsync();
        File.Delete(fixture.Inventory);
        await Assert.ThrowsAnyAsync<Exception>(() => owner.RefreshAsync());
        Assert.Null(owner.Current); Assert.False(prior.ResourceAdmitted);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var production = ResourceRuntimeOwner.Create(fixture.Root);
        var fabricated = new ResourceRuntimePublication(production, prior.Generation, prepared);
        Assert.False(fabricated.ResourceAdmitted); Assert.False(fabricated.TlsOriginObserved);
        Assert.False(production.IsCurrentAdmission(prior));
        Assert.False(owner.IsCurrentAdmission(fabricated));
        production.Invalidate(); Assert.False(fabricated.ResourceAdmitted);
    }
    [Fact]
    public async Task Offline_current_publication_and_fabricated_handles_cannot_activate_catalogs()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var publication = await owner.RefreshAsync();
        Assert.False(owner.TryActivate(publication, out var activation)); Assert.Null(activation);
        Assert.False(owner.TryActivate(null, out activation)); Assert.Null(activation);
        var fabricated = new ResourceRuntimeActivation(owner, publication);
        Assert.Equal(publication.Generation, fabricated.Generation);
        Assert.Same(publication.Identity, fabricated.Identity);
        Assert.False(fabricated.IsActive);
        Assert.False(fabricated.TryReadCatalogs(out var catalogs)); Assert.Null(catalogs);
        Assert.False(fabricated.CanLogin); Assert.False(fabricated.CanSendPackets);
        await using var other = ResourceRuntimeOwner.Create(fixture.Root);
        Assert.False(other.TryActivate(publication, out activation)); Assert.Null(activation);
        var crossOwner = new ResourceRuntimeActivation(other, publication);
        Assert.False(crossOwner.IsActive);
        Assert.False(crossOwner.TryReadCatalogs(out catalogs)); Assert.Null(catalogs);
        owner.Invalidate();
        Assert.False(owner.TryActivate(publication, out activation)); Assert.Null(activation);
        Assert.False(fabricated.TryReadCatalogs(out catalogs)); Assert.Null(catalogs);
        var next = await owner.RefreshAsync();
        Assert.True(next.Generation > publication.Generation);
        Assert.False(owner.TryActivate(publication, out activation)); Assert.Null(activation);
        Assert.False(owner.TryActivate(next, out activation)); Assert.Null(activation);
        await owner.DisposeAsync();
        Assert.False(owner.TryActivate(next, out activation)); Assert.Null(activation);
    }
    [Theory]
    [InlineData("begin")]
    [InlineData("disconnect")]
    [InlineData("hold")]
    [InlineData("confirm")]
    [InlineData("receive")]
    [InlineData("invalidate")]
    [InlineData("dispose")]
    [InlineData("refresh")]
    public async Task Account_resource_binding_retires_on_either_owner_lifecycle(string change)
    {
        using var fixture = new Fixture();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        // Test-only admitted-state setup. This proves binding mechanics, not production trust.
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        var session = new AccountSession();
        var snapshot = session.Begin("synthetic-account", "synthetic-endpoint");
        Assert.True(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, publication, out var binding));
        Assert.NotNull(binding); Assert.True(binding.IsCurrent);
        Assert.Equal(snapshot.Generation, binding.AccountGeneration);
        Assert.Equal(publication.Generation, binding.ResourceGeneration); Assert.Same(publication.Identity, binding.Identity);
        Assert.True(binding.TryReadCatalogs(out var catalogs)); Assert.Same(publication.Candidate, catalogs);
        Assert.Same(snapshot, session.Snapshot); Assert.Equal(SessionPhase.Preparing, session.Snapshot.Phase);
        Assert.False(binding.CanLogin); Assert.False(binding.CanSendPackets);
        switch (change)
        {
            case "begin": session.Begin("synthetic-account", "synthetic-endpoint"); break;
            case "disconnect": session.Disconnect(); break;
            case "hold": session.Hold(snapshot.Generation); break;
            case "confirm": session.ConfirmResources(snapshot.Generation, "synthetic", "synthetic", true); break;
            case "receive":
                await using (var receive = session.AttachHeldReceive(snapshot.Generation, new EmptyReceiveTransport(),
                    0xAD, () => 0, (_, now) => new(now))) Assert.NotNull(receive);
                break;
            case "invalidate": owner.Invalidate(); break;
            case "dispose": await owner.DisposeAsync(); break;
            case "refresh":
                using (var cancelled = new CancellationTokenSource())
                {
                    cancelled.Cancel();
                    await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancelled.Token));
                }
                break;
        }
        Assert.False(binding.IsCurrent); Assert.False(binding.TryReadCatalogs(out catalogs)); Assert.Null(catalogs);
        Assert.False(Directory.Exists(fixture.Root));
    }
    private sealed class EmptyReceiveTransport : Lala.Core.Sessions.Receive.IReceiveTransport
    {
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken cancellationToken)
            => ValueTask.FromResult(0);
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    [Fact]
    public async Task Account_resource_binding_requires_explicit_rebind_after_resource_replacement()
    {
        using var fixture = new Fixture();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var currentField = typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!;
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        currentField.SetValue(owner, publication); // Test state only; no production trust claim.
        var session = new AccountSession(); var snapshot = session.Begin("synthetic", "synthetic");
        Assert.True(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, publication, out var prior));
        Assert.NotNull(prior);
        owner.Invalidate();
        var replacement = new ResourceRuntimePublication(owner, 1, prepared);
        currentField.SetValue(owner, replacement);
        Assert.False(prior.IsCurrent); Assert.False(prior.TryReadCatalogs(out _));
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, publication, out var rejected));
        Assert.Null(rejected);
        Assert.True(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, replacement, out var next));
        Assert.NotNull(next); Assert.True(next.TryReadCatalogs(out _)); Assert.True(next.ResourceGeneration > prior.ResourceGeneration);
        Assert.Same(snapshot, session.Snapshot); Assert.False(next.CanSendPackets);
    }
    [Fact]
    public async Task Account_resource_binding_rejects_disconnected_wrong_generation_and_untrusted_publications()
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        await using var offline = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var observed = await offline.RefreshAsync();
        var session = new AccountSession(); var snapshot = session.Begin("synthetic", "synthetic");
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation, offline, observed, out var binding));
        Assert.Null(binding); Assert.Same(snapshot, session.Snapshot);
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, publication, out binding));
        Assert.Null(binding);
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation + 1, owner, publication, out binding));
        Assert.Null(binding);
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, observed, out binding));
        Assert.Null(binding);
        Assert.False(AccountResourceBinding.TryBind(session, snapshot.Generation, owner, null, out binding));
        Assert.Null(binding);
        session.Disconnect();
        Assert.False(AccountResourceBinding.TryBind(session, session.Snapshot.Generation, owner, publication, out binding));
        Assert.Null(binding);
    }
    [Fact]
    public async Task Held_account_binding_is_read_only_and_other_accounts_cannot_keep_retired_binding_alive()
    {
        using var fixture = new Fixture();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        var first = new AccountSession(); var second = new AccountSession();
        long generation = first.Begin("first", "synthetic").Generation;
        first.Hold(generation); second.Begin("second", "synthetic");
        Assert.True(AccountResourceBinding.TryBind(first, generation, owner, publication, out var firstBinding));
        Assert.True(AccountResourceBinding.TryBind(second, second.Snapshot.Generation, owner, publication, out var secondBinding));
        Assert.NotNull(firstBinding); Assert.NotNull(secondBinding);
        Assert.Equal(SessionPhase.Held, first.Snapshot.Phase);
        first.Hold(generation); // Same generation and phase still replace the lifecycle snapshot.
        Assert.False(firstBinding.IsCurrent); Assert.False(firstBinding.TryReadCatalogs(out _));
        Assert.True(secondBinding.IsCurrent); Assert.True(secondBinding.TryReadCatalogs(out _));
        Assert.True(AccountResourceBinding.TryBind(first, generation, owner, publication, out var rebound));
        Assert.NotNull(rebound); Assert.True(rebound.IsCurrent);
        Assert.Equal(SessionPhase.Held, first.Snapshot.Phase);
        Assert.False(rebound.CanSendPackets); Assert.False(rebound.CanLogin);
    }
    [Theory]
    [InlineData("invalidate")]
    [InlineData("dispose")]
    [InlineData("refresh")]
    public async Task Activation_state_machine_reuses_selection_and_revokes_on_retirement(string retirement)
    {
        using var fixture = new Fixture();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        // White-box state-machine fixture ONLY. No production injection API is introduced,
        // no HTTP is performed, and this does not establish production acquisition or trust.
        typeof(ResourceRuntimeOwner).GetField("_current", System.Reflection.BindingFlags.NonPublic |
            System.Reflection.BindingFlags.Instance)!.SetValue(owner, publication);
        Assert.False(owner.IsCurrentAdmission(null));
        Assert.False(owner.IsCurrentActivation(null!, publication));
        Assert.False(owner.TryReadActivatedCatalogs(null!, publication, out var absent)); Assert.Null(absent);
        Assert.True(owner.TryActivate(publication, out var selected)); Assert.NotNull(selected);
        Assert.True(selected.IsActive);
        Assert.True(selected.TryReadCatalogs(out var catalogs)); Assert.Same(publication.Candidate, catalogs);
        Assert.True(owner.TryActivate(publication, out var repeated)); Assert.Same(selected, repeated);
        var fabricated = new ResourceRuntimeActivation(owner, publication);
        Assert.False(fabricated.IsActive); Assert.False(fabricated.TryReadCatalogs(out _));
        var different = new ResourceRuntimePublication(owner, 0, prepared);
        Assert.False(owner.TryActivate(different, out var rejected)); Assert.Null(rejected);
        Assert.True(selected.IsActive); // Failed stale selection must not revoke the real one.
        Assert.False(selected.CanLogin); Assert.False(selected.CanSendPackets);
        if (retirement == "invalidate") owner.Invalidate();
        else if (retirement == "dispose") await owner.DisposeAsync();
        else
        {
            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => owner.RefreshAsync(cancelled.Token));
        }
        Assert.Null(owner.Current); Assert.False(selected.IsActive);
        Assert.False(selected.TryReadCatalogs(out catalogs)); Assert.Null(catalogs);
        Assert.False(owner.TryActivate(publication, out rejected)); Assert.Null(rejected);
        Assert.False(Directory.Exists(fixture.Root));
    }
    [Fact]
    public async Task Fabricated_production_publication_cannot_activate_or_read_catalogs()
    {
        using var fixture = new Fixture();
        var prepared = await new OfflineBundleRuntimePreparation().PrepareAsync(new Source());
        await using var owner = ResourceRuntimeOwner.Create(fixture.Root);
        var publication = new ResourceRuntimePublication(owner, 0, prepared);
        Assert.False(owner.TryActivate(publication, out var activation)); Assert.Null(activation);
        var fabricated = new ResourceRuntimeActivation(owner, publication);
        Assert.False(fabricated.IsActive);
        Assert.False(fabricated.TryReadCatalogs(out var catalogs)); Assert.Null(catalogs);
        owner.Invalidate();
        Assert.False(owner.TryActivate(publication, out activation)); Assert.Null(activation);
        Assert.False(Directory.Exists(fixture.Root));
    }
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Post_database_full_version_or_executable_drift_prevents_publication(bool executable)
    {
        using var fixture = new Fixture(); var source = new Source(); await fixture.PopulateAsync(source);
        source.Snapshot = n => n < 7 ? RuntimeFlowFixtures.Snapshot() : executable
            ? OfficialVersionSnapshot.Parse(Encoding.UTF8.GetBytes(System.Text.Json.JsonSerializer.Serialize(new
            {
                schema_version = 1, origin = "official_pc_version_endpoint", data_ver = "1.3.21", exe_version = "1.4.0",
                packages = new { DataPackage = RuntimeFlowFixtures.Version,
                    MainPackage = BundleSourceFixtures.Case("main-valid").Text("package_version") },
                checked_at_utc = "2026-01-02T03:04:05Z", assets_ready = false
            })))
            : RuntimeFlowFixtures.Snapshot(packageVersion: "1286_2026_10_29_13_42_37_95");
        await using var owner = ResourceRuntimeOwner.CreateForOfflineTests(fixture.Root, source);
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => owner.RefreshAsync());
        Assert.Equal(BundleSourceFailure.VersionsChanged, error.Failure); Assert.Null(owner.Current);
    }
    [Fact]
    public async Task Production_construction_is_lazy_and_disposal_revokes_without_io()
    {
        using var fixture = new Fixture();
        var owner = ResourceRuntimeOwner.Create(fixture.Root);
        Assert.Null(owner.Current); Assert.False(Directory.Exists(fixture.Root));
        await owner.DisposeAsync(); await owner.DisposeAsync();
        await Assert.ThrowsAsync<ObjectDisposedException>(() => owner.RefreshAsync());
        Assert.False(Directory.Exists(fixture.Root));
        Assert.Throws<ArgumentException>(() => ResourceRuntimeOwner.Create("relative"));
    }
}
