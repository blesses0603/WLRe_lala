using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Input;
using Lala.Core.Social;

namespace Lala.Desktop;

/// <summary>Desktop arrangement from dashboard_layout/overview_ui: 870px overview and
/// chat, 380px minimap/activity. Separate backpack and skills follow the revised UI request.</summary>
public sealed class DashboardWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly DesktopWindows windows;
    private readonly TextBlock connection = Ui.Text("尚未連線", 13, Ui.Muted);
    private readonly TextBlock position = Ui.Text("尚未收到角色位置", 16, bold: true);
    private readonly TextBlock role = Ui.Text("等待登入與角色資料同步", color: Ui.Muted);
    private readonly TextBlock companion = Ui.Text("等待夥伴資料同步", color: Ui.Muted);
    private readonly TextBlock activity = Ui.Text("等待登入與角色資料同步", color: Ui.Muted);
    private readonly TextBlock supply = Ui.Text("尚無補給紀錄", color: Ui.Muted);
    private readonly TextBlock expedition = Ui.Text("自動派遣未啟用\n遠征資料待同步", color: Ui.Muted);
    private readonly TextBlock party = Ui.Text("等待隊伍資料同步", color: Ui.Muted);
    private readonly TextBlock efficiency = Ui.Text("等待角色經驗資料；首場作基準", color: Ui.Muted);
    private readonly TextBlock eventLog = Ui.Text("尚未連線，沒有遊戲事件紀錄。", color: Ui.Muted);
    private readonly TabControl activityTabs;
    private readonly TextBox chatInput = new() { Name = "ChatInput", MaxLength = 127, PlaceholderText = "登入後即可聊天" };
    private readonly TextBox whisperTarget = new() { Name = "ChatTarget", Width = 120, MaxLength = 128, PlaceholderText = "名稱/ID", IsVisible = false };
    private long generation;
    private bool closed, closingStarted, closingReady;
    private readonly PortraitView playerPortrait=new(){Name="PlayerPortrait"};
    private readonly PortraitView companionPortrait=new(){Name="CompanionPortrait"};
    private readonly ComboBox chatFilter = Ui.Combo(["全部", "區域", "世界", "隊伍", "組織", "密語", "跨服", "系統"], name: "ChatFilter");
    private readonly ComboBox chatChannel = Ui.Combo(["區域", "世界", "隊伍", "組織", "密語"], name: "ChatChannel");
    private readonly TextBlock chatMessages = Ui.Text("尚無聊天訊息", 13, Ui.Ink);
    private readonly TextBlock chatStatus = Ui.Text("登入後即可聊天", 12, Ui.Muted);
    private readonly ScrollViewer chatScroll = new();
    private Button chatSend = null!;
    private bool chatSending;
    private ChatReceiveSnapshot? displayedChat;
    private readonly List<Button> gameButtons = [];
    private readonly List<(Button Button, string Kind, string Label)> automaticButtons = [];
    private readonly TextBlock battleStatus = Ui.Text("未啟用", color: Ui.Muted);
    private readonly TextBlock roamingStatus = Ui.Text("未啟用", color: Ui.Muted);

    public DashboardWindow(DesktopSession session, DesktopWindows windows)
        : base("飄流Re:LaLa  =By赤寧= · C# 桌面開發版", 1280, 800)
    {
        this.session = session; this.windows = windows; generation = session.Generation;
        eventLog.Name = "CharacterEventLog";
        position.TextWrapping = TextWrapping.NoWrap;
        position.TextTrimming = TextTrimming.CharacterEllipsis;
        foreach (var text in new[] { role, companion, supply, party, efficiency })
        {
            text.MaxLines = 2; text.TextTrimming = TextTrimming.CharacterEllipsis;
        }
        foreach (var text in new[] { activity, expedition })
        {
            text.MaxLines = 3; text.TextTrimming = TextTrimming.CharacterEllipsis;
        }
        var body = new Grid { Name = "DashboardRoot", RowDefinitions = new RowDefinitions("Auto,*"), RowSpacing = 7 };
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto"), RowDefinitions = new RowDefinitions("Auto,Auto,Auto"), ColumnSpacing = 6, RowSpacing = 3 };
        Ui.At(header, position, 0);
        Ui.At(header, Ui.Button("中斷連線", async () => await windows.Login.StopAsync(), "DashboardDisconnect"), 1);
        Ui.At(header, Ui.Button("登入／選角", () => windows.OpenLogin(), "OpenLogin"), 2);
        Ui.At(header, Ui.Text("LALA 桌面客戶端", 13, Ui.Muted), 0, 1);
        connection.HorizontalAlignment = HorizontalAlignment.Right;
        Ui.At(header, connection, 1, 1, 2);
        Ui.At(header, Ui.Button("官方版本與資源檢查", () => windows.OpenVersion(), "OpenVersion"), 0, 2, 3);
        Ui.At(body, header, 0);

        var content = new Grid { ColumnDefinitions = new ColumnDefinitions("870,380"), ColumnSpacing = 10 };
        var left = new Grid { RowDefinitions = new RowDefinitions("40,*,175"), RowSpacing = 8 };
        Ui.At(left, Navigation(), 0);
        Ui.At(left, Overview(), 0, 1);
        Ui.At(left, Chat(), 0, 2);
        Ui.At(content, left, 0);
        var right = new Grid { RowDefinitions = new RowDefinitions("320,*"), RowSpacing = 8 };
        var mapView=new MapView(session, () => windows.OpenNavigation());
        Ui.At(right,mapView,0);
        var log = new ScrollViewer { Content = eventLog, Padding = new Thickness(10) };
        activityTabs = Ui.Tabs(("事件紀錄", log), ("戰場陣形", new BattleView(session)));
        activityTabs.Name = "ActivityTabs";
        Ui.At(right, activityTabs, 0, 1); Ui.At(content, right, 1);
        Ui.At(body, content, 0, 1); SetBody(body, dashboard: true);
        session.Changed += SessionChanged;
        Closing += async (_, e) =>
        {
            if(closingReady)return;e.Cancel=true;if(closingStarted)return;
            closingStarted=true;closed=true;session.Changed-=SessionChanged;
            await Task.WhenAll(playerPortrait.DisposeAsync().AsTask(),companionPortrait.DisposeAsync().AsTask(),mapView.DisposeAsync().AsTask());
            closingReady=true;Avalonia.Threading.Dispatcher.UIThread.Post(Close);
        };
        Closed += (_, _) => { closed = true; session.Changed -= SessionChanged; chatInput.Text = ""; whisperTarget.Text = ""; };
        Refresh();
    }

    public void SelectBattleTab() => activityTabs.SelectedIndex = 1;
    public void SelectEventTab() => activityTabs.SelectedIndex = 0;

    private Control Navigation()
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 9 };
        (string Label, string Icon, Action? Open)[] items =
        [
            ("主頁", "function-icons/MainIcon_041.png", () => { }),
            ("組隊", "function-icons/MainIcon_005.png", () => windows.OpenPythonFeature("party")),
            ("夥伴出戰", "function-icons/MainIcon_010.png", () => windows.OpenPythonFeature("companion")),
            ("遠征", "function-icons/MainIcon_038.png", () => windows.OpenExpedition()),
            ("副本", "instance-menu/Menu_Dungeon.png", () => windows.OpenPythonFeature("instance")),
            ("福利", "function-icons/MainIcon_023.png", () => windows.OpenPythonFeature("benefits")),
            ("其他功能", "function-icons/Btn_CategoryAISetting004.png", () => windows.OpenPythonFeature("other")),
            ("煉金", "function-icons/MainIcon_007.png", () => windows.OpenPythonFeature("alchemy")),
            ("製作", "function-icons/MainIcon_011.png", () => windows.OpenPythonFeature("crafting"))
        ];
        foreach (var (label, path, open) in items)
        {
            var back = new Border { Width = 34, Height = 34, CornerRadius = new CornerRadius(17),
                BorderBrush = Brush.Parse("#b4e1eb"), BorderThickness = new Thickness(1), Background = Brush.Parse("#2d5165"), Child = Ui.Icon(path, 27) };
            var button = new Button { Content = back, Padding = new Thickness(0), Width = 38, Height = 38,
                Background = Brushes.Transparent, BorderThickness = new Thickness(0), IsEnabled = open is not null };
            AutomationProperties.SetName(button, label); ToolTip.SetTip(button, label + (open is null ? "｜此功能尚未移植" : ""));
            if (open is not null) button.Click += (_, _) => open();
            button.Name = label == "遠征" ? "OpenExpedition" : "OpenFeature_" + label;
            row.Children.Add(button);
        }
        Ui.At(grid, row, 0);
        Ui.At(grid, Ui.IconButton("經驗效率", "function-icons/MainIcon_020.png", () => windows.OpenPythonFeature("efficiency"), 34), 1);
        return grid;
    }

    private Control Overview()
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,*,*,*,*,*"), RowDefinitions = new RowDefinitions("1.24*,*,76,76"), ColumnSpacing = 6, RowSpacing = 6 };
        var roleTools = Ui.Row(Ui.Button("背包", () => windows.OpenInventory(), "OpenInventory"),
            Ui.Button("特技", () => windows.OpenSkills(), "OpenSkills"), Ui.Button("配點", () => windows.OpenPythonFeature("attributes"), "OpenAttributes"));
        var portraits = new Grid { RowDefinitions = new RowDefinitions("*,*") };
        Ui.At(portraits, Portrait(role,playerPortrait), 0); Ui.At(portraits, Portrait(companion,companionPortrait), 0, 1);
        Ui.At(grid, Card("角色與夥伴", portraits, roleTools), 0, 0, 3);
        var leaveTent = GameButton("離開帳篷", () => new("tent", "leave")); leaveTent.Name = "DashboardTentLeave";
        var activityTools = Ui.Row(GameButton("展開帳篷", () => new("tent", "open")), GameButton("進入", () => new("tent", "enter")), GameButton("收起帳篷", () => new("tent", "close")), leaveTent);
        Ui.At(grid, Card("目前活動", activity, activityTools), 3, 0, 3);
        var settings = Ui.IconButton("AI 設定", "buttons/Btn_Setting.png", () => windows.OpenSettings()); settings.Name = "OpenSettings";
        Ui.At(grid, Card("自動戰鬥", battleStatus, Ui.Row(settings, Play("啟動自動戰鬥"))), 0, 1, 2);
        Ui.At(grid, Card("自動徘徊", roamingStatus, Play("啟動自動徘徊")), 2, 1, 2);
        Ui.At(grid, Card("遠征", expedition, Ui.Row(Ui.IconButton("遠征設定", "buttons/Btn_Setting.png", () => windows.OpenExpedition()), Play("啟動自動派遣"))), 4, 1, 2);
        Ui.At(grid, Card("補給紀錄", supply, Ui.IconButton("補給設定", "buttons/Btn_CategoryAISetting003.png", () => windows.OpenSettings(2))), 0, 2, 2);
        Ui.At(grid, Card("煉金", Ui.Text("等待煉金資料同步", color: Ui.Muted), Ui.IconButton("煉金", "function-icons/MainIcon_007.png", () => windows.OpenPythonFeature("alchemy"))), 2, 2, 2);
        Ui.At(grid, Card("製作", Ui.Text("等待製作資料同步", color: Ui.Muted), Ui.IconButton("製作", "function-icons/MainIcon_011.png", () => windows.OpenPythonFeature("crafting"))), 4, 2, 2);
        Ui.At(grid, Card("隊伍檢查", party, Ui.IconButton("組隊", "function-icons/MainIcon_005.png", () => windows.OpenPythonFeature("party"))), 0, 3, 3);
        Ui.At(grid, Card("經驗效率", efficiency, Ui.IconButton("經驗效率", "function-icons/MainIcon_020.png", () => windows.OpenPythonFeature("efficiency"))), 3, 3, 3);
        return grid;
    }

    private static Control Portrait(TextBlock text,PortraitView portrait)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("40,*"), ColumnSpacing = 7 };
        Ui.At(row, portrait, 0);
        text.FontSize = 13; Ui.At(row, text, 1); return row;
    }
    private Button Play(string label)
    {
        string kind = label switch { "啟動自動戰鬥" => "battle", "啟動自動派遣" => "expedition", _ => "roaming" };
        var button = Ui.IconButton(label, "automation-controls/Auto_Play.png", () => _ = ToggleAutomaticAsync(kind), 26, false);
        automaticButtons.Add((button, kind, label)); return button;
    }
    private async Task ToggleAutomaticAsync(string kind)
    {
        try { await session.SetAutomationAsync(kind, session.Automations.GetValueOrDefault(kind)?.Enabled != true, GameplayPreferences.Read(session)); }
        catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { eventLog.Text = error.Message; }
    }
    private Button GameButton(string label, Func<Lala.Core.Gameplay.GameAction> create)
    {
        var button = Ui.Button(label, async () =>
        {
            try { await session.ExecuteGameActionAsync(create()); }
            catch (Exception error) when (error is Lala.Core.Protocol.ProtocolException or InvalidOperationException) { eventLog.Text = error.Message; }
        });
        button.IsEnabled = false; gameButtons.Add(button); return button;
    }
    private static Border Card(string title, Control content, Control tools)
    {
        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,*"), RowSpacing = 4 };
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 3 };
        Ui.At(header, Ui.Text(title, 14, Brush.Parse("#c5f1ff"), true), 0); Ui.At(header, tools, 1); Ui.At(grid, header, 0);
        Ui.At(grid, content, 0, 1);
        return new Border { Background = Brush.Parse("#d20d2030"), BorderBrush = Ui.BorderBrush, BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8), Padding = new Thickness(10, 4), ClipToBounds = true, Child = grid };
    }

    internal void InsertEmojiDraft(byte token,long expectedGeneration)
    {
        if(closed||session.Generation!=expectedGeneration)return;
        string literal="[Emoji"+token.ToString(System.Globalization.CultureInfo.InvariantCulture)+"]";
        string text=chatInput.Text??"";int start=Math.Min(chatInput.SelectionStart,chatInput.SelectionEnd),end=Math.Max(chatInput.SelectionStart,chatInput.SelectionEnd);
        start=Math.Clamp(start,0,text.Length);end=Math.Clamp(end,start,text.Length);
        if(text.Length-(end-start)+literal.Length>chatInput.MaxLength)return;
        chatInput.Text=text[..start]+literal+text[end..];chatInput.CaretIndex=start+literal.Length;chatInput.SelectionStart=chatInput.SelectionEnd=chatInput.CaretIndex;chatInput.Focus();
    }
    private Control Chat()
    {
        var layout = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto"), RowSpacing = 4 };
        chatFilter.Width = 95;
        chatFilter.SelectionChanged += (_, _) => RefreshChat(force: true);
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto"), ColumnSpacing = 7 };
        Ui.At(header, Ui.Text("顯示"), 0); Ui.At(header, chatFilter, 1);
        Ui.At(header, chatStatus, 2);
        Ui.At(header, Ui.Button("最新", () => chatScroll.ScrollToEnd(), "ChatLatest"), 3); Ui.At(layout, header, 0);
        chatScroll.Content = chatMessages; chatScroll.Padding = new Thickness(8);
        Ui.At(layout, new Border { Background = Brush.Parse("#a5142638"), Child = chatScroll }, 0, 1);
        var compose = new Grid { ColumnDefinitions = new ColumnDefinitions("88,Auto,*,Auto,Auto"), ColumnSpacing = 5 };
        chatChannel.SelectionChanged += (_, _) => whisperTarget.IsVisible = chatChannel.SelectedIndex == 4;
        whisperTarget.PlaceholderText = "對方角色 ID";
        chatSend = Ui.Button("送出", () => _ = SendChatAsync(), "ChatSend"); chatSend.IsEnabled = false;
        chatInput.TextChanged += (_, _) => UpdateChatAdmission();
        chatInput.KeyDown += (_, e) => { if (e.Key == Key.Enter && e.KeyModifiers == KeyModifiers.None) { e.Handled = true; _ = SendChatAsync(); } };
        Ui.At(compose, chatChannel, 0); Ui.At(compose, whisperTarget, 1); Ui.At(compose, chatInput, 2);
        Ui.At(compose, Ui.Button("表情", () => windows.OpenPythonFeature("emoji"), "OpenEmoji"), 3); Ui.At(compose, chatSend, 4);
        Ui.At(layout, compose, 0, 2); return Ui.Card("聊天", layout);
    }
    private void UpdateChatAdmission()
    {
        if (chatSend is null) return;
        chatSend.IsEnabled = session.CanSendChat && !chatSending && !string.IsNullOrWhiteSpace(chatInput.Text);
        ToolTip.SetTip(chatSend, session.CanSendChat ? "送出聊天訊息" : "請先完成登入。");
    }
    private async Task SendChatAsync()
    {
        if (chatSending || !session.CanSendChat || string.IsNullOrWhiteSpace(chatInput.Text)) return;
        var text = chatInput.Text; var expectedGeneration = session.Generation;
        uint? target = null;
        if (chatChannel.SelectedIndex == 4)
        {
            if (!uint.TryParse(whisperTarget.Text, out var value) || value == 0) { chatStatus.Text = "密語請填入對方角色 ID。"; return; }
            target = value;
        }
        chatSending = true; UpdateChatAdmission();
        try
        {
            await session.SendChatAsync(chatChannel.SelectedItem as string ?? "區域", text, target);
            if (closed || session.Generation != expectedGeneration) return;
            if (chatInput.Text == text) chatInput.Text = "";
            chatStatus.Text = "已送出，等待伺服器回覆。";
        }
        catch (Lala.Core.Protocol.ProtocolException error) { if (!closed && session.Generation == expectedGeneration) chatStatus.Text = error.Message; }
        catch (Exception) { if (!closed && session.Generation == expectedGeneration) chatStatus.Text = "傳送未完成，請確認連線；不會自動重送。"; }
        finally { chatSending = false; if (!closed) UpdateChatAdmission(); }
    }
    private void RefreshChat(bool force = false)
    {
        var chat = session.Snapshot.Chat;
        if (!force && ReferenceEquals(chat, displayedChat)) { UpdateChatAdmission(); return; }
        displayedChat = chat;
        string selected = chatFilter.SelectedItem as string ?? "全部";
        var messages = chat.Messages.Select(row => row.Receipt.Event switch
        {
            ChatMessageEvent message => (message.Channel, Text: $"[{message.Channel}] {row.Name}：{message.Text}"),
            ChatAnnouncementEvent announcement => (Channel: "系統", Text: $"[系統] {announcement.Text}"),
            _ => (Channel: "", Text: "")
        }).Where(row => row.Text.Length > 0 && (selected == "全部" || row.Channel == selected)).Select(row => row.Text);
        chatMessages.Text = string.Join("\n", messages);
        if (chatMessages.Text.Length == 0) chatMessages.Text = "尚無聊天訊息";
        if (chat.LatestFeedback?.Event is ChatResultEvent result) chatStatus.Text = result.Text;
        else if (chat.LatestFeedback?.Event is ChatNoticeEvent notice) chatStatus.Text = notice.Text;
        else if (!chatSending) chatStatus.Text = session.IsConnected ? "已連線" : "尚未連線";
        UpdateChatAdmission();
    }

    private void SessionChanged() => Ui.OnUi(() => { if (!closed) Refresh(); });
    private void Refresh()
    {
        connection.Text = session.ConnectionText;
        foreach (var button in gameButtons) button.IsEnabled = session.CanSendGameCommands && session.ActionStatus?.Pending != true;
        foreach (var (button, kind, label) in automaticButtons)
        {
            bool enabled = session.Automations.GetValueOrDefault(kind)?.Enabled == true;
            button.IsEnabled = session.CanSendGameCommands || enabled;
            ToolTip.SetTip(button, enabled ? "停止自動接續" : label);
        }
        battleStatus.Text = session.Automations.GetValueOrDefault("battle")?.Message ?? "未啟用；登入後可按播放啟動";
        roamingStatus.Text = session.Automations.GetValueOrDefault("roaming")?.Message ?? session.NavigationStatus.Message;
        var view = session.ReadView();
        if (generation != view.Generation)
        {
            generation = view.Generation; chatInput.Text = ""; whisperTarget.Text = "";
        }
        var snapshot = view.Snapshot;
        var player = snapshot.Player;
        string syncLabel = session.IsConnected ? "即時同步" : "最後同步";
        playerPortrait.Update(session.ReadPortrait(snapshot,false));
        companionPortrait.Update(session.ReadPortrait(snapshot,true),player is not null && snapshot.Companions.ActiveNpcId is null or 0);
        var current = snapshot.Local.World.Location;
        position.Text = player is null ? "尚未收到角色位置" :
            current.ConfirmedIsCurrent && current.Confirmed is { } confirmed && confirmed.Scene == player.Scene
            ? $"{view.Labels.Scene(player.Scene)}｜({confirmed.X}, {confirmed.Y})（{syncLabel}）"
            : $"{view.Labels.Scene(player.Scene)}｜座標待同步";
        var stats = snapshot.PlayerKnowledge.Stats;
        string Stat(string key) => stats.TryGetValue(key, out var value) ? value.ToString(System.Globalization.CultureInfo.InvariantCulture) : "待同步";
        role.Text = player is null ? "等待登入與角色資料同步" : $"{player.Name}｜等級 {Stat("level")}（{syncLabel}）\nHP {Stat("hp")}/{Stat("max_hp")}　SP {Stat("sp")}/{Stat("max_sp")}";
        var active = snapshot.Companions.ActiveNpcId;
        var profile = snapshot.Companions.Companions.Values.FirstOrDefault(p => p.Data.NpcId == active);
        companion.Text = !snapshot.Companions.Ready ? "等待夥伴資料同步" : profile is null ? "夥伴：未出戰" :
            $"{(profile.Data.NpcId <= ushort.MaxValue ? view.Labels.Npc((ushort)profile.Data.NpcId) : "夥伴") }（{syncLabel}）｜Lv.{(profile.StatOverrides.TryGetValue("level", out var level) ? level : profile.Data.Level)}";
        activity.Text = snapshot.Local.Battle.Active == true ? $"戰鬥中｜第 {snapshot.Local.Battle.Round?.ToString() ?? "待同步"} 回合\n{(session.IsConnected ? "已連線" : "已中斷，顯示最後同步資料")}" :
            player is null ? "等待登入與角色資料同步" : (session.IsConnected ? "已連線\n" : "目前未連線，顯示最後同步資料\n") + snapshot.Tent.Status;
        var exp = snapshot.Expedition;
        expedition.Text = !exp.Ready || !exp.OutpostReady ? "自動派遣未啟用\n遠征資料待同步" :
            $"最後同步：遠征 {exp.Teams.Values.Count(t => t.Quest != 0)} 隊\n{exp.Status}";
        string Balance(string key) => snapshot.Recovery.Resources.TryGetValue(key, out var resource) && resource.Value is { } amount ? amount.ToString() : "待同步";
        supply.Text = $"HP 儲存槽 {Balance("hp")}｜SP 儲存槽 {Balance("sp")}";
        var ownTeam = snapshot.Party.OwnTeam(player?.RoleId);
        party.Text = ownTeam is null ? snapshot.Party.Status : $"隊長：{snapshot.Party.PlayerName(ownTeam.LeaderId, player?.RoleId, player?.Name)}｜{ownTeam.Members.Length}/4 人（最後同步）";
        var ownEfficiency = snapshot.Efficiency.Rows.GetValueOrDefault(Lala.Core.Battle.EfficiencySubject.Player);
        var rate = ownEfficiency is null ? null : Lala.Core.Battle.EfficiencyRules.Rates(ownEfficiency).All.ExperiencePerMinute;
        efficiency.Text = rate is {} perMinute ? $"經驗 {perMinute:N1}／分｜累計 {ownEfficiency!.Earned}\n有效樣本 {ownEfficiency.Count} 場" : "等待足夠的戰鬥經驗樣本";
        eventLog.Text = snapshot.Player is { } currentPlayer
            ? $"目前角色：{currentPlayer.Name}\n{session.ConnectionText}"
            : "尚未選擇角色，沒有角色事件紀錄。";
        if (!session.ActionLog.IsEmpty) eventLog.Text += "\n\n本機操作紀錄\n" + string.Join("\n", session.ActionLog);
        if (!session.ServerEvents.IsEmpty)
        {
            var summaries=CharacterEventSummary.Lines(session.ServerEvents);
            eventLog.Text += $"\n\n角色接收紀錄（最近 {summaries.Length} 筆）\n" + string.Join("\n",summaries);
        }
        RefreshChat();
        foreach (var text in new[] { position, role, companion, activity, supply, expedition, party, efficiency })
            ToolTip.SetTip(text, text.Text);
    }
}
