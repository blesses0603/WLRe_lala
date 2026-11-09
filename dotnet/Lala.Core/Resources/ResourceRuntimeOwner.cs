using System.Data.Common;
using Lala.Core.Catalogs;
using Microsoft.Data.Sqlite;

namespace Lala.Core.Resources;

/// <summary>Historical immutable resource publication, never login or packet authority.
/// Consumers must reacquire Current: retained publications do not survive owner invalidation.</summary>
internal sealed class ResourceRuntimePublication
{
    internal long Generation { get; }
    internal ManifestIdentity Identity { get; }
    internal OfflineRuntimeCandidate Candidate { get; }
    internal ItemImageReadback? ItemImages { get; }
    internal PortraitPngReadback? Portraits { get; }
    private readonly ResourceRuntimeOwner _owner;
    internal bool ResourceAdmitted => _owner.IsCurrentAdmission(this);
    internal bool TlsOriginObserved => _owner.IsCurrentAdmission(this);
    internal bool PublisherSignatureVerified => false;
    internal string ProtocolCompatibility => "unverified";
    internal bool CanLogin => false;
    internal bool CanSendPackets => false;
    internal ResourceRuntimePublication(ResourceRuntimeOwner owner, long generation, OfflinePreparedRuntimeCandidate prepared,
        OfflineRuntimeCandidate? readbackCandidate = null, ItemImageReadback? itemImages = null, PortraitPngReadback? portraits = null)
        => (_owner, Generation, Identity, Candidate, ItemImages, Portraits) = (owner, generation, prepared.Identity, readbackCandidate ?? prepared.Candidate, itemImages, portraits);
}

