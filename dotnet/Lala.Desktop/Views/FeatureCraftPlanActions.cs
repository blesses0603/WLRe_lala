using System.Collections.Immutable;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

public sealed partial class PythonFeatureWindow
{
    private sealed record PlanDraftRow(Guid Key, CraftPlanEntry Entry);
    private sealed record PlanRecipe(ushort Id, string Label) { public override string ToString() => Label; }
    private readonly List<PlanDraftRow> planRows = [];
    private readonly List<Control> planEditors = [];
    private ComboBox? planRecipes;
    private NumericUpDown? planBatches;
    private TextBox? planSearch;
    private Button? planStart, planRestart, planStop;
    private TextBlock? planStatus;
    private bool planBusy;
    private string planRecipeKey = "";

    private Control CraftPlanControls()
    {
        planRows.Clear(); planEditors.Clear(); planBusy = false; planRecipeKey = "";
        planRecipes = Ui.Combo([], -1); planRecipes.Name = "CraftPlanRecipe"; planRecipes.Width = 260;
        planSearch = Edit("搜尋配方名稱／ID"); planSearch.Name = "CraftPlanSearch"; planSearch.Width = 180; planSearch.TextChanged += (_, _) => RefreshCraftPlanControls();
        planBatches = Ui.Number(1, 1, 255); planBatches.Name = "CraftPlanBatches";
        planStatus = Ui.Text("儲存只保存清單草稿；開始後才會使用材料。", 12, Ui.Muted);
        var table = Table("CraftPlan", ["順序", "製作物", "批數", "總產量"], 230);
        void Load()
        {
            var saved = session.Preferences.ReadCraftPlan(session.IdentityKey);
            planRows.Clear(); planRows.AddRange(saved.Entries.Select(e => new PlanDraftRow(Guid.NewGuid(), e)));
        }
        try { Load(); }
        catch (Exception error) when (SettingsFiles.IsExpected(error)) { planStatus.Text = "製作清單無法讀取，尚未覆寫。"; }
        int SelectedPlan()
        {
            int index = planRows.FindIndex(x => x.Key.ToString("N") == table.SelectedKey);
            return index >= 0 ? index : throw new InvalidOperationException("請先選擇清單項目。");
        }
        Button EditButton(string label, Action edit, string id)
        {
            var button = Ui.Button(label, () =>
            {
                try { session.RequireCurrentDraft(generation); edit(); RefreshCraftPlanControls(); }
                catch (Exception error) when (SettingsFiles.IsExpected(error)) { planStatus.Text = error.Message; }
            }, id); planEditors.Add(button); return button;
        }
        void Add()
        {
            if (planRows.Count >= 512) throw new InvalidOperationException("製作清單最多 512 項。");
            if (planRecipes.SelectedItem is not PlanRecipe recipe) throw new InvalidOperationException("請選擇已同步的官方配方。");
            planRows.Add(new(Guid.NewGuid(), new(recipe.Id, checked((int)(planBatches.Value ?? 1)))));
        }
        void Move(int delta)
        {
            int index = SelectedPlan(), target = index + delta; if (target < 0 || target >= planRows.Count) return;
            var row = planRows[index]; planRows.RemoveAt(index); planRows.Insert(target, row);
        }
        void Save()
        {
            var saved = new CraftPlanPreferences { Entries = planRows.Select(x => x.Entry).ToArray() };
            saved.Validate(); session.SaveCraftPlan(generation, session.IdentityKey, saved); planStatus.Text = "清單草稿已儲存，未啟動製作。";
        }
        planStart = Ui.Button("開始／繼續清單", async () => await RunPlan(false), "CraftPlanStart");
        planRestart = Ui.Button("重新執行整份清單", async () => await RunPlan(true), "CraftPlanRestart");
        async Task RunPlan(bool restart)
        {
            if (planBusy) return; long expectedGeneration = generation;
            try
            {
                if (planRows.Count == 0) throw new InvalidOperationException("清單不可為空。");
                planBusy = true; RefreshCraftPlanControls(); Save();
                var entries = planRows.Select(row => new GameCraftPlanEntry(row.Entry.ItemId, row.Entry.Batches)).ToImmutableArray();
                await session.SetAutomationAsync("craft", true, GameplayPreferences.Read(session) with { CraftPlan = entries, RestartCraftPlan = restart });
                if (!closed && generation == expectedGeneration) planStatus.Text = "清單已交由核心執行，每次加入均等待伺服器與材料扣除確認。";
            }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException)
            { if (!closed) planStatus.Text = error.Message; }
            finally { planBusy = false; if (!closed) RefreshCraftPlanControls(); }
        }
        planStop = Ui.Button("暫停清單接續", async () =>
        {
            if (planBusy) return;
            try { planBusy = true; RefreshCraftPlanControls(); await session.SetAutomationAsync("craft", false); if (!closed) planStatus.Text = "已暫停後續接續，已送出的製作不會撤回。"; }
            catch (Exception error) when (SettingsFiles.IsExpected(error) || error is Lala.Core.Protocol.ProtocolException) { if (!closed) planStatus.Text = error.Message; }
            finally { planBusy = false; if (!closed) RefreshCraftPlanControls(); }
        }, "CraftPlanStop");
        planEditors.AddRange([planRecipes, planSearch, planBatches]);
        return Page("自訂製作清單", Ui.Row(planSearch, planRecipes, Ui.Text("批數"), planBatches, EditButton("加入配方", Add, "CraftPlanAdd")), table,
            Ui.Row(EditButton("上移", () => Move(-1), "CraftPlanUp"), EditButton("下移", () => Move(1), "CraftPlanDown"),
                EditButton("移除", () => planRows.RemoveAt(SelectedPlan()), "CraftPlanDelete"), EditButton("清空", planRows.Clear, "CraftPlanClear"),
                EditButton("更新批數", () => { int i = SelectedPlan(); planRows[i] = planRows[i] with { Entry = planRows[i].Entry with { Batches = checked((int)(planBatches.Value ?? 1)) } }; }, "CraftPlanUpdate"),
                EditButton("儲存", Save, "CraftPlanSave"), EditButton("載入", Load, "CraftPlanLoad")),
            Ui.Row(planStart, planStop, planRestart), planStatus,
            Ui.Text("同次連線暫停後可繼續；重新登入只載入草稿，不會自動恢復或推算已完成項目。重新執行會再次使用材料。", 12, Ui.Muted));
    }
    private void RefreshCraftPlanControls()
    {
        if (key != "crafting-plan" || planRecipes is null) return;
        var labels = session.ReadView().Labels; string query = planSearch?.Text?.Trim() ?? "";
        var recipes = session.Catalogs?.Recipes.Products.Values.OrderBy(r => r.Recipe.Order)
            .Where(r => query.Length == 0 || r.Recipe.ItemId.ToString().Contains(query, StringComparison.Ordinal) || labels.Item(r.Recipe.ItemId).Contains(query, StringComparison.OrdinalIgnoreCase))
            .Select(r => new PlanRecipe(r.Recipe.ItemId, labels.Item(r.Recipe.ItemId) + " · " + r.Recipe.ItemId)).ToArray() ?? [];
        string identity = string.Join('|', recipes.Select(r => r.Id + ":" + r.Label));
        if (identity != planRecipeKey)
        {
            var selected = (planRecipes.SelectedItem as PlanRecipe)?.Id; planRecipeKey = identity;
            planRecipes.ItemsSource = recipes; planRecipes.SelectedItem = recipes.FirstOrDefault(r => r.Id == selected);
        }
        if (tables.TryGetValue("CraftPlan", out var table)) table.SetRows(planRows.Select((row, i) =>
        {
            var recipe = session.Catalogs?.Recipes.Products.GetValueOrDefault(row.Entry.ItemId)?.Recipe;
            return (row.Key.ToString("N"), new[] { (i + 1).ToString(), labels.Item(row.Entry.ItemId), row.Entry.Batches.ToString(),
                recipe is null ? "配方待核對" : ((long)recipe.Output * row.Entry.Batches).ToString() });
        }));
        bool running = session.Automations.GetValueOrDefault("craft")?.Enabled == true;
        foreach (var control in planEditors) control.IsEnabled = !planBusy && !running;
        planStart!.IsEnabled = planRestart!.IsEnabled = !planBusy && !running && session.CanSendGameCommands && planRows.Count > 0;
        planStop!.IsEnabled = !planBusy && running;
        if (running && !planBusy) planStatus!.Text = session.Automations["craft"].Message;
    }
}
