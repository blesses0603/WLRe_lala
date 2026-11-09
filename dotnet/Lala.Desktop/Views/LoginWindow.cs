using System.Collections.Immutable;
using Lala.Core.Catalogs;
using System.Net;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Threading;
using Lala.Core.Sessions;
using Lala.Core.Protocol;

namespace Lala.Desktop;

/// <summary>Single-attempt desktop host. No saved credentials or general game commands; release-owned protocol policy.</summary>
public sealed class LoginWindow : DesktopWindow, IAccountLoginInput, IAccountRoleSelector, IAccountLoginSendConfirmation
{
    private readonly DesktopSession session;
    private readonly TextBox account = new() { Name = "LoginAccount", MaxLength = 255 };
    private readonly TextBox password = new() { Name = "LoginPassword", PasswordChar = '*', MaxLength = 255 };
    private readonly ComboBox servers = Ui.Combo([], -1, "LoginServer");
    private readonly ComboBox lines = Ui.Combo([], -1, "LoginLine");
    private readonly IDesktopServerCatalog catalogSource;
    private DesktopServerCatalogSnapshot? catalog;
    private DesktopServerLine[] groupLines = [];
    private CancellationTokenSource discoveryStop = new();
    private Task? discoveryTask;
    private readonly Button refresh;
    private readonly TextBlock catalogStatus = Ui.Text("正在載入官方伺服器清單…", color: Ui.Muted);
    private readonly ComboBox roles = Ui.Combo([], -1, "LoginRoles");
    private readonly TextBlock status = Ui.Text("請選擇伺服器與分流，再輸入帳號密碼。", color: Ui.Muted);
    private readonly Button submit, disconnect, enter;
    private readonly Action openMain;
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private AccountLoginPreparation? preparation;
    private AccountRuntime? runtime;
    private readonly Func<string?> resourceRoot;
    private readonly Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady;
    private OfflineRuntimeCandidate? lastCatalogs;
    private CancellationTokenSource? cancellation;
    private Task? operation;
    private TaskCompletionSource<AccountRoleSelectionChoice?>? roleCompletion;
    private AccountRoleSelectionRequest? roleRequest;
    private long presentationGeneration, sequence;
    private AccountReceivePublication? lastPublication;
    private bool openedMain, stopping, closed;
    private Window? confirmationWindow;
    private bool closePending;
    private readonly Button preview, inspector;

    public LoginWindow(DesktopSession session, Action openPreview, Action openInspector, Action? openVersion = null, Func<string?>? resourceRoot = null, Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady = null)
        : this(session, openPreview, openInspector, Program.UiSmokeTest ? new OfflineDesktopServerCatalog() : new OfficialDesktopServerCatalog(), openVersion, resourceRoot, resourcesReady) { }

