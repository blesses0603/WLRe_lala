using System.Text;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using CheckBox = Avalonia.Controls.CheckBox;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private Control ToolsPage()
    {
        string[] tabNames = ["一般設定", "規則", "恢復", "補給", "守衛", "維護", "交換"];
        string[] tabIcons = ["gear", "file", "heart", "cube", "shield", "hammer", "refresh"];
        var tabButtons = new List<Control>();
        for (int i = 0; i < tabNames.Length; i++) { int index = i; tabButtons.Add(ActionButton(tabNames[i], tabIcons[i], () => { state.SettingsTab = index; ShowPage(4); }, state.SettingsTab == i, true)); }
        var ruleList = new ContentControl(); var transferPanel = new ContentControl(); var detail = new ContentControl();
        string RuleHint(int category) => category switch
        {
            2 => $"HP ≤ {state.RecoveryHp}% · SP ≤ {state.RecoverySp}%", 3 => $"不足 {state.SupplyCount} 個時顯示補給示範",
            4 => $"HP ≤ {state.GuardHp}% 時顯示警戒示範", 5 => $"背包 ≥ {state.CleanupPercent}% 時顯示整理示範", _ => $"每 {state.ExchangeInterval} 秒顯示交換示範"
        };
        void RenderRules()
        {
            var rows = Column(6);
            foreach (var rule in state.Rules.Where(x => state.SettingsTab < 2 || x.Category == state.SettingsTab).ToArray())
            {
                var check = new CheckBox { IsChecked = rule.Enabled, MinHeight = 25 }; check.IsCheckedChanged += (_, _) => rule.Enabled = check.IsChecked == true;
                void Move(int delta) { int oldIndex = state.Rules.IndexOf(rule), newIndex = oldIndex + delta; if (newIndex < 0 || newIndex >= state.Rules.Count) return; state.Rules.RemoveAt(oldIndex); state.Rules.Insert(newIndex, rule); RenderRules(); }
                rows.Children.Add(Surface(Column(4, Sides(Row(4, check, new NeonIcon(rule.Icon, Accent, 16), Label(rule.Name, 11)),
                    Row(3, IconButton("up", "上移規則 " + rule.Name, () => Move(-1), 25), IconButton("down", "下移規則 " + rule.Name, () => Move(1), 25),
                        IconButton("trash", "刪除規則 " + rule.Name, () => { state.Rules.Remove(rule); RenderRules(); }, 25)), "*,81", 4), Label(RuleHint(rule.Category), 9, Muted)), new(7, 4), 8, false));
            }
            if (rows.Children.Count == 0) rows.Children.Add(Label("此分頁尚無規則，可新增預覽動作。", 10, Muted));
            ruleList.Content = rows;
        }
        var mode = Combo("智慧模式（推薦）", "依序執行", "手動預覽"); mode.SelectedIndex = state.TaskMode; mode.SelectionChanged += (_, _) => state.TaskMode = Math.Max(0, mode.SelectedIndex);
        Control NumberSetting(string title, Func<int> read, Action<int> write, int minimum, int maximum) => Sides(Label(title, 11),
            Stepper(read, value => { write(value); RenderRules(); }, minimum, maximum, title), "*,136");
        Control options = state.SettingsTab switch
        {
            0 => Column(8, Sides(Column(4, Label("啟用 AI 自動化（預覽）", 12, Ink, true), Label("依規則展示恢復、補給、守衛等設定", 9, Muted)), Switch(state.AiEnabled, value => state.AiEnabled = value)),
                Sides(Label("任務執行模式", 11), mode, "*,175"), NumberSetting("掃描 / 執行間隔（秒）", () => state.ScanInterval, value => state.ScanInterval = value, 1, 3600)),
            2 => Column(8, NumberSetting("HP 恢復門檻（%）", () => state.RecoveryHp, value => state.RecoveryHp = value, 0, 100), NumberSetting("SP 恢復門檻（%）", () => state.RecoverySp, value => state.RecoverySp = value, 0, 100)),
            3 => NumberSetting("補給最低數量", () => state.SupplyCount, value => state.SupplyCount = value, 1, 999),
            4 => NumberSetting("警戒 HP 門檻（%）", () => state.GuardHp, value => state.GuardHp = value, 0, 100),
            5 => NumberSetting("整理背包門檻（%）", () => state.CleanupPercent, value => state.CleanupPercent = value, 1, 100),
            6 => NumberSetting("交換掃描間隔（秒）", () => state.ExchangeInterval, value => state.ExchangeInterval = value, 1, 3600),
            _ => Label("調整規則優先順序，僅影響本次預覽。", 11, Muted)
        };
        RenderRules();
        void TransferSettings()
        {
            var editor = Input("預覽設定 JSON"); editor.AcceptsReturn = true; editor.Height = 145; editor.Text = ExportSettings(); editor.FontSize = 10;
            transferPanel.Content = Surface(Column(7, Label("匯入 / 匯出預覽設定", 12, Accent, true), Label("可複製或貼上以下 JSON，只包含介面選項與規則，不含帳密。", 10, Muted), editor,
                EqualRow(6, ActionButton("匯入設定", "download", () => { if (ImportSettings(editor.Text ?? "")) { AddEvent("匯入預覽設定"); ShowPage(4); Toast("已匯入本次預覽，未修改正式設定檔。"); } }, true, true),
                    ActionButton("關閉", "minus", () => transferPanel.Content = null, compact: true))), new(9), 10, false);
            Dispatcher.UIThread.Post(() => transferPanel.BringIntoView(), DispatcherPriority.Loaded);
        }
        Control ToolTile(int art, string title, string subtitle, string button, Action action) => Surface(AdaptiveSides(
            Sides(new SheetArtwork(Asset("tool-illustrations.png"), art) { Width = 60, Height = 60 }, Column(5, Label(title, 13, Ink, true), Label(subtitle, 9, Muted)), "62,*", 7),
            ActionButton(button, "play", action, true, true), "*,98", 300), new(9));
        void OpenNpc()
        {
            var speech = Label("歡迎來到冒險服務處！這是 NPC 對話介面示範。", 11);
            detail.Content = Card("NPC 互動與對話（範例）", "chat", speech,
                EqualRow(5, ActionButton("對話", "chat", () => speech.Text = "今天也要平安歸來。可試試任務、商店或交換入口。", compact: true),
                    ActionButton("任務", "file", () => { speech.Text = "已接取範例任務：收集風之草 ×10。未向遊戲送出指令。"; AddEvent("預覽 NPC 任務"); }, compact: true),
                    ActionButton("商店", "bag", () => speech.Text = "範例商店：治療藥水 100 G、純淨水 20 G。正式購買尚未接入。", compact: true),
                    ActionButton("交換", "refresh", () => speech.Text = "範例交換：風之草 ×5 → 純淨水 ×1。未消耗物品。", compact: true)));
            Dispatcher.UIThread.Post(() => detail.BringIntoView(), DispatcherPriority.Loaded);
        }
        void OpenStorage()
        {
            var stored = Label("", 12, Accent); void UpdateStored() => stored.Text = $"範例儲藏室：{state.ToolStored:N0} / 2,000 格";
            UpdateStored();
            detail.Content = Card("儲藏存取（範例）", "cube", stored, Label("治療藥水、風之草、純淨水等範例物品。", 10, Muted),
                EqualRow(6, ActionButton("存入 10 格", "download", () => { state.ToolStored = Math.Min(2000, state.ToolStored + 10); UpdateStored(); }, compact: true),
                    ActionButton("取出 10 格", "up", () => { state.ToolStored = Math.Max(0, state.ToolStored - 10); UpdateStored(); }, compact: true),
                    ActionButton("整理", "layers", () => Toast("已展示儲藏整理回饋；真實物品不受影響。"), compact: true)));
            Dispatcher.UIThread.Post(() => detail.BringIntoView(), DispatcherPriority.Loaded);
        }
        void OpenBenefits()
        {
            var summary = Label("", 11, Accent); void UpdateSummary() => summary.Text = $"每日任務：{state.ToolTaskProgress} / 5 · 魔方：{state.ToolCrystals} 個 · " + (state.ToolGiftClaimed ? "範例福利已領取" : "範例福利可領取");
            UpdateSummary();
            detail.Content = Card("福利 / 魔方 / 每日任務（範例）", "star", summary,
                EqualRow(6, ActionButton("領取福利", "star", () => { state.ToolGiftClaimed = true; UpdateSummary(); Toast("已標記範例福利領取，沒有取得真實獎勵。"); }, compact: true),
                    ActionButton("魔方轉換", "cube", () => { if (state.ToolCrystals > 0) state.ToolCrystals--; UpdateSummary(); }, compact: true),
                    ActionButton("每日任務", "file", () => { state.ToolTaskProgress = Math.Min(5, state.ToolTaskProgress + 1); UpdateSummary(); }, compact: true)));
            Dispatcher.UIThread.Post(() => detail.BringIntoView(), DispatcherPriority.Loaded);
        }
        return Page(FeatureMenu(), Card("設定與工具中心", "gear", Label("AI、補給、守衛、維護等介面選項集中管理。", 10, Muted),
                EqualRow(4, tabButtons.Take(4).ToArray()), EqualRow(4, tabButtons.Skip(4).ToArray()), options,
                Sides(Column(3, Label("行動流程（優先順序）", 12, Ink, true), Label("↑ / ↓ 調整順序；只影響預覽。", 9, Muted)),
                    ActionButton("新增動作", "plus", () => { if (state.Rules.Count >= 12) { Toast("預覽最多保留 12 個動作。"); return; } state.Rules.Add(DefaultRule(state.SettingsTab >= 2 ? state.SettingsTab : 2)); RenderRules(); }, true, true)), ruleList,
                EqualRow(6, ActionButton("重置為預設", "refresh", () => { ResetSettings(); ShowPage(4); Toast("已還原預覽設定，未修改正式設定檔。"); }, compact: true),
                    ActionButton("匯入 / 匯出", "file", TransferSettings, compact: true)), transferPanel,
                ActionButton("保存設定", "save", () => { state.SavedSettingsJson = ExportSettings(); AddEvent("保存本次預覽設定"); Toast("已保存至本次預覽記憶體，重新啟動不保留。"); }, true)),
            ToolTile(0, "NPC 互動與對話", "可展示對話、任務、商店與交換", "開啟 NPC", OpenNpc),
            ToolTile(1, "儲藏存取", "儲藏室 / 雜物櫃 · 容量與批次操作", "開啟儲藏", OpenStorage),
            ToolTile(2, "福利 / 魔方 / 每日任務", "領取狀態與每日任務樣式預覽", "開啟福利", OpenBenefits), detail,
            ActionButton("核心診斷工具", "gear", () => page.Content = Column(8, ActionButton("返回工具中心", "arrow", () => ShowPage(4)), diagnostics())),
            Label("以上選項均為本機預覽，不會啟動 AI、操作 NPC 或讀取電腦版帳密。", 9, Muted));
    }
    private static PreviewRule DefaultRule(int category) => category switch
    {
        2 => new("自動恢復", "heart", 2), 3 => new("自動補給", "cube", 3), 4 => new("守衛／警戒", "shield", 4),
        5 => new("清理與維護", "star", 5), _ => new("定期交換", "refresh", 6)
    };
    private void ResetSettings()
    {
        state.AiEnabled = true; state.TaskMode = 0; state.ScanInterval = 120; state.RecoveryHp = 70; state.RecoverySp = 40;
        state.SupplyCount = 20; state.GuardHp = 25; state.CleanupPercent = 85; state.ExchangeInterval = 300;
        state.Rules.Clear(); for (int category = 2; category <= 5; category++) state.Rules.Add(DefaultRule(category));
    }
    private string ExportSettings()
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new() { Indented = true }))
        {
            writer.WriteStartObject(); writer.WriteNumber("schema", 1); writer.WriteBoolean("ai", state.AiEnabled);
            writer.WriteNumber("mode", state.TaskMode); writer.WriteNumber("interval", state.ScanInterval); writer.WriteNumber("hp", state.RecoveryHp); writer.WriteNumber("sp", state.RecoverySp);
            writer.WriteNumber("supply", state.SupplyCount); writer.WriteNumber("guard", state.GuardHp); writer.WriteNumber("cleanup", state.CleanupPercent); writer.WriteNumber("exchange", state.ExchangeInterval);
            writer.WriteStartArray("rules"); foreach (var rule in state.Rules) { writer.WriteStartObject(); writer.WriteNumber("category", rule.Category); writer.WriteBoolean("enabled", rule.Enabled); writer.WriteEndObject(); } writer.WriteEndArray(); writer.WriteEndObject();
        }
        return Encoding.UTF8.GetString(stream.ToArray());
    }
    private bool ImportSettings(string text)
    {
        try
        {
            if (text.Length > 16000) { Toast("預覽設定內容過長。 "); return false; }
            using var document = JsonDocument.Parse(text, new() { MaxDepth = 8 }); var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("schema", out var schema) || schema.GetInt32() != 1) { Toast("請使用本頁匯出的 schema 1 預覽設定。"); return false; }
            int Number(string name, int minimum, int maximum) => Math.Clamp(root.GetProperty(name).GetInt32(), minimum, maximum);
            bool ai = root.GetProperty("ai").GetBoolean();
            int mode = Number("mode", 0, 2), interval = Number("interval", 1, 3600), hp = Number("hp", 0, 100), sp = Number("sp", 0, 100), supply = Number("supply", 1, 999), guard = Number("guard", 0, 100), cleanup = Number("cleanup", 1, 100), exchange = Number("exchange", 1, 3600);
            var rules = new List<PreviewRule>();
            foreach (var entry in root.GetProperty("rules").EnumerateArray())
            {
                int category = entry.GetProperty("category").GetInt32();
                if (rules.Count >= 12 || category is < 2 or > 6) { Toast("規則數量或類型無效。"); return false; }
                var rule = DefaultRule(category); rule.Enabled = entry.GetProperty("enabled").GetBoolean(); rules.Add(rule);
            }
            state.AiEnabled = ai; state.TaskMode = mode; state.ScanInterval = interval; state.RecoveryHp = hp; state.RecoverySp = sp;
            state.SupplyCount = supply; state.GuardHp = guard; state.CleanupPercent = cleanup; state.ExchangeInterval = exchange;
            state.Rules.Clear(); state.Rules.AddRange(rules); return true;
        }
        catch (Exception error) when (error is JsonException or InvalidOperationException or FormatException or OverflowException or KeyNotFoundException)
        { Toast("預覽設定格式不正確，未套用任何變更。"); return false; }
    }
}
