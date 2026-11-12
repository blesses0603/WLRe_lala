using System.Collections.Immutable;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Android.Live;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private bool officialOperationRunning;
    private Control OfficialPage(int index) => index switch
    {
        0 => OfficialLoginPage(), 2 => OfficialResourcesPage(), 5 => OfficialPlayerPage(), 7 => OfficialChatPage(),
        1 => OfficialInventoryPage(), 8 => OfficialCompanionsPage(), 6 => OfficialMapPage(),
        3 => OfficialEventsPage(), _ => OfficialModulePage(index)
    };
    private async void OfficialOperation(Func<Task> operation)
    {
        if (officialOperationRunning) { Toast("正在等待上一個操作完成。"); return; }
        officialOperationRunning = true;
        try { await operation(); }
        catch (Lala.Core.Protocol.ProtocolException error) { Toast(error.Message); }
        catch (Exception) { Toast("操作尚未完成，請確認連線與伺服器回覆後再試。"); }
        finally { officialOperationRunning = false; RefreshOfficial(); }
    }
    private Control OfficialLoginPage()
    {
        var line = new ComboBox { MinHeight = 38, FontSize = 12, HorizontalAlignment = HorizontalAlignment.Stretch };
        var account = Input("官方遊戲帳號"); account.Name = "OfficialAccount"; account.MaxLength = 64;
        var password = Input("遊戲密碼"); password.PasswordChar = '●'; password.Name = "OfficialPassword"; password.MaxLength = 64;
        var status = Label("", 11, Accent); var resource = Label("", 10, Muted);
        var roleCards = Column(7); var connected = Label("", 12, Green);
        var notifications = ActionButton("允許背景連線通知", "bell", () => official!.RequestNotifications(), compact: true);
        var login = ActionButton("登入官方伺服器", "link", () =>
        {
            if (line.SelectedItem is not MobileOfficialLine selected) return;
            if (official!.Login(selected.Id, (account.Text ?? "").AsSpan(), (password.Text ?? "").AsSpan()))
            { account.Text = ""; password.Text = ""; }
            else Toast(official.Snapshot.Status);
            RefreshOfficial();
        }, true);
        string catalogKey = ""; Guid? roleKey = null;
        void Admission() { var value = official!.Snapshot; login.IsEnabled = !value.Busy && !value.Connected && value.ResourcesReady && value.NotificationsAllowed && value.ServiceBound &&
            line.SelectedItem is MobileOfficialLine { Supported: true } && !string.IsNullOrWhiteSpace(account.Text) && !string.IsNullOrWhiteSpace(password.Text); }
        line.SelectionChanged += (_, _) => { if (line.SelectedItem is MobileOfficialLine selected) state.OfficialLineId = selected.Id; Admission(); };
        account.TextChanged += (_, _) => Admission(); password.TextChanged += (_, _) => Admission();
        renderOfficial = value =>
        {
            status.Text = value.Status; resource.Text = value.ResourcesReady ? "官方資源已驗證，可進行登入。" : value.ResourceProgress.Phase;
            string key = value.Version?.DataVersion + ":" + string.Join(',', value.Lines.Select(x => x.Id));
            if (key != catalogKey)
            {
                catalogKey = key; line.ItemsSource = value.Lines.ToArray(); line.SelectedItem = value.Lines.FirstOrDefault(x => x.Id == state.OfficialLineId);
            }
            notifications.IsVisible = !value.NotificationsAllowed; account.IsEnabled = password.IsEnabled = line.IsEnabled = !value.Busy && !value.Connected;
            connected.Text = value.Publication?.Receive.State.Player is { } player ? "已連線角色：" + player.Name : "尚未登入官方伺服器";
            if (value.RoleRequest?.RequestId != roleKey)
            {
                roleKey = value.RoleRequest?.RequestId; roleCards.Children.Clear();
                if (value.RoleRequest is { } request)
                    foreach (var role in request.Roles)
                    {
                        var portrait = new OfficialImageView(44); portrait.Set(official!.RolePortrait(request.RequestId, role.Index));
                        var choose = ActionButton($"選擇角色 {role.Name} · Lv.{role.Level}", "user", () => official!.SelectRole(request.RequestId, role.Index), true, true); choose.IsEnabled = !role.Locked;
                        roleCards.Children.Add(Surface(Sides(portrait, Column(5, choose, Label($"HP {role.Hp} / {role.MaxHp} · SP {role.Sp} / {role.MaxSp}", 10, Muted)), "46,*"), new(8), 10));
                    }
            }
            Admission();
        };
        return Page(FeatureMenu(), Card("帳號登入 / 官方連線", "user", status, resource, Field("db", "官方分流", line), Field("user", "帳號", account), Field("lock", "密碼", password),
                notifications, login, EqualRow(6, ActionButton("中斷連線", "stop", () => official!.Disconnect(), compact: true), ActionButton("官方資料檢查", "layers", () => ShowPage(2), compact: true)),
                Label("帳密只用於這次登入，不會複製電腦版密碼或存入設定檔。", 9, Muted)),
            Card("選擇角色", "user", connected, roleCards, ActionButton("角色概況", "arrow", () => ShowPage(5))),
            ActionButton("切換介面示範", "grid", () =>
            {
                var value = official!.Snapshot; if (value.Connected || value.Busy) { Toast("請先停止連線或等待資料準備完成。"); return; }
                state.DemoMode = true; ShowPage(0);
            }, compact: true));
    }
    private Control OfficialResourcesPage()
    {
        var status = Label("", 12, Accent); var version = Label("", 13, Ink, true); var packages = Label("", 10, Muted);
        var progress = new ProgressBar { Maximum = 100, Height = 6, Foreground = Accent }; var stage = Label("", 11, Muted);
        var refresh = ActionButton("重新檢查官方資料", "refresh", () => OfficialOperation(official!.RefreshAsync), true);
        var login = ActionButton("進入登入", "user", () => ShowPage(0), true, true);
        renderOfficial = value =>
        {
            status.Text = value.Status;
            version.Text = value.Version is { } data ? $"遊戲 {data.ExeVersion} / 資料 {data.DataVersion}" : "尚未取得官方版本";
            packages.Text = value.Version is { } current ? string.Join('\n', current.Packages.Select(x => x.Key + "  " + x.Value)) : "";
            var phase = value.ResourceProgress; stage.Text = phase.Phase + (phase.Total is > 0 ? $" · {phase.Completed} / {phase.Total}" : "");
            progress.IsIndeterminate = value.Busy && !value.ResourcesReady && phase.Total is null; progress.Value = value.ResourcesReady ? 100 : phase.Total is > 0 ? 100.0 * (phase.Completed ?? 0) / phase.Total.Value : 0;
            refresh.IsEnabled = !value.Busy && !value.Connected;
            login.IsEnabled = value.ResourcesReady && !value.Busy;
        };
        return Page(Card("官方資料與資料庫檢查", "layers", status, version, packages, progress, stage,
                Label("使用官方 HTTPS 清單與共用核心驗證資源；已就緒的同版資源會重用。", 10, Muted)), refresh,
            EqualRow(6, ActionButton("停止準備", "stop", () => official!.CancelPreparation(), compact: true), login));
    }
    private Control OfficialEventsPage()
    {
        var status = Label("", 12, Accent); var count = Label("", 11, Muted);
        renderOfficial = value => { status.Text = value.Status; count.Text = "本次連線已接收封包：" + (value.Publication?.Receive.State.PacketCount.ToString() ?? "0"); };
        return Page(Card("官方連線狀態", "chart", status, count, Label("只顯示連線與封包數，不記錄帳密或原始登入封包。", 10, Muted)), ActionButton("返回登入", "user", () => ShowPage(0)));
    }
}