    internal LoginWindow(DesktopSession session, Action openPreview, Action openInspector, IDesktopServerCatalog catalogSource, Action? openVersion = null, Func<string?>? resourceRoot = null, Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady = null)
        : base("飄流Re:LaLa  =By赤寧= · 登入／選角", 900, 620)
    {
        this.catalogSource = catalogSource; this.resourceRoot = resourceRoot ?? (() => null); this.resourcesReady = resourcesReady;
        this.session = session; openMain = openPreview;
        submit = Ui.Button("登入", () => { if (operation is null) { stopping = false; operation = LoginAsync(); } }, "LoginSubmit");
        disconnect = Ui.Button("中斷", async () => await StopAsync(), "LoginDisconnect");
        enter = Ui.Button("選角進入", SelectRole, "LoginEnterRole");
        disconnect.IsEnabled = enter.IsEnabled = false;
        roles.SelectionChanged += (_, _) => enter.IsEnabled = !stopping && roleRequest is not null &&
            roles.SelectedIndex >= 0 && !roleRequest.Roles[roles.SelectedIndex].Locked;
        account.TextChanged += (_, _) => ClearSecrets();
        servers.SelectionChanged += (_, _) => SelectServer();
        lines.SelectionChanged += (_, _) => { account.Text = ""; ClearSecrets(); UpdateAdmission(); };
        refresh = Ui.Button("版本檢測", () => { if (openVersion is null) StartDiscovery(); else { ClearSecrets(); openVersion(); } }, "LoginVersionCheck");
        submit.IsEnabled = false;
        Opened += (_, _) => StartDiscovery();
        var body = new StackPanel { Spacing = 8 };
        body.Children.Add(Ui.Text("登入與選角", 22, bold: true));
        body.Children.Add(Ui.Text("選擇帳號與分流，登入後再選取角色。", color: Ui.Muted));
        var toolbar = new Grid { ColumnDefinitions = new("Auto,Auto,Auto,*,Auto,Auto"), ColumnSpacing = 6 };
        Ui.At(toolbar, Ui.Unavailable("載入設定", "LoginLoadProfile", "安全帳號設定匯入尚未接入，不讀取舊版密碼。"), 0);
        Ui.At(toolbar, Ui.Unavailable("儲存設定", "LoginSaveProfile", "帳密不寫入設定。"), 1);
        Ui.At(toolbar, Ui.Text("帳號清單"), 2);
        var saved = Ui.Combo(["選擇已記住的帳號"], name: "LoginSavedAccounts"); saved.IsEnabled = false;
        Ui.At(toolbar, saved, 3); Ui.At(toolbar, refresh, 4);
        Ui.At(toolbar, Ui.Button("新增", () => { account.Text = ""; ClearSecrets(); }, "LoginNewDraft"), 5);
        body.Children.Add(toolbar);
        body.Children.Add(Ui.Text("官方資料自動載入；一般遊戲操作及資源啟用仍未完成。", color: Ui.Muted));
        body.Children.Add(catalogStatus);
        var fields = new Grid { ColumnDefinitions = new("*,*,*,*"), RowDefinitions = new("Auto,Auto,Auto,Auto,Auto"), ColumnSpacing = 6, RowSpacing = 5 };
        Ui.At(fields, Ui.Text("伺服器"), 0); Ui.At(fields, servers, 1);
        Ui.At(fields, Ui.Text("分流選擇"), 2); Ui.At(fields, lines, 3);
        Ui.At(fields, Ui.Text("帳號"), 0, 1, 2); Ui.At(fields, Ui.Text("密碼"), 2, 1, 2);
        Ui.At(fields, account, 0, 2, 2); Ui.At(fields, password, 2, 2, 2);
        Ui.At(fields, new CheckBox { Content = "記住帳號", Name = "LoginRememberAccount", IsEnabled = false }, 0, 3);
        Ui.At(fields, new CheckBox { Content = "記住密碼", Name = "LoginRememberPassword", IsEnabled = false }, 1, 3);
        Ui.At(fields, Ui.Unavailable("儲存此組", "LoginSaveIdentity", "安全憑證儲存尚未接入；不保存帳密。"), 2, 3);
        Ui.At(fields, Ui.Unavailable("刪除此組", "LoginDeleteIdentity", "沒有已儲存的帳密。"), 3, 3);
        Ui.At(fields, submit, 2, 4); Ui.At(fields, disconnect, 3, 4);
        body.Children.Add(Ui.Card("帳號登入", fields));
        var roleRow = new Grid { ColumnDefinitions = new("*,Auto"), ColumnSpacing = 8 };
        Ui.At(roleRow, roles, 0); Ui.At(roleRow, enter, 1);
        body.Children.Add(Ui.Card("選擇角色", roleRow));
        body.Children.Add(Ui.Text("官方 TCP 沒有 TLS；XOR 可逆，不提供安全加密，網路觀察者可能還原帳密。", color: Ui.Muted));
        body.Children.Add(Ui.Text("每次登入只嘗試一次；兩次帳密傳送須在一分鐘內分別確認。包含登入 ACK／心跳，不開啟一般遊戲操作。", 12, Ui.Muted));
        body.Children.Add(Ui.Text("帳密不記錄或儲存；清除文字框無法保證 .NET 字串立即從記憶體抹除。", 12, Ui.Muted));
        body.Children.Add(status);
        preview = Ui.Button("檢視桌面介面", () => { ClearSecrets(); openPreview(); }, "LoginPreview");
        inspector = Ui.Button("封包檢查", () => { ClearSecrets(); openInspector(); }, "LoginInspector");
        body.Children.Add(Ui.Row(preview, inspector));
        SetBody(new ScrollViewer { Content = body });
        timer.Tick += (_, _) => Publish();
        Closing += (_, args) =>
        {
            ClearSecrets();
            if (operation is not null || discoveryTask is { IsCompleted: false }) { args.Cancel = true; _ = StopAndCloseAsync(); }
        };
        Closed += (_, _) => { closed = true; timer.Stop(); ClearSecrets(); account.Text = ""; };
    }

