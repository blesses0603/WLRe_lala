using System.Net;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Threading;
using Lala.Core.Sessions;
using Lala.Core.Protocol;

namespace Lala.Desktop;

/// <summary>Single-attempt desktop host. No saved credentials, endpoint defaults or game commands.</summary>
public sealed class LoginWindow : DesktopWindow, IAccountLoginInput, IAccountRoleSelector, IAccountLoginSendConfirmation
{
    private readonly DesktopSession session;
    private readonly TextBox account = new() { Name = "LoginAccount", MaxLength = 255 };
    private readonly TextBox password = new() { Name = "LoginPassword", PasswordChar = '*', MaxLength = 255 };
    private readonly TextBox verification = new() { Name = "LoginVerification", PlaceholderText = "IP:port" };
    private readonly TextBox formal = new() { Name = "LoginFormal", PlaceholderText = "IP:port" };
    private readonly TextBox tx = new() { Name = "LoginTx", PlaceholderText = "0–255" };
    private readonly TextBox rx = new() { Name = "LoginRx", PlaceholderText = "0–255" };
    private readonly TextBox platform = new() { Name = "LoginPlatform", PlaceholderText = "0–255" };
    private readonly TextBox language = new() { Name = "LoginLanguage", PlaceholderText = "0–255" };
    private readonly ComboBox roles = Ui.Combo([], -1, "LoginRoles");
    private readonly TextBlock status = Ui.Text("請輸入已核對的驗證與正式分流目的地及協定參數。", color: Ui.Muted);
    private readonly Button submit, disconnect, enter;
    private readonly Action openMain;
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private AccountLoginPreparation? preparation;
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

    public LoginWindow(DesktopSession session, Action openPreview, Action openInspector)
        : base("飄流Re:LaLa · 登入／選角", 900, 700)
    {
        this.session = session; openMain = openPreview;
        submit = Ui.Button("登入", () => { if (operation is null) { stopping = false; operation = LoginAsync(); } }, "LoginSubmit");
        disconnect = Ui.Button("中斷", async () => await StopAsync(), "LoginDisconnect");
        enter = Ui.Button("確認選角進入", SelectRole, "LoginEnterRole");
        disconnect.IsEnabled = enter.IsEnabled = false;
        roles.SelectionChanged += (_, _) => enter.IsEnabled = !stopping && roleRequest is not null &&
            roles.SelectedIndex >= 0 && !roleRequest.Roles[roles.SelectedIndex].Locked;
        account.TextChanged += (_, _) => ClearSecrets();
        foreach (var field in ProfileFields()) field.TextChanged += (_, _) => ClearSecrets();
        var body = new StackPanel { Spacing = 8 };
        body.Children.Add(Ui.Text("登入與選角", 22, bold: true));
        body.Children.Add(Ui.Text("官方 TCP 沒有 TLS；XOR 可逆，不提供安全加密，網路觀察者可能還原帳密。", color: Ui.Muted));
        body.Children.Add(Ui.Text("每次登入只嘗試一次；兩次帳密傳送須在一分鐘內分別確認。登入包含協定 ACK／心跳；一般遊戲操作停用。", color: Ui.Muted));
        var fields = new Grid { ColumnDefinitions = new("Auto,*,Auto,*"), RowDefinitions = new("Auto,Auto,Auto,Auto"), ColumnSpacing = 8, RowSpacing = 6 };
        AddField("驗證目的地", verification, 0, 0); AddField("正式分流目的地", formal, 2, 0);
        AddField("傳送 XOR（十進位）", tx, 0, 1); AddField("接收 XOR（十進位）", rx, 2, 1);
        AddField("平台（十進位）", platform, 0, 2); AddField("語言（十進位）", language, 2, 2);
        AddField("帳號", account, 0, 3); AddField("密碼", password, 2, 3);
        void AddField(string label, Control control, int column, int row) { Ui.At(fields, Ui.Text(label), column, row); Ui.At(fields, control, column + 1, row); }
        body.Children.Add(Ui.Card("手動核對連線設定（不儲存）", fields));
        body.Children.Add(Ui.Text("帳密僅在記憶體短暫使用，不記錄或儲存。清除文字框無法保證 .NET 字串立即從記憶體抹除。", 12, Ui.Muted));
        body.Children.Add(Ui.Row(submit, disconnect));
        body.Children.Add(Ui.Card("伺服器回傳角色（不預選）", Ui.Row(roles, enter)));
        body.Children.Add(status);
        preview = Ui.Button("檢視桌面介面", () => { ClearSecrets(); openPreview(); }, "LoginPreview");
        inspector = Ui.Button("封包檢查", () => { ClearSecrets(); openInspector(); }, "LoginInspector");
        body.Children.Add(Ui.Row(preview, inspector));
        SetBody(new ScrollViewer { Content = body });
        timer.Tick += (_, _) => Publish();
        Closing += (_, args) =>
        {
            ClearSecrets();
            if (operation is not null) { args.Cancel = true; _ = StopAndCloseAsync(); }
        };
        Closed += (_, _) => { closed = true; timer.Stop(); ClearSecrets(); account.Text = ""; };
    }

