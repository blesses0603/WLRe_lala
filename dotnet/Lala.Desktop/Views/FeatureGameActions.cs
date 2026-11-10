using System.Collections.Immutable;
using Avalonia;
using Avalonia.Controls;
using Lala.Core.Gameplay;
using Lala.Core.State;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private readonly List<Button> commandButtons = [];
    private TextBlock actionNote = Ui.Text("請先登入並等待資料同步。", 12, Ui.Muted);
    private TextBox? partyTarget;
    private readonly Dictionary<string, int> pointDraft = [];
    private readonly Dictionary<string, TextBlock> pointLabels = [];
    private TextBlock? pointBalance;
    private bool submitting;

    private Button GameButton(string label, Func<GameAction> create)
    {
        var button = Ui.Button(label, () => _ = SubmitActionAsync(create));
        button.IsEnabled = session.CanSendGameCommands;
        commandButtons.Add(button); return button;
    }
    private async Task SubmitActionAsync(Func<GameAction> create)
    {
        if (submitting) return;
        try
        {
            submitting = true; RefreshGameControls();
            await session.ExecuteGameActionAsync(create());
            if (!closed) actionNote.Text = session.ActionStatus?.Message ?? "操作已送出，狀態以伺服器回報為準。";
        }
        catch (Exception error) when (error is Lala.Core.Protocol.ProtocolException or InvalidOperationException)
        { if (!closed) actionNote.Text = error.Message; }
        finally { submitting = false; if (!closed) RefreshGameControls(); }
    }
    private static uint RoleId(string? text) => uint.TryParse(text, out var value) && value > 0 ? value : throw new InvalidOperationException("請輸入有效的角色 ID。");
    private int Selected(string name) => tables.TryGetValue(name, out var table) && int.TryParse(table.SelectedKey, out var value)
        ? value : throw new InvalidOperationException("請先從清單選擇項目。");
    private Control Actions(params string[] labels)
    {
        var panel = new WrapPanel();
        foreach (var label in labels)
        {
            Func<GameAction>? action = ActionFor(label);
            var button = action is null ? Ui.Unavailable(label) : GameButton(label, action);
            button.Margin = new Thickness(0, 0, 6, 4); panel.Children.Add(button);
        }
        return panel;
    }
    private Func<GameAction>? ActionFor(string label)
    {
        if (key == "party")
        {
            if (label is "邀請組隊" or "申請入隊") return () => new("party", label == "邀請組隊" ? "invite" : "apply", RoleId(partyTarget?.Text));
            if (label == "離隊／解散") return () => new("party", "leave");
            if (label is "移除隊員" or "轉交隊長") return () => new("party", label == "移除隊員" ? "kick" : "leader", checked((uint)Selected("PartyMembers")));
            if (label is "接受" or "拒絕") return () => new("party", "respond", Count: label == "接受" ? 1 : 2,
                Key: tables["PartyRequests"].SelectedKey ?? throw new InvalidOperationException("請選擇組隊請求。"));
        }
        if (key == "companion" && label is "設為出戰" or "休息") return () =>
        {
            int index = Selected("Companions");
            var profile = session.Snapshot.Companions.Companions.GetValueOrDefault((ushort)index) ?? throw new InvalidOperationException("夥伴已變更。");
            return new("companion", label == "設為出戰" ? "deploy" : "rest", profile.Data.NpcId, index);
        };
        if (key == "benefits" && label == "開啟魔方") return () => new("cube");
        if (key == "benefits" && label == "領取選取任務") return () => new("daily", "task", Index:
            tables["DailyTasks"].SelectedKey is not null ? Selected("DailyTasks") : Selected("WeeklyTasks"));
        if (key == "benefits" && label == "領取活躍寶箱") return () => new("daily", "chest", Count: 1);
        if (key == "other" && label == "立即簽到") return () => new("guild", "sign");
        if (key == "crafting-queue" && label is "暫停" or "停止接續") return () => new("craft", "pause");
        if (key == "crafting-queue" && label is "上移" or "下移" or "移除") return () => new("craft", label == "上移" ? "up" : label == "下移" ? "down" : "delete", Index: Selected("CraftQueue"));
        if (key == "attributes" && label == "確認配點") return () => new("attributes", Values: pointDraft.ToImmutableDictionary());
        return null;
    }
    private Control AttributeControls()
    {
        pointLabels.Clear(); pointDraft.Clear();
        var body = new StackPanel { Spacing = 8 };
        foreach (var (id, label) in new[] { ("int", "智力 INT"), ("str", "力量 STR"), ("con", "體質 CON"), ("wis", "智慧 WIS"), ("agi", "敏捷 AGI") })
        {
            var value = Ui.Text("待同步"); pointLabels[id] = value; pointDraft[id] = 0;
            void Adjust(int amount) { pointDraft[id] = Math.Clamp(pointDraft[id] + amount, 0, 602); RefreshGameControls(); }
            body.Children.Add(Columns("*,100,Auto", Ui.Text(label), value,
                Ui.Row(Ui.Button("－", () => Adjust(-1)), Ui.Button("＋", () => Adjust(1)), Ui.Button("＋10", () => Adjust(10)))));
        }
        pointBalance = Ui.Text("剩餘點數：待同步");
        return Page("角色能力配點", pointBalance, body, Ui.Text("確認配點後會消耗能力點數。", 12, Ui.Muted),
            Ui.Row(Ui.Button("取消預覽", () => { foreach (var id in pointDraft.Keys.ToArray()) pointDraft[id] = 0; RefreshGameControls(); }),
                GameButton("確認配點", () => new("attributes", Values: pointDraft.ToImmutableDictionary()))));
    }
    private void RefreshGameControls()
    {
        foreach (var button in commandButtons) button.IsEnabled = session.CanSendGameCommands && !submitting && session.ActionStatus?.Pending != true;
        if (!submitting) actionNote.Text = session.ActionStatus is {} status ? status.Label + "：" + status.Message
            : session.CanSendGameCommands ? "已連線；操作結果由伺服器確認。" : DesktopSession.ConnectionUnavailable;
        var stats = session.Snapshot.PlayerKnowledge.Stats;
        foreach (var (id, label) in pointLabels) label.Text = stats.TryGetValue(id, out var value) ? $"{value}　＋{pointDraft.GetValueOrDefault(id)}" : "待同步";
        if (pointBalance is not null) pointBalance.Text = stats.TryGetValue("attribute_potential", out var balance)
            ? $"剩餘點數：{balance}　預計使用：{pointDraft.Values.Sum()}" : "剩餘點數：待同步";
    }
}
