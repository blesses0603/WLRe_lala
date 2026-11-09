using System.Globalization;
using System.Numerics;
using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Lala.Core.Inventory;

namespace Lala.Desktop;

/// <summary>Independent backpack/storage window, projected only from immutable Core observations.</summary>
public sealed class InventoryWindow : DesktopWindow
{
    private readonly DesktopSession session;
    private readonly TextBox search = new() { Name = "InventorySearch", Width = 260, MaxLength = 128 };
    private readonly TextBlock status = Ui.Text("等待背包同步", 12, Ui.Muted);
    private readonly TextBlock storageStatus = Ui.Text("等待儲藏空間同步", 12, Ui.Muted);
    private readonly InventoryGrid bag = new("背包格位", "InventoryBag", storage: false);
    private readonly InventoryGrid garage = new("儲藏室物品", "InventoryGarage", storage: true);
    private readonly InventoryGrid materials = new("雜物櫃物品", "InventoryMaterials", storage: true);
    private readonly TabControl tabs;
    private long generation;
    private bool closed;
    private bool refreshing;

    public InventoryWindow(DesktopSession session, int initialTab = 0)
        : base("背包", 1040, 700)
    {
        ArgumentNullException.ThrowIfNull(session);
        this.session = session;
        bag.ImageReader = garage.ImageReader = materials.ImageReader = session.ReadItemImage;
        generation = session.ReadView().Generation;

        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,Auto,*"), RowSpacing = 6 };
        Ui.At(body, Ui.Column(Ui.Text("背包", 22, bold: true),
            Ui.Text("搜尋已同步物品，選取後使用下方操作。", color: Ui.Muted)), 0);
        Ui.At(body, Ui.Row(Ui.Text("搜尋名稱／ID"), search,
            Ui.Button("更新顯示", () => Refresh(), "InventoryRefresh")), 0, 1);
        Ui.At(body, status, 0, 2);

        var remote = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*"), RowSpacing = 4 };
        Ui.At(remote, Ui.Row(Ui.Text("超空間袋｜小屋儲藏室", 16, bold: true),
            Ui.Text("伺服器同步存取", 12, Ui.Muted)), 0);
        Ui.At(remote, storageStatus, 0, 1);
        var storageTabs = Ui.Tabs(("儲藏室", garage), ("雜物櫃", materials));
        storageTabs.Name = "InventoryStorageTabs";
        Ui.At(remote, storageTabs, 0, 2);

        tabs = Ui.Tabs(("實際背包", bag), ("超空間袋", remote));
        tabs.Name = "InventoryTabs";
        Ui.At(body, tabs, 0, 3);
        SetBody(body);
        search.TextChanged += (_, _) => { if (!refreshing && !closed) Refresh(resetPages: true); };
        session.Changed += SessionChanged;
        Closed += (_, _) => { closed = true; session.Changed -= SessionChanged; bag.ReleaseImages(); garage.ReleaseImages(); materials.ReleaseImages(); };
        SelectTab(initialTab);
        Refresh();
    }

    public void SelectTab(int index)
    {
        if (index is < 0 or > 1) throw new ArgumentOutOfRangeException(nameof(index));
        tabs.SelectedIndex = index;
    }

    public int SelectedTab => tabs.SelectedIndex;
    public string SearchText { get => search.Text ?? ""; set => search.Text = value; }
    public int VisibleBagItemCount => bag.ItemCount;
    internal int VisibleBagImageCount => bag.ImageCount;
    public int BagPageIndex => bag.PageIndex;
    public ushort? SelectedBagIndex => bag.SelectedIndex;
    public string BagDetailsText => bag.DetailsText;
    public void SelectBagItem(ushort index) => bag.SelectItem(index);
    public void ChangeBagPage(int direction) => bag.ChangePage(direction);

    private void SessionChanged() => Ui.OnUi(() => { if (!closed) Refresh(); });

