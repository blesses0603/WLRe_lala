using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Button = Avalonia.Controls.Button;
using ProgressBar = Avalonia.Controls.ProgressBar;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private readonly DispatcherTimer workshopTimer = new() { Interval = TimeSpan.FromMilliseconds(500) };
    private Action? updateWorkshop;
    private static readonly string[] RecipeNames = ["風靈長劍", "秘銀護甲", "高級治療藥水", "爆裂彈", "海鮮燉湯"];
    private void TickWorkshop()
    {
        if (state.AlchemyRunning)
        {
            state.AlchemyProgress = Math.Min(100, state.AlchemyProgress + 4);
            if (state.AlchemyProgress == 100) { state.AlchemyRunning = false; AddEvent("煉金示範完成，未消耗材料"); }
        }
        if (state.CraftRunning)
        {
            var job = state.CraftQueue.FirstOrDefault(x => x.Progress < 100);
            if (job is null) state.CraftRunning = false;
            else
            {
                job.Progress = Math.Min(100, job.Progress + 6);
                if (job.Progress == 100)
                {
                    AddEvent("製作示範完成：" + RecipeNames[job.Recipe]);
                    if (!state.CraftContinue) state.CraftRunning = false;
                    else if (state.CraftQueue.All(x => x.Progress == 100))
                    {
                        if (state.CraftLoop) foreach (var entry in state.CraftQueue) entry.Progress = 0;
                        else state.CraftRunning = false;
                    }
                }
            }
        }
        updateWorkshop?.Invoke();
        if (!state.AlchemyRunning && !state.CraftRunning) workshopTimer.Stop();
    }
    private Control WorkshopPage()
    {
        var materialSlots = new ContentControl(); var count = new ContentControl();
        var alchemyProgress = new ProgressBar { Maximum = 100, Value = state.AlchemyProgress, Height = 5, Foreground = Accent };
        var alchemyStatus = Label("", 10, Muted);
        void RefreshCount() => count.Content = Stepper(() => state.AlchemyCount, value => state.AlchemyCount = value, 1, 999, "煉金次數");
        void RefreshMaterials()
        {
            string[] names = ["魔晶碎片", "風之草", "純淨水", "金屬粉末", "星砂"];
            int[] art = [14, 12, 21, 10, 1]; int[] quantities = [30, 20, 10, 15, 5];
            var slots = new List<Control>();
            for (int i = 0; i < 5; i++)
            {
                int id = i;
                var body = state.AlchemyMaterials[i] ? Column(3, new AtlasIcon(Asset("item-atlas.png"), art[i]) { Width = 31, Height = 31, HorizontalAlignment = HorizontalAlignment.Center },
                    Label(names[i], 8, Ink, center: true), Label("×" + quantities[i], 9, Muted, center: true),
                    IconButton("minus", "移除煉金材料 " + names[i], () => { state.AlchemyMaterials[id] = false; RefreshMaterials(); }, 20)) : Column(5, Label("空槽", 9, Muted, center: true),
                        IconButton("plus", "填入煉金材料 " + names[i], () => { state.AlchemyMaterials[id] = true; RefreshMaterials(); }, 25));
                slots.Add(Surface(body, new(3, 5), 7, false));
            }
            materialSlots.Content = EqualRow(4, slots.ToArray());
        }
        RefreshMaterials(); RefreshCount();
        var alchemyModes = EqualRow(5, ActionButton("標準煉金", "flask", () => { state.AlchemyMode = 0; ShowPage(10); }, state.AlchemyMode == 0, true),
            ActionButton("批量煉金", "layers", () => { state.AlchemyMode = 1; ShowPage(10); }, state.AlchemyMode == 1, true),
            ActionButton("指定產物", "target", () => { state.AlchemyMode = 2; ShowPage(10); }, state.AlchemyMode == 2, true));
        var quickCount = EqualRow(5);
        foreach (int amount in new[] { 10, 50, 100, 999 })
            quickCount.Children.Add(ActionButton(amount == 999 ? "最大" : "×" + amount, "plus", () => { state.AlchemyCount = amount; RefreshCount(); }, compact: true));
        // EqualRow is constructed after collecting children so every shortcut gets a column.
        var shortcuts = quickCount.Children.ToArray(); quickCount.Children.Clear(); var counts = EqualRow(5, shortcuts);
        var alchemy = Card("煉金（Alchemy）", "flask", Label("調和材料，預覽隨機或指定產物。", 10, Muted), alchemyModes,
            Sides(Label("執行次數", 11), count, "65,*"), counts,
            Sides(Label("煉金材料（範例）", 11), ActionButton("一鍵填入", "plus", () => { Array.Fill(state.AlchemyMaterials, true); RefreshMaterials(); }, compact: true)), materialSlots,
            state.AlchemyMode == 2 ? Combo("指定產物：魔能結晶", "指定產物：治療藥水", "指定產物：風靈素材") : Label("預估產物：隨機（含稀有） · 示範機率 5 種 / 80 件", 9, Muted),
            alchemyStatus, alchemyProgress,
            EqualRow(6, ActionButton("預覽消耗", "search", () => Toast($"示範估算：{state.AlchemyCount} 次，使用 {state.AlchemyMaterials.Count(x => x)} 種範例材料；不會消耗物品。"), compact: true),
                ActionButton("開始連續煉金", "play", () =>
                {
                    if (!state.AlchemyMaterials.Any(x => x)) { Toast("請先填入至少一種範例材料。"); return; }
                    state.AlchemyProgress = 0; state.AlchemyRunning = true; workshopTimer.Start(); updateWorkshop?.Invoke(); AddEvent("開始煉金進度示範");
                }, true, true)),
            EqualRow(6, ActionButton("停止連續煉金", "stop", () => { state.AlchemyRunning = false; updateWorkshop?.Invoke(); }, compact: true),
                ActionButton("清空材料", "trash", () => { Array.Fill(state.AlchemyMaterials, false); RefreshMaterials(); }, compact: true)));

        var recipes = Column(5); var details = new ContentControl();
        var catalogueTabs = new List<Button>();
        var queue = Column(7); var queueProgress = new List<(PreviewCraftJob Job, ProgressBar Bar, TextBlock Status)>();
        var query = Input("搜尋配方（名稱 / 關鍵字）"); query.Text = state.RecipeQuery;
        var filter = Combo("全部類型", "武器", "防具", "消耗品");
        string Category(int id) => id == 0 ? "武器" : id == 1 ? "防具" : "消耗品";
        void BuildDetails()
        {
            int id = state.Recipe;
            details.Content = Surface(Column(7, Row(5, new NeonIcon("file", Accent, 17), Label("配方詳情", 12, Ink, true)),
                RecipeArt(id, 43), Label(RecipeNames[id], 13, Ink, true), Label(Category(id) + " · Lv." + (id == 0 || id == 1 ? 30 : 20), 9, Muted),
                ActionButton(state.FavoriteRecipes.Contains(id) ? "已收藏" : "收藏配方", "star", () => { if (!state.FavoriteRecipes.Add(id)) state.FavoriteRecipes.Remove(id); BuildRecipes(); BuildDetails(); }, state.FavoriteRecipes.Contains(id), true),
                Divider(), Label("所需材料（範例）", 11, Ink, true), Label("精煉鐵錠    12 / 12  ✓\n風之結晶      3 / 3  ✓\n優質木材      6 / 6  ✓\n魔法線        2 / 2  ✓", 9, Green),
                Label("製作時間  00:05:00\n熟練度  +180（範例）", 9, Muted),
                Stepper(() => state.CraftQuantity, value => state.CraftQuantity = value, 1, 999, "製作數量"),
                ActionButton("加入製作佇列", "plus", () =>
                {
                    if (state.CraftQueue.Count >= 20) { Toast("範例佇列最多保留 20 筆。"); return; }
                    state.CraftQueue.Add(new(state.Recipe, state.CraftQuantity)); BuildQueue(); Toast("已加入本機預覽佇列；按播放示範查看進度。");
                }, true, true)), new(8), 10, false);
        }
        void BuildRecipes()
        {
            recipes.Children.Clear(); state.RecipeQuery = query.Text ?? "";
            foreach (int id in Enumerable.Range(0, 5).Where(i => RecipeNames[i].Contains(state.RecipeQuery, StringComparison.OrdinalIgnoreCase) && (!state.FavoritesOnly || state.FavoriteRecipes.Contains(i)) && (filter.SelectedIndex == 0 || Category(i) == filter.SelectedItem?.ToString())))
            {
                var button = new Button { Content = Sides(RecipeArt(id, 27), Column(3, Label(RecipeNames[id], 11, Ink, true), Label(Category(id) + " · Lv.30", 8, Muted)), "29,*", 5),
                    Padding = new(6), CornerRadius = new(8), BorderThickness = new(.8), BorderBrush = id == state.Recipe ? Accent : Brush.Parse("#4C718B"),
                    Background = id == state.Recipe ? Gradient("#126075", "#0C354C") : Gradient("#17374F", "#0B2238"), HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
                Avalonia.Automation.AutomationProperties.SetName(button, "選擇配方 " + RecipeNames[id]); button.Click += (_, _) => { state.Recipe = id; BuildRecipes(); BuildDetails(); }; recipes.Children.Add(button);
            }
            if (recipes.Children.Count == 0) recipes.Children.Add(Label("找不到符合的配方。", 10, Muted));
        }
        query.TextChanged += (_, _) => BuildRecipes(); filter.SelectionChanged += (_, _) => BuildRecipes();
        void BuildQueue()
        {
            queue.Children.Clear(); queueProgress.Clear();
            foreach (var job in state.CraftQueue)
            {
                var bar = new ProgressBar { Maximum = 100, Value = job.Progress, Height = 5, Foreground = Accent };
                var status = Label("", 9, Muted); queueProgress.Add((job, bar, status));
                void Move(int delta) { int oldIndex = state.CraftQueue.IndexOf(job), newIndex = oldIndex + delta; if (newIndex < 0 || newIndex >= state.CraftQueue.Count) return; state.CraftQueue.RemoveAt(oldIndex); state.CraftQueue.Insert(newIndex, job); BuildQueue(); }
                var actions = Row(4, IconButton("up", "上移製作 " + RecipeNames[job.Recipe], () => Move(-1), 27), IconButton("down", "下移製作 " + RecipeNames[job.Recipe], () => Move(1), 27),
                    IconButton("trash", "刪除製作 " + RecipeNames[job.Recipe], () => { state.CraftQueue.Remove(job); BuildQueue(); }, 27));
                queue.Children.Add(Surface(Column(5, Sides(Row(5, RecipeArt(job.Recipe, 21), Label(RecipeNames[job.Recipe] + " ×" + job.Quantity, 11, Ink, true)), status), Sides(bar, actions, "*,91", 9)), new(7), 8, false));
            }
            if (state.CraftQueue.Count == 0) queue.Children.Add(Label("佇列為空，選擇配方後加入。", 11, Muted));
            updateWorkshop?.Invoke();
        }
        updateWorkshop = () =>
        {
            alchemyStatus.Text = state.AlchemyRunning ? $"煉金進度示範 {state.AlchemyProgress}%" : state.AlchemyProgress == 100 ? "煉金示範完成，未消耗材料。" : "煉金尚未播放 · 僅預覽";
            alchemyProgress.Value = state.AlchemyProgress;
            var active = state.CraftRunning ? state.CraftQueue.FirstOrDefault(x => x.Progress < 100) : null;
            foreach (var entry in queueProgress) { entry.Bar.Value = entry.Job.Progress; entry.Status.Text = entry.Job.Progress == 100 ? "示範完成" : entry.Job == active ? $"示範製作中 {entry.Job.Progress}%" : $"等待示範 {entry.Job.Progress}%"; }
        };
        BuildRecipes(); BuildDetails(); BuildQueue(); updateWorkshop();
        if (state.AlchemyRunning || state.CraftRunning) workshopTimer.Start();
        void ChooseCatalogue(bool favorites)
        {
            state.FavoritesOnly = favorites; BuildRecipes();
            for (int i = 0; i < catalogueTabs.Count; i++) SelectButton(catalogueTabs[i], favorites ? i == 1 : i == 0);
        }
        catalogueTabs.AddRange([ActionButton("配方目錄", "file", () => ChooseCatalogue(false), !state.FavoritesOnly, true), ActionButton("我的收藏", "star", () => ChooseCatalogue(true), state.FavoritesOnly, true)]);
        return Page(FeatureMenu(), alchemy, Card("製作（Crafting）", "hammer", Label("配方與材料皆為範例，未接入正式製作。", 10, Muted),
                EqualRow(6, catalogueTabs.ToArray()),
                Sides(Column(6, query, filter, recipes), details, "1*,1.1*", 8)),
            Card("製作佇列", "layers", Sides(Label("佇列完成後繼續製作", 10), Switch(state.CraftContinue, value => state.CraftContinue = value)),
                Sides(Label("循環佇列（範例）", 10), Switch(state.CraftLoop, value => state.CraftLoop = value)), queue,
                ActionButton("播放 / 暫停製作示範", "play", () =>
                {
                    if (state.CraftQueue.Count == 0) { Toast("請先加入範例配方。"); return; }
                    state.CraftRunning = !state.CraftRunning;
                    if (state.CraftRunning && state.CraftQueue.All(x => x.Progress == 100)) foreach (var job in state.CraftQueue) job.Progress = 0;
                    if (state.CraftRunning) workshopTimer.Start(); updateWorkshop?.Invoke();
                }, true)), Label("煉金與製作為進度示範，切頁或退到背景會暫停，不會消耗物品。", 9, Muted));
    }
    private static Control RecipeArt(int id, double size) => id is 0 or 1 ? Surface(new NeonIcon(id == 0 ? "sword" : "shield", Accent, size - 8), new(4), 7, false)
        : new AtlasIcon(Asset("item-atlas.png"), id == 2 ? 0 : id == 3 ? 4 : 16) { Width = size, Height = size };
}
