using System.Collections.Immutable;
using Avalonia;
using Lala.Core.Catalogs;
using System.Net;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Threading;
using Lala.Core.Sessions;
using Lala.Core.Protocol;

namespace Lala.Desktop;

/// <summary>Single-attempt desktop login with local account preferences and user-protected passwords.</summary>
public sealed partial class LoginWindow : DesktopWindow, IAccountLoginInput, IAccountRoleSelector, IAccountLoginSendConfirmation
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
    private readonly ListBox roles = new()
    {
        Name = "LoginRoles", Background = Avalonia.Media.Brushes.Transparent, BorderThickness = new(0), Padding = new(0),
        MaxHeight = 170, IsVisible = false,
        ItemsPanel = new Avalonia.Controls.Templates.FuncTemplate<Panel?>(() => new WrapPanel { Orientation = Orientation.Horizontal })
    };
    private readonly TextBlock roleEmpty = Ui.Text("登入後顯示角色資料卡", 13, Ui.Muted);
    private readonly TextBlock status = Ui.Text("請選擇伺服器與分流，再輸入帳號密碼。", color: Ui.Muted);
    private readonly Button submit, disconnect, enter;
    private readonly Action openMain;
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private AccountLoginPreparation? preparation;
    private AccountRuntime? runtime;
    private readonly Func<string?> resourceRoot;
    private readonly Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady;
    private readonly Func<Lala.Core.Resources.PreloginResourcePreparation?>? preparedResources;
    private OfflineRuntimeCandidate? lastCatalogs;
    private CancellationTokenSource? cancellation;
    private Task? operation;
    private TaskCompletionSource<AccountRoleSelectionChoice?>? roleCompletion;
    private AccountRoleSelectionRequest? roleRequest;
    private long presentationGeneration, sequence;
    private AccountReceivePublication? lastPublication;
    private bool openedMain, stopping, closed;
    private bool closePending;

    public LoginWindow(DesktopSession session, Action openPreview, Action openInspector, Action? openVersion = null, Func<string?>? resourceRoot = null, Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady = null,
        Func<AccountRoleSelectionRequest, byte, Lala.Core.Resources.PortraitRenderRequest?>? rolePortrait = null,
        Func<Lala.Core.Resources.PreloginResourcePreparation?>? preparedResources = null)
        : this(session, openPreview, openInspector, Program.UiSmokeTest ? new OfflineDesktopServerCatalog() : new OfficialDesktopServerCatalog(), openVersion, resourceRoot, resourcesReady, rolePortrait: rolePortrait, preparedResources: preparedResources) { }

    internal LoginWindow(DesktopSession session, Action openPreview, Action openInspector, IDesktopServerCatalog catalogSource, Action? openVersion = null, Func<string?>? resourceRoot = null, Func<Lala.Core.Resources.OfficialVersionSnapshot?, bool>? resourcesReady = null, LoginProfileStore? profileStore = null,
        Func<AccountRoleSelectionRequest, byte, Lala.Core.Resources.PortraitRenderRequest?>? rolePortrait = null,
        Func<Lala.Core.Resources.PreloginResourcePreparation?>? preparedResources = null)
        : base("飄流Re:LaLa  =By赤寧= · 登入／選角", 900, 620)
    {
        this.catalogSource = catalogSource; this.resourceRoot = resourceRoot ?? (() => null); this.resourcesReady = resourcesReady;
        this.session = session; openMain = openPreview;
        this.rolePortrait = rolePortrait;
        this.preparedResources = preparedResources;
        this.profileStore = profileStore ?? new LoginProfileStore(inMemory: Program.UiSmokeTest);
        submit = Ui.Button("登入", BeginLogin, "LoginSubmit");
        disconnect = Ui.Button("中斷", async () => await StopAsync(), "LoginDisconnect");
        enter = Ui.Button("選角進入", SelectRole, "LoginEnterRole");
        disconnect.IsEnabled = enter.IsEnabled = false;
        roles.SelectionChanged += (_, _) => enter.IsEnabled = !stopping && roleRequest is not null &&
            roles.SelectedIndex >= 0 && roles.SelectedIndex < roleRequest.Roles.Length && !roleRequest.Roles[roles.SelectedIndex].Locked;
        account.PropertyChanged += (_, change) =>
        {
            if (change.Property != TextBox.TextProperty) return;
            if (!applyingProfile) ClearSecrets();
            UpdateAdmission();
        };
        password.PropertyChanged += (_, change) => { if (change.Property == TextBox.TextProperty) UpdateAdmission(); };
        servers.SelectionChanged += (_, _) => SelectServer();
        lines.SelectionChanged += (_, _) => { if (!applyingProfile) { account.Text = ""; ClearSecrets(); } UpdateAdmission(); };
        refresh = Ui.Button("版本檢測", () => { if (openVersion is null) StartDiscovery(); else { ClearSecrets(); openVersion(); } }, "LoginVersionCheck");
        submit.IsEnabled = false;
        Opened += (_, _) => StartDiscovery();
        var body = new StackPanel { Spacing = 8 };
        body.Children.Add(Ui.Text("登入與選角", 22, bold: true));
        body.Children.Add(Ui.Text("選擇帳號與分流，登入後再選取角色。", color: Ui.Muted));
        var toolbar = new Grid { ColumnDefinitions = new("Auto,Auto,Auto,*,Auto,Auto"), ColumnSpacing = 6 };
        Ui.At(toolbar, Ui.Button("載入設定", () => _ = TransferProfilesAsync(import: true), "LoginLoadProfile"), 0);
        Ui.At(toolbar, Ui.Button("儲存設定", () => _ = TransferProfilesAsync(import: false), "LoginSaveProfile"), 1);
        Ui.At(toolbar, Ui.Text("帳號清單"), 2);
        Ui.At(toolbar, saved, 3); Ui.At(toolbar, refresh, 4);
        Ui.At(toolbar, Ui.Button("新增", NewProfile, "LoginNewDraft"), 5);
        managementControls.Add(toolbar);
        body.Children.Add(toolbar);
        var fields = new Grid { ColumnDefinitions = new("*,*,*,*"), RowDefinitions = new("Auto,Auto,Auto,Auto,Auto"), ColumnSpacing = 6, RowSpacing = 5 };
        Ui.At(fields, Ui.Text("伺服器"), 0); Ui.At(fields, servers, 1);
        Ui.At(fields, Ui.Text("分流選擇"), 2); Ui.At(fields, lines, 3);
        Ui.At(fields, Ui.Text("帳號"), 0, 1, 2); Ui.At(fields, Ui.Text("密碼"), 2, 1, 2);
        Ui.At(fields, account, 0, 2, 2); Ui.At(fields, password, 2, 2, 2);
        Ui.At(fields, rememberAccount, 0, 3);
        Ui.At(fields, rememberPassword, 1, 3);
        managementControls.Add(rememberAccount); managementControls.Add(rememberPassword);
        managementControls.Add(Ui.At(fields, Ui.Button("儲存此組", () => SaveCurrentProfile(), "LoginSaveIdentity"), 2, 3));
        managementControls.Add(Ui.At(fields, Ui.Button("刪除此組", DeleteProfile, "LoginDeleteIdentity"), 3, 3));
        Ui.At(fields, submit, 2, 4); Ui.At(fields, disconnect, 3, 4);
        body.Children.Add(Ui.Card("帳號登入", fields));
        var roleRow = new Grid { ColumnDefinitions = new("*,Auto"), ColumnSpacing = 8 };
        var roleContent = new Grid(); roleContent.Children.Add(roles); roleContent.Children.Add(roleEmpty);
        Ui.At(roleRow, roleContent, 0); Ui.At(roleRow, enter, 1);
        body.Children.Add(Ui.Card("選擇角色", roleRow));
        // Keep operational feedback available on the action without a footer row.
        submit.Bind(ToolTip.TipProperty, status.GetObservable(TextBlock.TextProperty));
        disconnect.Bind(ToolTip.TipProperty, status.GetObservable(TextBlock.TextProperty));
        enter.Bind(ToolTip.TipProperty, status.GetObservable(TextBlock.TextProperty));
        SetBody(new ScrollViewer { Content = body });
        InitializeProfiles();
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
        submit.IsEnabled = operation is null && !profileOperation && !closed && !string.IsNullOrWhiteSpace(account.Text) && !string.IsNullOrEmpty(password.Text) && catalog is not null && (resourcesReady is null || resourcesReady(catalog.Version)) &&
            lines.SelectedIndex >= 0 && lines.SelectedIndex < groupLines.Length && groupLines[lines.SelectedIndex].Profile is not null;
    }
    private void SelectServer()
    {
        if (!applyingProfile) { account.Text = ""; ClearSecrets(); }
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
        status.Text = "正在載入官方伺服器清單…";
        try
        {
            catalog = await catalogSource.LoadAsync(discoveryStop.Token);
            discoveryStop.Token.ThrowIfCancellationRequested();
            servers.ItemsSource = catalog.Lines.Select(line => line.Group).Distinct().ToArray();
            servers.SelectedIndex = -1; lines.SelectedIndex = -1;
            status.Text = "請選擇伺服器與分流，再輸入帳號密碼。";
            if (saved.SelectedItem is LoginProfile selected) ApplyProfile(selected);
        }
        catch (OperationCanceledException) { status.Text = "官方清單更新已取消。"; }
        catch (Exception) { status.Text = "官方伺服器清單無法驗證；登入已阻擋，請重新版本檢測。"; }
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
        session.SetItemImageReader(presentationGeneration, null); session.SetPortraitReader(presentationGeneration, null); session.SetEmojiReader(presentationGeneration, null); session.SetSmallMapReader(presentationGeneration, null); session.SetNpcReader(presentationGeneration,null);
        cancellation?.Cancel(); preparation?.Stop(); runtime?.Stop(); roleCompletion?.TrySetResult(null);
        if (operation is { } running) await running;
        if (discoveryTask is { } pending) await pending;
    }

    private DesktopServerCatalogSnapshot? attemptCatalog;
    private int attemptLineId;
    private async Task<bool> RevalidateTargetAsync(CancellationToken token)
    {
        if (attemptCatalog is not {} expected) return false;
        var observed = await catalogSource.LoadAsync(token);
        token.ThrowIfCancellationRequested();
        if (!DesktopLoginTarget.Matches(expected, observed, attemptLineId) ||
            (resourcesReady is not null && !resourcesReady(observed.Version)))
        { status.Text = "官方分流、協定或資源版本已變更；請重新查詢並選擇分流。"; return false; }
        catalog = observed;
        return true;
    }
    private async Task LoginAsync()
    {
        // Yield ensures the task is assigned before synchronous validation can finish.
        await Task.Yield();
        AccountSession? core = null;
        try
        {
            if (stopping) return;
            if (catalog is null || (resourcesReady is not null && !resourcesReady(catalog.Version)) || lines.SelectedIndex < 0 || lines.SelectedIndex >= groupLines.Length ||
                groupLines[lines.SelectedIndex].Profile is not { } profile)
                throw new InvalidOperationException("No current supported official line selected.");
            attemptCatalog = catalog; attemptLineId = groupLines[lines.SelectedIndex].Id;
            openedMain = false; sequence = 0; lastPublication = null; lastCatalogs = null;
            servers.IsEnabled = lines.IsEnabled = refresh.IsEnabled = false;
            SetManagementEnabled(false);
            account.IsEnabled = password.IsEnabled = submit.IsEnabled = false; disconnect.IsEnabled = true;
            cancellation = new(); core = new();
            var identity = Guid.NewGuid();
            var snapshot = core.Begin(identity.ToString("N"), profile.FormalEndpoint.ToString());
            session.Reset(AccountPreferenceIdentity.For(account.Text!, groupLines[lines.SelectedIndex].Group)); presentationGeneration = session.Generation;
            if (resourceRoot() is { } root)
            {
                if (preparedResources is not null)
                {
                    var prepared = preparedResources();
                    if (prepared?.Matches(catalog.Version) != true) throw new InvalidOperationException("Startup resources are no longer current.");
                    runtime = AccountRuntime.CreateUsingPreparedResources(core, snapshot.Generation, identity, profile, this, prepared,
                        new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                }
                else
                    runtime = AccountRuntime.CreatePrepared(core, snapshot.Generation, identity, profile, this, root,
                        new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                var sender = runtime; var sendToken = cancellation.Token;
                session.AttachChatSender(presentationGeneration, (channel, text, target) => sender.SendChatAsync(channel, text, target, sendToken));
                session.AttachGameSender(presentationGeneration, action => sender.ExecuteActionAsync(action, sendToken));
                session.AttachAutomationSender(presentationGeneration, (kind, enabled, settings) => sender.SetAutomationAsync(kind, enabled, settings),
                    (kind, settings) => sender.UpdateAutomationSettingsAsync(kind, settings));
                session.AttachEfficiencyResetter(presentationGeneration, () => sender.ResetEfficiencyAsync());
                session.AttachNavigation(presentationGeneration,
                    (target, token) => sender.PreviewNavigationAsync(target.Scene, target.X, target.Y, target.Synchronize, target.Mode, target.Smooth, token),
                    (target, token) => target.Mode == "land" ? sender.NavigateAsync(target.Scene, target.X, target.Y, target.Synchronize, token)
                        : Task.FromException(new InvalidOperationException("實際移動目前只支援步行；海上與飛行仍可預覽。")),
                    sender.StopNavigationAsync);
                if (resourcesReady is not null && !resourcesReady(catalog.Version)) throw new InvalidOperationException("Prelogin resources retired.");
                cancellation.Token.ThrowIfCancellationRequested();
                var imageRuntime = runtime;
                session.SetItemImageReader(presentationGeneration, id => imageRuntime.TryReadItemImage(id, out var png) ? png : null);
                session.SetEmojiReader(presentationGeneration, () => imageRuntime.TryGetEmojiGallery(out var gallery) ? gallery : null);
                session.SetNpcReader(presentationGeneration, scene=>imageRuntime.TryGetSceneNpcRoster(scene,out var roster)?roster:null);
                session.SetSmallMapReader(presentationGeneration, scene => imageRuntime.TryGetSmallMap(scene,out var request)?request:null);
                session.SetPortraitReader(presentationGeneration, (state, companion) => imageRuntime.TryGetPortrait(state, companion, out var request) ? request : null);
                if (!await RevalidateTargetAsync(cancellation.Token)) return;
                timer.Start();
                var result = await runtime.RunAsync(cancellation.Token);
                status.Text = $"{DesktopLoginTarget.DescribeEnd(result.Connection.Status)}；資源釋放：{result.ResourcesReleased}。";
            }
            else
            {
                preparation = new(core, snapshot.Generation, identity, profile, this,
                    new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
                var sender = preparation; var sendToken = cancellation.Token;
                session.AttachChatSender(presentationGeneration, (channel, text, target) => sender.SendChatAsync(channel, text, target, sendToken));
                if (!await RevalidateTargetAsync(cancellation.Token)) return;
                timer.Start();
                var result = await preparation.RunAsync(cancellation.Token);
                status.Text = $"{DesktopLoginTarget.DescribeEnd(result.Status)}；資源釋放：{result.ResourcesReleased}。重新登入需重新輸入帳密。";
            }
        }
        catch (OperationCanceledException) { status.Text = "登入已取消；不會自動重送。"; }
        catch (Exception) { status.Text = "登入未完成：官方清單重查、資源或連線檢查失敗，請重新查詢並選擇分流。"; }
        finally
        {
            timer.Stop(); session.SetItemImageReader(presentationGeneration, null); session.SetPortraitReader(presentationGeneration, null); session.SetEmojiReader(presentationGeneration, null); session.SetSmallMapReader(presentationGeneration, null); session.SetNpcReader(presentationGeneration,null);
            try { if (runtime is not null) await runtime.DisposeAsync(); if (preparation is not null) await preparation.DisposeAsync(); }
            catch (Exception) { status.Text = "連線清理失敗；請關閉程式後再試。"; closed = true; }
            core?.Disconnect(); preparation = null; runtime = null; lastCatalogs = null; attemptCatalog = null;
            cancellation?.Dispose(); cancellation = null;
            roleCompletion?.TrySetResult(null); roleCompletion = null; roleRequest = null;
            roles.ItemsSource = Array.Empty<ListBoxItem>(); roles.SelectedIndex = -1; enter.IsEnabled = false;
            roles.IsVisible = false; roleEmpty.IsVisible = true;
            session.Reset(); session.SetConnectionText(status.Text ?? "連線已結束。"); ClearSecrets(); account.Text = ""; ReloadProfiles();
            servers.IsEnabled = lines.IsEnabled = refresh.IsEnabled = !closed;
            account.IsEnabled = password.IsEnabled = !closed;
            disconnect.IsEnabled = false; operation = null; UpdateAdmission();
            SetManagementEnabled(!closed);
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
        => await Dispatcher.UIThread.InvokeAsync(async () =>
        {
            token.ThrowIfCancellationRequested();
            if (stopping || operation is null || attemptCatalog is null) return false;
            var profile = attemptCatalog.Lines.SingleOrDefault(line => line.Id == attemptLineId)?.Profile;
            var expected = recipient switch
            {
                AccountLoginRecipient.Verification => profile?.VerificationEndpoint,
                AccountLoginRecipient.Formal => profile?.FormalEndpoint,
                _ => null
            };
            // The Login click authorizes this one attempt. Revalidate the selected
            // target and resources before each credential send without a modal.
            return expected is not null && expected.Equals(endpoint) && await RevalidateTargetAsync(token);
        });

    public async ValueTask<AccountRoleSelectionChoice?> SelectAsync(AccountRoleSelectionRequest request, CancellationToken token)
        => await Dispatcher.UIThread.InvokeAsync(() => SelectOnUiAsync(request, token));

    private async Task<AccountRoleSelectionChoice?> SelectOnUiAsync(AccountRoleSelectionRequest request, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        roleRequest = request;
        var pending = new TaskCompletionSource<AccountRoleSelectionChoice?>(TaskCreationOptions.RunContinuationsAsynchronously);
        roleCompletion = pending;
        roles.SelectedIndex = -1;
        roles.IsEnabled = true;
        roles.ItemsSource = request.Roles.Select(role => CreateRoleCardWithPortrait(request, role)).ToArray();
        roles.IsVisible = true; roleEmpty.IsVisible = false; enter.IsEnabled = false;
        status.Text = "請選擇角色，再按「選角進入」或 Enter。";
        using var registration = token.Register(() => pending.TrySetCanceled(token));
        try { return await pending.Task; }
        finally
        {
            roleRequest = null; roleCompletion = null; roles.SelectedIndex = -1; enter.IsEnabled = false; roles.IsEnabled = false;
            foreach (var portrait in rolePortraitViews) await portrait.DisposeAsync();
            rolePortraitViews.Clear();
        }
    }
    private void SelectRole()
    {
        if (stopping || roleRequest is not { } request || roles.SelectedIndex < 0) return;
        var role = request.Roles[roles.SelectedIndex];
        if (!role.Locked) { enter.IsEnabled = false; roleCompletion?.TrySetResult(request.Choose(role.Index)); }
    }
    private void Publish()
    {
        if (stopping || (preparation is null && runtime is null)) return;
        if (session.Generation != presentationGeneration) { cancellation?.Cancel(); preparation?.Stop(); runtime?.Stop(); return; }
        var joined = runtime?.PublicationSnapshot;
        var connection = joined?.Connection ?? preparation!.Snapshot;
        var publication = joined?.Publication?.Receive ?? (runtime is null ? preparation?.Publication : null);
        var catalogs = joined?.Publication?.Catalogs;
        session.SetCatalogs(presentationGeneration, catalogs);
        var resourceState = runtime?.Snapshot;
        var resourceText = resourceState is null ? "本次連線未載入資源" : resourceState.HasCurrentResources ? "資源已就緒" :
            preparedResources is not null ? (resourceState.ResourceHistory.IsEmpty ? "正在綁定啟動資源" : "啟動資源已失效，請回資源準備頁") :
            resourceState.ResourceHistory.LastOrDefault()?.Preparation is { } outcome
                ? $"資源 {outcome.Status}／寫入 {outcome.StorageOutcome}／物品圖寫入 {outcome.ItemImageStorageOutcome}／頭像寫入 {outcome.PortraitStorageOutcome}／表情寫入 {outcome.EmojiStorageOutcome}／小地圖寫入 {outcome.SmallMapStorageOutcome}；回讀 {outcome.ReadbackMatched}／來源重查 {outcome.SourcesRechecked}"
                : "資源驗證中：" + runtime!.ResourceProgress.Phase;
        var stageText = DesktopLoginTarget.Describe((runtime?.LoginProgress ?? preparation?.LoginProgress)?.Stage);
        bool connected = connection.Phase == AccountConnectionPhase.ReceivingHeld && publication?.Phase == AccountReceivePhase.Running;
        session.SetConnected(presentationGeneration, connected);
        if (runtime is not null) session.SetGameplayState(presentationGeneration, runtime.CanSendGameActions, runtime.ActionStatus, runtime.ActionLog, runtime.Automations, runtime.NavigationStatus);
        session.SetConnectionText(connected ? "已連線｜" + resourceText : stageText);
        if (!openedMain) status.Text = stageText;
        if (publication is null) return;
        session.SetServerEvents(presentationGeneration, publication.CharacterEvents, publication.State.Player?.RoleId);
        if (!ReferenceEquals(publication, lastPublication) || !ReferenceEquals(catalogs, lastCatalogs))
        {
            lastPublication = publication; lastCatalogs = catalogs;
            var labels = catalogs is null ? new DesktopLabels() : new DesktopLabels
            {
                Items = catalogs.Items.ToImmutableDictionary(p => p.Key, p => p.Value.Name),
                Skills = (catalogs.OptionalSkills ?? new Dictionary<ushort, Lala.Core.Catalogs.SkillDataRow>())
                    .Where(p => catalogs.Texts.TryGetValue(p.Value.NameTextId, out var name) && !string.IsNullOrWhiteSpace(name))
                    .ToImmutableDictionary(p => (uint)p.Key, p => catalogs.Texts[p.Value.NameTextId]),
                SkillDetails = (catalogs.OptionalSkills ?? new Dictionary<ushort, Lala.Core.Catalogs.SkillDataRow>())
                    .ToImmutableDictionary(p => (uint)p.Key, p => new DesktopSkillDetails(p.Value.Fields["KindSort"],
                        p.Value.Fields["ReduceSP"], p.Value.Fields["TargetKind"], p.Value.RecoveryKind)),
                Scenes = catalogs.SceneNames.ToImmutableDictionary(),
                Npcs = catalogs.ReviewedNpcs?.Where(p => p.Key <= ushort.MaxValue && !string.IsNullOrWhiteSpace(p.Value.Name))
                    .ToImmutableDictionary(p => (ushort)p.Key, p => p.Value.Name!) ?? ImmutableDictionary<ushort, string>.Empty
            };
            session.Publish(presentationGeneration, ++sequence, publication.State, labels);
        }
        if (!openedMain && connection.Phase == AccountConnectionPhase.ReceivingHeld && publication.State.Player is not null)
        {
            openedMain = true; status.Text = "已接收世界登入資料；" + resourceText + "，一般遊戲操作停用。"; openMain();
        }
    }
}
