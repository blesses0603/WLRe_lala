using Lala.Core.Resources;

namespace Lala.Desktop;

/// <summary>Position in the observed preparation pipeline, not elapsed time or download bytes.</summary>
internal sealed class ResourceStageProgress
{
    private static readonly string[] Stages =
    [
        "檢查寫入前狀態", "查詢官方版本與下載清單", "檢查既有必要資源快取",
        "取得並驗證必要資源（含快取）", "重新核對官方版本與清單", "解碼並驗證必要資料表",
        "取得並驗證可選資料與圖資", "寫入必要資源資料庫", "獨立回讀並驗證必要資源",
        "寫入來源快取", "物品圖快取與回讀驗證", "頭像快取與回讀驗證", "表情快取與回讀驗證",
        "取得並驗證小地圖來源", "寫入小地圖快取", "獨立回讀並驗證小地圖",
        "最終來源與版本重查", "釋放暫存資源並完成檢查", "必要資源驗證完成", "重新核對登入清單"
    ];
    internal double Value { get; private set; }
    internal void Observe(ResourcePreparationProgress progress)
    {
        int stage = Array.IndexOf(Stages, progress.Phase);
        if (stage < 0) return;
        double fraction = progress.Total is > 0 && progress.Completed is {} completed
            ? Math.Clamp((double)completed / progress.Total.Value, 0, 1) : 0;
        Value = Math.Max(Value, 100.0 * (stage + fraction) / Stages.Length);
    }
    // Only the host's final fresh-catalog/resource match can complete this display.
    internal void Complete() => Value = 100;
}
