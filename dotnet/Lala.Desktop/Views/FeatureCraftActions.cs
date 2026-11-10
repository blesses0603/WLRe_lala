using Avalonia.Controls;
using Lala.Core.Inventory;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private TextBox? craftSearch;
    private NumericUpDown? craftCount;
    private TextBlock? craftDetail, craftProgress;
    private CheckBox? craftAvailable;
    private int craftPage;
    private Control CraftControls()
    {
        craftPage = 0; craftSearch = Edit("名稱／物品 ID"); craftSearch.TextChanged += (_, _) => { craftPage = 0; RefreshCraftControls(); };
        craftCount = Ui.Number(1, 1, 255); craftCount.ValueChanged += (_, _) => RefreshCraftDetails();
        craftAvailable = Check("只列已有設備"); craftAvailable.IsCheckedChanged += (_, _) => { craftPage = 0; RefreshCraftControls(); };
        craftDetail = Ui.Text("請先選擇配方。", color: Ui.Muted);
        var catalog = Table("CraftCatalog", ["製作物", "設備", "時間", "產量"], 285);
        catalog.SelectionChanged += RefreshCraftDetails;
        return Page("製作", Ui.Row(Ui.Button("自訂清單", () => windows.OpenPythonFeature("crafting-plan")),
            GameButton("進入自家帳篷", () => new("tent", "enter")), Ui.Button("製作排程", () => windows.OpenPythonFeature("crafting-queue"))),
            Ui.Row(craftAvailable, Ui.Text("搜尋"), craftSearch), catalog,
            Ui.Row(Ui.Button("上一頁", () => { craftPage = Math.Max(0, craftPage - 1); RefreshCraftControls(); }), Ui.Button("下一頁", () => { craftPage++; RefreshCraftControls(); })),
            craftDetail, Ui.Row(Ui.Text("批數"), craftCount, GameButton("加入排程", () => new("craft", "add", checked((uint)Selected("CraftCatalog")), Count: (int)(craftCount.Value ?? 1)))),
            Table("CraftMaterials", ["材料", "背包", "雜物櫃", "需求"], 115));
    }
    private Control CraftQueueControls()
    {
        craftProgress = Ui.Text("等待伺服器排程。", color: Ui.Muted);
        return Page("製作排程", craftProgress, Table("CraftQueue", ["順序", "製作物", "批數", "剩餘時間"], 230),
            Ui.Row(Ui.Button("開始／接續", async () => await ToggleCraftAsync(true)),
                Ui.Button("暫停", async () => { await ToggleCraftAsync(false); if (session.Snapshot.Crafting.Crafting.Running) await SubmitActionAsync(() => new("craft", "pause")); }),
                Ui.Button("停止接續", async () => await ToggleCraftAsync(false))), Actions("上移", "下移", "移除"));
    }
    private async Task ToggleCraftAsync(bool enabled)
    {
        try { await session.SetAutomationAsync("craft", enabled); }
        catch (Exception error) when (error is Lala.Core.Protocol.ProtocolException or InvalidOperationException) { actionNote.Text = error.Message; }
    }
    private void RefreshCraftControls()
    {
        if (key != "crafting" || !tables.TryGetValue("CraftCatalog", out var table)) return;
        var s = session.Snapshot; var labels = session.ReadView().Labels; string query = craftSearch?.Text?.Trim() ?? "";
        var tools = s.Crafting.Furniture.Items.Values.Where(i => i.Status == 0).Select(i => i.ItemId).ToHashSet();
        var rows = session.Catalogs?.Recipes.Products.Values.Where(row => (craftAvailable?.IsChecked != true || tools.Contains(row.Recipe.ToolId)) &&
            (query.Length == 0 || row.Recipe.ItemId.ToString().Contains(query, StringComparison.Ordinal) || labels.Item(row.Recipe.ItemId).Contains(query, StringComparison.OrdinalIgnoreCase)))
            .OrderBy(row => row.Recipe.Order).ToArray() ?? [];
        craftPage = Math.Min(craftPage, Math.Max(0, (rows.Length - 1) / 40));
        table.SetRows(rows.Skip(craftPage * 40).Take(40).Select(row => (row.Recipe.ItemId.ToString(), new[]
            { labels.Item(row.Recipe.ItemId), labels.Item(row.Recipe.ToolId), row.Recipe.Seconds + " 秒", row.Recipe.Output.ToString() })));
        RefreshCraftDetails();
    }
    private void RefreshCraftDetails()
    {
        if (!tables.TryGetValue("CraftCatalog", out var table) || !ushort.TryParse(table.SelectedKey, out var id) || session.Catalogs?.Recipes.Products.GetValueOrDefault(id) is not {} selected) return;
        var s = session.Snapshot; var labels = session.ReadView().Labels; int count = (int)(craftCount?.Value ?? 1);
        if (craftDetail is not null) craftDetail.Text = $"{labels.Item(id)}｜設備：{labels.Item(selected.Recipe.ToolId)}｜每批產量 {selected.Recipe.Output}｜每批 {selected.Recipe.Seconds} 秒";
        if (tables.TryGetValue("CraftMaterials", out var materials)) materials.SetRows(selected.Recipe.Materials.Select(row =>
            (row.ItemId.ToString(), new[] { labels.Item(row.ItemId), s.Bag.Items.Values.Where(i => i.ItemId == row.ItemId).Sum(i => (long)i.Count).ToString(),
                s.Storage.Storage.Materials.Items.Values.Where(i => i.ItemId == row.ItemId).Aggregate(System.Numerics.BigInteger.Zero, (sum, i) => sum + i.Count).ToString(), ((long)row.Count * count).ToString() })));
    }
}
