using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Button = Avalonia.Controls.Button;

namespace Lala.Android.Preview;

internal sealed partial class MobilePreviewView
{
    private static readonly string[] ItemNames = ["特級治療藥水", "星耀結晶", "時空鑰匙", "傳送卷軸", "靈魂精髓", "中級治療藥水", "中級魔力藥水", "營火套組", "復活羽毛", "淨化結晶", "精煉鐵礦", "堅韌木材", "療癒香草", "星露蘑菇", "魔能碎片", "熟成獸皮", "紅蘋果", "香脆麵包", "基礎飼料", "採集鎬", "簡易釣竿", "清水瓶", "麻繩", "簡易火把"];
    private static readonly int[] ItemQuantities = [35, 12, 3, 8, 6, 48, 27, 18, 14, 22, 99, 99, 77, 66, 54, 33, 120, 87, 63, 41, 28, 50, 38, 25];
    private static string Rarity(int index) => index < 2 ? "UR" : index < 5 ? "SSR" : index < 10 ? "SR" : index < 16 ? "R" : "N";
    private static IBrush RarityColor(int index) => Brush.Parse(index < 2 ? "#F6D36D" : index < 5 ? "#CE93EF" : index < 10 ? "#70BEEB" : "#77AABD");
    private static string ItemType(int index) => index is 0 or 3 or 5 or 6 or 8 or 16 or 17 or 18 or 21 ? "消耗品" : index is 7 or 19 or 20 or 23 ? "工具" : "素材";

