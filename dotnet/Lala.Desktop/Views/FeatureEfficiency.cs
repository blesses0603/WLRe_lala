using System.Globalization;
using Avalonia.Controls;
using Lala.Core.Battle;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private sealed record EfficiencyChoice(EfficiencySubject Subject, string Label) { public override string ToString() => Label; }
    private ComboBox? efficiencySubjects, efficiencyUnit;
    private TextBlock? efficiencyDetail, efficiencyNote;
    private ProgressBar? efficiencyProgress;
    private Button? efficiencyReset;
    private string efficiencyChoicesKey = "";
    private bool efficiencyResetting;
    private Control EfficiencyControls()
    {
        efficiencyChoicesKey = ""; efficiencyResetting = false;
        efficiencySubjects = Ui.Combo([], -1, "EfficiencySubject"); efficiencySubjects.MinWidth = 220;
        efficiencyUnit = Ui.Combo(["天", "時", "分"], 2, "EfficiencyUnit");
        efficiencyDetail = Ui.Text("等待登入角色與經驗資料"); efficiencyNote = Ui.Text("首場作基準，從第二個有效樣本計算效率。", 12, Ui.Muted);
        efficiencyProgress = new() { Maximum = 100, Value = 0, Height = 8 };
        efficiencyReset = Ui.Button("重設統計", async () =>
        {
            if (efficiencyResetting) return;
            try { efficiencyResetting = true; RefreshEfficiencyControls(); await session.ResetEfficiencyAsync(generation); if (!closed) efficiencyNote.Text = "已清除本次連線的效率樣本，角色經驗與等級維持伺服器資料。"; }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { if (!closed) efficiencyNote.Text = error.Message; }
            finally { efficiencyResetting = false; if (!closed) RefreshEfficiencyControls(); }
        }, "EfficiencyReset");
        efficiencySubjects.SelectionChanged += (_, _) => RefreshEfficiencyControls(); efficiencyUnit.SelectionChanged += (_, _) => RefreshEfficiencyControls();
        return Page("經驗效率", Ui.Row(Ui.Text("統計對象"), efficiencySubjects, Ui.Text("效率單位"), efficiencyUnit, efficiencyReset),
            Ui.Card("經驗資料", Ui.Column(efficiencyDetail, efficiencyProgress)),
            Table("Efficiency", ["統計範圍", "經驗／單位", "有效樣本", "升級估時", "一轉190估時"], 180), efficiencyNote,
            Ui.Text("只顯示公用核心記錄的本機角色與已確認夥伴，不推算尚未收到的經驗。估時是依樣本計算，並非保證到達時間。", 12, Ui.Muted));
    }
    private void RefreshEfficiencyControls()
    {
        if (key != "efficiency" || efficiencySubjects is null) return;
        var snapshot = session.Snapshot.Efficiency;
        var choices = snapshot.Rows.OrderBy(p => !p.Key.IsPlayer).ThenBy(p => p.Key.Slot)
            .Select(p => new EfficiencyChoice(p.Key, (p.Key.IsPlayer ? "角色 · " : "夥伴 " + p.Key.Slot + " · ") + p.Value.Name)).ToArray();
        string choiceKey = string.Join('|', choices.Select(c => c.Subject + ":" + c.Label));
        if (choiceKey != efficiencyChoicesKey)
        {
            var selected = (efficiencySubjects.SelectedItem as EfficiencyChoice)?.Subject; efficiencyChoicesKey = choiceKey;
            efficiencySubjects.ItemsSource = choices; efficiencySubjects.SelectedItem = choices.FirstOrDefault(c => c.Subject == selected) ?? choices.FirstOrDefault();
        }
        efficiencyReset!.IsEnabled = !efficiencyResetting && session.CanResetEfficiency;
        if (efficiencySubjects.SelectedItem is not EfficiencyChoice choice || !snapshot.Rows.TryGetValue(choice.Subject, out var row))
        { efficiencyDetail!.Text = "等待登入角色與經驗資料"; efficiencyProgress!.Value = 0; tables["Efficiency"].SetRows([]); return; }
        var progress = EfficiencyRules.Progress(row.LastTotal, row.Level, row.Degree);
        efficiencyProgress!.Value = progress.Percent ?? 0;
        efficiencyDetail!.Text = $"{choice.Label}｜Lv.{row.Level?.ToString() ?? "待同步"}{(row.LevelInferred ? "（推估）" : "")}｜階段 {row.Degree?.ToString() ?? "待同步"}\n" +
            $"經驗 {row.Experience?.ToString("N0", CultureInfo.InvariantCulture) ?? "待同步"}｜升級尚需 {progress.Remaining?.ToString("N0", CultureInfo.InvariantCulture) ?? "未知"}｜本次累積 {row.Earned:N0}";
        var rates = EfficiencyRules.Rates(row); double factor = efficiencyUnit?.SelectedIndex switch { 0 => 1440, 1 => 60, _ => 1 };
        string unit = efficiencyUnit?.SelectedItem?.ToString() ?? "分";
        tables["Efficiency"].SetRows(new[] { ("全部", rates.All), ("最近10場", rates.Last10), ("最近30場", rates.Last30) }.Select(item =>
            (item.Item1, new[] { item.Item1, item.Item2.ExperiencePerMinute is { } rate ? (rate * factor).ToString("N1", CultureInfo.InvariantCulture) + "／" + unit : "等待效率樣本", item.Item2.Count.ToString(),
                EfficiencyRules.Forecast(progress.Remaining, item.Item2.ExperiencePerMinute), EfficiencyRules.Forecast(progress.FirstRebirth190Remaining, item.Item2.ExperiencePerMinute) })));
    }
}
