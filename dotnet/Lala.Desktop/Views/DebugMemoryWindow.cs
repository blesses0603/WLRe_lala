#if DEBUG
using System.Diagnostics;
using Avalonia.Controls;
using Avalonia.Threading;

namespace Lala.Desktop;

/// <summary>Compiled out of Release, including its entry point and sampling code.</summary>
internal sealed class DebugMemoryWindow : DesktopWindow
{
    private static DebugMemoryWindow? current;
    private readonly Process process = Process.GetCurrentProcess();
    private readonly TextBlock usage = Ui.Text("—", 16, Ui.Accent, true);
    private readonly TextBlock peak = Ui.Text("—", 16, Ui.Gold, true);
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(1) };

    internal static void Toggle(Window owner)
    {
        if (current is { } existing) { existing.Close(); return; }
        current = new DebugMemoryWindow();
        current.Show(owner);
    }
    private DebugMemoryWindow() : base("記憶體", 200, 112)
    {
        Name = "DebugMemoryMonitor";
        var body = new Grid { ColumnDefinitions = new("42,*"), RowDefinitions = new("*,*"), RowSpacing = 2 };
        Ui.At(body, Ui.Text("目前", 12, Ui.Muted), 0); Ui.At(body, usage, 1);
        Ui.At(body, Ui.Text("最高", 12, Ui.Muted), 0, 1); Ui.At(body, peak, 1, 1);
        ToolTip.SetTip(body, "本次 LALA 程序的總工作集／尖峰工作集（MiB），每秒更新；僅 Debug 測試版提供。");
        SetBody(body);
        timer.Tick += (_, _) => Sample();
        Opened += (_, _) => { Sample(); timer.Start(); };
        Closed += (_, _) => { timer.Stop(); process.Dispose(); if (ReferenceEquals(current, this)) current = null; };
    }
    private void Sample()
    {
        try
        {
            process.Refresh();
            usage.Text = $"{process.WorkingSet64 / 1048576.0:N1} MiB";
            peak.Text = $"{process.PeakWorkingSet64 / 1048576.0:N1} MiB";
        }
        catch (InvalidOperationException) { timer.Stop(); usage.Text = "已結束"; }
    }
}
#endif
