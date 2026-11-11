using Avalonia.Controls;
using Lala.Android.Live;
using Lala.Core.Expedition;
using Lala.Core.Inventory;
using Button = Avalonia.Controls.Button;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control OfficialModulePage(int index) => index switch
    { 9 => OfficialExpeditionPage(), 10 => OfficialCraftingPage(), _ => OfficialToolsPage() };

    private Control OfficialToolsPage()
    {
        var status = Label("", 11, Accent); var controls = Column(7);
        var buttons = new List<(Button Button, string Kind)>();
        foreach (var (name, kind) in new[] { ("自動戰鬥", "battle"), ("自動徘徊", "roaming"), ("自動遠征", "expedition") })
        {
            var button = ActionButton(name, "play", () => OfficialOperation(() => official!.SetAutomationAsync(kind,
                official.Snapshot.Automations.FirstOrDefault(x => x.Kind == kind)?.Enabled != true)), compact: true);
            buttons.Add((button, kind)); controls.Children.Add(button);
        }
        renderOfficial = value =>
        {
            status.Text = value.Status;
            foreach (var (button, kind) in buttons)
            {
                var current = value.Automations.FirstOrDefault(x => x.Kind == kind);
                button.IsEnabled = value.CanAct;
                button.Content = (current?.Enabled == true ? "停止" : "啟動") + (kind switch { "battle" => "自動戰鬥", "roaming" => "自動徘徊", _ => "自動遠征" })
                    + (current is null ? "" : " · " + current.Message);
            }
        };
        return Page(FeatureMenu(), Card("連線與自動化", "gear", status, controls,
                Label("自動化預設關閉。按下啟動才會使用公用核心的預設規則執行，連線結束即停止。示範模式的設定不會套用至正式角色。", 10, Muted)),
            ActionButton("連線生命週期診斷", "chart", () => page.Content = diagnostics(), compact: true),
            ActionButton("中斷官方連線", "stop", () => official!.Disconnect()));
    }

    private Control OfficialExpeditionPage()
    {
        var status = Label("", 11, Accent); var rows = Column(7); ExpeditionReceiveSnapshot? previous = null; bool? allowed = null;
        renderOfficial = value =>
        {
            status.Text = value.Status;
            var data = value.Publication?.Receive.State.Expedition;
            if (ReferenceEquals(previous, data) && allowed == value.CanAct) return; previous = data; allowed = value.CanAct; rows.Children.Clear();
            if (data is not { Ready: true }) { rows.Children.Add(Label("等待官方遠征資料同步。", 11, Muted)); return; }
            rows.Children.Add(Label(data.Status, 11, Muted));
            foreach (var team in data.Teams.Values.OrderBy(x => x.Index))
            {
                var claim = ActionButton("領取結果", "gift", () => OfficialOperation(() => official!.ExecuteAsync(new("expedition", "claim", Index: team.Index))), compact: true);
                claim.IsEnabled = value.CanAct && !data.Uncertain && data.Pending is null;
                rows.Children.Add(Surface(Column(5, Label($"隊伍 {team.Index} · 任務 {team.Quest}", 12, Ink, true),
                    Label($"成員 {team.Members.Length} · 任務時間 {team.Minutes} 分鐘", 10, Muted), claim), new(9), 10, false));
            }
            if (data.Teams.Count == 0) rows.Children.Add(Label("目前沒有收到執行中的遠征隊伍。", 11, Muted));
            rows.Children.Add(Label($"已同步據點夥伴 {data.Roles.Count} 位 · 可派遣任務 {data.Quests.Count} 項", 11, Accent));
        };
        var refresh = ActionButton("查詢副本房間", "refresh", () => OfficialOperation(() => official!.ExecuteAsync(new("instance", "refresh"))), compact: true);
        var render = renderOfficial; renderOfficial = value => { render?.Invoke(value); refresh.IsEnabled = value.CanAct; };
        return Page(FeatureMenu(), Card("遠征 · 官方資料", "flag", status, rows),
            Card("副本", "layers", refresh, Label("房間建立與完整副本管理仍在手機介面接線中。", 10, Muted)),
            ActionButton("自動遠征設定", "gear", () => ShowPage(4)));
    }

    private Control OfficialCraftingPage()
    {
        var status = Label("", 11, Accent); var rows = Column(7); CraftingSnapshot? previous = null; bool? allowed = null;
        var start = ActionButton("開始製作", "play", () => OfficialOperation(() => official!.ExecuteAsync(new("craft", "start"))), true, true);
        var pause = ActionButton("暫停製作", "stop", () => OfficialOperation(() => official!.ExecuteAsync(new("craft", "pause"))), compact: true);
        renderOfficial = value =>
        {
            var data = value.Publication?.Receive.State.Crafting.Crafting;
            status.Text = data?.Status ?? "等待官方製作排程同步";
            start.IsEnabled = pause.IsEnabled = value.CanAct && data?.Ready == true;
            if (ReferenceEquals(data, previous) && allowed == value.CanAct) return; previous = data; allowed = value.CanAct; rows.Children.Clear();
            if (data?.Ready != true) { rows.Children.Add(NeedOfficialLogin()); return; }
            foreach (var row in data.Queue.Values.OrderBy(x => x.Index))
            {
                string name = value.Publication?.Catalogs?.Items.GetValueOrDefault(row.ItemId)?.Name ?? "物品 " + row.ItemId;
                var delete = ActionButton("移除", "trash", () => OfficialOperation(() => official!.ExecuteAsync(new("craft", "delete", Index: row.Index))), compact: true);
                delete.IsEnabled = value.CanAct;
                rows.Children.Add(Surface(Column(5, Label($"{row.Index}. {name} ×{row.Count}", 12), delete), new(8), 10, false));
            }
            if (data.Queue.Count == 0) rows.Children.Add(Label("伺服器尚未回傳製作項目。", 11, Muted));
        };
        return Page(FeatureMenu(), Card("製作排程 · 官方資料", "hammer", status, rows, EqualRow(6, start, pause)),
            Card("煉金", "flask", Label("正式煉金需選擇目前背包格位與材料。材料選取介面仍在接線，這裡不會使用示範材料送出指令。", 11, Muted)));
    }
}
