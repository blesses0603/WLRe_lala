using Avalonia.Controls;
using Lala.Core.Resources;

namespace Lala.Desktop;

/// <summary>Prelogin required-resource preparation and read-only diagnostics. Never sends game commands.</summary>
public sealed class VersionWindow : DesktopWindow
{
    private readonly IDesktopServerCatalog source;
    private readonly Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect;
    private readonly Action openLogin;
    private readonly TextBlock heading = Ui.Text("準備查詢官方版本", 24, bold: true);
    private readonly TextBlock status = Ui.Text("只查詢公開 HTTPS metadata，不需要遊戲帳密。");
    private readonly TextBlock versions = Ui.Text("官方版本：尚未查詢");
    private readonly TextBlock inventory = Ui.Text("本機資源：尚未檢查；不會自動讀取舊帳號設定。");
    private readonly TextBlock location = Ui.Text("由系統管理資源位置", 12, Ui.Muted);
    private readonly ProgressBar progress = new() { IsIndeterminate = false, Height = 6 };
    private readonly Button retry, inspectButton, next, prepare;
    private readonly Func<string> resourceDirectory;
    private readonly Action<string?>? selectResources;
    private string? selectedRoot;
    private PreloginResourcePreparation? prelogin;
    private Task resourceRetirement = Task.CompletedTask;
    private Window? resourceConfirmation;
    internal bool ResourcesMatch(OfficialVersionSnapshot? version) => prelogin?.Matches(version) == true;
    private readonly TextBlock selection = Ui.Text("尚未完成登入前必要資源準備。", 12, Ui.Muted);
    private CancellationTokenSource stop = new();
    private Task? operation;
    private DesktopServerCatalogSnapshot? catalog;
    private bool closed, closing;
    internal Task Pending => operation ?? Task.CompletedTask;

