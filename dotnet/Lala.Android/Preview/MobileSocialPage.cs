using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Button = Avalonia.Controls.Button;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private static readonly string[] NearbyNames = ["lalaplayer02", "RiverMoon", "星璃", "WindLeaf"];
    private Control SocialPage()
    {
        var input = Input("輸入訊息...（僅本機預覽，不會傳送）"); input.Name = "PreviewChatInput"; input.MaxLength = 300;
        var displayChannel = Combo("全部頻道", "世界頻道", "組隊頻道", "區域頻道");
        var sendChannel = Combo("組隊頻道", "世界頻道", "區域頻道", "私訊");
        var messages = Column(10);
        var conversation = new ScrollViewer { Content = messages, Height = 242, HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled };
        string replying = "";
        var reply = Label("", 10, Accent); reply.IsVisible = false;
        void RefreshMessages()
        {
            messages.Children.Clear();
            var visible = state.Messages.Where(m => displayChannel.SelectedIndex == 0 || m.Channel + "頻道" == displayChannel.SelectedItem?.ToString());
            foreach (var message in visible)
            {
                var bubble = Column(5);
                if (message.Reply.Length > 0) bubble.Children.Add(Label("↳ 回覆 " + message.Reply, 9, Muted));
                bubble.Children.Add(Label(message.Text, 11));
                var identity = Row(5, Pill(message.Own ? "我" : "S" + (message.Portrait + 1), "user", Accent), Label(message.Sender, 11, Ink, true), Label(message.Channel, 8, Muted));
                var body = Surface(bubble, new(8, 6), 10, false);
                if (message.Own) body.BorderBrush = Accent;
                var answer = IconButton("arrow", "回覆訊息 " + message.Sender, () => { replying = message.Sender; reply.Text = "↳ 回覆 " + replying; reply.IsVisible = true; }, 25);
                messages.Children.Add(Sides(Portrait(message.Portrait, 31), Column(4, identity, body, Sides(Label(message.At + (message.Own ? " · 僅本機，未送出" : " · 範例"), 8, Muted), answer)), "33,*", 6));
            }
            if (messages.Children.Count == 0) messages.Children.Add(Label("此頻道尚無範例訊息。", 11, Muted));
        }
        displayChannel.SelectionChanged += (_, _) => RefreshMessages(); RefreshMessages();
        var announcement = Surface(Sides(Label("【預覽公告】此頁僅展示聊天與組隊介面，訊息不會傳送至伺服器。", 9, Muted),
            IconButton("minus", "關閉預覽公告", () => { state.AnnouncementVisible = false; ShowPage(7); }, 24)), new(7), 8, false);
        announcement.IsVisible = state.AnnouncementVisible;
        var emojis = new List<Control>();
        foreach (string emoji in new[] { "👍", "❤️", "😆", "😮", "🥲", "✨", "🔥", "👏" })
        {
            var button = new Button { Content = emoji, FontSize = 17, Padding = new(1), MinHeight = 31, CornerRadius = new(10), Background = Brush.Parse("#16354C"), HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center };
            AutomationProperties.SetName(button, "插入表情 " + emoji); button.Click += (_, _) => input.Text = (input.Text ?? "") + emoji; emojis.Add(button);
        }
        void Send()
        {
            string text = (input.Text ?? "").Trim(); if (text.Length == 0) return;
            string channel = sendChannel.SelectedItem?.ToString()?.Replace("頻道", "") ?? "組隊";
            state.Messages.Add(new("我", text, channel, 0, true, replying, DateTimeOffset.UtcNow.ToOffset(TimeSpan.FromHours(8)).ToString("HH:mm")));
            if (state.Messages.Count > 50) state.Messages.RemoveAt(0);
            input.Text = ""; replying = ""; reply.IsVisible = false; displayChannel.SelectedIndex = 0; RefreshMessages();
            Dispatcher.UIThread.Post(() => conversation.ScrollToEnd());
        }
        var send = ActionButton("送出", "mail", Send, true, true); send.IsEnabled = false;
        input.TextChanged += (_, _) => send.IsEnabled = !string.IsNullOrWhiteSpace(input.Text);
        input.KeyDown += (_, e) => { if (e.Key == Key.Enter) { Send(); e.Handled = true; } };
        var teamContent = new ContentControl();
        var teamButtons = new List<Button>();
        var teamTitle = Label("組隊管理", 14, Ink, true);
        void RefreshTeam()
        {
            teamTitle.Text = $"組隊管理 · 我的隊伍（{state.Party.Count + 1} / 5）";
            for (int i = 0; i < teamButtons.Count; i++) SelectButton(teamButtons[i], i == state.TeamTab);
            var list = Column(6);
            var players = state.TeamTab == 1 ? state.Requests.Order().ToArray() : state.TeamTab == 2 ? state.Party.Order().ToArray() : Enumerable.Range(0, 4).ToArray();
            foreach (int id in players)
            {
                var identity = Row(6, Portrait(id, 30), Column(3, Label(NearbyNames[id], 11, Ink, true), Label($"● 範例在線 · Lv.{129 + id} · {48 + id * 12} m", 8, Muted)));
                var invite = ActionButton(state.TeamTab == 1 ? "接受" : state.Party.Contains(id) ? "隊友" : "邀請", "users", () =>
                {
                    if (!state.Party.Contains(id) && state.Party.Count >= 4) { Toast("範例隊伍已滿，最多 5 人。"); return; }
                    state.Party.Add(id); state.Requests.Remove(id); AddEvent("預覽邀請隊友"); RefreshTeam(); Toast("已加入範例隊伍，未傳送組隊封包。");
                }, state.TeamTab == 1, true);
                var follow = ActionButton("跟隨", "walk", () => { state.Following = state.Following == id ? -1 : id; RefreshTeam(); Toast("已切換跟隨樣式，角色不會移動。"); }, state.Following == id, true);
                var guard = ActionButton("守護", "shield", () => { state.Guarding = state.Guarding == id ? -1 : id; RefreshTeam(); }, state.Guarding == id, true);
                Control actions = state.TeamTab == 2 ? EqualRow(4, follow, guard, ActionButton("移除", "minus", () => { state.Party.Remove(id); RefreshTeam(); }, compact: true)) : EqualRow(4, invite, follow, guard);
                list.Children.Add(Surface(AdaptiveSides(identity, actions, "*,155", 310), new(7), 9, false));
            }
            if (players.Length == 0) list.Children.Add(Label(state.TeamTab == 1 ? "暫無組隊申請。" : "目前尚無範例隊友。", 11, Muted));
            teamContent.Content = list;
        }
        teamButtons.AddRange([ActionButton("附近玩家", "pin", () => { state.TeamTab = 0; RefreshTeam(); }, state.TeamTab == 0, true),
            ActionButton("組隊申請", "mail", () => { state.TeamTab = 1; RefreshTeam(); }, state.TeamTab == 1, true),
            ActionButton("我的隊伍", "users", () => { state.TeamTab = 2; RefreshTeam(); }, state.TeamTab == 2, true)]);
        var teamTabs = EqualRow(5, teamButtons.ToArray());
        RefreshTeam();
        return Page(FeatureMenu(), Card("聊天 / 組隊", "chat",
                Sides(Row(5, new NeonIcon("layers", Accent, 17), Label("頻道", 10)), displayChannel, "55,*"), announcement, conversation,
                Surface(EqualRow(3, emojis.ToArray()), new(5), 9, false),
                EqualRow(7, sendChannel, Combo("星穹遺跡（範例）", "附近玩家（範例）")), reply, Sides(input, send, "*,72", 6)),
            Surface(Column(9, Row(6, new NeonIcon("users"), teamTitle), Divider(), teamTabs, teamContent,
                EqualRow(6, ActionButton("快速組隊", "users", () => { for (int id = 0; id < 4; id++) state.Party.Add(id); state.Requests.Clear(); state.TeamTab = 2; RefreshTeam(); Toast("已填入範例隊伍，未連線伺服器。"); }, true, true),
                    ActionButton("重新整理", "refresh", () => { RefreshTeam(); Toast("已重新整理本機範例清單。"); }, compact: true)))),
            Label("聊天與組隊均為本機預覽；訊息、邀請、跟隨與守護不會傳送至遊戲。", 9, Muted));
    }
}