/// <summary>Uninstalled resource-only owner. Construction does no network or database I/O.
/// Path containment is lexical, not a sandbox against symlinks or hostile filesystem replacement.
/// Ordinary OS TLS trust is used; no publisher signatures or protocol compatibility are claimed.</summary>
internal sealed class ResourceRuntimeOwner : IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly Func<Task>? _afterAdmission;
    private readonly Action? _cleanupEntered;
    private readonly ResourceRuntimeBootstrapTestHooks? _bootstrapHooks;
    private readonly IResourceSource _source;
    private readonly bool _production;
    private readonly string _inventory;
    private readonly string _itemImages;
    private readonly string _portraits;
    private readonly IBundleSourceCacheReader _cache;
    private readonly RuntimeBundleCacheWriter _cacheWriter;
    private readonly OfflineBundleRuntimePreparation _preparation = new();
    private Attempt? _attempt;
    private ResourceRuntimePublication? _current;
    private ResourceRuntimeActivation? _activation;
    private long _generation;
    private bool _disposed;

    private Task? _disposeTask;

    // No source/handler/provider/claimed evidence injection on the production route.
    internal static ResourceRuntimeOwner Create(string dataRoot)
        => new(dataRoot, null);
    internal static ResourceRuntimeOwner CreateForOfflineTests(string dataRoot, IResourceSource source, Func<Task>? afterAdmission = null,
        Action? cleanupEntered = null, ResourceRuntimeBootstrapTestHooks? bootstrapHooks = null)
        => new(dataRoot, source ?? throw new ArgumentNullException(nameof(source)), afterAdmission, cleanupEntered, bootstrapHooks);
    private ResourceRuntimeOwner(string dataRoot, IResourceSource? offlineSource, Func<Task>? afterAdmission = null,
        Action? cleanupEntered = null, ResourceRuntimeBootstrapTestHooks? bootstrapHooks = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(dataRoot);
        if (!Path.IsPathFullyQualified(dataRoot)) throw new ArgumentException("An absolute data root is required", nameof(dataRoot));
        // Python game_version_gate.py selects data_root()/official_sync/derived_catalogs/resource_inventory.sqlite3.
        string root = Path.GetFullPath(dataRoot);
        _cache = new RuntimeBundleCacheReader(root);
        _cacheWriter = new RuntimeBundleCacheWriter(root);
        _inventory = Path.Combine(root, "official_sync", "derived_catalogs", "resource_inventory.sqlite3");
        _itemImages = Path.Combine(root, "official_sync", "derived_catalogs", "core_item_images_v1.sqlite3");
        _portraits = Path.Combine(root, "official_sync", "derived_catalogs", "core_portraits_v1.sqlite3");
        _afterAdmission = afterAdmission;
        _cleanupEntered = cleanupEntered;
        _bootstrapHooks = bootstrapHooks;
        _production = offlineSource is null;
        _source = offlineSource ?? new HttpOfficialResourceSource();
    }
    internal bool IsCurrentAdmission(ResourceRuntimePublication? publication)
    {
        lock (_gate) return publication is not null && _production && !_disposed && ReferenceEquals(_current, publication) && publication.Generation == _generation;
    }
    /// <summary>Explicit resource-only activation of the caller's exact observed publication.
    /// A stale receipt never silently selects newer resources. No callback, I/O or session
    /// transition runs under the gate. Offline owners cannot create an activation.</summary>
    internal bool TryActivate(ResourceRuntimePublication? expected, out ResourceRuntimeActivation? activation)
    {
        lock (_gate)
        {
            activation = null;
            if (expected is null || !IsCurrentAdmission(expected)) return false;
            _activation ??= new(this, expected);
            activation = _activation;
            return true;
        }
    }
    internal bool IsCurrentActivation(ResourceRuntimeActivation activation, ResourceRuntimePublication publication)
    {
        lock (_gate) return activation is not null && ReferenceEquals(_activation, activation) && IsCurrentAdmission(publication);
    }
    internal bool TryReadActivatedCatalogs(ResourceRuntimeActivation activation, ResourceRuntimePublication publication,
        out OfflineRuntimeCandidate? candidate)
    {
        lock (_gate)
        {
            candidate = IsCurrentActivation(activation, publication) ? publication.Candidate : null;
            return candidate is not null;
        }
    }
    internal bool TryReadItemImage(ResourceRuntimeActivation activation, ResourceRuntimePublication publication,
        ushort itemId, out byte[]? png)
    {
        lock (_gate)
        {
            png = IsCurrentActivation(activation, publication) ? publication.ItemImages?.CopyPng(itemId) : null;
            return png is not null;
        }
    }
    internal bool TryReadPortrait(ResourceRuntimeActivation activation, ResourceRuntimePublication publication,
        PortraitMaterialKey key, out PortraitCachedImage? image)
    {
        lock (_gate)
        {
            image = null;
            return IsCurrentActivation(activation, publication) && publication.Portraits is not null &&
                publication.Portraits.Images.TryGetValue(key, out image);
        }
    }
    internal bool TrySelectPortrait(ResourceRuntimeActivation activation, ResourceRuntimePublication publication,
        Lala.Core.Protocol.WorldPlayer? player, Lala.Core.Inventory.CompanionReceiveSnapshot companions, bool companion,
        out PortraitSelection? selection, out PortraitCachedImage? image)
    {
        lock (_gate)
        {
            selection = null; image = null;
            if (!IsCurrentActivation(activation, publication) || publication.Portraits is not { } portraits) return false;
            selection = portraits.Select(player, companions, companion);
            return selection is not null && portraits.Images.TryGetValue(selection.Key, out image);
        }
    }
    internal ResourceRuntimePublication? Current { get { lock (_gate) return _current; } }

    internal void Invalidate()
    {
        Attempt? previous;
        lock (_gate)
        {
            _generation = checked(_generation + 1); _current = null; _activation = null; previous = _attempt;
            _preparation.Invalidate();
        }
        _ = previous?.RequestCancellation(); // Callbacks run asynchronously, never under publication lock.
    }

    /// <summary>Read-only admission. A missing inventory is never created or repaired.</summary>
    internal async Task<ResourceRuntimePublication> RefreshAsync(CancellationToken cancellationToken = default)
    {
        var result = await RunAsync(bootstrap: false, cancellationToken).ConfigureAwait(false);
        if (result.Failure is not null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(result.Failure).Throw();
        return result.Publication!;
    }

    /// <summary>New composition of ten-table preparation and the existing inventory writer,
    /// independent readback, bounded verified bundle caching, then fresh-source reobservation.
    /// Not full rebuild/ZIP parity. Refresh remains strictly read-only.
    /// Rejected admission (busy/disposed) throws before an attempt; admitted failures are retained
    /// in the historical result, including cancellation after a durable or uncertain write.</summary>
    internal Task<ResourceRuntimeBootstrapResult> BootstrapAndRefreshAsync(CancellationToken cancellationToken = default)
        => RunAsync(bootstrap: true, cancellationToken);

    internal Task<ResourceRuntimeBootstrapResult> RefreshWithResultAsync(CancellationToken cancellationToken = default)
        => RunAsync(bootstrap: false, cancellationToken);

    private async Task<ResourceRuntimeBootstrapResult> RunAsync(bool bootstrap, CancellationToken cancellationToken)
        => await Reserve(bootstrap, cancellationToken)().ConfigureAwait(false);

    // Pure synchronous admission: no I/O, cancellation registration, callbacks or async
    // execution. The caller must execute the returned work exactly once outside its gates.
    // The reserved slot is visible to Invalidate/Dispose even before execution begins;
    // retirement continues to await its ordinary cleanup and Retired signal.
    internal Func<Task<ResourceRuntimeBootstrapResult>> Reserve(bool bootstrap, CancellationToken cancellationToken)
    {
        Attempt mine;
        long generation;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_attempt is not null) throw new InvalidOperationException("A resource refresh is already retiring or running");
            generation = _generation = checked(_generation + 1); _current = null; _activation = null;
            // One slot remains occupied through writes, readback, cancellation callbacks and
            // cleanup. A newer attempt in this owner cannot overtake an older retiring writer.
            mine = new Attempt(this); _attempt = mine;
        }
        int executed = 0;
        return () => Interlocked.Exchange(ref executed, 1) == 0
            ? ExecuteAsync(bootstrap, cancellationToken, generation, mine)
            : Task.FromException<ResourceRuntimeBootstrapResult>(
                new InvalidOperationException("A reserved resource attempt can execute only once"));
    }

    private async Task<ResourceRuntimeBootstrapResult> ExecuteAsync(bool bootstrap,
        CancellationToken cancellationToken, long generation, Attempt mine)
    {
        var execution = new OwnerExecution(this);
        OfflinePreparedRuntimeCandidate? preparedResult = null;
        OfflineRuntimeCandidate? readbackCandidate = null;
        ResourceInventoryReceipt? receipt = null;
        ResourceInventoryWriteOutcome storage = ResourceInventoryWriteOutcome.NotCommitted;
        bool storageAttempted = false, sourcesRechecked = false;
        var readback = ResourceRuntimeReadback.NotAttempted;
        ResourceRuntimePublication? publication = null;
        ItemImageReadback? itemImages = null;
        PortraitPngReadback? portraits = null;
        var portraitStorage = AccountResourceStorageOutcome.NotAttempted;
        var imageStorage = AccountResourceStorageOutcome.NotAttempted;
        Exception? failure = null;
        try
        {
            mine.RegisterCaller(cancellationToken);
            // Invalidation between reservation and execution must reject before any hook
            // or I/O, independently of asynchronous cancellation callback delivery.
            EnsureCurrent(generation, mine);
            if (_afterAdmission is not null) await _afterAdmission().ConfigureAwait(false);
            EnsureCurrent(generation, mine);
            var baseline = bootstrap ? await CaptureWriteBaselineAsync(mine.Token).ConfigureAwait(false) : null;
            EnsureCurrent(generation, mine);
            var prepared = await _preparation.PrepareAsync(_source, cache: _cache, cancellationToken: mine.Token).ConfigureAwait(false);
            EnsureCurrent(generation, mine);
            if (bootstrap)
            {
                if (_bootstrapHooks?.BeforeWrite is not null) await _bootstrapHooks.BeforeWrite().ConfigureAwait(false);
                EnsureCurrent(generation, mine);
                Directory.CreateDirectory(Path.GetDirectoryName(_inventory)!);
                var writer = await CreateConnectionAsync(SqliteOpenMode.ReadWriteCreate).ConfigureAwait(false);
                storageAttempted = true;
                // A store that cannot report its outcome is conservatively uncertain. The
                // existing store normally annotates every failure, including cleanup failures.
                storage = ResourceInventoryWriteOutcome.Unknown;
                try
                {
                    receipt = await ResourceInventoryStore.RecordAsync(writer, prepared.InventoryInput, mine.Token,
                        () => AdmitCommit(generation, mine), baseline).ConfigureAwait(false);
                    storage = receipt.Outcome;
                }
                catch (Exception error)
                {
                    if (error.Data[ResourceInventoryDatabase.OutcomeKey] is ResourceInventoryWriteOutcome outcome) storage = outcome;
                    throw;
                }
                EnsureCurrent(generation, mine);
                if (_bootstrapHooks?.BeforeReadback is not null) await _bootstrapHooks.BeforeReadback().ConfigureAwait(false);
                EnsureCurrent(generation, mine);
            }
            // Reopen independently after the writer and every SQL resource are disposed.
            // Never promote the write receipt itself to readback or runtime admission.
            readback = ResourceRuntimeReadback.Failed;
            var connection = await CreateConnectionAsync(SqliteOpenMode.ReadOnly).ConfigureAwait(false);
            var database = await RuntimeDatabaseSnapshotReader.ReadAsync(connection, mine.Token, includeSkillData: prepared.Candidate.OptionalSkills is not null,
                includeDailyCatalog: prepared.Candidate.OptionalDailyCatalog is not null,
                includeInstanceCatalog: prepared.Candidate.OptionalInstances is not null).ConfigureAwait(false);
            EnsureCurrent(generation, mine);
            var hashes = prepared.Candidate.SourceSha256.ToDictionary(p => p.Key, p => (string?)p.Value, StringComparer.Ordinal);
            if (!RuntimeDatabaseStructuralMatcher.Match(database.Snapshot, prepared.Identity, hashes, mine.Token).MatchesSuppliedRuntime)
                throw new ResourceValidationException("Stored resource bytes differ from current decoded sources");
            // Optional mismatch removes only its feature. Required ten-table matching above still
            // gates the complete publication; no database row can introduce new catalog evidence.
            readbackCandidate = prepared.Candidate.OptionalSkills is not null &&
                !RuntimeDatabaseStructuralMatcher.MatchReviewedSkillData(database.Snapshot, mine.Token)
                ? prepared.Candidate.WithoutOptionalSkills() : prepared.Candidate;
            if (readbackCandidate.OptionalDailyCatalog is not null && !RuntimeDatabaseStructuralMatcher.MatchDailyCatalog(
                database.Snapshot,
                prepared.InventoryInput.Tables.Single(table => table.Name == "DailyTaskData_C.bytes").Sha256,
                prepared.InventoryInput.Tables.Single(table => table.Name == "DailyTaskRewardData_C.bytes").Sha256, mine.Token))
                readbackCandidate = readbackCandidate.WithoutOptionalDailyCatalog();
            if (readbackCandidate.OptionalInstances is not null && !RuntimeDatabaseStructuralMatcher.MatchInstanceCatalog(
                database.Snapshot,
                prepared.InventoryInput.Tables.Single(table => table.Name == "DungeonData_C.bytes").Sha256,
                prepared.InventoryInput.Tables.Single(table => table.Name == "CooperateEventData_C.bytes").Sha256, mine.Token))
                readbackCandidate = readbackCandidate.WithoutOptionalInstances();
            readback = ResourceRuntimeReadback.Matched;
            if (bootstrap)
            {
                if (_bootstrapHooks?.BeforeCacheWrite is not null) await _bootstrapHooks.BeforeCacheWrite().ConfigureAwait(false);
                EnsureCurrent(generation, mine);
                // Cache files are only version-keyed byte candidates, never database or
                // runtime authority. A later failure cannot undo already atomic file writes
                // or the committed inventory. Keep the final source recheck after disk work.
                await _cacheWriter.StoreAsync(prepared.VerifiedSources, mine.Token).ConfigureAwait(false);
                EnsureCurrent(generation, mine);
                if (_bootstrapHooks?.AfterCacheWrite is not null) await _bootstrapHooks.AfterCacheWrite().ConfigureAwait(false);
                EnsureCurrent(generation, mine);
            }
            if ((_bootstrapHooks?.ItemImagesForOfflineTest?.Invoke(prepared) ?? prepared.ItemImages) is { } batch)
            {
                if (bootstrap)
                {
                    // Reobserve remote identity before storage; reobserve again before publication.
                    // Remote changes cannot be made atomic with local SQLite. A later failure may
                    // leave durable cache bytes, but never a current image publication.
                    await _preparation.ConfirmUnchangedAsync(_source, prepared, mine.Token).ConfigureAwait(false);
                    EnsureCurrent(generation, mine);
                    imageStorage = AccountResourceStorageOutcome.Unknown;
                    try
                    {
                        await SpritePngStore.WriteAsync(ImageConnection(SqliteOpenMode.ReadWriteCreate), batch.Pixels,
                            () => { _bootstrapHooks?.BeforeImageCommitAdmission?.Invoke(); EnsureCurrent(generation, mine); }, mine.Token).ConfigureAwait(false);
                        imageStorage = AccountResourceStorageOutcome.Committed;
                    }
                    catch (Exception error)
                    {
                        imageStorage = error.Data[ResourceInventoryDatabase.OutcomeKey] switch
                        {
                            ResourceInventoryWriteOutcome.NotCommitted => AccountResourceStorageOutcome.NotCommitted,
                            ResourceInventoryWriteOutcome.Committed => AccountResourceStorageOutcome.Committed,
                            _ => AccountResourceStorageOutcome.Unknown
                        };
                        throw; // No automatic retry or silent storage failure.
                    }
                }
                EnsureCurrent(generation, mine);
                // Read-only refresh never creates a missing image cache.
                if (bootstrap || File.Exists(_itemImages))
                {
                    var pngs = await SpritePngStore.ReadAsync(ImageConnection(SqliteOpenMode.ReadOnly), batch.Pixels,
                        () => EnsureCurrent(generation, mine), mine.Token).ConfigureAwait(false);
                    itemImages = new(batch, pngs);
                }
            }
            if ((_bootstrapHooks?.PortraitsForOfflineTest?.Invoke(prepared) ?? prepared.Portraits) is { } portraitBatch)
            {
                if (bootstrap)
                {
                    await _preparation.ConfirmUnchangedAsync(_source, prepared, mine.Token).ConfigureAwait(false);
                    EnsureCurrent(generation, mine);
                    portraitStorage = AccountResourceStorageOutcome.Unknown;
                    try
                    {
                        await PortraitPngStore.WriteAsync(PortraitConnection(SqliteOpenMode.ReadWriteCreate), portraitBatch.Plan,
                            portraitBatch.Rebuild, () => { _bootstrapHooks?.BeforePortraitCommitAdmission?.Invoke(); EnsureCurrent(generation, mine); }, mine.Token).ConfigureAwait(false);
                        portraitStorage = AccountResourceStorageOutcome.Committed;
                    }
                    catch (Exception error)
                    {
                        portraitStorage = error.Data[ResourceInventoryDatabase.OutcomeKey] switch
                        {
                            ResourceInventoryWriteOutcome.NotCommitted => AccountResourceStorageOutcome.NotCommitted,
                            ResourceInventoryWriteOutcome.Committed => AccountResourceStorageOutcome.Committed,
                            _ => AccountResourceStorageOutcome.Unknown
                        };
                        throw;
                    }
                }
                EnsureCurrent(generation, mine);
                if (bootstrap || File.Exists(_portraits))
                {
                    portraits = await PortraitPngStore.ReadAsync(PortraitConnection(SqliteOpenMode.ReadOnly), portraitBatch.Plan,
                        portraitBatch.Rebuild, () => EnsureCurrent(generation, mine), mine.Token).ConfigureAwait(false);
                    portraits = portraits with { Mapping = portraitBatch.Mapping };
                }
            }
            await _preparation.ConfirmUnchangedAsync(_source, prepared, mine.Token).ConfigureAwait(false);
            sourcesRechecked = true;
            preparedResult = prepared;
        }
        catch (Exception error) { failure = error; }
        try
        {
            // Offline-only instrumentation cannot bypass or prevent actual cleanup.
            try { _cleanupEntered?.Invoke(); }
            catch (Exception error) { failure = Combine(failure, error); }
            try { await mine.CleanupAsync().ConfigureAwait(false); }
            catch (Exception error) { failure = Combine(failure, error); }
            if (failure is null)
            {
                try
                {
                    lock (_gate)
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        EnsureCurrent(generation, mine);
                        publication = _current = new(this, generation, preparedResult!, readbackCandidate, itemImages, portraits);
                    }
                }
                catch (Exception error) { failure = error; }
            }
            return new(storageAttempted, storage, mine.CommitAdmitted, receipt, readback,
                sourcesRechecked, publication, failure) { ItemImageStorageOutcome = imageStorage, PortraitStorageOutcome = portraitStorage };
        }
        finally
        {
            execution.Dispose();
            lock (_gate)
            {
                if (ReferenceEquals(_attempt, mine)) _attempt = null;
                mine.Retired.SetResult();
            }
        }
    }
    private async Task<ResourceInventoryWriteBaseline> CaptureWriteBaselineAsync(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        try
        {
            if ((File.GetAttributes(_inventory) & FileAttributes.Directory) != 0)
                throw new InvalidDataException("Inventory location is not a file");
        }
        catch (FileNotFoundException) { return ResourceInventoryWriteBaseline.Empty; }
        catch (DirectoryNotFoundException) { return ResourceInventoryWriteBaseline.Empty; }
        // Missing is distinct from unreadable/malformed. Never create storage to capture a
        // baseline, and complete read cleanup before source acquisition or writer creation.
        var connection = await CreateConnectionAsync(SqliteOpenMode.ReadOnly).ConfigureAwait(false);
        return await ResourceInventoryWriteBaseline.CaptureAsync(connection, token).ConfigureAwait(false);
    }

    private SqliteConnection PortraitConnection(SqliteOpenMode mode) => new(new SqliteConnectionStringBuilder
    { DataSource = _portraits, Mode = mode, Cache = SqliteCacheMode.Private, Pooling = false, DefaultTimeout = 5 }.ToString());

    private SqliteConnection ImageConnection(SqliteOpenMode mode) => new(new SqliteConnectionStringBuilder
    { DataSource = _itemImages, Mode = mode, Cache = SqliteCacheMode.Private, Pooling = false, DefaultTimeout = 5 }.ToString());

    private async Task<DbConnection> CreateConnectionAsync(SqliteOpenMode mode)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder
        {
            DataSource = _inventory, Mode = mode, Cache = SqliteCacheMode.Private, Pooling = false,
            DefaultTimeout = RuntimeDatabaseSnapshotReader.CommandTimeoutSeconds
        }.ToString());
        try
        {
            return _bootstrapHooks?.WrapConnection is { } wrap
                ? wrap(connection) ?? throw new InvalidOperationException("Offline connection wrapper returned null") : connection;
        }
        catch (Exception error)
        {
            try { await connection.DisposeAsync().ConfigureAwait(false); }
            catch (Exception cleanup) { throw new AggregateException(error, cleanup); }
            throw;
        }
    }
    private void AdmitCommit(long generation, Attempt attempt)
    {
        // This offline hook runs before the gate; no SQL, provider, callback or await runs
        // under the gate. Production construction has neither hooks nor provider injection.
        _bootstrapHooks?.BeforeCommitAdmission?.Invoke();
        lock (_gate)
        {
            EnsureCurrent(generation, attempt);
            attempt.CommitAdmitted = true;
        }
    }
    private static Exception Combine(Exception? primary, Exception addition)
        => primary is null ? addition : new AggregateException(primary, addition);
    private void EnsureCurrent(long generation, Attempt attempt)
    {
        attempt.ThrowIfCancellationRequested();
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_generation != generation || !ReferenceEquals(_attempt, attempt))
                throw new OperationCanceledException("Resource refresh superseded");
        }
    }
    // The shared active flag also retires copies captured by callbacks/background work.
    // On the cancellation worker, the thread-local scope survives Register's context
    // replacement, UnsafeRegister and suppressed-flow registration. An external dispatcher
    // moving a callback to another thread without this context is outside the self-join guard.
    private sealed class OwnerExecution : IDisposable
    {
        private static readonly AsyncLocal<OwnerExecution?> Ambient = new();
        [ThreadStatic] private static OwnerExecution? _cancelling;
        private readonly ResourceRuntimeOwner _owner;
        private readonly OwnerExecution? _parent;
        private readonly OwnerExecution? _previousCancellation;
        private readonly bool _cancellation;
        private int _active = 1;
        internal OwnerExecution(ResourceRuntimeOwner owner, bool cancellation = false)
        {
            _owner = owner; _parent = Ambient.Value; _cancellation = cancellation;
            Ambient.Value = this;
            if (cancellation) { _previousCancellation = _cancelling; _cancelling = this; }
        }
        internal static bool Contains(ResourceRuntimeOwner owner)
        {
            for (var scope = Ambient.Value; scope is not null; scope = scope._parent)
                if (ReferenceEquals(scope._owner, owner) && Volatile.Read(ref scope._active) != 0) return true;
            for (var scope = _cancelling; scope is not null; scope = scope._previousCancellation)
                if (ReferenceEquals(scope._owner, owner) && Volatile.Read(ref scope._active) != 0) return true;
            return false;
        }
        public void Dispose()
        {
            Volatile.Write(ref _active, 0);
            Ambient.Value = _parent;
            if (_cancellation) _cancelling = _previousCancellation;
        }
    }
    // All cancellation, including caller cancellation, enters this owned asynchronous operation.
    // Sealing prevents late cancellation from racing CTS disposal; cleanup joins every callback.
    private sealed class Attempt
    {
        private readonly object _gate = new();
        private readonly CancellationTokenSource _cts = new();
        private readonly ResourceRuntimeOwner _owner;
        private CancellationTokenRegistration _caller;
        private Task? _cancellation;
        private bool _sealed;
        private int _cancellationRequested;
        private CancellationToken _callerToken;
        internal bool CommitAdmitted { get; set; }
        internal CancellationToken Token { get; }
        internal TaskCompletionSource Retired { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal Attempt(ResourceRuntimeOwner owner) => (_owner, Token) = (owner, _cts.Token);
        internal void RegisterCaller(CancellationToken token)
        {
            _callerToken = token;
            _caller = token.UnsafeRegister(state => { _ = RequestCancellation(); }, null);
        }
        internal void ThrowIfCancellationRequested()
        {
            _callerToken.ThrowIfCancellationRequested();
            if (Volatile.Read(ref _cancellationRequested) != 0) throw new OperationCanceledException(Token);
            Token.ThrowIfCancellationRequested();
        }
        internal Task RequestCancellation()
        {
            lock (_gate)
            {
                if (_sealed) return _cancellation ?? Task.CompletedTask;
                Volatile.Write(ref _cancellationRequested, 1);
                // Own the actual callback execution thread, not just the caller's context.
                // No callbacks execute under either lock. The task completes only after
                // every callback returns, even when a callback throws or reenters disposal.
                return _cancellation ??= Task.Run(() =>
                {
                    using var execution = new OwnerExecution(_owner, cancellation: true);
                    _cts.Cancel();
                });
            }
        }
        internal async Task CleanupAsync()
        {
            Exception? failure = null;
            try { await _caller.DisposeAsync().ConfigureAwait(false); }
            catch (Exception error) { failure = error; }
            Task? pending;
            lock (_gate) { _sealed = true; pending = _cancellation; }
            try { if (pending is not null) await pending.ConfigureAwait(false); }
            catch (Exception error) { failure = failure is null ? error : new AggregateException(failure, error); }
            finally { _cts.Dispose(); }
            if (failure is not null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }
    public ValueTask DisposeAsync()
    {
        TaskCompletionSource? completion = null;
        Attempt? previous = null;
        Task result;
        lock (_gate)
        {
            if (_disposeTask is null)
            {
                _disposed = true; _current = null; _activation = null; _generation = checked(_generation + 1);
                previous = _attempt;
                completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
                _disposeTask = completion.Task;
            }
            result = _disposeTask;
        }
        if (completion is not null) _ = FinishDisposeAsync(previous, completion);
        // Starting disposal is safe here; joining our own refresh/callback/source cleanup
        // is not. Report the rejected join honestly, while the real disposal stays pending.
        if (!result.IsCompleted && OwnerExecution.Contains(this))
            return ValueTask.FromException(new InvalidOperationException(
                "Resource owner disposal was requested, but cannot be awaited from its own active operation. " +
                "An external caller must await DisposeAsync to observe complete cleanup."));
        return new(result);
    }
    private async Task FinishDisposeAsync(Attempt? previous, TaskCompletionSource completion)
    {
        var execution = new OwnerExecution(this);
        Exception? failure = null;
        try
        {
            if (previous is not null)
            {
                // Retirement includes admission-to-first-await gaps and asynchronous callbacks.
                Task cancellation = previous.RequestCancellation();
                await previous.Retired.Task.ConfigureAwait(false);
                try { await cancellation.ConfigureAwait(false); }
                catch (Exception error) { failure = error; }
            }
            try
            {
                if (_source is IAsyncDisposable asyncDisposable) await asyncDisposable.DisposeAsync().ConfigureAwait(false);
                else if (_source is IDisposable disposable) disposable.Dispose();
            }
            catch (Exception error) { failure = failure is null ? error : new AggregateException(failure, error); }
        }
        catch (Exception error) { failure = failure is null ? error : new AggregateException(failure, error); }
        finally { execution.Dispose(); }
        if (failure is null) completion.SetResult();
        else completion.SetException(failure);
    }
}
