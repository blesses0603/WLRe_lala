using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private static readonly (string Icon, string Name, string Description)[] Checks =
    [
        ("cube", "官方版本", "確認應用程式與官方版本相符"), ("db", "DataPackage", "檢查資料包完整性與版本"),
        ("layers", "MainPackage", "檢查主程式包完整性與版本"), ("file", "Manifest", "驗證雙 Manifest 檔案"),
        ("cube", "Bundle", "檢查必要資源 Bundle 完整性"), ("gear", "Runtime", "檢查 Runtime 環境完整性"),
        ("db", "SQLite", "驗證資料庫結構與完整性")
    ];
    private Control ResourcePage()
    {
        var rows = Column(5);
        for (int i = 0; i < Checks.Length; i++)
        {
            var (icon, name, description) = Checks[i];
            var status = Label("示範通過", 10, Green); resourceStatuses.Add(status);
            var row = Sides(Row(7, new NeonIcon(icon, Accent, 19), Column(3, Label(name, 12, Ink, true), Label(description, 9, Muted))),
                Row(4, new NeonIcon("check", Green, 13), status));
            rows.Children.Add(Sides(new CheckStepArtwork(i == 0, i == Checks.Length - 1),
                Surface(row, new(8, 7), 9, false), "17,*", 6));
        }
        resourceProgress = new ProgressBar { Minimum = 0, Maximum = 100, Value = state.Progress, Height = 5, Foreground = Accent };
        resourceSummary = Label("所有項目驗證通過（示範畫面）", 12, Green, true);
        resourceTimestamp = Label("檢查時間：" + state.ResourceCheckedAt, 9, Muted);
        RefreshResourceProgress();
        return Page(Card("官方資料與資料庫檢查", "layers",
                Label("首次啟動檢查官方版本、雙 Manifest、必要 Bundle、完整 Runtime 與 SQLite 資料庫。此頁先展示檢查流程與結果樣式。", 11, Muted), rows),
            Card("版本資訊", "info", EqualRow(7, Surface(Column(5, Row(5, new NeonIcon("cube", Accent, 15), Label("DataPackage", 10)), Label("1286", 18, Ink, true)), new(9), 9, false),
                Surface(Column(5, Row(5, new NeonIcon("layers", Accent, 15), Label("MainPackage", 10)), Label("1284", 18, Ink, true)), new(9), 9, false)),
                Label("範例版本 · 資料來源：介面示範 · 未查詢官方伺服器", 9, Muted)),
            Card("最近檢查結果", "chart", resourceSummary, resourceProgress,
                Label("✓  版本與資源完整性：通過樣式預覽\n✓  Manifest · Bundle · Runtime · SQLite：示範有效\n○  正式驗證：尚未執行", 10, Muted),
                resourceTimestamp),
            ActionButton("重新檢查官方資料", "refresh", () => { state.Progress = 0; RefreshResourceProgress(); progressTimer.Start(); }, true),
            ActionButton("啟動 / 重新連接背景服務", "play", ServiceNotice),
            Row(6, new NeonIcon("info", Muted, 15), Label("預覽不會略過正式驗證，也不會啟動遊戲連線。", 10, Muted)));
    }
    private void RefreshResourceProgress()
    {
        if (resourceProgress is not null) resourceProgress.Value = state.Progress;
        if (resourceSummary is not null) resourceSummary.Text = state.Progress == 100 ? "所有項目驗證通過（示範畫面）" : $"正在播放檢查示範 · {state.Progress}%";
        for (int i = 0; i < resourceStatuses.Count; i++)
        {
            bool passed = state.Progress >= (i + 1) * 100.0 / Checks.Length;
            resourceStatuses[i].Text = passed ? "示範通過" : "等待示範";
            resourceStatuses[i].Foreground = passed ? Green : Muted;
        }
    }
}