    public VersionWindow(Action openLogin, Action openPreview, Action exit, Action<string?>? selectResources = null)
        : this(openLogin, openPreview, exit, Program.UiSmokeTest ? new OfflineDesktopServerCatalog() : new OfficialDesktopServerCatalog(), ResourceInventoryInspector.InspectAsync, selectResources) { }
    internal VersionWindow(Action openLogin, Action openPreview, Action exit, IDesktopServerCatalog source,
        Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect, Action<string?>? selectResources = null, Func<string>? resourceDirectory = null)
        : base("飄流Re:LaLa · 資源準備與官方線上版本檢測", 1000, 710)
    {
        this.resourceDirectory = resourceDirectory ?? DesktopResourceDirectory.Resolve;
        this.source = source; this.inspect = inspect; this.openLogin = openLogin; this.selectResources = selectResources;
        prepare = Ui.Button("登入前下載、驗證與準備", () => _ = PrepareResourcesAsync(), "VersionPrepare"); prepare.IsEnabled = false;
        heading.Name = "VersionHeading"; status.Name = "VersionStatus"; versions.Name = "VersionMetadata"; inventory.Name = "VersionInventory";
        retry = Ui.Button("重新查詢官方版本", () => _ = RefreshAsync(), "VersionRefresh");
        inspectButton = Ui.Button("重新檢查本機資源", () => _ = RunAsync(token => InspectCoreAsync(this.resourceDirectory(), token)), "VersionInspect");
        next = Ui.Button("進入登入畫面", Continue, "VersionContinue"); next.IsEnabled = false;
        var content = Ui.Column(Ui.Card("檢查結果", Ui.Column(heading)),
            Ui.Card("官方線上版本", versions),
            Ui.Card("本機資源資料庫", Ui.Column(location, inventory, inspectButton, Ui.Row(prepare, Ui.Button("停止資源準備", () => _ = StopAsync(), "VersionClearPreparation")), selection)),
            Ui.Card("LaLa 程式更新（GitHub 正式 Release）", Ui.Text("C# Desktop 發行更新尚未接入；不下載或執行 Python 安裝程式。", 12, Ui.Muted)),
            Ui.Text("官方 TCP 沒有 TLS；XOR 可逆，不提供安全加密。進入登入後，帳密傳送仍逐次確認。", 12, Ui.Muted));
        var body = new Grid { RowDefinitions = new("*,Auto,Auto"), RowSpacing = 10 };
        Ui.At(body, new ScrollViewer { Content = content }, 0);
        Ui.At(body, progress, 0, 1);
        Ui.At(body, Ui.Row(Ui.Button("結束程式", exit), retry, next, Ui.Button("檢視未連線桌面", openPreview, "VersionPreview")), 0, 2);
        SetBody(body);
        Opened += (_, _) => { if (catalog?.IsFresh != true) _ = RefreshAsync(); };
        Closing += (_, args) =>
        {
            if (operation is null && prelogin is null && resourceRetirement.IsCompleted) return;
            args.Cancel = true;
            if (!closing) { closing = true; _ = StopAndCloseAsync(); }
        };
        Closed += (_, _) => { closed = true; stop.Cancel(); };
    }
    private void Continue()
    {
        if (operation is not null || closed || catalog?.IsFresh != true || !catalog.Lines.Any(x => x.Profile is not null) || !ResourcesMatch(catalog.Version))
        { next.IsEnabled = false; status.Text = "清單或同版必要資源未就緒；請重新查詢並準備資源。"; return; }
        openLogin();
    }
    internal Task RefreshAsync() => RunAsync(async token =>
    {
        await RetireResourcesAsync();
        catalog = null;
        await InspectCoreAsync(resourceDirectory(), token);
        versions.Text = "官方版本：查詢中…"; heading.Text = "正在查詢官方版本";
        var value = await source.LoadAsync(token);
        token.ThrowIfCancellationRequested();
        catalog = value;
        RenderVersion(value);
        heading.Text = value.IsFresh && value.Lines.Any(x => x.Profile is not null) ? "官方清單已取得；請完成登入前資源準備" : "沒有可用的已知登入設定";
        status.Text = value.Status;
    });
    private void RenderVersion(DesktopServerCatalogSnapshot value)
    {
        var v = value.Version;
        versions.Text = v is null ? value.Status : $"遊戲版本：{v.ExeVersion}\n資料版本：{v.DataVersion}\n" +
            string.Join("\n", v.Packages.OrderBy(p => p.Key).Select(p => $"{p.Key}：{p.Value}")) + $"\n觀測時間（UTC）：{v.CheckedAtUtc}";
    }
    internal Task InspectAsync(string root) => RunAsync(token => InspectCoreAsync(root, token));
    private async Task InspectCoreAsync(string root, CancellationToken token)
    {
        await RetireResourcesAsync(); selectedRoot = null;
        inventory.Text = "正在唯讀檢查本機資源…";
        var result = await Task.Run(() => inspect(root, token), token);
        token.ThrowIfCancellationRequested();
        selectedRoot = Path.GetFullPath(root); location.Text = "資源由程式自動管理";
        inventory.Text = result.Status switch
        {
            ResourceInventoryInspectionStatus.Missing => "找不到資源資料庫；沒有建立或下載任何檔案。",
            ResourceInventoryInspectionStatus.Invalid => "資料庫內容無效；沒有修復或覆寫。",
            ResourceInventoryInspectionStatus.Unavailable => "資料庫目前無法讀取；沒有重試或覆寫。",
            _ => $"本機資料庫自洽（不代表官方驗證）\n遊戲 {result.ExeVersion}／資料 {result.DataVersion}\n必要資料表 {result.RequiredTables}／{result.RequiredTableBytes} bytes"
        };
    }
    private Task RetireResourcesAsync()
    {
        var previous = prelogin; prelogin = null; selectResources?.Invoke(null);
        if (previous is not null)
        {
            previous.Stop(); resourceRetirement = DrainResourcesAsync(resourceRetirement, previous);
        }
        return resourceRetirement;
    }
    private static async Task DrainResourcesAsync(Task prior, PreloginResourcePreparation previous)
    {
        try { await prior; }
        finally { await previous.DisposeAsync(); }
    }
    internal Task PrepareResourcesAsync() => RunAsync(async token =>
    {
        if (selectedRoot is null) return;
        await RetireResourcesAsync();
        prelogin = PreloginResourcePreparation.Create(selectedRoot);
        var disclosure = prelogin.Disclosure;
        var dialog = new Window { Title = "確認登入前資源準備", Icon = Icon, Width = 720, Height = 620, MinWidth = 520, MinHeight = 420, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        resourceConfirmation = dialog;
        var details = new Expander { Header = "進階細節：驗證方式", IsExpanded = false,
            Name = "PreloginResourceDetails", HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Stretch,
            Content = Ui.Column(
                Ui.Text("小地圖串流階段最多 4 檔／64 MiB；其餘下載額度不變。"),
                Ui.Text("來源、版本、Manifest、格式與像素依各資源驗證，SQLite 獨立回讀；頭像另需角色映射，小地圖另需目前場景綁定。驗證未通過的圖資保持不可用。")) };
        var summary = Ui.Column(
            Ui.Text("準備遊戲資源", 22, bold: true),
            Ui.Text("此步驟不需要帳密，也不會登入遊戲。", 14, Ui.Muted),
            Ui.Text("下載內容", 16, bold: true),
            Ui.Text("必要資料表，以及受支援、通過驗證的物品圖、頭像、表情與小地圖。"),
            Ui.Text("官方來源", 16, bold: true),
            Ui.Text(disclosure.ResourceUrlPrefix),
            Ui.Text("資源由程式自動管理；將建立必要目錄，下載並寫入 Bundle、暫存檔與 SQLite 資料庫（含 journal）。停止不會回復已完成或結果不明的寫入，也不會自動重試。", 13),
            Ui.Text("資源準備不代表全圖資或正式登入驗收完成；一般遊戲操作仍停用。", 13, Ui.Muted),
            details);
        var layout = new Grid { RowDefinitions = new RowDefinitions("*,Auto"), Margin = new Avalonia.Thickness(20) };
        Ui.At(layout, new ScrollViewer { Content = summary }, 0, 0);
        Ui.At(layout, Ui.Row(Ui.Button("取消", () => dialog.Close(false), "PreloginCancel"),
            Ui.Button("確認下載與寫入", () => dialog.Close(true), "PreloginConfirm")), 0, 1);
        dialog.Content = layout;
        bool approved;
        using (token.Register(() => Avalonia.Threading.Dispatcher.UIThread.Post(() => dialog.Close(false))))
        {
            try { approved = await dialog.ShowDialog<bool>(this); token.ThrowIfCancellationRequested(); }
            finally { resourceConfirmation = null; }
        }
        if (!approved) { await RetireResourcesAsync(); selection.Text = "未同意下載；沒有啟動資源準備。"; return; }
        heading.Text = "正在下載、驗證及回讀必要資源";
        var currentPreparation = prelogin;
        void RenderProgress()
        {
            if (closed || !ReferenceEquals(prelogin, currentPreparation)) return;
            var observedProgress = currentPreparation.Progress;
            selection.Text = observedProgress.Phase;
            bool measured = observedProgress.Total is > 0 && observedProgress.Completed is not null;
            progress.IsIndeterminate = !observedProgress.IsFinished && !measured;
            progress.Value = measured ? 100.0 * observedProgress.Completed!.Value / observedProgress.Total!.Value : 0;
            if (measured) selection.Text += $"：{observedProgress.Completed}／{observedProgress.Total} 檔（本階段 {progress.Value:0}%）";
            else if (!observedProgress.IsFinished) selection.Text += "（進行中）";
        }
        var progressTimer = new Avalonia.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
        progressTimer.Tick += (_, _) => RenderProgress();
        PreloginResourceResult result;
        try { progressTimer.Start(); result = await currentPreparation.PrepareAsync(token); RenderProgress(); }
        finally { progressTimer.Stop(); }
        token.ThrowIfCancellationRequested();
        if (result.Status != PreloginResourceStatus.Ready)
        {
            string reason = currentPreparation.Progress.Phase;
            await RetireResourcesAsync(); heading.Text = "資源準備未完成"; selection.Text = reason; return;
        }
        heading.Text = "必要資源已驗證；正在重新核對登入清單";
        progress.IsIndeterminate = true;
        var observed = await source.LoadAsync(token); token.ThrowIfCancellationRequested();
        catalog = observed; RenderVersion(observed); status.Text = observed.Status;
        if (!observed.IsFresh || !ResourcesMatch(observed.Version)) { await RetireResourcesAsync(); heading.Text = "清單與資源版本不同，禁止登入"; return; }
        selectResources?.Invoke(selectedRoot);
        heading.Text = "同版必要資源準備完成";
        selection.Text = "必要資料已完成驗證與回讀。可進入登入畫面；可選圖資仍依個別驗證結果啟用，尚非正式登入驗收。";
        status.Text = observed.Status;
    });
    private Task RunAsync(Func<CancellationToken, Task> action)
    {
        if (closed || operation is not null) return Pending;
        if (stop.IsCancellationRequested) { stop.Dispose(); stop = new(); }
        operation = RunCoreAsync(action); return operation;
    }
    private async Task RunCoreAsync(Func<CancellationToken, Task> action)
    {
        await Task.Yield();
        retry.IsEnabled = inspectButton.IsEnabled = next.IsEnabled = prepare.IsEnabled = false; progress.IsIndeterminate = true;
        try { await action(stop.Token); }
        catch (OperationCanceledException) { await RetireResourcesAsync(); catalog = null; selectedRoot = null; heading.Text = "檢查已取消"; status.Text = "未啟用任何資源或登入。"; }
        catch (Exception) { await RetireResourcesAsync(); catalog = null; selectedRoot = null; heading.Text = "檢查未完成"; status.Text = "來源或本機檢查失敗，請重新查詢；不使用先前結果放行。"; }
        finally
        {
            operation = null; progress.IsIndeterminate = false;
            retry.IsEnabled = inspectButton.IsEnabled = !closed;
            prepare.IsEnabled = !closed && selectedRoot is not null && selectResources is not null;
            next.IsEnabled = !closed && catalog?.IsFresh == true && catalog.Lines.Any(x => x.Profile is not null) && ResourcesMatch(catalog.Version);
        }
    }
    private async Task StopAndCloseAsync()
    {
        try { await StopAsync(); Close(); }
        finally { closing = false; }
    }
    internal async Task StopAsync()
    {
        stop.Cancel(); prelogin?.Stop(); resourceConfirmation?.Close(false);
        if (operation is { } pending) await pending;
        await RetireResourcesAsync();
        catalog = null; selectedRoot = null; next.IsEnabled = prepare.IsEnabled = false;
        selection.Text = "資源準備已撤銷；已完成或結果不明的磁碟寫入不會回復。";
    }
}
