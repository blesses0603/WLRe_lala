using System.Collections.Immutable;
using Avalonia;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

internal sealed class SettingsSupplySlotWindow : DesktopWindow
{
    private sealed record Choice(ushort Id, string Label) { public override string ToString() => Label; }
    internal SettingsSupplySlotWindow(string title, ImmutableArray<FieldRecoveryItem> items, DesktopLabels labels) : base("選擇" + title, 680, 480)
    {
        var search = new TextBox { PlaceholderText = "搜尋名稱或物品 ID", Name = "SupplyItemSearch" };
        var list = new ListBox { Name = "SupplyItemChoices", Background = Ui.Panel, Padding = new Thickness(4) };
        var choices = items.Select(i => new Choice(i.ItemId, $"{labels.Item(i.ItemId)} · {i.ItemId}　×{i.Count}　HP +{i.Hp}／SP +{i.Sp}")).ToArray();
        var select = Ui.Button("選擇此物品", () => { if (list.SelectedItem is Choice c) Close((ushort?)c.Id); }, "SupplyItemChoose"); select.IsEnabled = false;
        list.SelectionChanged += (_, _) => select.IsEnabled = list.SelectedItem is Choice;
        void Filter() { list.ItemsSource = choices.Where(c => c.Label.Contains(search.Text?.Trim() ?? "", StringComparison.OrdinalIgnoreCase)).ToArray(); }
        search.TextChanged += (_, _) => Filter(); Filter();
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*,Auto,Auto"), RowSpacing = 10 };
        Ui.At(body, Ui.Text("選擇" + title, 22, bold: true), 0);
        Ui.At(body, search, 0, 1); Ui.At(body, list, 0, 2);
        Ui.At(body, Ui.Text(choices.Length == 0 ? "目前背包沒有可用且已核對效果的補品。" : "只設定優先物品，不會在此使用或扣除。鎖定、限時或保留中的物品不列入。", 12, Ui.Muted), 0, 3);
        Ui.At(body, Ui.Row(select, Ui.Button("清除此格", () => Close((ushort?)0), "SupplyItemClear"), Ui.Button("取消", () => Close(null), "SupplyItemCancel")), 0, 4);
        SetBody(body);
    }
}
