using Avalonia;
using Avalonia.Automation;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Styling;
using Avalonia.Threading;

namespace Lala.Desktop;

internal static class Ui
{
    public static readonly IBrush Background = Brush.Parse("#101c2b");
    public static readonly IBrush Panel = Brush.Parse("#e8142638");
    public static readonly IBrush Input = Brush.Parse("#16364b");
    public static readonly IBrush BorderBrush = Brush.Parse("#397c98");
    public static readonly IBrush Ink = Brush.Parse("#eff7ff");
    public static readonly IBrush Muted = Brush.Parse("#a7cbdc");
    public static readonly IBrush Accent = Brush.Parse("#62c9e0");
    public static readonly IBrush Gold = Brush.Parse("#f9c57a");

    public static TextBlock Text(string text, double size = 14, IBrush? color = null, bool bold = false) => new()
    {
        Text = text, FontSize = size, Foreground = color ?? Ink,
        FontWeight = bold ? FontWeight.SemiBold : FontWeight.Normal,
        TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center
    };

    public static Button Button(string text, Action? action = null, string? name = null, bool enabled = true)
    {
        var result = new ArtButton(text) { Name = name, IsEnabled = enabled };
        AutomationProperties.SetName(result, text);
        if (action is not null) result.Click += (_, _) => action();
        return result;
    }

    public static Button Unavailable(string text, string? name = null, string? reason = null)
    {
        var result = Button(text, name: name, enabled: false);
        ToolTip.SetTip(result, reason ?? DesktopSession.ConnectionUnavailable);
        return result;
    }

    public static StackPanel Row(params Control[] children)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, VerticalAlignment = VerticalAlignment.Center };
        foreach (var child in children) row.Children.Add(child);
        return row;
    }

    public static StackPanel Column(params Control[] children)
    {
        var column = new StackPanel { Spacing = 6 };
        foreach (var child in children) column.Children.Add(child);
        return column;
    }

    public static Grid Field(string title, Control value, string columns = "120,*")
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions(columns), Margin = new Thickness(0, 3) };
        At(grid, Text(title), 0); At(grid, value, 1);
        return grid;
    }

    public static Border Card(string title, Control content)
    {
        var body = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
        At(body, Text(title, 14, Brush.Parse("#c5f1ff"), true), 0);
        content.Margin = new Thickness(0, 5, 0, 0);
        At(body, content, 0, 1);
        return new Border { Background = Panel, BorderBrush = BorderBrush, BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(7), Padding = new Thickness(10, 7), ClipToBounds = true, Child = body };
    }

    public static T At<T>(Grid parent, T control, int column, int row = 0, int columnSpan = 1, int rowSpan = 1) where T : Control
    {
        Grid.SetColumn(control, column); Grid.SetRow(control, row);
        Grid.SetColumnSpan(control, columnSpan); Grid.SetRowSpan(control, rowSpan);
        parent.Children.Add(control); return control;
    }

    public static TabControl Tabs(params (string Title, Control Content)[] entries) => new()
    {
        ItemsSource = entries.Select(e => new TabItem { Header = Text(e.Title, 14, bold: true), Content = e.Content,
            FontSize = 14, Padding = new Thickness(10, 6), MinHeight = 32 }).ToArray()
    };

    public static ComboBox Combo(IEnumerable<string> values, int selected = 0, string? name = null) => new()
    {
        ItemsSource = values.ToArray(), SelectedIndex = selected, MinHeight = 30, Name = name,
        HorizontalAlignment = HorizontalAlignment.Stretch
    };

    public static NumericUpDown Number(decimal value, decimal minimum, decimal maximum, decimal increment = 1, double width = 120) => new()
    {
        Value = value, Minimum = minimum, Maximum = maximum, Increment = increment, Width = width,
        FormatString = increment < 1 ? "0.0" : "0", MinHeight = 30
    };

    public static Image Icon(string path, double size = 24) => new()
    {
        Source = DesktopAssets.Bitmap(path), Width = size, Height = size, Stretch = Stretch.Uniform
    };

    public static Button IconButton(string title, string path, Action? action, double size = 24, bool enabled = true)
    {
        var button = new Button { Content = Icon(path, size), Width = size + 10, Height = size + 8,
            Padding = new Thickness(3), Background = Brushes.Transparent, IsEnabled = enabled };
        AutomationProperties.SetName(button, title);
        ToolTip.SetTip(button, title + (enabled ? "" : "｜等待功能接入"));
        if (action is not null) button.Click += (_, _) => action();
        return button;
    }

    public static void OnUi(Action action)
    {
        if (Dispatcher.UIThread.CheckAccess()) action(); else Dispatcher.UIThread.Post(action);
    }

    public static void InstallStyles(Application app)
    {
        var font = new FontFamily("Microsoft JhengHei UI, Noto Sans CJK TC, Noto Serif CJK TC, WenQuanYi Micro Hei, sans-serif");
        app.Styles.Add(new Style(s => s.OfType<Window>())
        {
            Setters = { new Setter(TemplatedControl.FontFamilyProperty, font), new Setter(TemplatedControl.FontSizeProperty, 14d),
                new Setter(TemplatedControl.ForegroundProperty, Ink) }
        });
        app.Styles.Add(new Style(s => s.OfType<TextBox>())
        {
            Setters = { new Setter(TemplatedControl.BackgroundProperty, Input), new Setter(TemplatedControl.BorderBrushProperty, BorderBrush),
                new Setter(TemplatedControl.CornerRadiusProperty, new CornerRadius(4)), new Setter(Layoutable.MinHeightProperty, 30d) }
        });
        app.Styles.Add(new Style(s => s.OfType<ComboBox>())
        {
            Setters = { new Setter(TemplatedControl.BackgroundProperty, Input), new Setter(TemplatedControl.PaddingProperty, new Thickness(7, 3)) }
        });
        app.Styles.Add(new Style(s => s.OfType<TabControl>())
        {
            Setters = { new Setter(TemplatedControl.BackgroundProperty, Brushes.Transparent), new Setter(TemplatedControl.PaddingProperty, new Thickness(0)) }
        });
        app.Styles.Add(new Style(s => s.OfType<TabItem>())
        {
            Setters = { new Setter(TemplatedControl.PaddingProperty, new Thickness(12, 6)), new Setter(TemplatedControl.MinHeightProperty, 32d) }
        });
    }
}