    private void UpdateAdmission()
    {
        submit.IsEnabled = operation is null && !closed && catalog?.IsFresh == true && (resourcesReady is null || resourcesReady(catalog.Version)) &&
            lines.SelectedIndex >= 0 && lines.SelectedIndex < groupLines.Length && groupLines[lines.SelectedIndex].Profile is not null;
    }
    private void SelectServer()
    {
        account.Text = ""; ClearSecrets();
        groupLines = catalog?.Lines.Where(line => line.Group == servers.SelectedItem as string).ToArray() ?? [];
        lines.ItemsSource = groupLines.Select(line => line.Label).ToArray();
        lines.SelectedIndex = groupLines.Length > 0 ? 0 : -1; // Same group -> first available line as Python.
        UpdateAdmission();
    }
    internal void StartDiscovery()
    {
        if (operation is not null || discoveryTask is { IsCompleted: false } || closed) return;
        if (discoveryStop.IsCancellationRequested) { discoveryStop.Dispose(); discoveryStop = new(); }
        discoveryTask = DiscoverAsync();
    }
    private async Task DiscoverAsync()
    {
        catalog = null; groupLines = []; servers.ItemsSource = Array.Empty<string>(); lines.ItemsSource = Array.Empty<string>();
        account.Text = ""; ClearSecrets(); submit.IsEnabled = refresh.IsEnabled = false;
        catalogStatus.Text = "正在載入官方伺服器清單…";
        try
        {
            catalog = await catalogSource.LoadAsync(discoveryStop.Token);
            discoveryStop.Token.ThrowIfCancellationRequested();
            servers.ItemsSource = catalog.Lines.Select(line => line.Group).Distinct().ToArray();
            servers.SelectedIndex = -1; lines.SelectedIndex = -1;
            catalogStatus.Text = catalog.Status;
        }
        catch (OperationCanceledException) { catalogStatus.Text = "官方清單更新已取消。"; }
        catch (Exception) { catalogStatus.Text = "官方伺服器清單無法驗證；登入已阻擋，請重新版本檢測。"; }
        finally { refresh.IsEnabled = !closed; UpdateAdmission(); }
    }
    public void ClearSecrets() => password.Text = "";
    private async Task StopAndCloseAsync()
    {
        if (closePending) return; closePending = true;
        try { await ShutdownAsync(); if (!closed) Close(); }
        finally { closePending = false; }
    }
    internal Task ShutdownAsync() => StopAsync();
    public async Task StopAsync()
    {
        stopping = true; enter.IsEnabled = false;
        discoveryStop.Cancel();
        session.SetItemImageReader(presentationGeneration, null);
        cancellation?.Cancel(); preparation?.Stop(); runtime?.Stop(); roleCompletion?.TrySetResult(null);
        confirmationWindow?.Close(false);
        if (operation is { } running) await running;
        if (discoveryTask is { } pending) await pending;
    }