    private Control InventoryPage()
    {
        var search = Input("搜尋道具名稱、關鍵字..."); search.Text = state.ItemQuery;
        var rarity = Combo("全部稀有度", "UR", "SSR", "SR", "R", "N");
        var type = Combo("全部類型", "消耗品", "素材", "工具");
        var sorting = Combo("取得時間（新→舊）", "名稱排序");
        var tiles = new Grid { ColumnDefinitions = new("*,*,*,*"), ColumnSpacing = 4, RowSpacing = 5 };
        var detail = new ContentControl();
        var count = Label("道具清單（24 / 240）", 12, Ink, true);
        var tileButtons = new Dictionary<int, Button>();
        void ChooseItem(int index)
        {
            state.SelectedItem = index; detail.Content = ItemDetail(index);
            foreach (var (id, button) in tileButtons) button.BorderBrush = id == index ? Gold : RarityColor(id);
        }
        void FilterItems()
        {
            state.ItemQuery = search.Text ?? "";
            var visible = Enumerable.Range(0, ItemNames.Length).Where(i =>
                ItemNames[i].Contains(state.ItemQuery, StringComparison.OrdinalIgnoreCase) &&
                (rarity.SelectedIndex == 0 || Rarity(i) == rarity.SelectedItem?.ToString()) &&
                (type.SelectedIndex == 0 || ItemType(i) == type.SelectedItem?.ToString()));
            if (sorting.SelectedIndex == 1) visible = visible.OrderBy(i => ItemNames[i], StringComparer.Ordinal);
            var ids = visible.ToArray(); tiles.Children.Clear(); tiles.RowDefinitions.Clear(); tileButtons.Clear();
            for (int row = 0; row < (ids.Length + 3) / 4; row++) tiles.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            for (int position = 0; position < ids.Length; position++)
            {
                int index = ids[position];
                var art = new AtlasIcon(Asset("item-atlas.png"), index) { Height = 38, Width = 38, HorizontalAlignment = HorizontalAlignment.Center };
                var button = new Button
                {
                    Content = Column(1, Sides(Label(Rarity(index), 8, RarityColor(index), true), Label("×" + ItemQuantities[index], 8)), art, Label(ItemNames[index], 8, Ink, center: true)),
                    Padding = new(2, 3), CornerRadius = new(8), BorderThickness = new(1), Background = Brush.Parse("#081B2F"),
                    BorderBrush = index == state.SelectedItem ? Gold : RarityColor(index), HorizontalAlignment = HorizontalAlignment.Stretch,
                    HorizontalContentAlignment = HorizontalAlignment.Stretch
                };
                AutomationProperties.SetName(button, "選取道具 " + ItemNames[index]);
                button.Click += (_, _) => ChooseItem(index);
                Grid.SetColumn(button, position % 4); Grid.SetRow(button, position / 4); tiles.Children.Add(button); tileButtons[index] = button;
            }
            if (ids.Length == 0)
            {
                tiles.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
                var empty = Label("找不到符合的道具", 11, Muted); Grid.SetColumnSpan(empty, 4); tiles.Children.Add(empty);
            }
            count.Text = $"道具清單（{ids.Length} / 240）";
        }
        search.TextChanged += (_, _) => FilterItems(); rarity.SelectionChanged += (_, _) => FilterItems();
        type.SelectionChanged += (_, _) => FilterItems(); sorting.SelectionChanged += (_, _) => FilterItems();
        FilterItems(); ChooseItem(state.SelectedItem);
        var categories = EqualRow(5, ActionButton("包包", "bag", () => { state.BagTab = 0; ShowPage(1); }, state.BagTab == 0, true),
            ActionButton("超空間袋", "cube", () => { state.BagTab = 1; ShowPage(1); }, state.BagTab == 1, true),
            ActionButton("特技", "star", () => { state.BagTab = 2; ShowPage(1); }, state.BagTab == 2, true));
        var body = state.BagTab == 2 ? SkillList() : Sides(tiles, Column(10, detail, SkillList()), "3*,2*", 8);
        return Page(Card("包包與特技", "bag", Label("管理道具、超空間袋與角色特技（範例）", 10, Muted), categories,
                Sides(search, Combo(state.BagTab == 1 ? "超空間袋" : "包包（主）"), "3*,2*", 8), EqualRow(6, type, rarity, sorting)),
            Sides(Row(5, new NeonIcon("grid", Accent, 17), count), Label("容量 24 / 240", 9, Muted)), body,
            Surface(EqualRow(6, Row(5, new NeonIcon("layers", Accent, 17), Label("包包總覽", 10, Ink, true)), Label("道具：24", 10), Label("超空間袋：180", 10), Label("特技：3 / 100", 10)), new(9)),
            Label("道具與特技均為設計範例；使用、存入不會操作真實背包。", 9, Muted));
    }
    private Control ItemDetail(int index)
    {
        string effect = index is 0 or 5 ? "回復 HP 6,000（即時）" : index == 6 ? "回復 SP 1,200（即時）" : "點選查看道具範例效果";
        return Surface(Column(8, new AtlasIcon(Asset("item-atlas.png"), index) { Width = 58, Height = 58, HorizontalAlignment = HorizontalAlignment.Center },
            Label(ItemNames[index], 13, Ink, true), Label(Rarity(index) + " · " + ItemType(index), 9, RarityColor(index)),
            Surface(Sides(Label("持有數量", 9, Muted), Label("×" + ItemQuantities[index], 11)), new(7), 7, false),
            Label(index == 0 ? "散發溫暖光輝的高級治療藥水，可迅速恢復大量生命力。" : "旅途中收集的冒險道具，可在正式功能接入後查看完整資訊。", 10, Muted),
            Divider(), Row(4, new NeonIcon("heart", Accent, 14), Label("使用效果", 11, Ink, true)),
            Label(effect, 10, Green), Label("冷卻時間 2 秒（範例）", 9, Muted),
            ActionButton("使用", "play", () => { AddEvent("預覽道具：" + ItemNames[index]); Toast("這是使用效果預覽，未消耗任何道具。"); }, true, true),
            ActionButton("存入", "bag", () => Toast("存入功能尚未接入，真實背包不受影響。"), compact: true),
            ActionButton("查看詳情", "file", () => Toast(ItemNames[index] + " · " + Rarity(index) + " · " + ItemType(index) + "（設計範例）"), compact: true)), new(8), 12);
    }
    private Control SkillList()
    {
        var skills = Column(7, Row(5, new NeonIcon("star", Accent, 18), Label("特技一覽（3）", 12, Ink, true)));
        var definitions = new[] { ("迅影斬", "sword", "#41C7FF", "SP 12 · Lv. 5"), ("治癒術", "plus", "#6AF6A6", "SP 18 · Lv. 4"), ("守護結界", "shield", "#67A9FF", "SP 24 · Lv. 3") };
        foreach (var (name, icon, color, cost) in definitions)
        {
            var row = Sides(new NeonIcon(icon, Brush.Parse(color), 25), Column(3, Label(name, 11, Ink, true), Label("● 可用（範例）", 8, Green), Label(cost, 8, Muted)), "29,*", 5);
            var button = new Button { Content = row, Padding = new(6), CornerRadius = new(8), Background = Gradient("#17354B", "#0A2035"), BorderBrush = Brush.Parse("#3E6B88"), BorderThickness = new(.7), HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
            AutomationProperties.SetName(button, "查看特技 " + name); button.Click += (_, _) => Toast(name + "：特技詳情預覽，未施放技能。"); skills.Children.Add(button);
        }
        return Surface(skills, new(8), 12);
    }
}
