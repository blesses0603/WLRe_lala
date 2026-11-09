using Lala.Core.Catalogs;
using Lala.Core.Sessions;

namespace Lala.Core.Resources;

public enum AccountResourcePreparationStatus { Bound, NotAdmitted, AccountChanged, Revoked, Cancelled, Failed }
public enum AccountResourceStorageOutcome { NotAttempted, NotCommitted, Committed, Unknown }

/// <summary>Historical, sanitized preparation outcome. A committed/unknown database write is
/// not undone by later failure. WasBound is not current authority; query the runtime again.</summary>
public sealed record AccountResourcePreparationResult(
    long AccountGeneration, AccountResourcePreparationStatus Status,
    AccountResourceStorageOutcome StorageOutcome, bool ReadbackMatched, bool SourcesRechecked)
{
    public AccountResourceStorageOutcome PortraitStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome SmallMapStorageOutcome {get;init;}=AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome EmojiStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome ItemImageStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public bool WasBound => Status == AccountResourcePreparationStatus.Bound;
    public bool CanLogin => false;
    public bool CanSendPackets => false;
}

/// <summary>
/// Host-callable resource-only composition for one AccountSession. The default source and fixed
/// SQLite inventory are owned internally; no public factory accepts claimed integrity or sources.
/// Construction is inert. Preparation may acquire official HTTPS resources and write the shared
/// resource inventory, but never authenticates an account or enables its command/resource gate.
/// </summary>
public sealed class AccountResourceRuntime : IAsyncDisposable
{
    private readonly object _gate = new();
    private readonly AccountSession _session;
    private readonly ResourceRuntimeOwner _owner;
    private AccountResourceBinding? _binding;
    private bool _running, _disposed;
    private long _revision;
    private TaskCompletionSource _bindingChanged = NewBindingSignal();
    internal long Revision { get { lock (_gate) return _revision; } }
    internal Task BindingChanged { get { lock (_gate) return _bindingChanged.Task; } }
    private static TaskCompletionSource NewBindingSignal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private void SetBindingLocked(AccountResourceBinding? binding)
    {
        if (ReferenceEquals(_binding, binding)) return;
        var previous = _bindingChanged;
        _binding = binding;
        _bindingChanged = NewBindingSignal();
        previous.SetResult();
    }

    private AccountResourceRuntime(AccountSession session, ResourceRuntimeOwner owner)
        => (_session, _owner) = (session, owner);

    public static AccountResourceRuntime Create(AccountSession session, string absoluteDataRoot)
    {
        ArgumentNullException.ThrowIfNull(session);
        return new(session, ResourceRuntimeOwner.Create(absoluteDataRoot));
    }

    // Test assembly only. Ownership transfers; normal offline owners remain non-authorizing.
    internal static AccountResourceRuntime CreateForOfflineTests(AccountSession session, ResourceRuntimeOwner owner)
    {
        ArgumentNullException.ThrowIfNull(session); ArgumentNullException.ThrowIfNull(owner);
        return new(session, owner);
    }

    public bool HasCurrentResources { get { lock (_gate) return !_disposed && _binding?.IsCurrent == true; } }
    public bool CanLogin => false;
    public bool CanSendPackets => false;

    /// <summary>Prepare ten required tables, persist the resource inventory, independently
    /// read it back, then reobserve source versions/manifests. No automatic retry on uncertainty.</summary>
    public Task<AccountResourcePreparationResult> BootstrapAsync(long expectedAccountGeneration,
        CancellationToken cancellationToken = default) => RunAsync(expectedAccountGeneration, true, cancellationToken);

    /// <summary>Same acquisition/readback validation without creating or repairing the database.</summary>
    public Task<AccountResourcePreparationResult> RefreshAsync(long expectedAccountGeneration,
        CancellationToken cancellationToken = default) => RunAsync(expectedAccountGeneration, false, cancellationToken);

    internal Task<AccountResourcePreparationResult> BootstrapAsync(SessionSnapshot expected, CancellationToken token,
        long? expectedRevision = null)
        => RunAsync(expected.Generation, true, token, expected, expectedRevision);
    internal Task<AccountResourcePreparationResult> RefreshAsync(SessionSnapshot expected, CancellationToken token,
        long? expectedRevision = null)
        => RunAsync(expected.Generation, false, token, expected, expectedRevision);

