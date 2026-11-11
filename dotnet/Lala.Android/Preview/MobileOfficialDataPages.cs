using System.Collections.Immutable;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Lala.Android.Live;
using Lala.Core.Gameplay;
using Lala.Core.Inventory;
using Lala.Core.Sessions;
using Lala.Core.Social;
using Lala.Core.State;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private static Control NeedOfficialLogin() => Label("請先在首頁登入官方伺服器。此處只顯示收到的資料。", 11, Muted);
    private Control OfficialPlayerPage()
    {
        var portrait = new OfficialImageView(60); var name = Label("尚未登入", 18, Ink, true); var position = Label("等待角色位置同步", 11, Muted);
        var hp = Label("HP 待同步", 12, Green); var sp = Label("SP 待同步", 12, Accent); var status = Label("", 10, Muted);
        var hpBar = new ProgressBar { Maximum = 100, Height = 6, Foreground = Green }; var spBar = new ProgressBar { Maximum = 100, Height = 6, Foreground = Accent };
        var actions = new List<Avalonia.Controls.Button>();
        var tent = EqualRow(5);
        foreach (var (label, operation) in new[] { ("展開帳篷", "open"), ("收起帳篷", "close"), ("進入帳篷", "enter") })
            actions.Add(ActionButton(label, "tent", () => OfficialOperation(() => official!.ExecuteAsync(new("tent", operation))), compact: true));
        var tentControls = actions.Cast<Control>().ToArray(); tent = EqualRow(5, tentControls);
        renderOfficial = value =>
        {
            status.Text = value.Status;
            var data = value.Publication?.Receive.State;
            if (data?.Player is not { } player) { name.Text = "尚未登入"; position.Text = "等待官方角色資料"; hp.Text = "HP 待同步"; sp.Text = "SP 待同步"; portrait.Set((Lala.Core.Resources.PortraitRenderRequest?)null); }
            else
            {
                var stats = data.PlayerKnowledge.Stats; long currentHp = stats.GetValueOrDefault("hp"), maxHp = stats.GetValueOrDefault("max_hp"), currentSp = stats.GetValueOrDefault("sp"), maxSp = stats.GetValueOrDefault("max_sp");
                name.Text = player.Name + (stats.TryGetValue("level", out long level) ? " · Lv." + level : "");
                string scene = value.Publication?.Catalogs?.SceneNames.GetValueOrDefault(player.Scene) ?? "地圖 " + player.Scene;
                position.Text = $"{scene} · ({player.X}, {player.Y})";
                hp.Text = maxHp > 0 ? $"HP {currentHp:N0} / {maxHp:N0}" : "HP 尚未同步"; sp.Text = maxSp > 0 ? $"SP {currentSp:N0} / {maxSp:N0}" : "SP 尚未同步";
                hpBar.Value = maxHp > 0 ? Math.Clamp(100.0 * currentHp / maxHp, 0, 100) : 0; spBar.Value = maxSp > 0 ? Math.Clamp(100.0 * currentSp / maxSp, 0, 100) : 0;
                portrait.Set(official!.Portrait(false));
            }
            foreach (var button in actions) button.IsEnabled = value.CanAct;
        };
        return Page(HomeTabs(5), FeatureMenu(), Card("角色概況 · 官方即時資料", "user", Sides(portrait, Column(7, name, hp, hpBar, sp, spBar), "63,*"), position, status),
            Card("帳篷活動", "tent", tent), EqualRow(6, ActionButton("夥伴與配點", "users", () => ShowPage(8), compact: true), ActionButton("小地圖", "map", () => ShowPage(6), compact: true)),
            ActionButton("中斷官方連線", "stop", () => official!.Disconnect()));
    }
    private Control OfficialChatPage()
    {
        var channel = Combo("區域", "世界", "隊伍", "組織", "密語"); var input = Input("輸入訊息，按送出後傳往所選頻道"); input.MaxLength = 127; input.Name = "OfficialChatInput";
        var target = Input("密語角色 ID"); target.IsVisible = false;
        channel.SelectionChanged += (_, _) => target.IsVisible = channel.SelectedItem?.ToString() == "密語";
        var messages = Column(8); var team = Column(7); var status = Label("", 10, Muted);
        var send = ActionButton("送出", "mail", () => OfficialOperation(async () =>
        {
            string text = (input.Text ?? "").Trim(); if (text.Length == 0) return;
            uint? recipient = null;
            if (channel.SelectedItem?.ToString() == "密語") { if (!uint.TryParse(target.Text, out uint id)) { Toast("請填入密語對象的角色 ID。"); return; } recipient = id; }
            await official!.SendChatAsync(channel.SelectedItem?.ToString() ?? "區域", text, recipient);
            input.Text = ""; Toast("訊息已送往伺服器，送達狀態以伺服器回覆為準。");
        }), true, true);
        ChatReceiveSnapshot? lastChat = null; Lala.Core.Social.PartyEventSnapshot? lastParty = null; bool? priorPermission = null;
        input.TextChanged += (_, _) => send.IsEnabled = official!.Snapshot.CanChat && !string.IsNullOrWhiteSpace(input.Text);
        renderOfficial = value =>
        {
            status.Text = value.Status; send.IsEnabled = value.CanChat && !string.IsNullOrWhiteSpace(input.Text);
            var data = value.Publication?.Receive.State;
            if (!ReferenceEquals(data?.Chat, lastChat))
            {
                lastChat = data?.Chat; messages.Children.Clear();
                foreach (var row in lastChat?.Messages.TakeLast(80) ?? [])
                {
                    string text = row.Receipt.Event switch { ChatMessageEvent message => message.Text, ChatAnnouncementEvent notice => notice.Text, _ => "" };
                    string scope = row.Receipt.Event is ChatMessageEvent item ? item.Channel : "公告";
                    messages.Children.Add(Surface(Column(4, Label(row.Name + " · " + scope, 10, Accent, true), Label(text, 12)), new(9, 7), 10, false));
                }
            }
            if (messages.Children.Count == 0) messages.Children.Add(Label(value.Connected ? "尚未收到聊天訊息。" : "登入後接收官方聊天訊息。", 11, Muted));
            if (!ReferenceEquals(data?.Party, lastParty) || priorPermission != value.CanAct)
            {
                priorPermission = value.CanAct;
                lastParty = data?.Party; team.Children.Clear();
                if (lastParty is { } party)
                {
                    team.Children.Add(Label(party.Status, 11, Muted));
                    foreach (var row in party.Nearby.Take(40))
                    {
                        uint id = row.Key;
                        var invite = ActionButton("邀請", "users", () => OfficialOperation(() => official!.ExecuteAsync(new("party", "invite", Target: id))), compact: true); invite.IsEnabled = value.CanAct;
                        team.Children.Add(Sides(Label(party.PlayerName(id, data!.Player?.RoleId, data.Player?.Name), 12), invite, "*,78"));
                    }
                    foreach (var request in party.Requests.Values)
                    {
                        var accept = ActionButton("接受", "check", () => OfficialOperation(() => official!.ExecuteAsync(new("party", "respond", Target: request.RoleId, Count: 1, Key: request.Key))), true, true); accept.IsEnabled = value.CanAct;
                        team.Children.Add(Sides(Label("組隊請求 · " + party.PlayerName(request.RoleId), 11), accept, "*,78"));
                    }
                }
            }
            if (team.Children.Count == 0) team.Children.Add(Label("等待附近玩家與隊伍資料。", 11, Muted));
        };
        return Page(FeatureMenu(), Card("聊天 · 官方頻道", "chat", status, new ScrollViewer { Content = messages, Height = 280 }, channel, target, Sides(input, send, "*,75", 6)),
            Card("組隊管理", "users", team, ActionButton("離開隊伍", "minus", () => OfficialOperation(() => official!.ExecuteAsync(new("party", "leave"))), compact: true)));
    }
    private Control OfficialInventoryPage()
    {
        var count = Label("等待背包資料", 12, Accent); var rows = Column(7); BagReceiveSnapshot? previous = null; bool? priorPermission = null;
        renderOfficial = value =>
        {
            var inventory = value.Publication?.Receive.State.Bag;
            count.Text = inventory?.Ready == true ? $"背包 {inventory.Items.Count} / {inventory.Capacity?.ToString() ?? "?"}" : "等待官方背包資料同步";
            if (ReferenceEquals(previous, inventory) && priorPermission == value.CanAct) return; previous = inventory; priorPermission = value.CanAct; rows.Children.Clear();
            if (inventory?.Ready != true) { rows.Children.Add(NeedOfficialLogin()); return; }
            foreach (var item in inventory.Items.Values.OrderBy(x => x.Index))
            {
                string name = value.Publication?.Catalogs?.Items.GetValueOrDefault(item.ItemId)?.Name ?? "物品 " + item.ItemId;
                var image = new OfficialImageView(37); var bytes = official!.ItemImage(item.ItemId);
                if (bytes is not null) image.Set(item.ItemId + ":" + inventory.Revision, () => official.Snapshot.Connected, _ => Task.FromResult<byte[]?>(bytes));
                var hp = ActionButton("補 HP", "heart", () => OfficialOperation(() => official!.ExecuteAsync(new("field_item", "hp", Target: item.ItemId, Index: item.Index, Count: 0))), compact: true);
                var sp = ActionButton("補 SP", "star", () => OfficialOperation(() => official!.ExecuteAsync(new("field_item", "sp", Target: item.ItemId, Index: item.Index, Count: 0))), compact: true);
                hp.IsEnabled = sp.IsEnabled = value.CanAct;
                rows.Children.Add(Surface(Column(6, Sides(Row(7, image, Column(4, Label(name, 12, Ink, true), Label($"格位 {item.Index} · ID {item.ItemId}", 9, Muted))), Label("×" + item.Count, 13, Accent)), EqualRow(5, hp, sp)), new(9), 10, false));
            }
        };
        return Page(Card("包包 · 官方資料", "bag", count, rows, Label("補給按鈕會由公用核心核對物品效果、目標與目前數量，再決定是否傳送。", 10, Muted)));
    }
    private Control OfficialCompanionsPage()
    {
        var companions = Column(7); var attributes = Column(6); var status = Label("", 11, Accent);
        CompanionReceiveSnapshot? previous = null; ImmutableDictionary<string, long>? priorStats = null; bool? priorPermission = null;
        renderOfficial = value =>
        {
            status.Text = value.Status; var data = value.Publication?.Receive.State;
            bool permissionChanged = priorPermission != value.CanAct; priorPermission = value.CanAct;
            if (!ReferenceEquals(previous, data?.Companions) || permissionChanged)
            {
                previous = data?.Companions; companions.Children.Clear();
                foreach (var item in previous?.Companions ?? ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty)
                {
                    var pet = item.Value.Data; ushort slot = item.Key;
                    var deploy = ActionButton("設為出戰", "sword", () => OfficialOperation(() => official!.ExecuteAsync(new("companion", "deploy", Target: pet.NpcId, Index: slot))), true, true);
                    var rest = ActionButton("休息", "coffee", () => OfficialOperation(() => official!.ExecuteAsync(new("companion", "rest", Target: pet.NpcId, Index: slot))), compact: true);
                    deploy.IsEnabled = rest.IsEnabled = value.CanAct;
                    companions.Children.Add(Surface(Column(5, Label((pet.Name ?? "夥伴 " + pet.NpcId) + " · Lv." + pet.Level, 13, Ink, true),
                        Label($"HP {pet.Hp?.ToString() ?? "待同步"} · SP {pet.Sp?.ToString() ?? "待同步"} · 好感 {pet.Faith}", 10, Muted), EqualRow(5, deploy, rest)), new(9), 10, false));
                }
                if (companions.Children.Count == 0) companions.Children.Add(Label("等待官方夥伴資料同步。", 11, Muted));
            }
            var stats = data?.PlayerKnowledge.Stats;
            if (!ReferenceEquals(stats, priorStats) || permissionChanged)
            {
                priorStats = stats; attributes.Children.Clear();
                attributes.Children.Add(Label("可分配點數：" + (stats?.GetValueOrDefault("attribute_potential").ToString() ?? "待同步"), 12, Accent));
                foreach (var (label, key) in new[] { ("力量", "str"), ("體質", "con"), ("敏捷", "agi"), ("智力", "int"), ("知力", "wis") })
                {
                    var plus = ActionButton("+1", "plus", () => OfficialOperation(() => official!.ExecuteAsync(new("attributes", Values: ImmutableDictionary<string, int>.Empty.Add(key, 1)))), compact: true);
                    plus.IsEnabled = value.CanAct && stats?.GetValueOrDefault("attribute_potential") > 0;
                    attributes.Children.Add(Sides(Label(label + "  " + (stats?.GetValueOrDefault(key).ToString() ?? "待同步"), 12), plus, "*,70"));
                }
            }
        };
        return Page(FeatureMenu(), Card("夥伴出戰 · 官方資料", "users", status, companions), Card("角色能力", "chart", attributes));
    }
    private Control OfficialMapPage()
    {
        var title = Label("等待角色位置同步", 13, Accent); var image = new OfficialImageView(280); image.HorizontalAlignment = HorizontalAlignment.Center;
        var x = Input("目標 X"); var y = Input("目標 Y"); x.MaxLength = y.MaxLength = 5;
        var status = Label("", 11, Muted);
        var go = ActionButton("步行前往", "map", () =>
        {
            if (!ushort.TryParse(x.Text, out ushort targetX) || !ushort.TryParse(y.Text, out ushort targetY)) { Toast("請輸入有效的目標座標。"); return; }
            if (official!.Snapshot.Publication?.Receive.State.Player is { } player)
                OfficialOperation(() => official.NavigateAsync(player.Scene, targetX, targetY));
        }, true, true);
        var stop = ActionButton("停止導航", "stop", StopOfficialNavigation, compact: true);
        renderOfficial = value =>
        {
            if (value.Publication?.Receive.State.Player is { } player)
            { title.Text = $"地圖 {player.Scene} · 座標 ({player.X}, {player.Y})"; image.Set(official!.SmallMap(player.Scene)); }
            else { title.Text = "登入後同步官方地圖與座標"; image.Set((Lala.Core.Resources.SmallMapRenderRequest?)null); }
            status.Text = value.Navigation.Message; go.IsEnabled = value.CanAct && !value.Navigation.Running; stop.IsEnabled = value.Navigation.Running;
        };
        return Page(HomeTabs(6), Card("小地圖 · 官方資料", "map", title, image, EqualRow(6, x, y), EqualRow(6, go, stop), status,
            Label("導航由公用核心核對目前地圖、起點與可行走路線後執行。圖資未就緒或路線無效時會拒絕移動。", 10, Muted)));
    }
    private async void StopOfficialNavigation()
    {
        // Cancellation must remain available while the awaited navigation is running.
        try { await official!.StopNavigationAsync(); }
        catch (Exception) { Toast("導航停止尚未完成，請確認連線狀態。"); }
        finally { RefreshOfficial(); }
    }
}
