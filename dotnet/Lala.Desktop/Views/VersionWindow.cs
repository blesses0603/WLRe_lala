using Avalonia.Controls;
using Avalonia.Platform.Storage;
using Lala.Core.Resources;

namespace Lala.Desktop;

/// <summary>Explicit metadata and read-only inventory entry point. Never admits resources or sends game commands.</summary>
public sealed class VersionWindow : DesktopWindow
{
    private readonly IDesktopServerCatalog source;
    private readonly Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect;
    private readonly Action openLogin;
    private readonly TextBlock heading = Ui.Text("準備查詢官方版本", 24, bold: true);
    private readonly TextBlock status = Ui.Text("只查詢公開 HTTPS metadata，不需要遊戲帳密。");
    private readonly TextBlock versions = Ui.Text("官方版本：尚未查詢");
    private readonly TextBlock inventory = Ui.Text("本機資源：尚未檢查；不會自動讀取舊帳號設定。");
    private readonly TextBlock location = Ui.Text("尚未選擇資料根目錄", 12, Ui.Muted);
    private readonly ProgressBar progress = new() { IsIndeterminate = false, Height = 6 };
    private readonly Button retry, choose, next;
    private CancellationTokenSource stop = new();
    private Task? operation;
    private DesktopServerCatalogSnapshot? catalog;
    private bool closed, closing;
    internal Task Pending => operation ?? Task.CompletedTask;

    public VersionWindow(Action openLogin, Action openPreview, Action exit)
        : this(openLogin, openPreview, exit, Program.UiSmokeTest ? new OfflineDesktopServerCatalog() : new OfficialDesktopServerCatalog(), ResourceInventoryInspector.InspectAsync) { }
    internal VersionWindow(Action openLogin, Action openPreview, Action exit, IDesktopServerCatalog source,
        Func<string, CancellationToken, Task<ResourceInventoryInspection>> inspect)
        : base("飄流Re:LaLa · 資源準備與官方線上版本檢測", 1000, 710)
    {
        this.source = source; this.inspect = inspect; this.openLogin = openLogin;
        heading.Name = "VersionHeading"; status.Name = "VersionStatus"; versions.Name = "VersionMetadata"; inventory.Name = "VersionInventory";
        retry = Ui.Button("重新查詢官方版本", () => _ = RefreshAsync(), "VersionRefresh");
        choose = Ui.Button("選擇資料根目錄並檢查", () => _ = RunAsync(async token =>
        {
            if (!StorageProvider.CanPickFolder) { inventory.Text = "此環境無法選擇資料夾。"; return; }
            var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { Title = "選擇 LaLa 資料根目錄（唯讀檢查）", AllowMultiple = false });
            try
            {
                token.ThrowIfCancellationRequested();
                if (folders.Count == 0) return;
                var path = folders[0].TryGetLocalPath();
                if (path is null) { inventory.Text = "只支援本機資料根目錄。"; return; }
                await InspectCoreAsync(path, token);
            }
            finally { foreach (var folder in folders) folder.Dispose(); }
        }), "VersionInspect");
        next = Ui.Button("進入登入畫面", Continue, "VersionContinue"); next.IsEnabled = false;
        var content = Ui.Column(Ui.Card("檢查結果", Ui.Column(heading, status)),
            Ui.Card("官方線上版本", versions),
            Ui.Card("本機資源資料庫", Ui.Column(location, inventory, choose,
                Ui.Text("只讀取所選目錄下 official_sync/derived_catalogs/resource_inventory.sqlite3；不修復、不下載、不讀帳密。", 12, Ui.Muted))),
            Ui.Card("資源啟用狀態", Ui.Column(Ui.Text("尚未接入完整下載、同版來源核對與資源啟用。", color: Ui.Gold),
                Ui.Text("資料庫自洽不代表官方來源可信，也不能解除 Held。版本資料只供選擇分流，不授權遊戲指令。", 12, Ui.Muted))),
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
            if (operation is null) return;
            args.Cancel = true;
            if (!closing) { closing = true; _ = StopAndCloseAsync(); }
        };
        Closed += (_, _) => { closed = true; stop.Cancel(); };
    }
    private void Continue()
    {
        if (operation is not null || closed || catalog?.IsFresh != true || !catalog.Lines.Any(x => x.Profile is not null))
        { next.IsEnabled = false; status.Text = "清單未就緒或已過期，請重新查詢。"; return; }
        openLogin();
    }
    internal Task RefreshAsync() => RunAsync(async token =>
    {
        catalog = null; versions.Text = "官方版本：查詢中…"; heading.Text = "正在查詢官方版本";
        var value = await source.LoadAsync(token);
        token.ThrowIfCancellationRequested();
        catalog = value;
        var v = value.Version;
        versions.Text = v is null ? value.Status : $"遊戲版本：{v.ExeVersion}\n資料版本：{v.DataVersion}\n" +
            string.Join("\n", v.Packages.OrderBy(p => p.Key).Select(p => $"{p.Key}：{p.Value}")) + $"\n觀測時間（UTC）：{v.CheckedAtUtc}";
        heading.Text = value.IsFresh && value.Lines.Any(x => x.Profile is not null) ? "官方清單已取得；資源尚未啟用" : "沒有可用的已知登入設定";
        status.Text = value.Status;
    });
    internal Task InspectAsync(string root) => RunAsync(token => InspectCoreAsync(root, token));
    private async Task InspectCoreAsync(string root, CancellationToken token)
    {
        inventory.Text = "正在唯讀檢查本機資源…";
        var result = await Task.Run(() => inspect(root, token), token);
        token.ThrowIfCancellationRequested();
        location.Text = root;
        inventory.Text = result.Status switch
        {
            ResourceInventoryInspectionStatus.Missing => "找不到資源資料庫；沒有建立或下載任何檔案。",
            ResourceInventoryInspectionStatus.Invalid => "資料庫內容無效；沒有修復或覆寫。",
            ResourceInventoryInspectionStatus.Unavailable => "資料庫目前無法讀取；沒有重試或覆寫。",
            _ => $"本機資料庫自洽（不代表官方驗證）\n遊戲 {result.ExeVersion}／資料 {result.DataVersion}\n必要資料表 {result.RequiredTables}／{result.RequiredTableBytes} bytes"
        };
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
        retry.IsEnabled = choose.IsEnabled = next.IsEnabled = false; progress.IsIndeterminate = true;
        try { await action(stop.Token); }
        catch (OperationCanceledException) { catalog = null; heading.Text = "檢查已取消"; status.Text = "未啟用任何資源或登入。"; }
        catch (Exception) { catalog = null; heading.Text = "檢查未完成"; status.Text = "來源或本機檢查失敗，請重新查詢；不使用先前結果放行。"; }
        finally
        {
            operation = null; progress.IsIndeterminate = false;
            retry.IsEnabled = choose.IsEnabled = !closed;
            next.IsEnabled = !closed && catalog?.IsFresh == true && catalog.Lines.Any(x => x.Profile is not null);
        }
    }
    private async Task StopAndCloseAsync()
    {
        try { await StopAsync(); Close(); }
        finally { closing = false; }
    }
    internal async Task StopAsync()
    {
        stop.Cancel();
        if (operation is { } pending) await pending;
        catalog = null; next.IsEnabled = false;
    }
}
