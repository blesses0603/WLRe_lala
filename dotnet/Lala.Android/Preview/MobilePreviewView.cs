using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Lala.Android.Live;
using Button = Avalonia.Controls.Button;
using ProgressBar = Avalonia.Controls.ProgressBar;
using Orientation = Avalonia.Layout.Orientation;

namespace Lala.Android.Preview;

/// <summary>Mobile shell with separate official-session and offline design modes.</summary>
internal sealed partial class MobilePreviewView : UserControl
{
    private static readonly IBrush Ink = Brush.Parse("#DDEFF8"), Muted = Brush.Parse("#99B5C8"), Accent = Brush.Parse("#70F8F1"), Green = Brush.Parse("#7FFAAD"), Gold = Brush.Parse("#FFE38A");
    private static readonly Dictionary<string, Bitmap> Images = [];
    private readonly MobilePreviewState state;
    private readonly Func<Control> diagnostics;
    private readonly IMobileOfficialClient? official;
    private readonly DispatcherTimer officialTimer = new() { Interval = TimeSpan.FromMilliseconds(300) };
    private Action<MobileOfficialSnapshot>? renderOfficial;
    private TextBlock? officialBadge;
    private bool OfficialMode => official is not null && !state.DemoMode;
    private readonly ContentControl page = new();
    private readonly List<Button> tabs = [];
    private readonly Border notice;
    private readonly TextBlock noticeText;
    private readonly DispatcherTimer progressTimer = new() { Interval = TimeSpan.FromMilliseconds(110) };
    private readonly DispatcherTimer toastTimer = new() { Interval = TimeSpan.FromSeconds(5) };
    private readonly List<TextBlock> resourceStatuses = [];
    private ProgressBar? resourceProgress;
    private TextBlock? resourceSummary;
    private TextBlock? resourceTimestamp;

