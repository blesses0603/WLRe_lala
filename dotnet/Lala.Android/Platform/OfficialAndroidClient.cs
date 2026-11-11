using System.Net;
using Lala.Android.Lifecycle;
using Lala.Android.Live;
using Lala.Core.Gameplay;
using Lala.Core.Resources;
using Lala.Core.Sessions;
using Lala.Desktop;

namespace Lala.Android.Platform;

/// <summary>Process-owned official client. The Activity never owns a socket or a password store.</summary>
internal sealed class OfficialAndroidClient : IMobileOfficialClient, IConnectionAdapterFactory
{
    internal static OfficialAndroidClient Instance { get; } = new();
    private readonly object gate = new();
    private readonly SemaphoreSlim preparationLane = new(1, 1);
    private readonly string root = Path.Combine(global::Android.App.Application.Context.FilesDir!.AbsolutePath, "official-resources");
    private DesktopServerCatalogSnapshot? catalog;
    private PreloginResourcePreparation? prepared;
    private CancellationTokenSource? preparationStop;
    private LoginAdapter? pending, active;
    private bool busy, cleanupBlocked;
    private string status = "正在準備官方連線入口";
    private AccountRuntimePublication? publication;
    private AccountRoleSelectionRequest? roles;
    private bool connected, canChat, canAct;
    public bool IsAvailable => true;
    public MobileOfficialSnapshot Snapshot
    {
        get
        {
            lock (gate)
            {
                var host = ConnectionServiceClient.Instance.Snapshot;
                return new(catalog?.Lines.Select(x => new MobileOfficialLine(x.Id, x.Group, x.Label, x.Profile is not null)).ToArray() ?? [],
                    catalog?.Version, prepared?.Progress ?? new("尚未準備官方資源"), busy || pending is not null || active is not null && !connected,
                    prepared?.Matches(catalog?.Version) == true, connected, canChat, canAct, host.NotificationsAllowed,
                    host.Bound, status, roles, publication)
                {
                    Automations = active?.Runtime?.Automations.Values.ToArray() ?? [],
                    Navigation = active?.Runtime?.NavigationStatus ?? new(false, "尚未啟動導航")
                };
            }
        }
    }
    public async Task RefreshAsync()
    {
        if (!await preparationLane.WaitAsync(0).ConfigureAwait(false)) return;
        CancellationTokenSource stop;
        lock (gate)
        {
            if (active is not null || pending is not null || cleanupBlocked) { preparationLane.Release(); return; }
            busy = true; status = "正在查詢官方版本與分流"; preparationStop = stop = new();
        }
        try
        {
            var observed = await new OfficialDesktopServerCatalog().LoadAsync(stop.Token).ConfigureAwait(false);
            lock (gate) catalog = observed;
            if (!observed.Lines.Any(x => x.Profile is not null)) { lock (gate) status = "官方版本或協定尚未支援，登入保持停用"; return; }
            PreloginResourcePreparation? old;
            lock (gate)
            {
                if (prepared?.Matches(observed.Version) == true) { status = "官方資源已就緒，請選擇分流登入"; return; }
                old = prepared; prepared = null; status = "正在驗證、下載官方資源";
            }
            if (old is not null) await old.DisposeAsync().ConfigureAwait(false);
            var next = PreloginResourcePreparation.Create(root);
            lock (gate) prepared = next;
            var result = await next.PrepareAsync(stop.Token).ConfigureAwait(false);
            var after = await new OfficialDesktopServerCatalog().LoadAsync(stop.Token).ConfigureAwait(false);
            lock (gate)
            {
                catalog = after;
                status = result.Status == PreloginResourceStatus.Ready && next.Matches(after.Version)
                    ? "官方資源已驗證，請選擇分流登入" : next.Progress.Phase;
            }
        }
        catch (OperationCanceledException) { lock (gate) status = "官方資料準備已取消"; }
        catch (Exception) { lock (gate) status = "官方清單或資源準備失敗，請重新檢查網路後查詢"; }
        finally
        {
            lock (gate) { busy = false; if (ReferenceEquals(preparationStop, stop)) preparationStop = null; }
            stop.Dispose(); preparationLane.Release();
        }
    }
    public void CancelPreparation() { lock (gate) preparationStop?.Cancel(); }
    public bool Login(int lineId, ReadOnlySpan<char> account, ReadOnlySpan<char> password)
    {
        LoginAdapter selected;
        lock (gate)
        {
            if (busy || active is not null || pending is not null || cleanupBlocked) return false;
            // This only stages one user-requested attempt. The adapter obtains a fresh
            // official observation before opening TCP and again before each credential
            // write, so an older UI list must not force resource preparation to repeat.
            if (catalog is not { } expected || prepared?.Matches(expected.Version) != true ||
                expected.Lines.SingleOrDefault(x => x.Id == lineId)?.Profile is not { } profile) { status = "請先完成官方清單與資源驗證"; return false; }
            var host = ConnectionServiceClient.Instance.Snapshot;
            if (!host.Bound) { status = "連線服務尚未綁定，請返回 App 後重試"; return false; }
            if (!host.NotificationsAllowed) { status = "請先允許連線通知，再按登入"; return false; }
            try { selected = new(this, expected, lineId, profile, prepared, new AccountLoginCredentials(account, password)); }
            catch (ArgumentException) { status = "帳號或密碼格式不正確"; return false; }
            pending = selected; status = "正在建立官方登入連線";
        }
        if (ConnectionServiceClient.Instance.StartFromUser(new(selected.Key, selected.Endpoint))) { _ = ExpirePendingAsync(selected); return true; }
        lock (gate) { if (ReferenceEquals(pending, selected)) pending = null; status = "Android 尚未接受連線請求，請重新操作"; }
        selected.ClearCredentials(); return false;
    }
    private async Task ExpirePendingAsync(LoginAdapter selected)
    {
        await Task.Delay(TimeSpan.FromMinutes(2)).ConfigureAwait(false);
        lock (gate) if (ReferenceEquals(pending, selected)) { pending = null; selected.ClearCredentials(); status = "等待連線已逾時，請重新輸入帳密"; }
    }
    public IConnectionAdapter Create(ConnectionTarget target)
    {
        lock (gate)
        {
            if (active is not null || pending is not { } selected || selected.Key != target.AccountKey || selected.Endpoint != target.Endpoint)
                throw new InvalidOperationException("No current Android login selection.");
            pending = null; active = selected; return selected;
        }
    }
    public void SelectRole(Guid requestId, int index) { lock (gate) active?.Choose(requestId, index); }
    public void Disconnect()
    {
        LoginAdapter? staged; lock (gate) { preparationStop?.Cancel(); staged = pending; pending = null; }
        staged?.ClearCredentials(); ConnectionServiceClient.Instance.StopFromUser();
    }
    public void RequestNotifications() => ConnectionServiceClient.Instance.RequestNotificationsFromUser();
    public Task SendChatAsync(string channel, string text, uint? target = null)
    {
        AccountRuntime runtime; lock (gate) runtime = canChat && active?.Runtime is { } value ? value : throw new InvalidOperationException("請先完成登入");
        return runtime.SendChatAsync(channel, text, target);
    }
    public Task ExecuteAsync(GameAction action)
    {
        AccountRuntime runtime; lock (gate) runtime = canAct && active?.Runtime is { } value ? value : throw new InvalidOperationException("連線或必要資源尚未就緒");
        return runtime.ExecuteActionAsync(action);
    }
    private AccountRuntime ActionRuntime()
    { lock (gate) return canAct && active?.Runtime is { } runtime ? runtime : throw new InvalidOperationException("連線或必要資源尚未就緒"); }
    public Task SetAutomationAsync(string kind, bool enabled) => ActionRuntime().SetAutomationAsync(kind, enabled);
    public Task NavigateAsync(ushort scene, ushort x, ushort y) => ActionRuntime().NavigateAsync(scene, x, y);
    public Task StopNavigationAsync()
    {
        AccountRuntime? runtime; lock (gate) runtime = active?.Runtime;
        return runtime?.StopNavigationAsync() ?? Task.CompletedTask;
    }
    public PortraitRenderRequest? Portrait(bool companion)
    {
        AccountRuntime? runtime; lock (gate) runtime = active?.Runtime;
        var state = runtime?.Publication?.Receive.State;
        return state is not null && runtime!.TryGetPortrait(state, companion, out var image) ? image : null;
    }
    public PortraitRenderRequest? RolePortrait(Guid requestId, byte index)
    {
        lock (gate) return roles is { } current && current.RequestId == requestId && prepared is { } resources && resources.TryGetRolePortrait(current, index, out var image) ? image : null;
    }
    public SmallMapRenderRequest? SmallMap(ushort scene)
    {
        AccountRuntime? runtime; lock (gate) runtime = active?.Runtime;
        return runtime is not null && runtime.TryGetSmallMap(scene, out var image) ? image : null;
    }
    public byte[]? ItemImage(ushort itemId)
    {
        AccountRuntime? runtime; lock (gate) runtime = active?.Runtime;
        return runtime is not null && runtime.TryReadItemImage(itemId, out var png) ? png : null;
    }
    private void Observe(LoginAdapter owner)
    {
        var runtime = owner.Runtime; if (runtime is null) return;
        var current = runtime.PublicationSnapshot;
        lock (gate)
        {
            if (!ReferenceEquals(active, owner)) return;
            publication = current.Publication;
            connected = runtime.LoginProgress?.Stage == AccountLoginStage.ProtocolComplete && publication?.Receive.Phase == AccountReceivePhase.Running;
            canChat = connected && runtime.CanSendChat; canAct = connected && runtime.CanSendGameActions;
            status = connected ? "已登入官方伺服器，正在接收即時資料" : DesktopLoginTarget.Describe(runtime.LoginProgress?.Stage);
            if (runtime.ActionStatus is { } action) status = action.Label + "：" + action.Message;
        }
    }
    private sealed class LoginAdapter(OfficialAndroidClient owner, DesktopServerCatalogSnapshot expected, int lineId,
        AccountConnectionProfile profile, PreloginResourcePreparation prepared, AccountLoginCredentials input)
        : IHeldConnectionAdapter, IAccountLoginInput, IAccountRoleSelector, IAccountLoginSendConfirmation
    {
        private readonly object gate = new();
        private AccountLoginCredentials? credentials = input;
        private AccountRoleSelectionRequest? request;
        private TaskCompletionSource<AccountRoleSelectionChoice?>? selection;
        private bool disposed;
        internal string Key { get; } = Guid.NewGuid().ToString("N");
        internal string Endpoint => profile.FormalEndpoint.ToString();
        internal AccountRuntime? Runtime { get; private set; }
        internal void ClearCredentials() { lock (gate) { credentials?.Dispose(); credentials = null; } }
        internal void Choose(Guid requestId, int index)
        {
            lock (gate) if (request is { } current && current.RequestId == requestId && current.Roles.Any(x => x.Index == index && !x.Locked)) selection?.TrySetResult(current.Choose(index));
        }
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            lock (gate) { var result = credentials; credentials = null; return ValueTask.FromResult(result); }
        }
        public async ValueTask<bool> ConfirmAsync(AccountLoginRecipient recipient, IPEndPoint endpoint, CancellationToken token)
        {
            var destination = recipient == AccountLoginRecipient.Verification ? profile.VerificationEndpoint : profile.FormalEndpoint;
            if (!destination.Equals(endpoint)) return false;
            var observed = await new OfficialDesktopServerCatalog().LoadAsync(token).ConfigureAwait(false);
            return DesktopLoginTarget.Matches(expected, observed, lineId) && prepared.Matches(observed.Version);
        }
        public async ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest current, CancellationToken token)
        {
            TaskCompletionSource<AccountRoleSelectionChoice?> pending;
            lock (gate) { request = current; selection = pending = new(TaskCreationOptions.RunContinuationsAsynchronously); }
            lock (owner.gate) if (ReferenceEquals(owner.active, this)) owner.roles = current;
            using var registration = token.Register(() => pending.TrySetCanceled(token));
            try { return await pending.Task.ConfigureAwait(false); }
            finally { lock (gate) { request = null; selection = null; } lock (owner.gate) if (ReferenceEquals(owner.roles, current)) owner.roles = null; }
        }
        public Task<ConnectionEndReason> RunAsync(Action active, CancellationToken token) => RunHeldAsync(active, () => { }, token);
        public async Task<ConnectionEndReason> RunHeldAsync(Action receiving, Action retiring, CancellationToken token)
        {
            var session = new AccountSession(); bool announced = false, draining = false;
            try
            {
                var observed = await new OfficialDesktopServerCatalog().LoadAsync(token).ConfigureAwait(false);
                if (!DesktopLoginTarget.Matches(expected, observed, lineId) || !prepared.Matches(observed.Version))
                {
                    lock (owner.gate) owner.status = "官方分流或版本已變更，請重新查詢官方資料";
                    return ConnectionEndReason.ResourceHeld;
                }
                var snapshot = session.Begin(Key, Endpoint);
                Runtime = AccountRuntime.CreateUsingPreparedResources(session, snapshot.Generation, Guid.ParseExact(Key, "N"), profile, this, prepared,
                    new() { MaximumAttempts = 1, LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                var operation = Runtime.RunAsync(token);
                while (!operation.IsCompleted)
                {
                    owner.Observe(this);
                    if (!announced && Runtime.LoginProgress?.Stage == AccountLoginStage.ProtocolComplete) { announced = true; receiving(); }
                    if (!draining && Runtime.Snapshot.Connection.Phase is AccountConnectionPhase.Draining or AccountConnectionPhase.Stopping or AccountConnectionPhase.Ended) { draining = true; retiring(); }
                    await Task.WhenAny(operation, Task.Delay(200, token)).ConfigureAwait(false); token.ThrowIfCancellationRequested();
                }
                var result = await operation.ConfigureAwait(false);
                lock (owner.gate) owner.status = DesktopLoginTarget.DescribeEnd(result.Connection.Status);
                return token.IsCancellationRequested ? ConnectionEndReason.UserStopped : ConnectionEndReason.RemoteClosed;
            }
            catch (OperationCanceledException) { return ConnectionEndReason.UserStopped; }
            catch (Exception) { lock (owner.gate) owner.status = "官方登入或資料接收未完成，連線已停止"; return ConnectionEndReason.AdapterFailure; }
            finally
            {
                if (!draining) retiring();
                ClearCredentials();
                if (Runtime is { } runtime)
                {
                    runtime.Stop();
                    try { await runtime.DisposeAsync().ConfigureAwait(false); }
                    catch (Exception) { lock (owner.gate) { owner.cleanupBlocked = true; owner.status = "連線清理未完成，請關閉 App 後重試"; } }
                }
                session.Disconnect();
                lock (owner.gate)
                {
                    if (ReferenceEquals(owner.active, this))
                    { owner.connected = owner.canChat = owner.canAct = false; owner.publication = null; owner.roles = null; if (!owner.cleanupBlocked) owner.active = null; }
                }
            }
        }
        public ValueTask DisposeAsync()
        {
            lock (gate) { if (!disposed) { disposed = true; selection?.TrySetResult(null); ClearCredentials(); Runtime?.Stop(); } }
            return Volatile.Read(ref owner.cleanupBlocked) ? ValueTask.FromException(new InvalidOperationException("Connection cleanup is incomplete.")) : ValueTask.CompletedTask;
        }
    }
}
