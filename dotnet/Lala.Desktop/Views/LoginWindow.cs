using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;

namespace Lala.Desktop;

/// <summary>
/// Desktop-only reproduction of the existing login/role window. Credentials are an
/// unsaved local edit; no login, resource approval, or remembered identity is simulated.
/// </summary>
public sealed class LoginWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly TextBox account = new() { Name = "LoginAccount", MaxLength = 128 };
    private readonly TextBox password = new() { Name = "LoginPassword", PasswordChar = '*', MaxLength = 256 };
    private readonly ComboBox servers = Ui.Combo(["等待官方伺服器清單"], name: "LoginServer");
    private readonly ComboBox lines = Ui.Combo(["等待分流資料"], name: "LoginLine");
    private readonly ComboBox roles = Ui.Combo([], -1, "LoginRoles");
    private readonly TextBlock status = Ui.Text(DesktopSession.ConnectionUnavailable, color: Ui.Muted);
    private readonly TextBlock roleStatus = Ui.Text("選角後等待世界資料同步完成，將自動開啟主頁。", color: Ui.Muted);
    private long generation;
    private bool closed;

    public LoginWindow(DesktopSession session, Action openPreview, Action openInspector)
        : base("飄流Re:LaLa  =By赤寧= · 登入／選角", 900, 620)
    {
        ArgumentNullException.ThrowIfNull(session);
        ArgumentNullException.ThrowIfNull(openPreview);
        ArgumentNullException.ThrowIfNull(openInspector);
        this.session = session;
        generation = session.ReadView().Generation;
        account.TextChanged += (_, _) => ClearSecrets();

        var body = new StackPanel { Spacing = 7 };
        body.Children.Add(Ui.Text("登入與選角", 22, bold: true));
        body.Children.Add(Ui.Text("選擇帳號與分流，登入後再選取角色。", color: Ui.Muted));

        var toolbar = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,Auto,*,Auto,Auto"), ColumnSpacing = 6 };
        Ui.At(toolbar, Ui.Unavailable("載入設定", "LoginLoadProfile", "連線設定匯入尚未接入。"), 0);
        Ui.At(toolbar, Ui.Unavailable("儲存設定", "LoginSaveProfile", "連線設定匯出尚未接入；帳密不會寫入檔案。"), 1);
        Ui.At(toolbar, Ui.Text("帳號清單"), 2);
        var saved = Ui.Combo(["尚無已記住的帳號"], name: "LoginSavedAccounts");
        saved.IsEnabled = false;
        ToolTip.SetTip(saved, "帳號與密碼安全儲存尚未接入。");
        Ui.At(toolbar, saved, 3);
        Ui.At(toolbar, Ui.Unavailable("版本檢測", "LoginVersionCheck", "正式資源檢測流程尚未接入桌面宿主。"), 4);
        Ui.At(toolbar, Ui.Button("新增", NewDraft, "LoginNewDraft"), 5);
        body.Children.Add(toolbar);
        body.Children.Add(Ui.Text("版本檢測尚未接入；目前尚無可登入的正式連線。", color: Ui.Muted));
        body.Children.Add(Ui.Text("伺服器與分流清單待同步；不使用預設或推測的連線目的地。", color: Ui.Muted));

        var login = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,*,*,*"),
            RowDefinitions = new RowDefinitions("Auto,Auto,Auto,Auto,Auto"),
            ColumnSpacing = 6, RowSpacing = 5
        };
        Ui.At(login, Ui.Text("伺服器"), 0);
        servers.IsEnabled = false;
        lines.IsEnabled = false;
        servers.SelectionChanged += (_, _) => ClearSecrets();
        lines.SelectionChanged += (_, _) => ClearSecrets();
        Ui.At(login, servers, 1);
        Ui.At(login, Ui.Text("分流選擇"), 2);
        Ui.At(login, lines, 3);
        Ui.At(login, Ui.Text("帳號"), 0, 1, 2);
        Ui.At(login, Ui.Text("密碼"), 2, 1, 2);
        Ui.At(login, account, 0, 2, 2);
        Ui.At(login, password, 2, 2, 2);
        Ui.At(login, UnavailableCheck("記住帳號", "LoginRememberAccount"), 0, 3);
        Ui.At(login, UnavailableCheck("記住密碼", "LoginRememberPassword"), 1, 3);
        Ui.At(login, Ui.Unavailable("儲存此組", "LoginSaveIdentity", "安全儲存尚未接入，不會儲存輸入的帳密。"), 2, 3);
        Ui.At(login, Ui.Unavailable("刪除此組", "LoginDeleteIdentity", "尚無已儲存的登入資料。"), 3, 3);
        Ui.At(login, Ui.Text("輸入內容僅留在此視窗，不會傳送或儲存。", 12, Ui.Muted), 0, 4, 2);
        Ui.At(login, Ui.Unavailable("登入", "LoginSubmit"), 2, 4);
        Ui.At(login, Ui.Unavailable("中斷", "LoginDisconnect"), 3, 4);
        body.Children.Add(Ui.Card("帳號登入", login));

        var roleRow = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 8 };
        Ui.At(roleRow, roles, 0);
        Ui.At(roleRow, Ui.Unavailable("選角進入", "LoginEnterRole"), 1);
        body.Children.Add(Ui.Card("選擇角色", roleRow));
        body.Children.Add(status);
        body.Children.Add(roleStatus);

        var preview = Ui.Button("檢視桌面介面", () => { ClearSecrets(); openPreview(); }, "LoginPreview");
        var inspector = Ui.Button("封包檢查", () => { ClearSecrets(); openInspector(); }, "LoginInspector");
        body.Children.Add(Ui.Row(preview, inspector,
            Ui.Text("僅檢視介面與同步資料，不代表登入成功。", 12, Ui.Muted)));
        SetBody(new ScrollViewer
        {
            Content = body,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto
        });
        session.Changed += SessionChanged;
        Closed += (_, _) =>
        {
            closed = true;
            session.Changed -= SessionChanged;
            ClearSecrets();
            account.Text = "";
        };
        Refresh();
    }

    /// <summary>Clear on account/endpoint handoff, navigation, and final close.</summary>
    public void ClearSecrets() => password.Text = "";

    private static CheckBox UnavailableCheck(string title, string name)
    {
        var check = new CheckBox { Content = title, Name = name, IsEnabled = false };
        ToolTip.SetTip(check, "帳號與密碼安全儲存尚未接入；不會自動記住輸入內容。");
        return check;
    }

    private void NewDraft()
    {
        ClearSecrets();
        account.Text = "";
        account.Focus();
    }

    private void SessionChanged() => Ui.OnUi(() => { if (!closed) Refresh(); });

    private void Refresh()
    {
        var view = session.ReadView();
        if (generation != view.Generation)
        {
            generation = view.Generation;
            ClearSecrets();
            account.Text = "";
            roles.SelectedIndex = -1;
        }
        var selected = roles.SelectedItem as string;
        var state = view.Snapshot;
        var choices = state.Local.Session.Roles.IsDefault ? [] : state.Local.Session.Roles
            .Select(role => $"{role.Index} · {role.Name} · Lv.{role.Level}{(role.Locked ? "（鎖定）" : "")}").ToArray();
        roles.ItemsSource = choices;
        var previousIndex = Array.IndexOf(choices, selected);
        roles.SelectedIndex = previousIndex >= 0 ? previousIndex : choices.Length > 0 ? 0 : -1;
        roles.IsEnabled = choices.Length > 0;
        status.Text = session.ConnectionText + "｜" + DesktopSession.ConnectionUnavailable;
        roleStatus.Text = choices.Length == 0
            ? "選角後等待世界資料同步完成，將自動開啟主頁；目前尚未收到角色清單。"
            : "已呈現收到的角色清單；正式登入、選角與世界同步流程尚未接通。";
    }
}