    private void Refresh(bool resetPages = false)
    {
        if (closed || refreshing) return;
        refreshing = true;
        try
        {
            var view = session.ReadView();
            if (generation != view.Generation)
            {
                generation = view.Generation;
                search.Text = "";
                bag.Reset(); garage.Reset(); materials.Reset();
            }
            if (resetPages) { bag.FirstPage(); garage.FirstPage(); materials.FirstPage(); }
            var snapshot = view.Snapshot;
            var labels = view.Labels;
            var query = (search.Text ?? "").Trim();
            var inventory = snapshot.Bag;
            bag.SetItems(inventory.Items.OrderBy(pair => pair.Key).Select(pair =>
                new InventoryDisplayItem(pair.Key, pair.Value.ItemId, pair.Value.Count,
                    inventory.Reserved.GetValueOrDefault(pair.Key), labels.Item(pair.Value.ItemId),
                    inventory.Ready && inventory.Reliable,
                    pair.Value.OriginalRecord.Locked ? "已鎖定；效果與使用條件待同步。" : "效果與使用條件待同步。")),
                query, inventory.Capacity, inventory.Ready, inventory.Reliable);
            var storage = snapshot.Storage.Storage;
            RenderStorage(garage, storage.Garage, labels, query);
            RenderStorage(materials, storage.Materials, labels, query);
            var storageWarning = storage.Uncertain ? "｜結果未確認，需重新同步" : storage.Pending is not null ? "｜操作等待確認" : "";
            storageStatus.Text = $"{storage.Status}{storageWarning}｜存取功能尚未接通。";

            status.Text = $"背包：{(inventory.Ready ? "已同步" : "等待同步")}｜{(inventory.Reliable ? "數量有效" : "數量待確認")}｜{inventory.Items.Count} 格。" +
                "更新顯示只重繪已收到的資料，不會發送指令。";
        }
        finally { refreshing = false; }
    }

    private static void RenderStorage(InventoryGrid target, StorageBucketSnapshot bucket, DesktopLabels labels, string query) =>
        target.SetItems(bucket.Items.OrderBy(pair => pair.Key).Select(pair =>
            new InventoryDisplayItem(pair.Key, pair.Value.ItemId, pair.Value.Count,
                bucket.Reserved.GetValueOrDefault(pair.Key), labels.Item(pair.Value.ItemId),
                bucket.Ready && bucket.Reliable, "儲藏存取條件待同步；目前僅顯示收到的庫存。")),
            query, bucket.Capacity, bucket.Ready, bucket.Reliable);

}

internal sealed record InventoryDisplayItem(ushort Index, ushort ItemId, BigInteger Count,
    BigInteger Reserved, string Name, bool Reliable, string Note);

/// <summary>
/// Twenty-four presentation cells, not an invented inventory capacity. Empty cells carry
/// no slot identity; selection and quantity always refer to an observed Core record.
/// </summary>
internal sealed class InventoryGrid : UserControl
{
    internal Func<ushort, byte[]?>? ImageReader { get; set; }
    private readonly List<Bitmap> bitmaps = [];
    internal int ImageCount => bitmaps.Count;
    internal void ReleaseImages()
    {
        foreach (var cell in cells) if (cell is not null) cell.Content = null;
        foreach (var bitmap in bitmaps) bitmap.Dispose();
        bitmaps.Clear();
    }
    private const int Columns = 6;
    private const int Rows = 4;
    private const int PageSize = Columns * Rows;
    private readonly Button[] cells = new Button[PageSize];
    private readonly TextBlock summary = Ui.Text("等待背包同步", 12, Ui.Muted);
    private readonly TextBlock pageLabel = Ui.Text("1 / 1");
    private readonly TextBlock title = Ui.Text("物品資訊", 16, bold: true);
    private readonly TextBlock metadata = Ui.Text("請點選道具");
    private readonly TextBlock note = Ui.Text("", 12, Ui.Muted);
    private readonly TextBlock empty = Ui.Text("等待背包同步", 14, Ui.Muted);
    private readonly Button previous;
    private readonly Button next;
    private InventoryDisplayItem[] items = [];
    private ushort? selectedIndex;
    private ushort? selectedItemId;
    private int page;
    private readonly bool storage;

