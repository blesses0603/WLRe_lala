using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Core.Resources;

namespace Lala.Desktop;

/// <summary>Prelogin required-resource preparation and read-only diagnostics. Never sends game commands.</summary>
public sealed class VersionWindow : DesktopWindow
{
    private readonly IDesktopServerCatalog source;
    private readonly Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect;
    private readonly Action openLogin;
    private readonly TextBlock heading = Ui.Text("準備查詢官方版本", 22, bold: true);
    private readonly TextBlock dataPackageVersion = Ui.Text("—", 14, Ui.Accent, true);
    private readonly TextBlock mainPackageVersion = Ui.Text("—", 14, Ui.Accent, true);
    private readonly TextBlock gameVersion = Ui.Text("—", 26, bold: true);
    private readonly TextBlock dataVersion = Ui.Text("—", 26, Ui.Accent, true);
    private readonly TextBlock databaseVersion = Ui.Text("—", 26, bold: true);
    private readonly TextBlock databaseDataVersion = Ui.Text("—", 26, Ui.Accent, true);
    private readonly TextBlock observedTime = Ui.Text("尚未取得觀測時間", 12, Ui.Muted);
    private readonly TextBlock inventory = Ui.Text("本機資源：尚未檢查；不會自動讀取舊帳號設定。");
    private readonly ProgressBar progress = new()
    {
        Name = "VersionProgress", IsIndeterminate = false, Minimum = 0, Maximum = 100,
        Height = 22, Foreground = Brush.Parse("#277e94"), Background = Brush.Parse("#324c60"), CornerRadius = new CornerRadius(6)
    };
    private readonly TextBlock progressLabel = Ui.Text("階段進度 0%", 11, Ui.Ink, true);
    private readonly Button retry, next, prepare;
    private readonly Func<string, PreloginResourcePreparation> createPreparation;
    private readonly Func<string> resourceDirectory;
    private readonly Action<string?>? selectResources;
    private string? selectedRoot;
    private PreloginResourcePreparation? prelogin;
    private Task resourceRetirement = Task.CompletedTask;
    internal bool ResourcesMatch(OfficialVersionSnapshot? version) => prelogin?.Matches(version) == true;
    internal PreloginResourcePreparation? PreparedResources => prelogin?.HasCurrentResources == true ? prelogin : null;
    internal PortraitRenderRequest? GetRolePortrait(Lala.Core.Sessions.AccountRoleSelectionRequest request, byte index)
        => prelogin?.TryGetRolePortrait(request, index, out var portrait) == true ? portrait : null;
    private readonly TextBlock selection = Ui.Text("等待官方版本，自動驗證、下載將隨後開始。", 12, Ui.Muted);
    private CancellationTokenSource stop = new();
    private Task? operation;
    private DesktopServerCatalogSnapshot? catalog;
    private bool closed, closing;
    internal Task Pending => operation ?? Task.CompletedTask;

