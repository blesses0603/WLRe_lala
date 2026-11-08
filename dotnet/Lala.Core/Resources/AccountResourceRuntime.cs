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

    private async Task<AccountResourcePreparationResult> RunAsync(long expectedGeneration, bool bootstrap, CancellationToken token)
    {
        SessionSnapshot snapshot;
        long revision;
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_running) throw new InvalidOperationException("A resource preparation is already running or retiring");
            snapshot = _session.Snapshot;
            if (snapshot.Generation != expectedGeneration || snapshot.Phase == SessionPhase.Disconnected)
                throw new InvalidOperationException("A current active account generation is required");
            _running = true; revision = _revision; _binding = null;
        }
        ResourceRuntimeBootstrapResult? result = null;
        Exception? failure = null;
        try
        {
            try
            {
                result = bootstrap
                    ? await _owner.BootstrapAndRefreshAsync(token).ConfigureAwait(false)
                    : await _owner.RefreshWithResultAsync(token).ConfigureAwait(false);
                failure = result.Failure;
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
                    _binding = binding;
                    status = AccountResourcePreparationStatus.Bound;
                }
                else status = ReferenceEquals(_session.Snapshot, snapshot)
                    ? AccountResourcePreparationStatus.NotAdmitted : AccountResourcePreparationStatus.AccountChanged;
                return new(expectedGeneration, status, StorageOutcome(result),
                    result?.Readback == ResourceRuntimeReadback.Matched, result?.SourcesRechecked == true);
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
            _revision = checked(_revision + 1); _binding = null;
            // This owner operation only changes internal state and schedules cancellation;
            // it performs no I/O or synchronous caller callbacks.
            _owner.Invalidate();
        }
    }

    /// <summary>Revoke synchronously and join owned I/O/callback cleanup. An already-returning
    /// preparation may still deliver its historical result, but cannot publish after disposal.</summary>
    public ValueTask DisposeAsync()
    {
        lock (_gate) { _disposed = true; _binding = null; }
        return _owner.DisposeAsync();
    }
}