    public InventoryGrid(string heading, string name, bool storage)
    {
        Name = name;
        this.storage = storage;
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,*,Auto,Auto"), RowSpacing = 4 };
        var header = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        Ui.At(header, Ui.Text(heading, 16, bold: true), 0);
        Ui.At(header, summary, 1);
        Ui.At(body, header, 0);

        var board = new Grid
        {
            ColumnDefinitions = new ColumnDefinitions("*,*,*,*,*,*"),
            RowDefinitions = new RowDefinitions("*,*,*,*"),
            ColumnSpacing = 8, RowSpacing = 8
        };
        for (var position = 0; position < PageSize; position++)
        {
            var captured = position;
            var button = new Button
            {
                Name = name + "Cell" + position, Padding = new Thickness(5),
                HorizontalAlignment = HorizontalAlignment.Stretch, VerticalAlignment = VerticalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch,
                Background = Brush.Parse("#132d40"), BorderBrush = Brush.Parse("#3a627a"),
                BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(3), IsEnabled = false
            };
            button.Resources["ButtonBackgroundDisabled"] = Brush.Parse("#132d40");
            button.Resources["ButtonBorderBrushDisabled"] = Brush.Parse("#3a627a");
            button.Click += (_, _) => SelectPosition(captured);
            cells[position] = button;
            Ui.At(board, button, position % Columns, position / Columns);
        }
        var boardLayer = new Grid();
        boardLayer.Children.Add(board);
        empty.HorizontalAlignment = HorizontalAlignment.Center;
        empty.VerticalAlignment = VerticalAlignment.Center;
        empty.Background = Ui.Panel;
        empty.Padding = new Thickness(12, 5);
        empty.IsHitTestVisible = false;
        boardLayer.Children.Add(empty);
        Ui.At(body, boardLayer, 0, 1);

        var pager = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto") };
        previous = Ui.Button("上一頁", () => ChangePage(-1), name + "Previous");
        next = Ui.Button("下一頁", () => ChangePage(1), name + "Next");
        Ui.At(pager, previous, 0); Ui.At(pager, next, 2);
        pageLabel.HorizontalAlignment = HorizontalAlignment.Center;
        Ui.At(pager, pageLabel, 1);
        Ui.At(body, pager, 0, 2);

        var details = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 8 };
        metadata.Name = name + "Details";
        Ui.At(details, Ui.Column(title, metadata, note), 0);
        StackPanel actions;
        if (storage)
            actions = Ui.Column(Ui.Unavailable("取出到背包", name + "Withdraw"));
        else
            actions = Ui.Column(
                Ui.Row(Ui.Unavailable("補 HP", name + "HealHp"), Ui.Unavailable("補 SP", name + "HealSp")),
                Ui.Row(Ui.Unavailable("存入儲藏室", name + "DepositGarage"), Ui.Unavailable("存入雜物櫃", name + "DepositMaterials")));
        Ui.At(details, actions, 1);
        Ui.At(body, new Border { Padding = new Thickness(4, 5), Child = details }, 0, 3);
        Content = body;
        Paint();
    }

    public int ItemCount => items.Length;
    public int PageIndex => page;
    public ushort? SelectedIndex => selectedIndex;
    public string DetailsText => $"{title.Text}\n{metadata.Text}\n{note.Text}";

    public void Reset()
    {
        page = 0; selectedIndex = null; selectedItemId = null; items = [];
        Paint();
    }

    public void FirstPage()
    {
        if (page == 0) return;
        page = 0;
        Paint();
    }

    public void SetItems(IEnumerable<InventoryDisplayItem> source, string query, ushort? capacity, bool ready, bool reliable)
    {
        var replacement = source.Where(item => query.Length == 0 || item.Name.Contains(query, StringComparison.OrdinalIgnoreCase)
            || item.ItemId.ToString(CultureInfo.InvariantCulture).Contains(query, StringComparison.OrdinalIgnoreCase)).ToArray();
        items = replacement;
        if (!items.Any(item => item.Index == selectedIndex && item.ItemId == selectedItemId))
        {
            selectedIndex = null;
            selectedItemId = null;
        }
        page = Math.Clamp(page, 0, PageCount - 1);
        summary.Text = $"{items.Length} / {(capacity is { } value ? value.ToString(CultureInfo.InvariantCulture) : "?")} 格｜" +
            (!ready ? "等待同步" : reliable ? "已同步" : "數量待確認");
        empty.Text = query.Length > 0 ? "沒有符合搜尋條件的物品" : ready ? "尚無物品紀錄" : storage ? "等待儲藏物品同步" : "等待背包同步";
        // Image admission can change while inventory rows remain byte-for-byte identical.
        // Reacquire image data on every host refresh, including revocation-only updates.
        Paint();
    }

    public void SelectItem(ushort index)
    {
        var position = Array.FindIndex(items, item => item.Index == index);
        if (position < 0) return;
        selectedIndex = index;
        selectedItemId = items[position].ItemId;
        page = position / PageSize;
        Paint();
    }

    public void ChangePage(int direction)
    {
        page = (int)Math.Clamp((long)page + direction, 0, PageCount - 1);
        Paint();
    }

    private int PageCount => Math.Max(1, (items.Length + PageSize - 1) / PageSize);

    private void SelectPosition(int position)
    {
        var index = page * PageSize + position;
        if (index < items.Length) SelectItem(items[index].Index);
    }

    private void Paint()
    {
        ReleaseImages();
        for (var position = 0; position < PageSize; position++)
        {
            var index = page * PageSize + position;
            var item = index < items.Length ? items[index] : null;
            var cell = cells[position];
            cell.IsEnabled = item is not null;
            var selected = item is not null && item.Index == selectedIndex && item.ItemId == selectedItemId;
            cell.Background = Brush.Parse(selected ? "#244f67" : "#132d40");
            cell.BorderBrush = selected ? Ui.Accent : Brush.Parse("#3a627a");
            if (item is null)
            {
                cell.Content = null;
                AutomationProperties.SetName(cell, "無物品紀錄");
                ToolTip.SetTip(cell, "尚無對應物品資料，不代表已解鎖的背包容量。");
                continue;
            }
            var tile = new Grid { RowDefinitions = new RowDefinitions("*,Auto") };
            var label = Ui.Text(item.Name, 13);
            label.TextAlignment = TextAlignment.Center;
            label.TextTrimming = TextTrimming.CharacterEllipsis;
            label.MaxLines = 2;
            Bitmap? bitmap = null;
            try
            {
                if (ImageReader?.Invoke(item.ItemId) is { Length: > 0 and <= 4194304 } png)
                {
                    // Production bytes are canonical Core PNGs. Bound native allocation before decoding.
                    var copy = png.ToArray();
                    if (copy.Length < 33 || !copy.AsSpan(0, 8).SequenceEqual(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }) ||
                        System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(8)) != 13 ||
                        !copy.AsSpan(12, 4).SequenceEqual("IHDR"u8) ||
                        System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(16)) is 0 or > 512 ||
                        System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(copy.AsSpan(20)) is 0 or > 512 ||
                        copy[24] != 8 || copy[25] != 6 || copy[26] != 0 || copy[27] != 0 || copy[28] != 0)
                        throw new InvalidDataException("Unreviewed item PNG header");
                    using var stream = new MemoryStream(copy, writable: false);
                    var decoded = new Bitmap(stream);
                    if (decoded.PixelSize.Width is > 0 and <= 512 && decoded.PixelSize.Height is > 0 and <= 512)
                    { bitmap = decoded; bitmaps.Add(decoded); }
                    else decoded.Dispose();
                }
            }
            catch (Exception) { /* Display failure remains unavailable; never infer readiness. */ }
            if (bitmap is null) Ui.At(tile, label, 0);
            else
            {
                var content = new Grid { RowDefinitions = new RowDefinitions("*,Auto") };
                Ui.At(content, new Image { Source = bitmap, Stretch = Stretch.Uniform, MaxHeight = 48 }, 0);
                Ui.At(content, label, 0, 1); Ui.At(tile, content, 0);
            }
            var footer = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            Ui.At(footer, Ui.Text("#" + item.Index, 11, Ui.Muted), 0);
            Ui.At(footer, Ui.Text("×" + item.Count.ToString(CultureInfo.InvariantCulture), 13, Ui.Gold, true), 1);
            Ui.At(tile, footer, 0, 1);
            cell.Content = tile;
            var description = $"{item.Name}｜ID {item.ItemId}｜格位 {item.Index}｜數量 {item.Count}";
            AutomationProperties.SetName(cell, description);
            ToolTip.SetTip(cell, description + (bitmap is null ? "；物品圖示尚未通過驗證。" : "；已驗證物品圖示。"));
        }
        empty.IsVisible = items.Length == 0;
        pageLabel.Text = $"{page + 1} / {PageCount}";
        previous.IsEnabled = page > 0;
        next.IsEnabled = page + 1 < PageCount;
        var current = items.FirstOrDefault(item => item.Index == selectedIndex && item.ItemId == selectedItemId);
        title.Text = current?.Name ?? "物品資訊";
        if (current is null)
        {
            metadata.Text = "請點選道具";
            note.Text = "物品圖示與使用條件待同步。";
        }
        else
        {
            var available = current.Reliable ? BigInteger.Max(0, current.Count - current.Reserved).ToString(CultureInfo.InvariantCulture) : "待確認";
            metadata.Text = $"ID {current.ItemId}　格位 {current.Index}　持有 {current.Count}　待扣 {current.Reserved}　可用 {available}";
            note.Text = current.Note + " 操作尚未接通。";
        }
    }
}