/// <summary>Original game button artwork, preserving its end caps while stretching the middle.</summary>
internal sealed class ArtButton : Button
{
    protected override Type StyleKeyOverride => typeof(Button);
    private readonly Bitmap artwork;
    public ArtButton(string text)
    {
        Content = text; MinHeight = 30; Padding = new Thickness(13, 4); Background = Brushes.Transparent;
        BorderThickness = new Thickness(0); HorizontalContentAlignment = HorizontalAlignment.Center;
        string path = text.StartsWith("登入", StringComparison.Ordinal) || text.StartsWith("套用", StringComparison.Ordinal) || text.StartsWith("啟動", StringComparison.Ordinal)
            ? "Btn_014.png" : text.StartsWith("取消", StringComparison.Ordinal) || text.StartsWith("停止", StringComparison.Ordinal) || text.StartsWith("中斷", StringComparison.Ordinal)
            ? "Btn_016.png" : "Btn_004.png";
        artwork = DesktopAssets.Bitmap("buttons/" + path);
    }
    public override void Render(DrawingContext context)
    {
        var source = artwork.Size;
        double scale = Bounds.Height / source.Height;
        double left = Math.Min(Bounds.Width / 2, 34 * scale), right = Math.Min(Bounds.Width / 2, 37 * scale);
        using (context.PushOpacity(IsEnabled ? 1 : .48))
        {
            context.DrawImage(artwork, new Rect(0, 0, 34, source.Height), new Rect(0, 0, left, Bounds.Height));
            if (Bounds.Width > left + right)
                context.DrawImage(artwork, new Rect(34, 0, source.Width - 71, source.Height), new Rect(left, 0, Bounds.Width - left - right, Bounds.Height));
            context.DrawImage(artwork, new Rect(source.Width - 37, 0, 37, source.Height), new Rect(Bounds.Width - right, 0, right, Bounds.Height));
        }
        base.Render(context);
    }
}

