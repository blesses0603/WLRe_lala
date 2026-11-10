using System.Text;
using System.Text.Json.Nodes;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class BundleSourcePreparationTests
{
    [Fact]
    public async Task Required_progress_counts_only_verified_sources_and_clears_counts_for_recheck()
    {
        var state = new ResourceProgressState();
        var observed = new List<ResourcePreparationProgress>();
        var script = new Script { DuringRead = () => observed.Add(state.Snapshot) };
        var prepared = await new BundleSourcePreparation().PrepareAsync(script, progress: state);
        var measured = observed.Where(x => x.Total is not null).ToArray();
        Assert.NotEmpty(measured);
        Assert.All(measured, x => { Assert.Equal(prepared.Plan.Entries.Count, x.Total); Assert.InRange(x.Completed!.Value, 0, x.Total!.Value); });
        Assert.Equal(0, measured[0].Completed);
        Assert.True(measured.Select(x=>x.Completed!.Value).SequenceEqual(measured.Select(x=>x.Completed!.Value).OrderBy(x=>x)));
        Assert.Null(state.Snapshot.Total);
    }
    [Fact]
    public void Terminal_progress_cannot_be_resurrected_and_invalid_counts_are_rejected()
    {
        var state = new ResourceProgressState();
        Assert.Throws<ArgumentOutOfRangeException>(()=>state.Set("bad",2,1));
        state.Set("cancelled",finished:true); state.Set("late",1,1);
        Assert.Equal("cancelled",state.Snapshot.Phase); Assert.True(state.Snapshot.IsFinished);
    }
    private sealed class Script : IResourceSource
    {
        internal readonly List<string> Requests = [];
        internal readonly List<TrackingStream> Streams = [];
        internal int Observations;
        internal readonly Dictionary<string, byte[]> Extra = new();
        internal Func<int, OfficialVersionSnapshot> Observe = _ => BundleSourceFixtures.Snapshot();
        internal Func<string, int, byte[], byte[]> Mutate = (_, _, bytes) => bytes;
        internal Func<string, ResourceResponse, ResourceResponse> Response = (_, response) => response;
        internal Func<string, Task>? BeforeOpen;
        internal Action? DuringRead;
        internal int ChunkSize = 7;
        internal byte[] Data = BundleSourceFixtures.Bytes("data-valid"), Main = BundleSourceFixtures.Bytes("main-valid");
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token) => ValueTask.FromResult(Observe(++Observations));
        public async ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token)
        {
            Requests.Add(url);
            if (BeforeOpen is not null) await BeforeOpen(url);
            string name = url[(url.LastIndexOf('/') + 1)..];
            byte[] body = name switch
            {
                "DataPackage.bytes" => Data.ToArray(), "MainPackage.bytes" => Main.ToArray(),
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                _ => Extra.TryGetValue(name, out var extra) ? extra.ToArray() : BundleSourceFixtures.Payload(name)
            };
            body = Mutate(name, Requests.Count(x => x == url), body);
            var stream = new TrackingStream(body, ChunkSize, () => DuringRead?.Invoke()); Streams.Add(stream);
            return Response(name, new(url, 200, body.Length.ToString(System.Globalization.CultureInfo.InvariantCulture), stream));
        }
    }
    private sealed class TrackingStream(byte[] bytes, int chunkSize, Action? duringRead = null) : MemoryStream(bytes, writable: false)
    {
        internal bool Disposed;
        internal int Reads;
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            Reads++; duringRead?.Invoke();
            return base.ReadAsync(buffer[..Math.Min(buffer.Length, chunkSize)], cancellationToken);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
    private sealed class Cache(Func<BundleSourceSpec, int, byte[]?> read) : IBundleSourceCacheReader
    {
        private readonly Dictionary<string, int> _reads = new();
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            int count = _reads.GetValueOrDefault(spec.Name) + 1; _reads[spec.Name] = count;
            byte[]? bytes = read(spec, count);
            return ValueTask.FromResult<Stream?>(bytes is null ? null : new MemoryStream(bytes, writable: false));
        }
    }
    private static void Fails(BundleSourceFailure expected, BundleSourceException error) => Assert.Equal(expected, error.Failure);
    private static YooAssetManifest Parsed() => YooAssetManifest.Parse(BundleSourceFixtures.Bytes("data-valid"));

    private static Script ImageScript(bool collide = false)
    {
        var script = new Script(); var index = BundleSourceFixtures.Index();
        index["header"]!["package_name"] = "MainPackage";
        var asset = index["assets"]![0]!.DeepClone(); asset["path"] = ItemImageMapping.Prefix + "s1000.png";
        index["assets"] = new JsonArray(asset);
        foreach (var row in index["bundles"]!.AsArray())
        {
            string name = row!["name"]!.GetValue<string>();
            if (!collide) { row["name"] = "image-" + name; script.Extra["image-" + name] = BundleSourceFixtures.Payload(name); }
        }
        script.Main = BundleSourceFixtures.Encode(index); return script;
    }
    [Fact]
    public async Task Item_images_use_MainPackage_exact_closure_and_shared_budget()
    {
        var script = ImageScript(); var preparation = new BundleSourcePreparation();
        var required = await preparation.PrepareAsync(script); var totals = new BundleDownloadTotals(required.DownloadCount, required.DownloadBytes);
        var result = await preparation.PrepareItemImagesAsync(script, required, null, null, totals, default);
        Assert.Equal(new[] { "image-dep-a.bundle", "image-dep-b.bundle", "image-root-a.bundle" }, result.Single().Value.Select(x => x.Spec.Name));
        Assert.All(result.Single().Value, x => Assert.Equal("MainPackage", x.Spec.Package));
        Assert.Equal(7, totals.Count); Assert.DoesNotContain(script.Requests, x => x.EndsWith("image-unrelated.bundle"));
        int requests = script.Requests.Count;
        await preparation.PrepareItemImagesAsync(script, required, null, null, totals, default);
        Assert.Equal(requests, script.Requests.Count); Assert.Equal(7, totals.Count);
        await preparation.ConfirmUnchangedAsync(script, required, default);
    }
    [Fact]
    public async Task MainPackage_same_name_cannot_reuse_DataPackage_even_identical_bytes()
    {
        var script = ImageScript(collide: true); var preparation = new BundleSourcePreparation();
        var required = await preparation.PrepareAsync(script); int requests = script.Requests.Count;
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => preparation.PrepareItemImagesAsync(script, required, null, null,
            new(required.DownloadCount, required.DownloadBytes), default));
        Assert.Equal(BundleSourceFailure.InvalidBundle, error.Failure); Assert.Equal(requests, script.Requests.Count);
    }
    [Fact]
    public async Task Image_downloads_do_not_reset_required_budget_or_stale_attempt()
    {
        var script = ImageScript(); var preparation = new BundleSourcePreparation(); var required = await preparation.PrepareAsync(script);
        int requests = script.Requests.Count;
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => preparation.PrepareItemImagesAsync(script, required, null, new(6),
            new(required.DownloadCount, required.DownloadBytes), default));
        Assert.Equal(BundleSourceFailure.Budget, error.Failure); Assert.Equal(requests, script.Requests.Count);
        preparation.Invalidate();
        await Assert.ThrowsAnyAsync<Exception>(() => preparation.PrepareItemImagesAsync(script, required, null, null,
            new(required.DownloadCount, required.DownloadBytes), default));
        Assert.Equal(requests, script.Requests.Count);
    }
    [Fact]
    public async Task Image_checksum_and_final_manifest_change_are_rejected()
    {
        var script = ImageScript(); var preparation = new BundleSourcePreparation(); var required = await preparation.PrepareAsync(script);
        script.Mutate = (name, _, bytes) => { if (name.StartsWith("image-")) bytes[0] ^= 1; return bytes; };
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => preparation.PrepareItemImagesAsync(script, required, null, null,
            new(required.DownloadCount, required.DownloadBytes), default));
        Assert.Equal(BundleSourceFailure.Checksum, error.Failure);
        script.Mutate = (_, _, bytes) => bytes;
        await preparation.PrepareItemImagesAsync(script, required, null, null, new(required.DownloadCount, required.DownloadBytes), default);
        var index = BundleSourceFixtures.Index("main-valid"); script.Main = BundleSourceFixtures.Encode(index);
        await Assert.ThrowsAsync<BundleSourceException>(() => preparation.ConfirmUnchangedAsync(script, required, default));
    }

    [Fact]
    public async Task CompletePipelineChecksBothManifestContentsAndReturnsOwnedSourcesOnly()
    {
        var script = new Script(); var result = await new BundleSourcePreparation().PrepareAsync(script);
        Assert.Equal("required bundle sources verified; no runtime candidate built", result.Status);
        Assert.Equal("source observations; official provenance unavailable", result.Provenance);
        Assert.Equal(4, result.DownloadCount); Assert.Equal(170, result.DownloadBytes); Assert.Equal(4, script.Observations);
        Assert.Equal(new[] { "dep-a.bundle", "dep-b.bundle", "root-a.bundle", "root-b.bundle" }, result.Sources.Select(x => x.Spec.Name));
        Assert.All(script.Streams, x => Assert.True(x.Disposed));
        Assert.Equal(2, script.Requests.Count(x => x.EndsWith("MainPackage.bytes", StringComparison.Ordinal)));
        Assert.Equal(2, script.Requests.Count(x => x.EndsWith("DataPackage.bytes", StringComparison.Ordinal)));
        foreach (var source in result.Sources)
        {
            using var read = source.OpenRead(); Assert.False(read.CanWrite);
            Assert.False(((MemoryStream)read).TryGetBuffer(out _));
            using var copy = new MemoryStream(); await read.CopyToAsync(copy);
            Assert.Equal(BundleSourceFixtures.Payload(source.Spec.Name), copy.ToArray());
        }
        var snapshot = BundleSourceFixtures.Snapshot();
        var inputs = new Dictionary<string, ManifestIdentityInput>();
        foreach (string package in ResourceValidation.Packages)
        {
            byte[] bytes = package == "DataPackage" ? script.Data : script.Main;
            inputs.Add(package, new(snapshot.DataVersion, package, snapshot.Packages[package], package, snapshot.Packages[package],
                "2.2.5", ManifestIdentity.Crc32LittleEndian(bytes), bytes));
        }
        Assert.Equal(ManifestIdentity.Derive(snapshot, inputs).Key, result.ManifestContentIdentity);
    }
    [Fact]
    public void MutableInputCannotChangeManifestOrVerifiedHandle()
    {
        byte[] bytes = BundleSourceFixtures.Bytes("data-valid"); var manifest = YooAssetManifest.Parse(bytes); string digest = manifest.Sha256;
        Array.Fill(bytes, (byte)0); Assert.Equal(digest, manifest.Sha256); Assert.Equal(10, manifest.Assets.Count);
        var spec = BundleSourcePlan.Create(manifest, "1.3.21").Entries[0].Spec;
        byte[] body = BundleSourceFixtures.Payload(spec.Name); var handle = VerifiedBundleSource.Verify(spec, body, BundleAcquisition.Cache); body[0] ^= 1;
        using var copy = new MemoryStream(); using var read = handle.OpenRead(); read.CopyTo(copy);
        Assert.Equal(BundleSourceFixtures.Payload(spec.Name), copy.ToArray());
        Assert.False(typeof(YooAssetManifest).IsPublic); Assert.False(typeof(RequiredBundleSources).IsPublic);
        Assert.DoesNotContain(typeof(RequiredBundleSources).GetProperties(System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance), p => p.Name is "AssetsReady" or "CanSendPackets");
    }
    [Theory]
    [InlineData("redirect")]
    [InlineData("status")]
    public async Task SourceRejectionPrecedesMalformedLengthAndBody(string mode)
    {
        var script = new Script { Response = (_, response) => response with
        { FinalUrl = mode == "redirect" ? response.FinalUrl + "?redirected" : response.FinalUrl, Status = mode == "status" ? 301 : 200, ContentLength = "bad" } };
        Fails(BundleSourceFailure.ResponseSource, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.Single(script.Streams); Assert.Equal(0, script.Streams[0].Reads); Assert.True(script.Streams[0].Disposed);
    }
    [Theory]
    [InlineData("")]
    [InlineData("-1")]
    [InlineData(" 8")]
    [InlineData("9")]
    [InlineData("1844674407370955161500")]
    public async Task BadContentLengthRejectedBeforeReading(string length)
    {
        var script = new Script { Response = (_, response) => response with { ContentLength = length } };
        Fails(BundleSourceFailure.ResponseLength, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.Equal(0, script.Streams[0].Reads);
    }
    [Theory]
    [InlineData("corrupt", "Checksum")]
    [InlineData("short", "ResponseLength")]
    [InlineData("long", "ResponseLength")]
    public async Task BundleBodyFailuresFailClosedWithoutAnyPartialFiles(string mode, string expected)
    {
        var script = new Script { Mutate = (name, _, body) => !name.EndsWith(".bundle", StringComparison.Ordinal) ? body : mode switch
        { "short" => body[..^1], "long" => [.. body, 1], _ => [(byte)(body[0] ^ 1), .. body[1..]] },
            Response = (name, response) => name.EndsWith(".bundle", StringComparison.Ordinal) ? response with { ContentLength = null } : response };
        Fails(Enum.Parse<BundleSourceFailure>(expected), await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.All(script.Streams, x => Assert.True(x.Disposed));
    }
    [Fact]
    public async Task MainPackageFailureBlocksAllBundleAcquisition()
    {
        var script = new Script { Main = BundleSourceFixtures.Bytes("main-duplicate-path") };
        Fails(BundleSourceFailure.DuplicateAsset, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task SameVersionManifestReplacementFailsEvenWithMatchingReplacementCrc()
    {
        var script = new Script();
        var replacement = BundleSourceFixtures.Index(); replacement["header"]!["package_note"] = "replacement";
        script.BeforeOpen = url =>
        { if (url.EndsWith("DataPackage.hash", StringComparison.Ordinal) && script.Requests.Count(x => x == url) == 2) script.Data = BundleSourceFixtures.Encode(replacement); return Task.CompletedTask; };
        Fails(BundleSourceFailure.ManifestChanged, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
    }
    [Theory]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    public async Task ChangedVersionsBeforeDownloadOrDuringFinalRereadFailClosed(int observation)
    {
        var script = new Script { Observe = n => BundleSourceFixtures.Snapshot(n >= observation ? "1.3.22" : "1.3.21") };
        Fails(BundleSourceFailure.VersionsChanged, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        if (observation == 2) Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task CacheHitsAreReverifiedAndExcludedFromDownloadBudget()
    {
        var script = new Script(); var cache = new Cache((spec, _) => BundleSourceFixtures.Payload(spec.Name));
        var result = await new BundleSourcePreparation().PrepareAsync(script, cache, new(0, 0));
        Assert.Equal(0, result.DownloadBytes); Assert.Equal(0, result.DownloadCount);
        Assert.All(result.Sources, source => Assert.Equal(BundleAcquisition.Cache, source.Acquisition));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task InitiallyCorruptedCacheIsAMissButChangedPlannedCacheCannotFallback()
    {
        var corrupt = new Cache((spec, _) => new byte[checked((int)spec.Size)]);
        Assert.Equal(4, (await new BundleSourcePreparation().PrepareAsync(new Script(), corrupt)).DownloadCount);
        var script = new Script(); var changed = new Cache((spec, count) => count == 1 ? BundleSourceFixtures.Payload(spec.Name) : new byte[checked((int)spec.Size)]);
        Fails(BundleSourceFailure.CacheChanged, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script, changed)));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task CacheStreamCanBeOwnedTemporaryFileAndLaterTamperingCannotAlterHandle()
    {
        string root = Path.Combine(Path.GetTempPath(), "lala-synthetic-" + Guid.NewGuid().ToString("N")); Directory.CreateDirectory(root);
        try
        {
            var files = new Dictionary<string, string>();
            foreach (var row in BundleSourcePlan.Create(Parsed(), "1.3.21").Entries)
            { string path = Path.Combine(root, Guid.NewGuid().ToString("N")); await File.WriteAllBytesAsync(path, BundleSourceFixtures.Payload(row.Spec.Name)); files.Add(row.Spec.Name, path); }
            var cache = new OwnedTestFiles(files);
            var result = await new BundleSourcePreparation().PrepareAsync(new Script(), cache, new(0, 0));
            foreach (var path in files.Values) await File.WriteAllBytesAsync(path, new byte[] { 0 });
            foreach (var handle in result.Sources)
            { using var read = handle.OpenRead(); using var copy = new MemoryStream(); await read.CopyToAsync(copy); Assert.Equal(BundleSourceFixtures.Payload(handle.Spec.Name), copy.ToArray()); }
            Assert.Equal(4, Directory.GetFiles(root).Length); // Pipeline created no partials/receipts/cache writes.
        }
        finally { Directory.Delete(root, recursive: true); }
    }
    private sealed class OwnedTestFiles(IReadOnlyDictionary<string, string> files) : IBundleSourceCacheReader
    {
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken token)
        { token.ThrowIfCancellationRequested(); return ValueTask.FromResult<Stream?>(File.OpenRead(files[spec.Name])); }
    }
    [Theory]
    [InlineData(3, 170)]
    [InlineData(4, 169)]
    public async Task QuotaIsCheckedBeforeBundleReads(int count, long bytes)
    {
        var script = new Script();
        Fails(BundleSourceFailure.Budget, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script, budget: new(count, bytes))));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task ExactQuotaIsAcceptedAndOversizedConfigurationRejectedBeforeObservation()
    {
        Assert.Equal(4, (await new BundleSourcePreparation().PrepareAsync(new Script(), budget: new(4, 170))).Sources.Count);
        var script = new Script();
        foreach (var invalid in new[] { new BundleSourceBudget(-1, 0), new(25, 0), new(0, -1), new(0, 32L * 1024 * 1024 + 1) })
            Fails(BundleSourceFailure.Budget, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script, budget: invalid)));
        Assert.Equal(0, script.Observations);
    }
    [Fact]
    public async Task CancellationDuringStreamDisposesResponseAndNeverCompletes()
    {
        using var cts = new CancellationTokenSource(); var script = new Script { DuringRead = cts.Cancel };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new BundleSourcePreparation().PrepareAsync(script, cancellationToken: cts.Token));
        Assert.Single(script.Streams); Assert.True(script.Streams[0].Disposed);
    }
    [Fact]
    public async Task CancellationAfterSourceReturnsStillDisposesItsResponse()
    {
        using var cts = new CancellationTokenSource(); var script = new Script { Response = (_, response) => { cts.Cancel(); return response; } };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new BundleSourcePreparation().PrepareAsync(script, cancellationToken: cts.Token));
        Assert.Single(script.Streams); Assert.True(script.Streams[0].Disposed); Assert.Equal(0, script.Streams[0].Reads);
    }
    [Fact]
    public async Task StaleAttemptCannotCompleteOrReplaceANewerResult()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var script = new Script { BeforeOpen = async _ => { entered.TrySetResult(); await release.Task; } };
        var pipeline = new BundleSourcePreparation(); var old = pipeline.PrepareAsync(script); await entered.Task;
        var current = await pipeline.PrepareAsync(new Script()); release.SetResult();
        Fails(BundleSourceFailure.StaleAttempt, await Assert.ThrowsAsync<BundleSourceException>(() => old));
        Assert.Equal(2, current.Attempt); Assert.True(script.Streams[0].Disposed);
    }
    [Fact]
    public async Task InvalidationDuringReadDiscardsStagedBytes()
    {
        var pipeline = new BundleSourcePreparation(); var script = new Script { DuringRead = pipeline.Invalidate };
        Fails(BundleSourceFailure.StaleAttempt, await Assert.ThrowsAsync<BundleSourceException>(() => pipeline.PrepareAsync(script)));
        Assert.All(script.Streams, stream => Assert.True(stream.Disposed));
    }
    [Fact]
    public void BoundedParserRejectsCountsWithoutAllocatingDeclaredArraysAndHonorsCancellation()
    {
        Assert.Throws<BundleSourceException>(() => YooAssetManifest.Parse(new byte[ManifestIdentity.MaximumManifestBytes + 1]));
        using var cts = new CancellationTokenSource(); cts.Cancel();
        Assert.ThrowsAny<OperationCanceledException>(() => YooAssetManifest.Parse(BundleSourceFixtures.Bytes("data-valid"), cts.Token));
        byte[] bytes = BundleSourceFixtures.Bytes("data-valid");
        using var stream = new MemoryStream(bytes); using var reader = new BinaryReader(stream);
        stream.Position = 4; stream.Position += 2 + reader.ReadUInt16(); // format
        stream.Position += 11;
        for (int i = 0; i < 4; i++) { int length = reader.ReadUInt16(); stream.Position += length; }
        int offset = checked((int)stream.Position); System.Buffers.Binary.BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(offset), int.MaxValue);
        Assert.Throws<BundleSourceException>(() => YooAssetManifest.Parse(bytes));
    }
    [Theory]
    [InlineData("../escape.bundle")]
    [InlineData("/absolute.bundle")]
    [InlineData("a\\b.bundle")]
    [InlineData("x.bundle\n")]
    public void BundleNamesCannotEscapeAnyFutureCacheRootOrSourceUrl(string name)
    {
        var index = BundleSourceFixtures.Index(); index["bundles"]![0]!["name"] = name;
        Fails(BundleSourceFailure.InvalidBundle, Assert.Throws<BundleSourceException>(() => BundleSourcePlan.Create(YooAssetManifest.Parse(BundleSourceFixtures.Encode(index)), "1.3.21")));
    }
    [Fact]
    public void FingerprintDeltasCompareWholeIndexAndResolvedNamesNotIds()
    {
        var previous = Parsed(); var index = BundleSourceFixtures.Index();
        index["bundles"]![0]!["unity_crc"] = 1U;
        var plan = BundleSourcePlan.Create(YooAssetManifest.Parse(BundleSourceFixtures.Encode(index)), "1.3.21", previous);
        Assert.Equal(1, plan.ModifiedCount); Assert.Equal(BundleChange.Modified, plan.Entries.Single(x => x.Spec.Name == "root-a.bundle").Change);
        Assert.Equal(BundleChange.Unchanged, plan.Entries.Single(x => x.Spec.Name == "dep-a.bundle").Change);
        index = BundleSourceFixtures.Index(); index["bundles"]![4]!["name"] = "renamed.bundle";
        plan = BundleSourcePlan.Create(YooAssetManifest.Parse(BundleSourceFixtures.Encode(index)), "1.3.21", previous);
        Assert.Equal(1, plan.AddedCount); Assert.Equal(1, plan.RemovedCount); Assert.Equal(1, plan.ModifiedCount);
        Assert.Equal(BundleChange.Modified, plan.Entries.Single(x => x.Spec.Name == "dep-a.bundle").Change);
    }
    [Fact]
    public async Task OversizedOwnedClosureIsRejectedBeforeCacheOrBundleReads()
    {
        var index = BundleSourceFixtures.Index(); index["bundles"]![0]!["file_size"] = 32L * 1024 * 1024 + 1;
        var script = new Script { Data = BundleSourceFixtures.Encode(index) };
        var cache = new Cache((_, _) => throw new InvalidOperationException("Cache must not open above retained bound"));
        Fails(BundleSourceFailure.Budget, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script, cache)));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Fact]
    public async Task HashResponseValidationPrecedesManifestParse()
    {
        var script = new Script { Mutate = (name, _, body) => name.EndsWith(".hash", StringComparison.Ordinal) ? Encoding.ASCII.GetBytes("gggggggg") : body };
        Fails(BundleSourceFailure.Checksum, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.Single(script.Requests);
    }
    [Theory]
    [InlineData("package_name")]
    [InlineData("package_version")]
    [InlineData("output_name_style")]
    public async Task ActualParsedHeaderMustMatchObservedPackage(string field)
    {
        var index = BundleSourceFixtures.Index();
        if (field == "output_name_style") index["header"]![field] = 2;
        else index["header"]![field] = "wrong";
        var script = new Script { Data = BundleSourceFixtures.Encode(index) };
        Fails(BundleSourceFailure.ManifestIdentity, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }

    [Fact]
    public async Task PlannedCacheDisappearanceCannotTriggerAnExtraDownload()
    {
        var cache = new Cache((spec, count) => count == 1 ? BundleSourceFixtures.Payload(spec.Name) : null);
        var script = new Script();
        Fails(BundleSourceFailure.CacheChanged, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script, cache)));
        Assert.DoesNotContain(script.Requests, x => x.EndsWith(".bundle", StringComparison.Ordinal));
    }
    [Theory]
    [InlineData("asset-tags")]
    [InlineData("bundle-tags")]
    [InlineData("dependency-ids")]
    public void NestedCountsAreBoundedByRemainingBytesBeforeAllocation(string field)
    {
        byte[] bytes = BundleSourceFixtures.Bytes("data-valid");
        int offset = field switch
        {
            "asset-tags" => bytes.AsSpan().IndexOf(Encoding.UTF8.GetBytes("guid-0")) + 6,
            "bundle-tags" => bytes.AsSpan().IndexOf(Encoding.UTF8.GetBytes("fc121640")) + 8 + 8 + 1,
            _ => bytes.Length - 2
        };
        System.Buffers.Binary.BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(offset), ushort.MaxValue);
        Fails(BundleSourceFailure.ManifestSyntax, Assert.Throws<BundleSourceException>(() => YooAssetManifest.Parse(bytes)));
    }
    [Fact]
    public async Task BundleStageCancellationDisposesNewResponseAndAllEarlierResponses()
    {
        using var cts = new CancellationTokenSource();
        var script = new Script { Response = (name, response) => { if (name.EndsWith(".bundle", StringComparison.Ordinal)) cts.Cancel(); return response; } };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new BundleSourcePreparation().PrepareAsync(script, cancellationToken: cts.Token));
        Assert.Equal(5, script.Streams.Count); Assert.All(script.Streams, stream => Assert.True(stream.Disposed));
        Assert.Equal(0, script.Streams[^1].Reads);
    }
    [Fact]
    public async Task BundleStageResponseOriginIsRejectedBeforeLengthOrBody()
    {
        var script = new Script { Response = (name, response) => name.EndsWith(".bundle", StringComparison.Ordinal) ?
            response with { FinalUrl = "https://unapproved.invalid/changed", ContentLength = "invalid" } : response };
        Fails(BundleSourceFailure.ResponseSource, await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(script)));
        Assert.Equal(5, script.Streams.Count); Assert.Equal(0, script.Streams[^1].Reads);
    }

}