    internal MobilePreviewView(MobilePreviewState state, Func<Control> diagnostics, IMobileOfficialClient? official = null)
    {
        this.state = state; this.diagnostics = diagnostics; this.official = official; Name = "AndroidMobilePreview";
        RenderOptions.SetBitmapInterpolationMode(this, BitmapInterpolationMode.HighQuality);
        var layout = new Grid { RowDefinitions = new("Auto,*,Auto,Auto"), Background = Gradient("#031426", "#020E20") };
        At(layout, Header(), 0); At(layout, page, 1);
        noticeText = Label("", 11, Accent);
        notice = Surface(noticeText, new(12, 9), 10); notice.Margin = new(12, 4); notice.IsVisible = false;
        At(layout, notice, 2); At(layout, Navigation(), 3); Content = layout;
        progressTimer.Tick += (_, _) =>
        {
            state.Progress = Math.Min(100, state.Progress + 3); RefreshResourceProgress();
            if (state.Progress == 100)
            {
                progressTimer.Stop();
                state.ResourceCheckedAt = DateTimeOffset.UtcNow.ToOffset(TimeSpan.FromHours(8)).ToString("MM-dd HH:mm:ss");
                if (resourceTimestamp is not null) resourceTimestamp.Text = "檢查時間：" + state.ResourceCheckedAt;
                AddEvent("資源檢查示範完成，未連線官方伺服器"); Toast("示範流程完成。正式資源驗證尚未接入。");
            }
        };
        toastTimer.Tick += (_, _) => { toastTimer.Stop(); notice.IsVisible = false; };
        workshopTimer.Tick += (_, _) => TickWorkshop();
        officialTimer.Tick += (_, _) => RefreshOfficial();
        // Avalonia's Android host already applies the system-bar safe area.
        DetachedFromVisualTree += (_, _) => Suspend(); ShowPage(state.Page);
        AttachedToVisualTree += (_, _) => Resume();
    }
    internal void Suspend() { progressTimer.Stop(); toastTimer.Stop(); workshopTimer.Stop(); officialTimer.Stop(); }
    internal void Resume() { if (official is not null) { officialTimer.Start(); RefreshOfficial(); } }
    private void RefreshOfficial()
    {
        if (official is null) return;
        var value = official.Snapshot;
        if (officialBadge is not null) officialBadge.Text = OfficialMode ? value.Connected ? "官方連線 · 已登入" : "官方連線 · 尚未登入" : "預覽模式 · 範例資料";
        if (OfficialMode) renderOfficial?.Invoke(value);
    }
    private void ShowPage(int index)
    {
        progressTimer.Stop(); workshopTimer.Stop(); updateWorkshop = null; renderOfficial = null; resourceStatuses.Clear(); resourceProgress = null; resourceSummary = null; resourceTimestamp = null; state.Page = index;
        page.Content = OfficialMode ? OfficialPage(index) : index switch { 0 => AccountsPage(), 1 => InventoryPage(), 2 => ResourcePage(), 3 => EventsPage(), 4 => ToolsPage(), 5 => CharacterPage(), 6 => MapPage(),
            7 => SocialPage(), 8 => CompanionsPage(), 9 => ExpeditionPage(), 10 => WorkshopPage(), _ => AccountsPage() };
        int active = index is 5 or 6 or 7 or 8 or 9 or 10 ? 0 : index;
        for (int i = 0; i < tabs.Count; i++)
        {
            bool selected = tabs[i].Tag is int target && target == active;
            tabs[i].Background = selected ? Gradient("#15475C", "#073243") : Brushes.Transparent;
            tabs[i].BorderBrush = selected ? Accent : Brushes.Transparent;
        }
        RefreshOfficial();
        if (official is not null && !OfficialMode && page.Content is Control sample)
        {
            var mode = new Grid { RowDefinitions = new("Auto,*"), RowSpacing = 5 };
            At(mode, ActionButton("返回官方連線", "link", () => { state.DemoMode = false; ShowPage(0); }, compact: true), 0); At(mode, sample, 1); page.Content = mode;
        }
    }
    private Control Header()
    {
        var header = new Grid { Height = 98, ClipToBounds = true };
        header.Children.Add(new Image { Source = Asset("castle-header.png"), Stretch = Stretch.UniformToFill, Opacity = .92 });
        var content = new Grid { ColumnDefinitions = new("78,*,Auto"), Margin = new(8, 5, 10, 0), ColumnSpacing = 7 };
        content.Children.Add(new MascotArtwork(Asset("lala-mascot.png")) { VerticalAlignment = VerticalAlignment.Stretch });
        officialBadge = Label(official is null ? "預覽模式 · 範例資料" : "官方連線 · 尚未登入", 9, Accent);
        var name = Column(5, Label("飄流 RE:LaLa", 21, Accent), Label(official is null ? "ANDROID · 手機介面預覽" : "ANDROID · 官方連線", 9, Muted), Surface(Row(4, new NeonIcon("shield", Accent, 12), officialBadge), new(6, 3), 12, false));
        name.VerticalAlignment = VerticalAlignment.Center; Grid.SetColumn(name, 1); content.Children.Add(name);
        var actions = Row(5, IconButton("bell", "通知紀錄", () => ShowPage(3), 30), IconButton("gear", "設定與工具", () => ShowPage(4), 30));
        actions.VerticalAlignment = VerticalAlignment.Top; Grid.SetColumn(actions, 2); content.Children.Add(actions); header.Children.Add(content);
        header.Children.Add(new Border { Height = 1, Background = Gradient("#0059E9ED", "#9560F6F2", true), VerticalAlignment = VerticalAlignment.Bottom });
        return header;
    }
    private Control Navigation()
    {
        var nav = new Grid { ColumnDefinitions = new("*,*,*,*"), Margin = new(6, 5), ColumnSpacing = 2 };
        var entries = new[] { (0, "首頁", "home"), (1, "包包與特技", "bag"), (3, "運行紀錄", "chart"), (4, "工具箱", "grid") };
        for (int i = 0; i < entries.Length; i++)
        {
            var (index, label, icon) = entries[i]; var button = ActionButton(label, icon, () => ShowPage(index)); button.Name = "PreviewTab" + index; button.Tag = index;
            button.Padding = new(1, 7); button.MinHeight = 58; button.CornerRadius = new(12); button.BorderThickness = new(0, 0, 0, 1.5);
            button.Content = Column(5, new NeonIcon(icon, Accent, 21) { HorizontalAlignment = HorizontalAlignment.Center }, Label(label, 9, Ink, center: true));
            Grid.SetColumn(button, i); nav.Children.Add(button); tabs.Add(button);
        }
        return new Border { Background = Gradient("#102940", "#06152B"), BorderBrush = Brush.Parse("#365D7B"), BorderThickness = new(0, 1, 0, 0), CornerRadius = new(17, 17, 0, 0), Child = nav };
    }
    private Control HomeTabs(int selected) => EqualRow(5,
        ActionButton("帳號管理", "grid", () => ShowPage(0), selected == 0, true), ActionButton("角色概況", "user", () => ShowPage(5), selected == 5, true),
        ActionButton("資源檢查", "layers", () => ShowPage(2), selected == 2, true), ActionButton("小地圖", "map", () => ShowPage(6), selected == 6, true));
    private Control FeatureMenu() => EqualRow(5,
        ActionButton("聊天組隊", "chat", () => ShowPage(7), state.Page == 7, true), ActionButton("夥伴配點", "users", () => ShowPage(8), state.Page == 8, true),
        ActionButton("遠征副本", "flag", () => ShowPage(9), state.Page == 9, true), ActionButton("煉金製作", "flask", () => ShowPage(10), state.Page == 10, true));
    private static Control Portrait(int index, double size = 42) => new Border
    {
        Width = size, Height = size, CornerRadius = new(size / 2), BorderBrush = Accent, BorderThickness = new(1), ClipToBounds = true,
        Child = new SheetArtwork(Asset("companion-portraits.png"), index % 3), BoxShadow = Glow()
    };
    private static ToggleSwitch Switch(bool selected, Action<bool> changed)
    {
        var toggle = new ToggleSwitch { IsChecked = selected, OnContent = "", OffContent = "", MinWidth = 44, Height = 30 };
        toggle.IsCheckedChanged += (_, _) => changed(toggle.IsChecked == true); return toggle;
    }
    private static Control Stepper(Func<int> read, Action<int> write, int minimum, int maximum, string name)
    {
        var number = Label(read().ToString(), 12, Ink, center: true);
        void Change(int delta) { int value = Math.Clamp(read() + delta, minimum, maximum); write(value); number.Text = read().ToString(); }
        return Sides(IconButton("minus", "減少" + name, () => Change(-1), 28),
            Sides(Surface(number, new(5), 7, false), IconButton("plus", "增加" + name, () => Change(1), 28), "*,28", 5), "28,*", 5);
    }
    private void Toast(string text) { noticeText.Text = text; notice.IsVisible = true; toastTimer.Stop(); toastTimer.Start(); }
    private void AddEvent(string text)
    {
        state.Events.Insert(0, DateTimeOffset.UtcNow.ToOffset(TimeSpan.FromHours(8)).ToString("HH:mm:ss") + "  " + text);
        if (state.Events.Count > 30) state.Events.RemoveAt(state.Events.Count - 1);
    }
    private static LinearGradientBrush Gradient(string first, string last, bool horizontal = false) => new()
    {
        StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative), EndPoint = new RelativePoint(horizontal ? 1 : .3, 1, RelativeUnit.Relative),
        GradientStops = new() { new(Color.Parse(first), 0), new(Color.Parse(last), 1) }
    };
    private static BoxShadows Glow(string color = "#5930EAF4", double blur = 9) => new(new BoxShadow { Color = Color.Parse(color), Blur = blur });
    private static Bitmap Asset(string name)
    {
        if (Images.TryGetValue(name, out var image)) return image;
        using var stream = typeof(MobilePreviewView).Assembly.GetManifestResourceStream("AndroidPreviewAssets." + name) ?? throw new InvalidOperationException("Missing preview artwork: " + name);
        return Images[name] = new Bitmap(stream);
    }
    private static TextBlock Label(string text, double size = 12, IBrush? color = null, bool bold = false, bool center = false) => new()
    {
        Text = text, FontSize = size, Foreground = color ?? Ink, FontWeight = bold ? FontWeight.SemiBold : FontWeight.Normal,
        TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center, TextAlignment = center ? TextAlignment.Center : TextAlignment.Left
    };
    private static StackPanel Column(double gap, params Control[] children)
    { var panel = new StackPanel { Spacing = gap }; foreach (var child in children) panel.Children.Add(child); return panel; }
    private static StackPanel Row(double gap, params Control[] children)
    { var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = gap, VerticalAlignment = VerticalAlignment.Center }; foreach (var child in children) panel.Children.Add(child); return panel; }
    private static Grid EqualRow(double gap, params Control[] children)
    {
        var grid = new Grid { ColumnDefinitions = new(string.Join(",", children.Select(_ => "*"))), ColumnSpacing = gap };
        for (int i = 0; i < children.Length; i++) { Grid.SetColumn(children[i], i); grid.Children.Add(children[i]); } return grid;
    }
    private static Grid Sides(Control left, Control right, string columns = "*,Auto", double gap = 8)
    { var grid = new Grid { ColumnDefinitions = new(columns), ColumnSpacing = gap }; grid.Children.Add(left); Grid.SetColumn(right, 1); grid.Children.Add(right); return grid; }
    private static Grid AdaptiveSides(Control left, Control right, string columns, double breakpoint)
    {
        var grid = Sides(left, right, columns); bool? stacked = null;
        grid.SizeChanged += (_, e) =>
        {
            bool narrow = e.NewSize.Width < breakpoint;
            if (stacked == narrow) return; stacked = narrow;
            grid.ColumnDefinitions = new(narrow ? "*" : columns); grid.RowDefinitions = new(narrow ? "Auto,Auto" : "Auto"); grid.RowSpacing = narrow ? 7 : 0;
            Grid.SetColumn(right, narrow ? 0 : 1); Grid.SetRow(right, narrow ? 1 : 0);
        };
        return grid;
    }
    private static Border Surface(Control child, Thickness? padding = null, double radius = 13, bool glow = true) => new()
    {
        Padding = padding ?? new Thickness(11), CornerRadius = new(radius), BorderThickness = new(.85), BorderBrush = Gradient("#8DDDEB", "#327C9C"),
        Background = Gradient("#102E46", "#05182B"), BoxShadow = glow ? Glow() : default, Child = child
    };
    private static Control Card(string title, string icon, params Control[] children) => Surface(Column(8, [Row(8, new NeonIcon(icon), Label(title, 15, Ink, true)), Divider(), ..children]));
    private static Border Divider() => new() { Height = .7, Background = Brush.Parse("#34506A") };
    private static Control Page(params Control[] content) => new ScrollViewer
    {
        Content = new StackPanel { Children = { Column(11, content) }, Margin = new(10, 5, 10, 15) },
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Hidden
    };
    private static Control Pill(string text, string icon = "check", IBrush? color = null)
    {
        var ink = color ?? Green;
        return new Border { Background = Brush.Parse("#122B3F"), BorderBrush = Brush.Parse("#3D7D89"), BorderThickness = new(.7), CornerRadius = new(12),
            Padding = new(7, 3), HorizontalAlignment = HorizontalAlignment.Left, Child = Row(5, new NeonIcon(icon, ink, 12), Label(text, 10, ink)) };
    }
    private static Button ActionButton(string text, string icon, Action action, bool primary = false, bool compact = false)
    {
        var button = new Button
        {
            Content = Row(compact ? 4 : 8, new NeonIcon(icon, primary ? Ink : Accent, compact ? 15 : 19), Label(text, compact ? 10 : 13, Ink, primary)),
            MinHeight = compact ? 34 : 44, Padding = new(compact ? 5 : 12, 7), CornerRadius = new(compact ? 10 : 23), BorderThickness = new(1),
            BorderBrush = primary ? Accent : Brush.Parse("#5586A4"), Background = primary ? Gradient("#05B8C2", "#026078", true) : Gradient("#20435E", "#102D47"),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center
        };
        if (primary) button.Effect = new DropShadowEffect { Color = Color.Parse("#3CEFE9"), BlurRadius = 7, Opacity = .5, OffsetX = 0, OffsetY = 0 };
        AutomationProperties.SetName(button, text); button.Click += (_, _) => action(); return button;
    }
    private static Button IconButton(string icon, string name, Action action, double size = 34)
    {
        var button = ActionButton(name, icon, action, compact: true); button.Content = new NeonIcon(icon, Ink, 19);
        button.Width = size; button.MinHeight = button.Height = size; button.Padding = new(5); return button;
    }
    private static void SelectButton(Button button, bool selected)
    {
        button.Background = selected ? Gradient("#05B8C2", "#026078", true) : Gradient("#20435E", "#102D47");
        button.BorderBrush = selected ? Accent : Brush.Parse("#5586A4");
    }
    private static Control Avatar(double size = 44) => new Border
    {
        Width = size, Height = size, CornerRadius = new(size / 2), BorderBrush = Accent, BorderThickness = new(1.2), Background = Brush.Parse("#153754"),
        ClipToBounds = true, Child = new MascotArtwork(Asset("lala-mascot.png")), BoxShadow = Glow()
    };
    private static Control Field(string icon, string label, Control input) => Sides(Row(5, new NeonIcon(icon, Muted, 15), Label(label, 11)), input, "60,*");
    private static TextBox Input(string placeholder) => new() { PlaceholderText = placeholder, FontSize = 12, MinHeight = 38, CornerRadius = new(9), BorderBrush = Brush.Parse("#517996"), Background = Brush.Parse("#182D43"), Foreground = Ink, Padding = new(10, 7) };
    private static ComboBox Combo(params string[] choices) => new() { ItemsSource = choices, SelectedIndex = 0, FontSize = 11, MinHeight = 36, CornerRadius = new(8), HorizontalAlignment = HorizontalAlignment.Stretch, Background = Brush.Parse("#162E45"), Foreground = Ink, Padding = new(9, 5) };
    private static void At(Grid grid, Control child, int row) { Grid.SetRow(child, row); grid.Children.Add(child); }
}