    public VersionWindow(Action openLogin, Action openPreview, Action exit, Action<string?>? selectResources = null)
        : this(openLogin, openPreview, exit, Program.UiSmokeTest ? new OfflineDesktopServerCatalog() : new OfficialDesktopServerCatalog(), ResourceInventoryInspector.InspectAsync, selectResources) { }
    internal VersionWindow(Action openLogin, Action openPreview, Action exit, IDesktopServerCatalog source,
        Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect, Action<string?>? selectResources = null, Func<string>? resourceDirectory = null,
        Func<string, PreloginResourcePreparation>? createPreparation = null)
        : base("飄流Re:LaLa · 資源準備與官方線上版本檢測", 1000, 710)
    {
        this.resourceDirectory = resourceDirectory ?? DesktopResourceDirectory.Resolve;
        this.source = source; this.inspect = inspect; this.openLogin = openLogin; this.selectResources = selectResources;
        this.createPreparation = createPreparation ?? PreloginResourcePreparation.Create;
        prepare = ActionButton("重新驗證、下載", () => _ = RefreshAsync(), "VersionPrepare", primary: true); prepare.IsEnabled = false;
        heading.Name = "VersionHeading"; inventory.Name = "VersionInventory";
        dataPackageVersion.Name = "VersionDataPackageValue"; mainPackageVersion.Name = "VersionMainPackageValue";
        gameVersion.Name = "VersionGameValue"; dataVersion.Name = "VersionDataValue"; observedTime.Name = "VersionObservedTime";
        databaseVersion.Name = "DatabaseVersionValue"; databaseDataVersion.Name = "DatabaseDataValue";
        retry = ActionButton("重新查詢版本", () => _ = RefreshAsync(), "VersionRefresh");
        next = ActionButton("進入登入畫面 →", Continue, "VersionContinue", primary: true); next.IsEnabled = false;

        // Fit the startup overview and actions on one page without scrolling.
        var summary = Ui.Column(Ui.Text("啟動準備 / 檢查狀態", 12, Ui.Accent, true), heading);
        summary.Spacing = 10;
        var overview = Surface(summary, accent: true);
        overview.Name = "VersionOverview";

        var resourceActions = new Grid { ColumnDefinitions = new("*,Auto"), ColumnSpacing = 8 };
        Ui.At(resourceActions, prepare, 0);
        Ui.At(resourceActions, ActionButton("停止", () => _ = StopAsync(), "VersionClearPreparation"), 1);
        var databaseValues = new Grid { ColumnDefinitions = new("*,*"), ColumnSpacing = 10 };
        Ui.At(databaseValues, VersionTile("資料庫版本", databaseVersion), 0);
        Ui.At(databaseValues, VersionTile("資料", databaseDataVersion), 1);
        var progressDisplay = new Grid();
        progressLabel.Name = "VersionProgressLabel";
        progressLabel.HorizontalAlignment = HorizontalAlignment.Center;
        progressLabel.IsHitTestVisible = false;
        progressDisplay.Children.Add(progress); progressDisplay.Children.Add(progressLabel);
        ToolTip.SetTip(progressDisplay, "依實際處理階段前進；階段耗時不同，並非下載容量或剩餘時間比例。");
        var resourceActivity = Ui.Column(progressDisplay, selection, resourceActions);
        resourceActivity.Spacing = 10;
        resourceActivity.Name = "DatabaseActivity";
        var local = new Grid { RowDefinitions = new("Auto,Auto,Auto,*,Auto"), RowSpacing = 10 };
        Ui.At(local, Ui.Text("自動驗證、下載", 18, Ui.Accent, true), 0);
        Ui.At(local, databaseValues, 0, 1);
        Ui.At(local, inventory, 0, 2);
        Ui.At(local, resourceActivity, 0, 4);
        var panels = new Grid { ColumnDefinitions = new("*,*"), ColumnSpacing = 16 };
        panels.Name = "VersionPanels";
        var versionValues = new Grid { ColumnDefinitions = new("*,*"), ColumnSpacing = 10 };
        Ui.At(versionValues, VersionTile("遊戲版本", gameVersion), 0);
        Ui.At(versionValues, VersionTile("資料版本", dataVersion), 1);
        var packages = Ui.Column(VersionTile("資料套件 · DataPackage", dataPackageVersion, compact: true),
            VersionTile("主程式套件 · MainPackage", mainPackageVersion, compact: true));
        packages.Name = "VersionMetadata";
        var metadata = new Grid { RowDefinitions = new("Auto,Auto,*"), RowSpacing = 10 };
        observedTime.HorizontalAlignment = HorizontalAlignment.Right;
        observedTime.VerticalAlignment = VerticalAlignment.Bottom;
        observedTime.TextAlignment = TextAlignment.Right;
        Ui.At(metadata, versionValues, 0);
        Ui.At(metadata, packages, 0, 1);
        Ui.At(metadata, observedTime, 0, 2);
        Ui.At(panels, Section("官方線上版本", null, metadata), 0);
        Ui.At(panels, Section("LALA資料庫", null, local), 1);

        var update = Ui.Column(Ui.Text("LaLa 程式更新 · GitHub Release", 13, Ui.Muted),
            Ui.Text("C# Desktop 發行更新尚未接入；不下載或執行 Python 安裝程式。", 12, Ui.Muted));
        update.Name = "VersionUpdateDetails";
        var content = new Grid { RowDefinitions = new("Auto,*,Auto"), RowSpacing = 12 };
        Ui.At(content, overview, 0);
        Ui.At(content, panels, 0, 1);
        Ui.At(content, Surface(update), 0, 2);
        var actions = new Grid { ColumnDefinitions = new("Auto,*,Auto,Auto"), ColumnSpacing = 10 };
        Ui.At(actions, ActionButton("結束程式", exit), 0);
        Ui.At(actions, retry, 2);
        Ui.At(actions, next, 3);
        var body = new Grid { RowDefinitions = new("*,Auto"), RowSpacing = 12 };
        Ui.At(body, content, 0);
        Ui.At(body, actions, 0, 1);
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

    private static Border VersionTile(string label, TextBlock value, bool compact = false) => new()
    {
        Background = Brush.Parse("#c0254256"), BorderBrush = Brush.Parse("#3b6075"), BorderThickness = new Thickness(1),
        CornerRadius = new CornerRadius(8), Padding = new Thickness(12, compact ? 5 : 8),
        Child = Ui.Column(Ui.Text(label, 12, Ui.Muted), value)
    };

    private static Button ActionButton(string text, Action action, string? name = null, bool primary = false)
    {
        var button = new Button
        {
            Content = text, Name = name, MinHeight = 38, Padding = new Thickness(14, 8),
            CornerRadius = new CornerRadius(7), HorizontalContentAlignment = HorizontalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Background = Brush.Parse(primary ? "#277e94" : "#20394d"),
            BorderBrush = Brush.Parse(primary ? "#74d5e6" : "#456174"),
            BorderThickness = new Thickness(1), Foreground = Ui.Ink
        };
        Avalonia.Automation.AutomationProperties.SetName(button, text);
        button.Click += (_, _) => action();
        return button;
    }

    private static Border Surface(Control content, bool accent = false) => new()
    {
        Background = Brush.Parse(accent ? "#f01a3246" : "#f0102335"),
        BorderBrush = Brush.Parse(accent ? "#4b9db2" : "#344e63"),
        BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12),
        Padding = new Thickness(18, 16), Child = content
    };

