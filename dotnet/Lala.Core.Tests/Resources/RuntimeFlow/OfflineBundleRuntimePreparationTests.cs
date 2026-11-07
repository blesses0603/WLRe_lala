using System.Collections;
using System.Globalization;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class OfflineBundleRuntimePreparationTests
{
    private sealed class Script : IScriptedResourceSource
    {
        internal readonly Dictionary<string, byte[]> Bundles;
        internal byte[] Data;
        internal byte[] Main = BundleSourceFixtures.Bytes("main-valid");
        internal readonly List<string> Requests = [];
        internal readonly List<TrackingStream> Streams = [];
        internal int Observations;
        internal Func<int, OfficialVersionSnapshot> Observe = _ => RuntimeFlowFixtures.Snapshot();
        internal Func<int, Task>? BeforeObserve;
        internal Action<string, int>? BeforeOpen;
        internal Action<string>? DuringRead;
        internal Script(string fixture = "all-ten.bundle") : this(new Dictionary<string, byte[]>(StringComparer.Ordinal)
            { [fixture] = RuntimeFlowFixtures.Read(fixture) }) { }
        internal Script(Dictionary<string, byte[]> bundles, IReadOnlyDictionary<string, string>? roots = null,
            IReadOnlyDictionary<string, string[]>? dependencies = null)
        {
            Bundles = bundles; Data = RuntimeFlowFixtures.Manifest(bundles, roots, dependencies);
        }
        public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
        {
            int count = ++Observations;
            if (BeforeObserve is not null) await BeforeObserve(count);
            token.ThrowIfCancellationRequested(); return Observe(count);
        }
        public ValueTask<ScriptedResourceResponse> OpenAsync(string exactUrl, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Requests.Add(exactUrl);
            string name = exactUrl[(exactUrl.LastIndexOf('/') + 1)..];
            BeforeOpen?.Invoke(name, Requests.Count(url => url == exactUrl));
            // This script has no networking or path-opening implementation.
            byte[] bytes = name switch
            {
                "DataPackage.bytes" => Data, "MainPackage.bytes" => Main,
                "DataPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Data)),
                "MainPackage.hash" => Encoding.ASCII.GetBytes(ManifestIdentity.Crc32LittleEndian(Main)),
                _ => Bundles.TryGetValue(name, out var raw) ? raw : throw new InvalidOperationException("Unexpected scripted target")
            };
            var stream = new TrackingStream(bytes, () => DuringRead?.Invoke(name)); Streams.Add(stream);
            return ValueTask.FromResult(new ScriptedResourceResponse(exactUrl, 200,
                bytes.Length.ToString(CultureInfo.InvariantCulture), stream));
        }
    }
    private sealed class TrackingStream(byte[] bytes, Action read) : MemoryStream(bytes, writable: false)
    {
        internal bool Disposed;
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            read(); return base.ReadAsync(buffer[..Math.Min(buffer.Length, 127)], cancellationToken);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
    private sealed class Cache(Dictionary<string, byte[]> bundles) : IBundleSourceCacheReader
    {
        internal int Reads;
        public ValueTask<Stream?> OpenReadAsync(BundleSourceSpec spec, CancellationToken token)
        {
            token.ThrowIfCancellationRequested(); Reads++;
            return ValueTask.FromResult<Stream?>(new MemoryStream(bundles[spec.Name], writable: false));
        }
    }

    [Fact]
    public async Task Actual_owned_bundles_flow_through_all_ten_decoders_then_fresh_reobservations()
    {
        var source = new Script();
        using var diagnostics = ParserDiagnostics.BeginSession();
        source.BeforeObserve = count =>
        {
            if (count >= 5)
            {
                Assert.Contains(diagnostics.Run.Events, e => e.Definition.Schema == "eve-doors-v115");
                Assert.Contains(diagnostics.Run.Events, e => e.Definition.Parser.EndsWith("parse_npcs", StringComparison.Ordinal));
            }
            return Task.CompletedTask;
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        var candidate = result.Candidate;
        Assert.Equal(6, source.Observations);
        Assert.Equal(3, source.Requests.Count(url => url.EndsWith("DataPackage.bytes", StringComparison.Ordinal)));
        Assert.Equal(3, source.Requests.Count(url => url.EndsWith("MainPackage.bytes", StringComparison.Ordinal)));
        Assert.Equal(1, result.DownloadCount); Assert.Equal(source.Bundles.Values.Single().Length, result.DownloadBytes);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources, result.ExtractedTables);
        Assert.Equal("任務", candidate.Expedition.Tasks[1].Name); Assert.Equal("場景😀", candidate.SceneNames[500]);
        Assert.Equal("甲😀", candidate.Talks[1].Text); Assert.Equal(3, candidate.Items.Count);
        Assert.Equal(3, candidate.Recipes.Catalog.Length); Assert.Single(candidate.Recipes.Products);
        Assert.Equal(58001, candidate.Doors.Scenes[0].Doors[0].TouchEventRecords[0].ConveyTransfers[0].Convey.Destination);
        Assert.Equal(9001u, candidate.EveIndexes.Scenes[0].Npcs[0].NpcId);
        Assert.Equal(0, candidate.Npcs[1].Original); Assert.Single(candidate.Expedition.Levels);
        Assert.True(candidate.RequiredTablesStructurallyComplete);
        Assert.False(candidate.HasVerifiedProvenance); Assert.False(candidate.AssetsReady);
        Assert.False(candidate.CanSendPackets); Assert.False(candidate.RuntimeAdmitted);
        Assert.Equal("unavailable", result.OfficialProvenance); Assert.Equal("unavailable", result.DatabaseAdmission);
        Assert.Equal("unavailable", result.RuntimeInstallation); Assert.Equal("unavailable", result.Static1275Admission);
        Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
        var expected = JsonDocument.Parse(RuntimeFlowFixtures.Read("evidence.json")).RootElement.GetProperty("tables");
        foreach (var table in expected.EnumerateArray()) Assert.Equal(table.GetProperty("sha256").GetString(), candidate.SourceSha256[table.GetProperty("table").GetString()!]);
        Assert.Equal(DeriveIdentity(source), result.ManifestContentIdentity);
    }

    [Fact]
    public async Task Cache_is_reverified_but_not_reopened_for_extraction_and_mutation_cannot_change_result()
    {
        var source = new Script(); var cache = new Cache(source.Bundles);
        source.BeforeObserve = count =>
        {
            // All acquisition is done. Mutate the original cache bytes before the native
            // extractor sees them: only private verified snapshots may be used from now on.
            if (count == 4) foreach (byte[] bytes in source.Bundles.Values) Array.Fill(bytes, (byte)0xff);
            return Task.CompletedTask;
        };
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source, cache, new(0, 0));
        Assert.Equal(2, cache.Reads); Assert.Equal(0, result.DownloadCount); Assert.Equal(0, result.DownloadBytes);
        Assert.DoesNotContain(source.Requests, url => url.EndsWith(".bundle", StringComparison.Ordinal));
        Array.Fill(source.Data, (byte)0); Array.Fill(source.Main, (byte)0);
        Assert.Equal("任務", result.Candidate.Expedition.Tasks[1].Name);
        Assert.Equal(3, result.Candidate.Items.Count); Assert.False(result.Candidate.SourceSha256 is IDictionary);
    }

    [Fact]
    public async Task Single_asset_dependency_selection_does_not_invent_recursive_or_unrelated_sources()
    {
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["split-root.bundle"] = RuntimeFlowFixtures.Read("split-root.bundle"),
            ["split-dependency.bundle"] = RuntimeFlowFixtures.Read("split-dependency.bundle"),
            ["unrelated-duplicate.bundle"] = RuntimeFlowFixtures.Read("unrelated-duplicate.bundle")
        };
        var roots = BundleSourcePlan.RequiredTables.ToDictionary(name => name,
            name => name == "Eve" ? "unrelated-duplicate.bundle" : "split-root.bundle", StringComparer.Ordinal);
        // Dependencies are complete sets. The dependency's own reference is not followed.
        var dependencies = new Dictionary<string, string[]>
        {
            ["split-root.bundle"] = ["split-dependency.bundle", "split-root.bundle", "split-dependency.bundle"],
            ["split-dependency.bundle"] = ["unrelated-duplicate.bundle"]
        };
        var source = new Script(bundles, roots, dependencies);
        var plan = BundleSourcePlan.Create(YooAssetManifest.Parse(source.Data), "1.3.21");
        Assert.Equal(new[] { "unrelated-duplicate.bundle" }, plan.AssetSourceNames[RuntimeFlowFixtures.AssetRoot + "Eve.bytes"]);
        Assert.Equal(new[] { "split-dependency.bundle", "split-root.bundle" }, plan.AssetSourceNames[RuntimeFlowFixtures.AssetRoot + "ItemData_C.bytes"]);
        var readOnly = Assert.IsAssignableFrom<IDictionary>(plan.AssetSourceNames);
        Assert.True(readOnly.IsReadOnly); Assert.Throws<NotSupportedException>(readOnly.Clear);
        Assert.Throws<NotSupportedException>(() => ((IList<string>)plan.AssetSourceNames[RuntimeFlowFixtures.AssetRoot + "Eve.bytes"])[0] = "changed.bundle");
        var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
        Assert.Equal(3, result.DownloadCount); Assert.Equal("任務", result.Candidate.Expedition.Tasks[1].Name);
        // Extracting the union would reject Eve duplicates. The real per-asset plan must not.
        var handles = plan.Entries.Select(row => VerifiedBundleSource.Verify(row.Spec, bundles[row.Spec.Name], BundleAcquisition.Cache)).ToArray();
        Assert.Throws<UnityTextAssetException>(() => UnityTextAssetExtractor.Extract(RuntimeFlowFixtures.AssetRoot + "Eve.bytes", handles));
    }

    [Theory]
    [InlineData(5)]
    [InlineData(6)]
    public async Task Changed_versions_after_decoding_reject_instead_of_returning_candidate(int changedAt)
    {
        var source = new Script { Observe = count => RuntimeFlowFixtures.Snapshot(count >= changedAt ? "1.3.22" : "1.3.21") };
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(BundleSourceFailure.VersionsChanged, error.Failure);
        Assert.Equal(changedAt, source.Observations); Assert.All(source.Streams, s => Assert.True(s.Disposed));
    }

    [Theory]
    [InlineData("DataPackage")]
    [InlineData("MainPackage")]
    public async Task Same_version_manifest_byte_replacement_after_decoding_is_rejected(string package)
    {
        var source = new Script();
        source.BeforeOpen = (name, occurrence) =>
        {
            if (name != package + ".hash" || occurrence != 3) return;
            byte[] prior = package == "DataPackage" ? source.Data : source.Main;
            var parsed = YooAssetManifest.Parse(prior);
            // A final-byte change in a benign package note keeps the actual source layout,
            // version and matching CRC valid; final SHA content comparison must still fail.
            byte[] changed = prior.ToArray();
            byte[] note = Encoding.UTF8.GetBytes(parsed.Header.PackageNote);
            int at = changed.AsSpan().IndexOf(note);
            int ascii = Array.IndexOf(note, (byte)' ');
            Assert.True(note.Length > 0 && at >= 0 && ascii >= 0);
            changed[at + ascii] = (byte)'x';
            if (package == "DataPackage") source.Data = changed; else source.Main = changed;
        };
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(BundleSourceFailure.ManifestChanged, error.Failure);
        Assert.Equal(5, source.Observations); Assert.All(source.Streams, s => Assert.True(s.Disposed));
    }

    [Fact]
    public async Task Superseded_attempt_after_all_decoders_never_overwrites_or_returns_a_late_result()
    {
        var pipeline = new OfflineBundleRuntimePreparation(); var oldSource = new Script();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        oldSource.BeforeObserve = async count => { if (count == 5) { entered.SetResult(); await release.Task; } };
        Task<OfflinePreparedRuntimeCandidate> old = pipeline.PrepareAsync(oldSource);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(20));
        var latest = await pipeline.PrepareAsync(new Script());
        release.SetResult();
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => old);
        Assert.Equal(BundleSourceFailure.StaleAttempt, error.Failure); Assert.Equal(2, latest.Attempt);
        Assert.Equal("任務", latest.Candidate.Expedition.Tasks[1].Name);
    }

    [Theory]
    [InlineData(4)]
    [InlineData(5)]
    [InlineData(6)]
    public async Task Invalidation_or_cancellation_at_final_boundaries_never_publishes(int boundary)
    {
        foreach (bool cancel in new[] { false, true })
        {
            var pipeline = new OfflineBundleRuntimePreparation(); var source = new Script();
            using var cancellation = new CancellationTokenSource();
            source.BeforeObserve = count =>
            {
                if (count == boundary) { if (cancel) cancellation.Cancel(); else pipeline.Invalidate(); }
                return Task.CompletedTask;
            };
            if (cancel) await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pipeline.PrepareAsync(source, cancellationToken: cancellation.Token));
            else Assert.Equal(BundleSourceFailure.StaleAttempt,
                (await Assert.ThrowsAsync<BundleSourceException>(() => pipeline.PrepareAsync(source))).Failure);
            Assert.All(source.Streams, s => Assert.True(s.Disposed));
        }
    }

    [Theory]
    [InlineData("missing-path.bundle", "unity")]
    [InlineData("duplicate-path.bundle", "unity")]
    [InlineData("late-invalid.bundle", "catalog")]
    public async Task Actual_extraction_and_late_table_failures_are_atomic(string fixture, string kind)
    {
        var pipeline = new OfflineBundleRuntimePreparation();
        var prior = await pipeline.PrepareAsync(new Script());
        var source = new Script(fixture);
        using var diagnostics = ParserDiagnostics.BeginSession();
        if (kind == "unity")
        {
            await Assert.ThrowsAsync<UnityTextAssetException>(() => pipeline.PrepareAsync(source));
            Assert.Empty(diagnostics.Run.Events); // All raw assets extract before any table parses.
        }
        else
        {
            await Assert.ThrowsAsync<CatalogDecodeException>(() => pipeline.PrepareAsync(source));
            Assert.Contains(diagnostics.Run.Events, e => e.Definition.Schema == "eve-doors-v115");
        }
        Assert.Equal(4, source.Observations); // No fake successful final reobservation after failure.
        Assert.Equal("任務", prior.Candidate.Expedition.Tasks[1].Name);
        Assert.All(source.Streams, s => Assert.True(s.Disposed));
    }

    [Fact]
    public async Task Explicit_external_target_is_not_guessed_from_a_manifest_dependency()
    {
        var bundles = new Dictionary<string, byte[]>(StringComparer.Ordinal)
        {
            ["external-root.bundle"] = RuntimeFlowFixtures.Read("external-root.bundle"),
            ["external-target.bundle"] = RuntimeFlowFixtures.Read("external-target.bundle")
        };
        var source = new Script(bundles, dependencies: new Dictionary<string, string[]>
            { ["external-root.bundle"] = ["external-target.bundle"] });
        await Assert.ThrowsAsync<UnityTextAssetException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(4, source.Observations);
    }

    [Fact]
    public async Task Aggregate_raw_table_budget_rejects_before_table_decoding()
    {
        var source = new Script("aggregate-overflow.bundle");
        using var diagnostics = ParserDiagnostics.BeginSession();
        var error = await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source));
        Assert.Equal(BundleSourceFailure.Budget, error.Failure); Assert.Empty(diagnostics.Run.Events);
        Assert.Equal(32L * 1024 * 1024, OfflineBundleRuntimePreparation.MaximumExtractedTableBytes);
    }

    [Fact]
    public async Task Cancellation_during_genuine_bundle_acquisition_disposes_stream_without_decoding()
    {
        using var cancellation = new CancellationTokenSource();
        using var diagnostics = ParserDiagnostics.BeginSession();
        var source = new Script();
        source.DuringRead = name => { if (name.EndsWith(".bundle", StringComparison.Ordinal)) cancellation.Cancel(); };
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source,
            cancellationToken: cancellation.Token));
        Assert.Empty(diagnostics.Run.Events); Assert.All(source.Streams, stream => Assert.True(stream.Disposed));
    }

    [Fact]
    public async Task Source_preparation_owner_cannot_be_replaced_even_when_attempt_numbers_match()
    {
        var first = new BundleSourcePreparation(); var second = new BundleSourcePreparation();
        var owned = await first.PrepareAsync(new Script());
        _ = await second.PrepareAsync(new Script()); // Both counters are 1, owners differ.
        Assert.Equal(BundleSourceFailure.StaleAttempt, Assert.Throws<BundleSourceException>(() => second.EnsureCurrent(owned, default)).Failure);
        var unusedSource = new Script();
        Assert.Equal(BundleSourceFailure.StaleAttempt,
            (await Assert.ThrowsAsync<BundleSourceException>(() => second.ConfirmUnchangedAsync(unusedSource, owned))).Failure);
        Assert.Equal(0, unusedSource.Observations); Assert.Empty(unusedSource.Requests);
        Assert.Equal(BundleSourceFailure.StaleAttempt,
            Assert.Throws<BundleSourceException>(() => second.ReturnCurrent(owned, new object(), default)).Failure);
    }

    [Fact]
    public async Task No_public_source_decoder_or_admission_bypass_and_pre_cancelled_token_wins()
    {
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(null!, cancellationToken: cancelled.Token));
        Assert.False(typeof(OfflineBundleRuntimePreparation).IsPublic); Assert.False(typeof(OfflinePreparedRuntimeCandidate).IsPublic);
        Assert.DoesNotContain(typeof(OfflinePreparedRuntimeCandidate).GetProperties(BindingFlags.NonPublic | BindingFlags.Instance),
            property => property.Name is "AssetsReady" or "CanSendPackets" or "RuntimeAdmitted" or "IsCompleteState");
        Assert.DoesNotContain(typeof(OfflineBundleRuntimePreparation).GetMethods(BindingFlags.NonPublic | BindingFlags.Instance)
            .SelectMany(method => method.GetParameters()), parameter => typeof(Delegate).IsAssignableFrom(parameter.ParameterType));
    }

    private static string DeriveIdentity(Script source)
    {
        var snapshot = RuntimeFlowFixtures.Snapshot();
        var inputs = new Dictionary<string, ManifestIdentityInput>();
        foreach (string package in ResourceValidation.Packages)
        {
            byte[] bytes = package == "DataPackage" ? source.Data : source.Main;
            inputs.Add(package, new(snapshot.DataVersion, package, snapshot.Packages[package], package, snapshot.Packages[package],
                "2.2.5", ManifestIdentity.Crc32LittleEndian(bytes), bytes));
        }
        return ManifestIdentity.Derive(snapshot, inputs).Key;
    }
}
