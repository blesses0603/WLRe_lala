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
    private readonly ResourceProgressState progress = new();
    public ResourcePreparationProgress Progress => progress.Snapshot;
    private readonly ResourceRuntimeOwner owner;
    private ResourceRuntimeActivation? activation;
    private Task<PreloginResourceResult>? running;
    private Task? disposal;
    private bool retired;
    private readonly TaskCompletionSource retirement = new(TaskCreationOptions.RunContinuationsAsynchronously);
    internal Task Retirement => retirement.Task;
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
    // Borrow the current activation; the startup preparation retains ownership.
    // Binding performs no network, decode, database access or account transition.
    internal bool TryBindAccount(AccountSession session, SessionSnapshot snapshot, out AccountResourceBinding? binding)
    {
        lock (gate)
        {
            binding = null;
            return !retired && activation is not null && AccountResourceBinding.TryBind(session, snapshot, activation, out binding);
        }
    }
    /// <summary>Visual-only input from an immutable server role request and verified portrait readback.</summary>
    public bool TryGetRolePortrait(AccountRoleSelectionRequest request, byte index, out PortraitRenderRequest? portrait)
    {
        lock (gate)
        {
            portrait = null;
            var roles = request.Roles.Where(role => role.Index == index).ToArray();
            if (retired || activation is null || roles.Length != 1 ||
                !activation.TrySelectRolePortrait(roles[0], out var selection, out var image)) return false;
            var currentActivation = activation;
            portrait = new(image!, selection!, index, null, () =>
            {
                lock (gate) return !retired && ReferenceEquals(activation, currentActivation) && currentActivation.IsActive;
            });
            return true;
        }
    }
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
            execute = owner.Reserve(true, token, progress); // Pure reservation; Stop cannot miss an admitted attempt.
        }
        var result = await execute().ConfigureAwait(false);
        lock (gate)
        {
            var status = result.Failure is OperationCanceledException || token.IsCancellationRequested || retired ? PreloginResourceStatus.Cancelled :
                result.Failure is not null ? PreloginResourceStatus.Failed :
                owner.TryActivate(result.Publication, out activation) ? PreloginResourceStatus.Ready : PreloginResourceStatus.NotAdmitted;
            progress.Set(status switch
            {
                PreloginResourceStatus.Ready => "必要資源驗證完成",
                PreloginResourceStatus.Cancelled => "已取消資源準備",
                PreloginResourceStatus.NotAdmitted => "資源來源或版本未通過准入驗證",
                _ => result.Failure is BundleSourceException { Failure: BundleSourceFailure.VersionsChanged or BundleSourceFailure.ManifestChanged } ? "官方版本已變更，請重新查詢後準備" :
                    result.Failure is BundleSourceException { Failure: BundleSourceFailure.Budget } ? "資源超過安全容量限制，未啟用" :
                    result.Failure is BundleSourceException { Failure: BundleSourceFailure.SourceUnavailable } ? "官方資源暫時無法取得，請稍後重新查詢" :
                    result.Failure is HttpRequestException ? "官方資源連線失敗，請稍後重新查詢" :
                    result.Failure is IOException ? "資源讀寫失敗，請檢查磁碟空間與存取權限" :
                    "資源取得或驗證失敗；未啟用資源，請重新查詢官方版本"
            }, finished: true);
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
            progress.Set("已取消資源準備", finished: true);
            retired = true; activation = null; owner.Invalidate(); retirement.TrySetResult();
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