    private TextBox[] ProfileFields() => [verification, formal, tx, rx, platform, language];
    public void ClearSecrets() => password.Text = "";
    private async Task StopAndCloseAsync()
    {
        if (closePending) return; closePending = true;
        try { await StopAsync(); if (!closed) Close(); }
        finally { closePending = false; }
    }
    public async Task StopAsync()
    {
        stopping = true; enter.IsEnabled = false;
        cancellation?.Cancel(); preparation?.Stop(); roleCompletion?.TrySetResult(null);
        confirmationWindow?.Close(false);
        if (operation is { } running) await running;
    }

    private async Task LoginAsync()
    {
        // Yield ensures the task is assigned before synchronous validation can finish.
        await Task.Yield();
        AccountSession? core = null;
        try
        {
            if (stopping) return;
            var profile = new AccountConnectionProfile(IPEndPoint.Parse(verification.Text ?? ""), IPEndPoint.Parse(formal.Text ?? ""),
                byte.Parse(tx.Text ?? ""), byte.Parse(rx.Text ?? ""), 1, byte.Parse(platform.Text ?? ""), byte.Parse(language.Text ?? ""));
            // RoleIndex is ignored because this host always supplies the interactive selector.
            openedMain = false; sequence = 0; lastPublication = null;
            foreach (var field in ProfileFields()) field.IsEnabled = false;
            preview.IsEnabled = inspector.IsEnabled = false;
            account.IsEnabled = password.IsEnabled = submit.IsEnabled = false; disconnect.IsEnabled = true;
            cancellation = new(); core = new();
            var identity = Guid.NewGuid();
            var snapshot = core.Begin(identity.ToString("N"), profile.FormalEndpoint.ToString());
            session.Reset(identity.ToString("N")); presentationGeneration = session.Generation;
            preparation = new(core, snapshot.Generation, identity, profile, this,
                new() { LoginTimeout = TimeSpan.FromMinutes(2) }, roleSelector: this, sendConfirmation: this);
            timer.Start();
            var result = await preparation.RunAsync(cancellation.Token);
            status.Text = $"連線結束：{result.Status.EndReason}；資源釋放：{result.ResourcesReleased}。重新登入需重新輸入及確認。";
        }
        catch (Exception) { status.Text = "登入未完成：請檢查 IP:port、0–255 協定參數與 ASCII 帳密，或重新確認。"; }
        finally
        {
            timer.Stop();
            try { if (preparation is not null) await preparation.DisposeAsync(); }
            catch (Exception) { status.Text = "連線清理失敗；請關閉程式後再試。"; closed = true; }
            core?.Disconnect(); preparation = null;
            cancellation?.Dispose(); cancellation = null;
            roleCompletion?.TrySetResult(null); roleCompletion = null; roleRequest = null;
            roles.ItemsSource = Array.Empty<string>(); roles.SelectedIndex = -1; enter.IsEnabled = false;
            session.Reset(); ClearSecrets(); account.Text = "";
            foreach (var field in ProfileFields()) field.IsEnabled = !closed;
            account.IsEnabled = password.IsEnabled = submit.IsEnabled = !closed;
            preview.IsEnabled = inspector.IsEnabled = true;
            disconnect.IsEnabled = false; operation = null;
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
        var dialog = new Window { Title = "確認本次帳密傳送", Width = 620, Height = 260, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        confirmationWindow = dialog;
        var panel = new StackPanel { Margin = new(20), Spacing = 12 };
        panel.Children.Add(Ui.Text($"即將將帳號與密碼傳送至{(recipient == AccountLoginRecipient.Verification ? "驗證" : "正式")}端點：{endpoint}"));
        panel.Children.Add(Ui.Text("沒有 TLS；XOR 可逆，不提供安全加密。網路觀察者可能還原帳密。"));
        panel.Children.Add(Ui.Text("只同意這一次傳送；取消或關閉將中止本次登入。"));
        panel.Children.Add(Ui.Row(Ui.Button("取消", () => dialog.Close(false), "LoginSendCancel"), Ui.Button("知悉風險，確認傳送", () => dialog.Close(true), "LoginSendConfirm")));
        dialog.Content = panel;
        using var registration = token.Register(() => Dispatcher.UIThread.Post(() => dialog.Close(false)));
        try { var approved = await dialog.ShowDialog<bool>(this); token.ThrowIfCancellationRequested(); return approved; }
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
    private void Publish()
    {
        if (stopping || preparation is null) return;
        if (session.Generation != presentationGeneration) { cancellation?.Cancel(); preparation.Stop(); return; }
        var publication = preparation.Publication;
        session.SetConnectionText(preparation.Snapshot.Phase == AccountConnectionPhase.ReceivingHeld
            ? "登入協定完成｜資源 Held，遊戲操作停用" : "登入進行中｜等待確認或伺服器回覆");
        if (publication is null) return;
        if (!ReferenceEquals(publication, lastPublication))
        {
            lastPublication = publication;
            session.Publish(presentationGeneration, ++sequence, publication.State);
        }
        if (!openedMain && preparation.Snapshot.Phase == AccountConnectionPhase.ReceivingHeld &&
            publication.State.Player is not null)
        {
            openedMain = true; status.Text = "已接收世界登入資料；資源仍 Held，一般遊戲操作停用。"; openMain();
        }
    }
}