internal static class DesktopAssets
{
    private static readonly Dictionary<string, Bitmap> Images = new(StringComparer.Ordinal);
    public static Stream Open(string path) => typeof(DesktopAssets).Assembly.GetManifestResourceStream("DesktopAssets." + Path.GetFileName(path))
        ?? throw new InvalidOperationException("Missing desktop artwork: " + path);
    public static Bitmap Bitmap(string path)
    {
        if (Images.TryGetValue(path, out var bitmap)) return bitmap;
        using var stream = Open(path);
        bitmap = new Bitmap(stream); Images.Add(path, bitmap); return bitmap;
    }
    public static void Dispose()
    {
        foreach (var bitmap in Images.Values) bitmap.Dispose();
        Images.Clear();
    }
}

public abstract class DesktopWindow : Window
{
    protected override Type StyleKeyOverride => typeof(Window);
    private readonly double designWidth;
    private readonly double designHeight;
    protected DesktopWindow(string title, double width, double height)
    {
        Title = title; Width = designWidth = width; Height = designHeight = height; CanResize = false;
        WindowDecorations = WindowDecorations.None;
        ClosingBehavior = WindowClosingBehavior.OwnerWindowOnly;
        Background = Ui.Background; WindowStartupLocation = WindowStartupLocation.CenterOwner;
        using var icon = DesktopAssets.Open("app.ico"); Icon = new WindowIcon(icon);
        Opened += (_, _) =>
        {
            var screen = Screens.ScreenFromWindow(this);
            if (screen is null) return;
            var scale = Math.Min(1, Math.Min((screen.WorkingArea.Width / screen.Scaling - 24) / designWidth,
                (screen.WorkingArea.Height / screen.Scaling - 24) / designHeight));
            if (scale > 0)
            {
                Width = designWidth * scale; Height = designHeight * scale;
                if (scale < 1)
                    Position = new PixelPoint(screen.WorkingArea.X + (int)((screen.WorkingArea.Width - Width * screen.Scaling) / 2),
                        screen.WorkingArea.Y + (int)((screen.WorkingArea.Height - Height * screen.Scaling) / 2));
            }
        };
    }

    protected void SetBody(Control content, bool dashboard = false)
    {
        var layers = new Grid { Width = designWidth, Height = designHeight };
        layers.Children.Add(new LegacyBackdrop { IsHitTestVisible = false });
        layers.Children.Add(new Border { Background = Brush.Parse(dashboard ? "#75071526" : "#99071526"), IsHitTestVisible = false });
        var layout = new Grid { RowDefinitions = new RowDefinitions("44,*") };
        var chrome = new Grid { ColumnDefinitions = new ColumnDefinitions("*,32,32"), ColumnSpacing = 10,
            Margin = new Thickness(12, 5) };
        var caption = Ui.Row(Ui.Icon("function-icons/MainIcon_041.png", 24), Ui.Text(Title ?? "LaLa", 16, bold: true));
        caption.Background = Brushes.Transparent;
        caption.PointerPressed += (_, e) => { if (e.GetCurrentPoint(this).Properties.IsLeftButtonPressed) BeginMoveDrag(e); };
        Ui.At(chrome, caption, 0);
        var minimize = new Button { Content = "−", Width = 24, Height = 24, Padding = new Thickness(0), CornerRadius = new CornerRadius(12),
            Background = Brush.Parse("#165a65"), Foreground = Brushes.White, BorderBrush = Brush.Parse("#b4e1eb"), BorderThickness = new Thickness(1) };
        AutomationProperties.SetName(minimize, "最小化"); ToolTip.SetTip(minimize, "最小化");
        minimize.Click += (_, _) => WindowState = WindowState.Minimized; Ui.At(chrome, minimize, 1);
        var close = Ui.IconButton("關閉", "buttons/Btn_Close04.png", Close, 24); close.Width = close.Height = 28;
        Ui.At(chrome, close, 2); Ui.At(layout, chrome, 0);
        content.Margin = new Thickness(dashboard ? 10 : 12);
        Ui.At(layout, content, 0, 1); layers.Children.Add(layout);
        layers.Children.Add(new Border { BorderBrush = Ui.Accent, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(20), IsHitTestVisible = false });
        Content = new Viewbox { Child = layers, Stretch = Stretch.Uniform, StretchDirection = StretchDirection.DownOnly };
    }
}

