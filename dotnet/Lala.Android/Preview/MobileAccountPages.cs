using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Button = Avalonia.Controls.Button;
using CheckBox = Avalonia.Controls.CheckBox;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control AccountsPage()
    {
        var password = Input("請輸入遊戲密碼（預覽不傳送）"); password.PasswordChar = '●';
        var remember = new CheckBox { Content = "保存帳號", IsChecked = true, FontSize = 10, Foreground = Ink, MinHeight = 32 };
        var saved = Combo("S1 · lalaplayer01（範例）", "S2 · lalaplayer02（範例）");
        var login = Card("帳號登入 / 連線管理", "user",
            Field("db", "分流", Combo("官方伺服器（介面示範）", "地球 / 1 線", "地球 / 3 線")),
            Field("user", "帳號", Input("請輸入遊戲帳號（預覽不儲存）")), Field("lock", "密碼", password),
            Sides(remember, Sides(saved, IconButton("trash", "清除預覽輸入", () => { password.Text = ""; Toast("已清除預覽密碼，未修改任何正式帳號。"); }, 30)), "100,*"),
            ActionButton("建立新連線", "link", () =>
            {
                if (state.AccountCount < 4) { state.AccountCount++; AddEvent("新增範例帳號卡"); ShowPage(0); }
                Toast("已新增範例卡片；尚未建立遊戲連線，也不會傳送帳密。");
            }, true),
            ActionButton("啟動 / 重新連接背景服務", "play", ServiceNotice),
            Label("此為介面預覽；輸入內容不會傳送或保存。", 9, Muted));
        var accounts = Column(9);
        for (int i = 0; i < state.AccountCount; i++) accounts.Children.Add(AccountCard(i));
        return Page(FeatureMenu(), login, Sides(Row(7, new NeonIcon("layers"), Label($"連線中的帳號（{state.AccountCount}）", 14, Ink, true)), Label("範例資料", 9, Muted)),
            accounts,
            Surface(EqualRow(10, Column(6, Row(6, new NeonIcon("download", Accent, 18), Label("資源狀態", 12, Ink, true)),
                    Label("官方資源尚未驗證", 10, Muted), Label("Manifest · Bundle · Runtime · SQLite", 8, Muted)),
                Column(6, Row(6, new NeonIcon("link", Accent, 18), Label("連線服務", 12, Ink, true)), Label("未接入正式連線", 10, Muted), Label("目前僅供介面操作預覽", 9, Muted)))));
    }
    private void ServiceNotice() => Toast("背景連線服務尚未接入；這個預覽不會自動登入。");
    private Control AccountCard(int account)
    {
        var roles = EqualRow(5, ActionButton("角色 1", "user", () => OpenRole(account, 0), state.ActiveAccount == account && state.Role == 0, true),
            ActionButton("角色 2", "user", () => OpenRole(account, 1), state.ActiveAccount == account && state.Role == 1, true));
        var identity = AdaptiveSides(Row(9, Avatar(42), Column(5, Row(6, Pill($"S{account + 1}", "user", Accent), Label($"lalaplayer{account + 1:00}", 14, Ink, true)),
            Label("● 示範連線  |  尚未連線遊戲", 9, Green))), roles, "*,126", 340);
        var actions = EqualRow(5, ActionButton("戰鬥", "sword", () => SetMode(account, 0), compact: true),
            ActionButton("徘徊", "walk", () => SetMode(account, 1), compact: true), ActionButton("遠征", "mountain", () => SetMode(account, 2), compact: true),
            ActionButton("角色功能", "star", () => OpenRole(account, state.Role), true, true));
        return Surface(Column(10, identity, actions, Sides(ActionButton("停止連線", "stop", () => Toast("範例帳號沒有正式連線可停止。"), compact: true),
            Label("自動化：僅預覽 · 未執行", 9, Muted), "108,*")));
    }
    private void OpenRole(int account, int role) { state.ActiveAccount = account; state.Role = role; state.RoleSelected = true; ShowPage(5); }
    private void SetMode(int account, int mode)
    {
        state.ActiveAccount = account; state.Mode = mode;
        AddEvent("預覽切換：" + new[] { "戰鬥", "徘徊", "遠征" }[mode]);
        Toast("已切換預覽模式，未發送遊戲指令。");
        if (state.Page == 5) ShowPage(5);
    }
    private Control CharacterPage()
    {
        var roleButtons = EqualRow(5, ActionButton("角色 1", "user", () => OpenRole(state.ActiveAccount, 0), state.Role == 0, true),
            ActionButton("角色 2", "user", () => OpenRole(state.ActiveAccount, 1), state.Role == 1, true));
        var name = AdaptiveSides(Column(5, Row(7, Pill($"S{state.ActiveAccount + 1}", "user", Accent), Label($"lalaplayer{state.ActiveAccount + 1:00}", 16, Ink, true)),
            Label("● 示範連線  |  範例角色狀態", 10, Green)), roleButtons, "*,126", 295);
        var stats = Column(6,
            StatBar("HP", "36,420 / 36,420", Green, 100), StatBar("SP", "8,950 / 8,950", Brush.Parse("#55BDFF"), 100));
        var character = Surface(Column(10, name, Sides(Column(5, Avatar(52), Label("Lv. 128", 11, Ink, true, true)), stats, "58,*"),
            EqualRow(7, Surface(Row(5, new NeonIcon("map", Accent, 16), Label("場景  風鳴草原", 10)), new(7), 7, false),
                Surface(Row(5, new NeonIcon("pin", Accent, 16), Label("座標  (342, 178)", 10)), new(7), 7, false))));
        var continuation = new ToggleSwitch { IsChecked = state.ContinueFlow, OnContent = "", OffContent = "", MinWidth = 44, Height = 30 };
        continuation.IsCheckedChanged += (_, _) => { state.ContinueFlow = continuation.IsChecked == true; Toast("已更新預覽選項；未啟動自動流程。"); };
        var automation = Card("自動化控制", "grid",
            EqualRow(6, ActionButton("切換戰鬥", "sword", () => SetMode(state.ActiveAccount, 0), state.Mode == 0, true),
                ActionButton("切換徘徊", "walk", () => SetMode(state.ActiveAccount, 1), state.Mode == 1, true),
                ActionButton("切換遠征", "mountain", () => SetMode(state.ActiveAccount, 2), state.Mode == 2, true)),
            Sides(Row(7, new NeonIcon("refresh", Accent, 18), Column(3, Label("自動流程延續", 12, Ink, true), Label("介面選項預覽，尚未執行", 9, Muted))), continuation),
            EqualRow(7, ActionButton("AI / 補給 / 修理設定", "gear", () => ShowPage(4), compact: true), ActionButton("遠征詳情 / 設定", "file", () => ShowPage(9), compact: true)));
        var tent = Card("帳篷活動", "tent", Label("管理帳篷狀態與進出，目前：" + (state.TentOpen ? "範例已展開" : "未展開"), 10, Muted),
            EqualRow(5, ActionButton("展開帳篷", "tent", () => { state.TentOpen = true; AddEvent("預覽展開帳篷"); ShowPage(5); }, state.TentOpen, true),
                ActionButton("收起帳篷", "download", () => { state.TentOpen = false; ShowPage(5); }, compact: true),
                ActionButton("進入帳篷", "arrow", () => Toast("帳篷進入尚未接入，未傳送指令。"), compact: true),
                ActionButton("離開帳篷", "arrow", () => Toast("帳篷離開尚未接入，未傳送指令。"), compact: true)));
        return Page(HomeTabs(5), FeatureMenu(), Card("角色概況", "user", Label("查看角色狀態、切換行為與帳篷管理（範例）", 10, Muted), character), automation, tent,
            Card("近期事件（預覽操作）", "file", EventRows(5)),
            Card("自動化狀態", "chart", Pill("僅預覽 · 未啟動", "info", Accent),
                EqualRow(7, Column(5, Label("目前模式", 9, Muted), Label(new[] { "戰鬥", "徘徊", "遠征" }[state.Mode], 12, Accent)),
                    Column(5, Label("流程狀態", 9, Muted), Label("未接入", 12, Accent)), Column(5, Label("隊列任務", 9, Muted), Label("0 項", 12, Accent)))),
            ActionButton("開啟小地圖", "map", () => ShowPage(6)));
    }
    private static Control StatBar(string label, string value, IBrush color, double percent) => Column(4,
        Sides(Row(5, new NeonIcon(label == "HP" ? "heart" : "star", color, 13), Label(label, 11)), Label(value, 10, Ink)),
        new ProgressBar { Minimum = 0, Maximum = 100, Value = percent, Height = 6, Foreground = color, Background = Brush.Parse("#183247") });
    private Control EventRows(int maximum)
    {
        var rows = Column(9);
        if (state.Events.Count == 0) rows.Children.Add(Label("尚無操作紀錄。切換模式、檢查示範或點選地圖後會顯示於此。", 11, Muted));
        else foreach (string entry in state.Events.Take(maximum)) rows.Children.Add(Row(8, Label("●", 10, Accent), Label(entry, 10)));
        return rows;
    }
    private Control EventsPage() => Page(Card("運行紀錄", "chart", Label("只記錄本次預覽操作；不記錄帳號或密碼。", 10, Muted), EventRows(30),
        ActionButton("清除預覽紀錄", "trash", () => { state.Events.Clear(); ShowPage(3); })));
}