    private async Task LoginAsync()
    {
        // Yield ensures the task is assigned before synchronous validation can finish.
        await Task.Yield();
        AccountSession? core = null;
        try
        {
            if (stopping) return;
            if (catalog?.IsFresh != true || (resourcesReady is not null && !resourcesReady(catalog.Version)) || lines.SelectedIndex < 0 || lines.SelectedIndex >= groupLines.Length ||
                groupLines[lines.SelectedIndex].Profile is not { } profile)
                throw new InvalidOperationException("No current supported official line selected.");
            openedMain = false; sequence = 0; lastPublication = null; lastCatalogs = null;
            servers.IsEnabled = lines.IsEnabled = refresh.IsEnabled = false;
            preview.IsEnabled = inspector.IsEnabled = false;
            account.IsEnabled = password.IsEnabled = submit.IsEnabled = false; disconnect.IsEnabled = true;
            cancellation = new(); core = new();
            var identity = Guid.NewGuid();
            var snapshot = core.Begin(identity.ToString("N"), profile.FormalEndpoint.ToString());
            session.Reset(identity.ToString("N")); presentationGeneration = session.Generation;
            if (resourceRoot() is { } root)
            {
                runtime = AccountRuntime.CreatePrepared(core, snapshot.Generation, identity, profile, this, root,
                    new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                if (!await ConfirmResourcesAsync(runtime.Disclosure!.Resources, cancellation.Token)) return;
                if (resourcesReady is not null && !resourcesReady(catalog.Version)) throw new InvalidOperationException("Prelogin resources retired.");
                cancellation.Token.ThrowIfCancellationRequested();
                var imageRuntime = runtime;
                session.SetItemImageReader(presentationGeneration, id => imageRuntime.TryReadItemImage(id, out var png) ? png : null);
                timer.Start();
                var result = await runtime.RunAsync(cancellation.Token);
                status.Text = $"連線結束：{result.Connection.Status.EndReason}；資源釋放：{result.ResourcesReleased}。已完成或結果不明的寫入不會回復。";
            }
            else
            {
                preparation = new(core, snapshot.Generation, identity, profile, this,
                    new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                timer.Start();
                var result = await preparation.RunAsync(cancellation.Token);
                status.Text = $"連線結束：{result.Status.EndReason}；資源釋放：{result.ResourcesReleased}。重新登入需重新輸入及確認。";
            }
        }
        catch (Exception) { status.Text = "登入未完成：請重新版本檢測並選擇分流，確認 ASCII 帳密後重試。"; }
        finally
        {
            timer.Stop(); session.SetItemImageReader(presentationGeneration, null);
            try { if (runtime is not null) await runtime.DisposeAsync(); if (preparation is not null) await preparation.DisposeAsync(); }
            catch (Exception) { status.Text = "連線清理失敗；請關閉程式後再試。"; closed = true; }
            core?.Disconnect(); preparation = null; runtime = null; lastCatalogs = null;
            cancellation?.Dispose(); cancellation = null;
            roleCompletion?.TrySetResult(null); roleCompletion = null; roleRequest = null;
            roles.ItemsSource = Array.Empty<string>(); roles.SelectedIndex = -1; enter.IsEnabled = false;
            session.Reset(); ClearSecrets(); account.Text = "";
            servers.IsEnabled = lines.IsEnabled = refresh.IsEnabled = !closed;
            account.IsEnabled = password.IsEnabled = !closed;
            preview.IsEnabled = inspector.IsEnabled = true;
            disconnect.IsEnabled = false; operation = null; UpdateAdmission();
        }
    }

    public async ValueTask<AccountLoginCredentials?> AcquireAsync(AccountLoginDisclosure disclosure, CancellationToken token)
        => await Dispatcher.UIThread.InvokeAsync(() =>
        {
            token.ThrowIfCancellationRequested();
            try { return new AccountLoginCredentials((account.Text ?? "").AsSpan(), (password.Text ?? "").AsSpan()); }
            finally { ClearSecrets(); account.Text = ""; }
        });

    public async ValueTask<bool> ConfirmAsync(AccountLoginRecipient recipient, IPEndPoint endpoint, CancellationToken token)
        => await Dispatcher.UIThread.InvokeAsync(() => ConfirmOnUiAsync(recipient, endpoint, token));

    private async Task<bool> ConfirmOnUiAsync(AccountLoginRecipient recipient, IPEndPoint endpoint, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        var dialog = new Window { Title = "確認本次帳密傳送", Icon = Icon, Width = 620, Height = 260, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        confirmationWindow = dialog;
        var panel = new StackPanel { Margin = new(20), Spacing = 12 };
        panel.Children.Add(Ui.Text($"即將將帳號與密碼傳送至{(recipient == AccountLoginRecipient.Verification ? "驗證" : "正式")}端點：{endpoint}"));
        panel.Children.Add(Ui.Text("沒有 TLS；XOR 可逆，不提供安全加密。網路觀察者可能還原帳密。"));
        panel.Children.Add(Ui.Text("只同意這一次傳送；取消或關閉將中止本次登入。"));
        panel.Children.Add(Ui.Row(Ui.Button("取消", () => dialog.Close(false), "LoginSendCancel"), Ui.Button("知悉風險，確認傳送", () => dialog.Close(true), "LoginSendConfirm")));
        dialog.Content = panel;
        using var registration = token.Register(() => Dispatcher.UIThread.Post(() => dialog.Close(false)));
        try { var approved = await dialog.ShowDialog<bool>(this); token.ThrowIfCancellationRequested(); return approved && (resourcesReady is null || resourcesReady(catalog?.Version)); }
        finally { confirmationWindow = null; }
    }

    public async ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token)
        => await Dispatcher.UIThread.InvokeAsync(() => SelectOnUiAsync(request, token));

    private async Task<AccountRoleSelectionChoice?> SelectOnUiAsync(AccountRoleSelectionRequest request, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        roleRequest = request;
        var pending = new TaskCompletionSource<AccountRoleSelectionChoice?>(TaskCreationOptions.RunContinuationsAsynchronously);
        roleCompletion = pending;
        roles.ItemsSource = request.Roles.Select(r => $"{r.Index} · {r.Name} · Lv.{r.Level}{(r.Locked ? "（鎖定）" : "")}").ToArray();
        roles.SelectedIndex = -1; enter.IsEnabled = false;
        status.Text = "請選擇角色；按「確認選角進入」會傳送此角色選擇並繼續世界登入協定。";
        using var registration = token.Register(() => pending.TrySetCanceled(token));
        try { return await pending.Task; }
        finally { roleRequest = null; roleCompletion = null; roles.SelectedIndex = -1; enter.IsEnabled = false; }
    }
    private void SelectRole()
    {
        if (stopping || roleRequest is not { } request || roles.SelectedIndex < 0) return;
        var role = request.Roles[roles.SelectedIndex];
        if (!role.Locked) { enter.IsEnabled = false; roleCompletion?.TrySetResult(request.Choose(role.Index)); }
    }
    private async Task<bool> ConfirmResourcesAsync(AccountResourceDisclosure disclosure, CancellationToken token)
    {
        var dialog = new Window { Title = "確認本次資源下載與寫入", Icon = Icon, Width = 760, Height = 430, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        confirmationWindow = dialog;
        dialog.Content = new ScrollViewer { Content = Ui.Column(
            Ui.Text("登入協定完成後，下載並驗證官方資源", 20, bold: true),
            Ui.Text("HTTPS 來源：" + disclosure.ResourceUrlPrefix),
            Ui.Text("版本入口：" + disclosure.VersionMapUrl),
            Ui.Text("SQLite：" + disclosure.InventoryPath), Ui.Text("物品圖快取：" + disclosure.ItemImageCachePath), Ui.Text("Bundle 快取：" + disclosure.BundleCacheDirectory),
            Ui.Text("將建立目錄、寫入經驗證的 Bundle／暫存檔與 SQLite（含 journal），再獨立回讀及重查來源版本。停止不會撤銷已完成的寫入；結果不明時不自動重試。"),
            Ui.Text("資源綁定只提供唯讀目錄與核心投影；一般遊戲操作仍停用。尚非 Python 全量資源／圖資功能。帳密只傳給另行確認的遊戲端點，不傳到資源 HTTPS。"),
            Ui.Row(Ui.Button("取消", () => dialog.Close(false), "ResourceSendCancel"),
                Ui.Button("確認本次下載與寫入", () => dialog.Close(true), "ResourceSendConfirm"))) };
        using var registration = token.Register(() => Dispatcher.UIThread.Post(() => dialog.Close(false)));
        try { var approved = await dialog.ShowDialog<bool>(this); token.ThrowIfCancellationRequested(); return approved && (resourcesReady is null || resourcesReady(catalog?.Version)); }
        finally { confirmationWindow = null; }
    }
    private void Publish()
    {
        if (stopping || (preparation is null && runtime is null)) return;
        if (session.Generation != presentationGeneration) { cancellation?.Cancel(); preparation?.Stop(); runtime?.Stop(); return; }
        var joined = runtime?.PublicationSnapshot;
        var connection = joined?.Connection ?? preparation!.Snapshot;
        var publication = joined?.Publication?.Receive ?? (runtime is null ? preparation?.Publication : null);
        var catalogs = joined?.Publication?.Catalogs;
        var resourceState = runtime?.Snapshot;
        var resourceText = resourceState is null ? "未選資源準備" : resourceState.HasCurrentResources ? "資源目錄已綁定（唯讀）" :
            resourceState.ResourceHistory.LastOrDefault()?.Preparation is { } outcome
                ? $"資源 {outcome.Status}／寫入 {outcome.StorageOutcome}／物品圖寫入 {outcome.ItemImageStorageOutcome}；回讀 {outcome.ReadbackMatched}／來源重查 {outcome.SourcesRechecked}"
                : "等待登入完成或資源準備中";
        session.SetConnectionText(connection.Phase == AccountConnectionPhase.ReceivingHeld
            ? "登入協定完成｜" + resourceText + "｜遊戲操作 Held" : "登入進行中｜等待確認或伺服器回覆");
        if (publication is null) return;
        if (!ReferenceEquals(publication, lastPublication) || !ReferenceEquals(catalogs, lastCatalogs))
        {
            lastPublication = publication; lastCatalogs = catalogs;
            var labels = catalogs is null ? new DesktopLabels() : new DesktopLabels
            {
                Items = catalogs.Items.ToImmutableDictionary(p => p.Key, p => p.Value.Name),
                Scenes = catalogs.SceneNames.ToImmutableDictionary()
            };
            session.Publish(presentationGeneration, ++sequence, publication.State, labels);
        }
        if (!openedMain && connection.Phase == AccountConnectionPhase.ReceivingHeld && publication.State.Player is not null)
        {
            openedMain = true; status.Text = "已接收世界登入資料；" + resourceText + "，一般遊戲操作停用。"; openMain();
        }
    }
}