/// <summary>Fit the original wallpaper to the legacy 1280x800 design canvas, then crop
/// its center for dialogs. A dialog must not independently stretch the artwork.</summary>
internal sealed class LegacyBackdrop : Control
{
    public override void Render(DrawingContext context)
    {
        var bitmap = DesktopAssets.Bitmap("exp_background.png");
        double scale = Math.Max(1280 / bitmap.Size.Width, 800 / bitmap.Size.Height);
        double width = Bounds.Width / scale, height = Bounds.Height / scale;
        var source = new Rect((bitmap.Size.Width - width) / 2, (bitmap.Size.Height - height) / 2, width, height);
        context.DrawImage(bitmap, source, new Rect(Bounds.Size));
        base.Render(context);
    }
}

/// <summary>Selectable, scrollable desktop table; rows never become fabricated domain data.</summary>
internal sealed class TextTable : UserControl
{
    private readonly string columns;
    private readonly ListBox list = new() { Background = Brushes.Transparent, Padding = new Thickness(0) };
    private readonly TextBlock empty = Ui.Text("尚未收到資料。", color: Ui.Muted);
    private (string Key, string[] Cells)[] rows = [];
    public TextTable(string[] headings, string columns, string? name = null)
    {
        this.columns = columns; Name = name;
        var grid = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
        var header = new Border { Background = Brush.Parse("#243d52"), Padding = new Thickness(8, 5), Child = MakeRow(headings, true) };
        Ui.At(grid, header, 0);
        var body = new Grid { Background = Brush.Parse("#d20d2030") };
        body.Children.Add(list); empty.Margin = new Thickness(12); empty.VerticalAlignment = VerticalAlignment.Top; empty.IsHitTestVisible = false; body.Children.Add(empty);
        Ui.At(grid, body, 0, 1); Content = grid;
        list.SelectionChanged += (_, _) => SelectionChanged?.Invoke();
    }
    public event Action? SelectionChanged;
    public string? SelectedKey => list.SelectedIndex is var index && index >= 0 && index < rows.Length ? rows[index].Key : null;
    public int RowCount => rows.Length;
    public void SelectIndex(int index) => list.SelectedIndex = index;
    public void SetRows(IEnumerable<(string Key, string[] Cells)> value, string emptyMessage = "尚未收到資料。")
    {
        var updated = value.ToArray();
        if (rows.Length == updated.Length && rows.Zip(updated).All(pair => pair.First.Key == pair.Second.Key && pair.First.Cells.SequenceEqual(pair.Second.Cells)))
        {
            empty.Text = emptyMessage; empty.IsVisible = rows.Length == 0;
            return;
        }
        var selected = SelectedKey;
        rows = updated;
        list.ItemsSource = rows.Select(row => new ListBoxItem { Content = MakeRow(row.Cells), Padding = new Thickness(6, 4),
            HorizontalContentAlignment = HorizontalAlignment.Stretch }).ToArray();
        empty.Text = emptyMessage; empty.IsVisible = rows.Length == 0;
        list.SelectedIndex = Array.FindIndex(rows, r => r.Key == selected);
    }
    private Grid MakeRow(string[] cells, bool heading = false)
    {
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions(columns) };
        for (var i = 0; i < cells.Length; i++)
        {
            var label = Ui.Text(cells[i], 13, heading ? Brush.Parse("#c5f1ff") : Ui.Ink, heading);
            label.TextWrapping = TextWrapping.NoWrap; label.TextTrimming = TextTrimming.CharacterEllipsis;
            label.Margin = new Thickness(3, 0); ToolTip.SetTip(label, cells[i]); Ui.At(row, label, i);
        }
        return row;
    }
}