    private async Task<AccountResourcePreparationResult> RunAsync(long expectedGeneration, bool bootstrap, CancellationToken token,
        SessionSnapshot? expectedSnapshot = null, long? expectedRevision = null)
    {
        SessionSnapshot snapshot;
        long revision;
        Func<Task<ResourceRuntimeBootstrapResult>>? execute = null;
        Exception? failure = null;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_running) throw new InvalidOperationException("A resource preparation is already running or retiring");
            if (expectedRevision is not null && expectedRevision != _revision)
                return new(expectedGeneration, AccountResourcePreparationStatus.Revoked,
                    AccountResourceStorageOutcome.NotAttempted, false, false);
            snapshot = _session.Snapshot;
            if (expectedSnapshot is not null && !ReferenceEquals(snapshot, expectedSnapshot))
                return new(expectedGeneration, AccountResourcePreparationStatus.AccountChanged,
                    AccountResourceStorageOutcome.NotAttempted, false, false);
            if (snapshot.Generation != expectedGeneration || snapshot.Phase == SessionPhase.Disconnected)
                throw new InvalidOperationException("A current active account generation is required");
            // Reserve the owner's attempt while both this revision and the exact account
            // snapshot are protected. This is Core-owned synchronous state only; callbacks,
            // cancellation registration and I/O begin through execute after releasing gates.
            try
            {
                execute = _session.WithLoginSnapshot(current => ReferenceEquals(current, snapshot)
                    ? _owner.Reserve(bootstrap, token) : null);
            }
            catch (Exception error) { failure = error; }
            if (execute is null && failure is null)
                return new(expectedGeneration, AccountResourcePreparationStatus.AccountChanged,
                    AccountResourceStorageOutcome.NotAttempted, false, false);
            _running = true; revision = _revision; SetBindingLocked(null);
        }
        ResourceRuntimeBootstrapResult? result = null;
        try
        {
            try
            {
                // Every successful reservation is executed/drained exactly once, even if
                // retirement won since admission. The owner checks its epoch before I/O.
                if (execute is not null)
                {
                    result = await execute().ConfigureAwait(false);
                    failure = result.Failure;
                }
            }
            catch (Exception error) { failure = error; }
            lock (_gate)
            {
                AccountResourcePreparationStatus status;
                if (failure is not null)
                    status = failure is OperationCanceledException
                        ? AccountResourcePreparationStatus.Cancelled : AccountResourcePreparationStatus.Failed;
                else if (_disposed || revision != _revision || token.IsCancellationRequested)
                    status = token.IsCancellationRequested ? AccountResourcePreparationStatus.Cancelled : AccountResourcePreparationStatus.Revoked;
                else if (!ReferenceEquals(_session.Snapshot, snapshot)) status = AccountResourcePreparationStatus.AccountChanged;
                else if (AccountResourceBinding.TryBind(_session, expectedGeneration, _owner, result?.Publication, out var binding)
                    && ReferenceEquals(_session.Snapshot, snapshot))
                {
                    SetBindingLocked(binding);
                    status = AccountResourcePreparationStatus.Bound;
                }
                else status = ReferenceEquals(_session.Snapshot, snapshot)
                    ? AccountResourcePreparationStatus.NotAdmitted : AccountResourcePreparationStatus.AccountChanged;
                return new(expectedGeneration, status, StorageOutcome(result),
                    result?.Readback == ResourceRuntimeReadback.Matched, result?.SourcesRechecked == true)
                    { ItemImageStorageOutcome = result?.ItemImageStorageOutcome ?? AccountResourceStorageOutcome.NotAttempted,
                        PortraitStorageOutcome = result?.PortraitStorageOutcome ?? AccountResourceStorageOutcome.NotAttempted,
                        EmojiStorageOutcome = result?.EmojiStorageOutcome ?? AccountResourceStorageOutcome.NotAttempted, SmallMapStorageOutcome=result?.SmallMapStorageOutcome??AccountResourceStorageOutcome.NotAttempted };
            }
        }
        finally { lock (_gate) _running = false; }
    }

    private static AccountResourceStorageOutcome StorageOutcome(ResourceRuntimeBootstrapResult? result)
        => result?.StorageAttempted != true ? AccountResourceStorageOutcome.NotAttempted : result.StorageOutcome switch
        {
            ResourceInventoryWriteOutcome.NotCommitted => AccountResourceStorageOutcome.NotCommitted,
            ResourceInventoryWriteOutcome.Committed => AccountResourceStorageOutcome.Committed,
            _ => AccountResourceStorageOutcome.Unknown
        };

    /// <summary>Immutable point-in-time catalog data, never action authority. Each call rechecks
    /// account and resource lifetimes; later revocation cannot erase data already returned.</summary>
    /// <summary>Caller-owned historical PNG bytes. Reacquire on each operation; no send authority.</summary>
    public bool TryReadItemImage(ushort itemId, out byte[]? png)
    {
        lock (_gate) { png = null; return !_disposed && _binding is not null && _binding.TryReadItemImage(itemId, out png); }
    }
    public bool TryReadEmojiImage(byte token,out byte[]? png)
    {
        lock(_gate){png=null;return !_disposed&&_binding is not null&&_binding.TryReadEmoji(token,out png);}
    }
    internal SmallMapRenderRequest? ReadSmallMap(ushort scene,Func<bool> selectionCurrent)
    {lock(_gate)return !_disposed?_binding?.ReadSmallMap(scene,selectionCurrent):null;}
    internal EmojiGalleryRequest? ReadEmojiGallery()
    {lock(_gate)return !_disposed?_binding?.ReadEmojiGallery():null;}
    internal bool TrySelectPortrait(Lala.Core.Protocol.WorldPlayer? player,Lala.Core.Inventory.CompanionReceiveSnapshot companions,
        bool companion,out PortraitSelection? selection,out PortraitCachedImage? image)
    {
        lock(_gate) { selection=null;image=null;return !_disposed && _binding is not null && _binding.TrySelectPortrait(player,companions,companion,out selection,out image); }
    }
    public bool TryReadCatalogs(out OfflineRuntimeCandidate? catalogs)
    {
        lock (_gate)
        {
            catalogs = null;
            return !_disposed && _binding is not null && _binding.TryReadCatalogs(out catalogs);
        }
    }

    /// <summary>Immediately revoke selection and request cancellation. An already-admitted
    /// database commit may remain durable. No compensating write or automatic retry is made.</summary>
    public void Invalidate()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _revision = checked(_revision + 1); SetBindingLocked(null);
            // This owner operation only changes internal state and schedules cancellation;
            // it performs no I/O or synchronous caller callbacks.
            _owner.Invalidate();
        }
    }

    /// <summary>Revoke synchronously and join owned I/O/callback cleanup. An already-returning
    /// preparation may still deliver its historical result, but cannot publish after disposal.</summary>
    public ValueTask DisposeAsync()
    {
        lock (_gate) { _disposed = true; SetBindingLocked(null); }
        return _owner.DisposeAsync();
    }
}
