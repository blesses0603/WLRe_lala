using Lala.Core.Catalogs;
using Lala.Core.Sessions;

namespace Lala.Core.Resources;

public enum PreloginResourceStatus { Ready, NotAdmitted, Cancelled, Failed }
/// <summary>Historical result only. Reacquire Matches/HasCurrentResources before use.</summary>
public sealed record PreloginResourceResult(PreloginResourceStatus Status, AccountResourceStorageOutcome StorageOutcome,
    bool ReadbackMatched, bool SourcesRechecked)
{
    public AccountResourceStorageOutcome PortraitStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome SmallMapStorageOutcome {get;init;}=AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome EmojiStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public AccountResourceStorageOutcome ItemImageStorageOutcome { get; init; } = AccountResourceStorageOutcome.NotAttempted;
    public bool CanLogin => false;
    public bool CanSendPackets => false;
}

/// <summary>Single-attempt resource-only owner, with no account, credentials or game socket.
/// Construction is inert. Production sources and verification remain private to Core.
/// Ready means current required-table catalogs, not all images or protocol compatibility.</summary>
public sealed class PreloginResourcePreparation : IAsyncDisposable
{
    private readonly object gate = new();
    private readonly ResourceRuntimeOwner owner;
    private ResourceRuntimeActivation? activation;
    private Task<PreloginResourceResult>? running;
    private Task? disposal;
    private bool retired;
    public AccountResourceDisclosure Disclosure { get; }
    private PreloginResourcePreparation(string root, ResourceRuntimeOwner? supplied = null)
    {
        Disclosure = new(root);
        owner = supplied ?? ResourceRuntimeOwner.Create(Disclosure.AbsoluteDataRoot);
    }
    public static PreloginResourcePreparation Create(string absoluteDataRoot) => new(absoluteDataRoot);
    internal static PreloginResourcePreparation CreateForOfflineTests(string root, ResourceRuntimeOwner owner) => new(root, owner);
    public bool HasCurrentResources { get { lock (gate) return !retired && activation?.IsActive == true; } }
    public bool HasVisualAssets => false; // Other image families remain unavailable.
    public bool HasItemImages { get { lock (gate) return !retired && activation?.HasItemImages == true; } }
    public bool TryReadItemImage(ushort itemId, out byte[]? png)
    {
        lock (gate) { png = null; return !retired && activation is not null && activation.TryReadItemImage(itemId, out png); }
    }
    public bool CanLogin => false;
    public bool CanSendPackets => false;
    public bool Matches(OfficialVersionSnapshot? version)
    {
        lock (gate)
        {
            if (retired || version is null || activation?.IsActive != true) return false;
            var identity = activation.Identity;
            return identity.DataVersion == version.DataVersion && identity.ExeVersion == version.ExeVersion &&
                identity.Packages.Count == version.Packages.Count && identity.Packages.All(p => version.Packages.TryGetValue(p.Name, out var v) && v == p.FullVersion) && activation.IsActive;
        }
    }
    public bool TryReadCatalogs(out OfflineRuntimeCandidate? catalogs)
    {
        lock (gate)
        {
            catalogs = null;
            return !retired && activation is not null && activation.TryReadCatalogs(out catalogs);
        }
    }
    public Task<PreloginResourceResult> PrepareAsync(CancellationToken token = default)
    {
        lock (gate) return running ??= Task.Run(() => RunAsync(token));
    }
    private async Task<PreloginResourceResult> RunAsync(CancellationToken token)
    {
        using var registration = token.Register(Stop);
        Func<Task<ResourceRuntimeBootstrapResult>> execute;
        lock (gate)
        {
            if (retired) return new(PreloginResourceStatus.Cancelled, AccountResourceStorageOutcome.NotAttempted, false, false);
            execute = owner.Reserve(true, token); // Pure reservation; Stop cannot miss an admitted attempt.
        }
        var result = await execute().ConfigureAwait(false);
        lock (gate)
        {
            var status = result.Failure is OperationCanceledException || token.IsCancellationRequested || retired ? PreloginResourceStatus.Cancelled :
                result.Failure is not null ? PreloginResourceStatus.Failed :
                owner.TryActivate(result.Publication, out activation) ? PreloginResourceStatus.Ready : PreloginResourceStatus.NotAdmitted;
            if (status != PreloginResourceStatus.Ready) activation = null;
            var storage = !result.StorageAttempted ? AccountResourceStorageOutcome.NotAttempted : result.StorageOutcome switch
            {
                ResourceInventoryWriteOutcome.Committed => AccountResourceStorageOutcome.Committed,
                ResourceInventoryWriteOutcome.NotCommitted => AccountResourceStorageOutcome.NotCommitted,
                _ => AccountResourceStorageOutcome.Unknown
            };
            return new(status, storage, result.Readback == ResourceRuntimeReadback.Matched, result.SourcesRechecked)
                { ItemImageStorageOutcome = result.ItemImageStorageOutcome, PortraitStorageOutcome = result.PortraitStorageOutcome, EmojiStorageOutcome = result.EmojiStorageOutcome, SmallMapStorageOutcome=result.SmallMapStorageOutcome };
        }
    }
    public void Stop()
    {
        lock (gate)
        {
            if (retired) return;
            retired = true; activation = null; owner.Invalidate();
        }
    }
    public ValueTask DisposeAsync()
    {
        lock (gate) { Stop(); return new(disposal ??= DisposeCoreAsync()); }
    }
    private async Task DisposeCoreAsync()
    {
        try { if (running is { } pending) await pending.ConfigureAwait(false); }
        finally { await owner.DisposeAsync().ConfigureAwait(false); }
    }
}