    private static Border Section(string title, string? subtitle, Control content)
    {
        var header = Ui.Text(title, 17, bold: true);
        var column = Ui.Column(header);
        if (!string.IsNullOrEmpty(subtitle)) column.Children.Add(Ui.Text(subtitle, 12, Ui.Muted));
        column.Spacing = 12;
        var layout = new Grid { RowDefinitions = new("Auto,*"), RowSpacing = 12 };
        Ui.At(layout, column, 0);
        Ui.At(layout, content, 0, 1);
        return Surface(layout);
    }
    private void Continue()
    {
        if (operation is not null || closed || catalog?.IsFresh != true || !catalog.Lines.Any(x => x.Profile is not null) || !ResourcesMatch(catalog.Version))
        { next.IsEnabled = false; selection.Text = "清單或同版必要資源未就緒；請重新查詢並準備資源。"; return; }
        openLogin();
    }
    internal Task RefreshAsync() => RunAsync(async token =>
    {
        await RetireResourcesAsync();
        catalog = null;
        gameVersion.Text = dataVersion.Text = "—";
        dataPackageVersion.Text = mainPackageVersion.Text = "—";
        observedTime.Text = "正在查詢觀測時間…";
        selection.Text = "正在檢查 LALA資料庫…";
        await InspectCoreAsync(resourceDirectory(), token);
        heading.Text = "正在查詢官方版本";
        var value = await source.LoadAsync(token);
        token.ThrowIfCancellationRequested();
        catalog = value;
        RenderVersion(value);
        heading.Text = "官方清單已取得";
        if (value.IsFresh && value.Version is not null && value.Lines.Any(x => x.Profile is not null) && selectedRoot is not null && selectResources is not null)
            await PrepareResourcesCoreAsync(token);
        else
        {
            heading.Text = "官方版本或登入設定尚未就緒";
            selection.Text = "尚未啟動自動下載，請重新查詢官方版本。";
        }
    });
    private void RenderVersion(DesktopServerCatalogSnapshot value)
    {
        var v = value.Version;
        var observedAt = v is not null && DateTimeOffset.TryParse(v.CheckedAtUtc,
            System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.AssumeUniversal, out var timestamp)
            ? timestamp.ToOffset(TimeSpan.FromHours(8)).ToString("yyyy-MM-dd HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture)
            : "時間資料無效";
        gameVersion.Text = v?.ExeVersion ?? "—";
        dataVersion.Text = v?.DataVersion ?? "—";
        dataPackageVersion.Text = v?.Packages.GetValueOrDefault("DataPackage") ?? "—";
        mainPackageVersion.Text = v?.Packages.GetValueOrDefault("MainPackage") ?? "—";
        observedTime.Text = $"觀測時間 · {observedAt}";
    }
    internal Task InspectAsync(string root) => RunAsync(token => InspectCoreAsync(root, token));
    private async Task InspectCoreAsync(string root, CancellationToken token)
    {
        await RetireResourcesAsync(); selectedRoot = null;
        databaseVersion.Text = databaseDataVersion.Text = "—";
        inventory.IsVisible = true;
        inventory.Text = "正在唯讀檢查本機資源…";
        var result = await Task.Run(() => inspect(root, token), token);
        token.ThrowIfCancellationRequested();
        selectedRoot = Path.GetFullPath(root);
        inventory.Text = result.Status switch
        {
            ResourceInventoryInspectionStatus.Missing => "找不到資源資料庫；沒有建立或下載任何檔案。",
            ResourceInventoryInspectionStatus.Invalid => "資料庫內容無效；沒有修復或覆寫。",
            ResourceInventoryInspectionStatus.Unavailable => "資料庫目前無法讀取；沒有重試或覆寫。",
            _ => ""
        };
        inventory.IsVisible = !string.IsNullOrEmpty(inventory.Text);
        if (result.Status == ResourceInventoryInspectionStatus.SelfConsistent)
        {
            databaseVersion.Text = result.ExeVersion;
            databaseDataVersion.Text = result.DataVersion;
        }
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
    private async Task PrepareResourcesCoreAsync(CancellationToken token)
    {
        if (selectedRoot is null) return;
        token.ThrowIfCancellationRequested();
        await RetireResourcesAsync();
        token.ThrowIfCancellationRequested();
        prelogin = createPreparation(selectedRoot);
        heading.Text = "LALA資料庫正在自動驗證、下載";
        var currentPreparation = prelogin;
        var stageProgress = new ResourceStageProgress();
        void RenderProgress()
        {
            if (closed || !ReferenceEquals(prelogin, currentPreparation)) return;
            var observedProgress = currentPreparation.Progress;
            selection.Text = observedProgress.Phase;
            bool measured = observedProgress.Total is > 0 && observedProgress.Completed is not null;
            stageProgress.Observe(observedProgress);
            progress.Value = stageProgress.Value;
            progressLabel.Text = $"階段進度 {progress.Value:0}%";
            if (measured) selection.Text += $" · {observedProgress.Completed}／{observedProgress.Total} 檔";
        }
        var progressTimer = new Avalonia.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
        progressTimer.Tick += (_, _) => RenderProgress();
        PreloginResourceResult result;
        try { RenderProgress(); progressTimer.Start(); result = await currentPreparation.PrepareAsync(token); RenderProgress(); }
        finally { progressTimer.Stop(); }
        token.ThrowIfCancellationRequested();
        if (result.Status != PreloginResourceStatus.Ready)
        {
            string reason = currentPreparation.Progress.Phase;
            await RetireResourcesAsync(); heading.Text = "LALA資料庫尚未就緒"; selection.Text = reason;
            progressLabel.Text = $"未完成 · 階段進度 {progress.Value:0}%"; return;
        }
        heading.Text = "必要資源已驗證；正在重新核對登入清單";
        stageProgress.Observe(new ResourcePreparationProgress("重新核對登入清單"));
        progress.Value = stageProgress.Value;
        progressLabel.Text = $"階段進度 {progress.Value:0}%";
        selection.Text = "重新核對登入清單";
        var observed = await source.LoadAsync(token); token.ThrowIfCancellationRequested();
        catalog = observed; RenderVersion(observed);
        if (!observed.IsFresh || !observed.Lines.Any(x => x.Profile is not null) || !ResourcesMatch(observed.Version))
        { await RetireResourcesAsync(); heading.Text = "清單與資源版本不同，禁止登入"; progressLabel.Text = "版本核對未通過"; return; }
        selectResources?.Invoke(selectedRoot);
        stageProgress.Complete(); progress.Value = stageProgress.Value;
        progressLabel.Text = "驗證完成 100%";
        heading.Text = "LALA資料庫已就緒，可以登入";
        inventory.Text = "資料庫已完成驗證與回讀";
        inventory.IsVisible = true;
        databaseVersion.Text = observed.Version!.ExeVersion;
        databaseDataVersion.Text = observed.Version.DataVersion;
        selection.Text = "必要資料已完成驗證與回讀。可進入登入畫面；可選圖資仍依個別驗證結果啟用，尚非正式登入驗收。";
    }
    private Task RunAsync(Func<CancellationToken, Task> action)
    {
        if (closed || operation is not null) return Pending;
        if (stop.IsCancellationRequested) { stop.Dispose(); stop = new(); }
        operation = RunCoreAsync(action); return operation;
    }
    private async Task RunCoreAsync(Func<CancellationToken, Task> action)
    {
        await Task.Yield();
        retry.IsEnabled = next.IsEnabled = prepare.IsEnabled = false; progress.Value = 0; progressLabel.Text = "階段進度 0%";
        try { await action(stop.Token); }
        catch (OperationCanceledException) { await RetireResourcesAsync(); catalog = null; selectedRoot = null; heading.Text = "檢查已取消"; selection.Text = "自動處理已停止。"; progressLabel.Text = $"已停止 · 階段進度 {progress.Value:0}%"; }
        catch (Exception) { await RetireResourcesAsync(); catalog = null; selectedRoot = null; heading.Text = "檢查未完成"; selection.Text = "自動處理未完成，請重新驗證、下載。"; progressLabel.Text = $"未完成 · 階段進度 {progress.Value:0}%"; }
        finally
        {
            operation = null; progress.IsIndeterminate = false;
            retry.IsEnabled = !closed;
            prepare.IsEnabled = !closed && selectResources is not null;
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
        stop.Cancel(); prelogin?.Stop();
        if (operation is { } pending) await pending;
        await RetireResourcesAsync();
        catalog = null; selectedRoot = null; next.IsEnabled = prepare.IsEnabled = false;
        progressLabel.Text = "已停止";
        selection.Text = "資源準備已撤銷；已完成或結果不明的磁碟寫入不會回復。";
    }
}
