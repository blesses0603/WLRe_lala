using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using Avalonia.Threading;
using Lala.Presentation;

namespace Lala.Desktop;

/// <summary>Desktop-only composition root. Android continues to compile Shared/App.cs.</summary>
public sealed class DesktopApplication : Application
{
    private DesktopSession? session;
    private DesktopWindows? windows;
    private string? testPreferencesDirectory;
    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        Styles.Add(new FluentTheme()); Ui.InstallStyles(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            testPreferencesDirectory = Program.UiSmokeTest ? Path.Combine(Path.GetTempPath(), "lala-desktop-ui-" + Guid.NewGuid().ToString("N")) : null;
            var preferences = Program.UiSmokeTest
                ? new DesktopPreferencesStore(testPreferencesDirectory)
                : new DesktopPreferencesStore();
            session = new(preferences);
            windows = new(session, () => desktop.Shutdown());
            desktop.ShutdownRequested += (_, args) => { args.Cancel = true; windows.RequestShutdown(); };
            desktop.MainWindow = Program.UiSmokeTest ? windows.Dashboard : windows.Login;
            if (Program.UiSmokeTest)
                windows.Dashboard.Opened += (_, _) => Dispatcher.UIThread.Post(async () =>
                {
                    try
                    {
                        await DesktopUiSmokeTest.RunAsync(session, windows.Dashboard, Program.ScreenshotDirectory);
                        desktop.Shutdown(0);
                    }
                    catch (Exception error)
                    {
                        Console.Error.WriteLine("Desktop UI smoke test failed: " + error);
                        desktop.Shutdown(1);
                    }
                });
            desktop.Exit += (_, _) =>
            {
                windows.Dispose(); session.Dispose(); DesktopAssets.Dispose();
                if (testPreferencesDirectory is not null && Directory.Exists(testPreferencesDirectory))
                    Directory.Delete(testPreferencesDirectory, true);
            };
        }
        base.OnFrameworkInitializationCompleted();
    }
}

/// <summary>One non-modal instance per desktop feature. Closing settings discards its draft;
/// hiding login/expedition preserves local presentation state within the current session.</summary>
public sealed class DesktopWindows : IDisposable
{
    private readonly DesktopSession session;
    private readonly Action shutdown;
    private readonly Dictionary<string, FeatureWindow> features = new(StringComparer.Ordinal);
    private bool disposed;
    private bool shutdownRequested;
    public DashboardWindow Dashboard { get; }
    public LoginWindow Login { get; }
    public DesktopWindows(DesktopSession session, Action shutdown)
    {
        this.session = session; this.shutdown = shutdown;
        Dashboard = new(session, this);
        Login = new(session, OpenMain, () => OpenInspector());
        Dashboard.Closing += (_, args) => { if (!disposed) { args.Cancel = true; RequestShutdown(); } };
        Login.Closing += (_, args) =>
        {
            Login.ClearSecrets();
            if (disposed) return;
            if (!Dashboard.IsVisible) { args.Cancel = true; RequestShutdown(); return; }
            args.Cancel = true; Login.Hide();
        };
    }
    public void OpenMain()
    {
        Login.ClearSecrets(); Login.Hide();
        if (!Dashboard.IsVisible) Dashboard.Show();
        Dashboard.Activate();
    }
    public LoginWindow OpenLogin()
    {
        if (!Login.IsVisible) { if (Dashboard.IsVisible) Login.Show(Dashboard); else Login.Show(); }
        Login.Activate(); return Login;
    }
    public InventoryWindow OpenInventory() => Get("inventory", () => new InventoryWindow(session));
    public SkillsWindow OpenSkills() => Get("skills", () => new SkillsWindow(session));
    public ExpeditionWindow OpenExpedition() => Get("expedition", () => new ExpeditionWindow(session), preserve: true);
    public NavigationWindow OpenNavigation() => Get("navigation", () => new NavigationWindow(session));
    public SettingsWindow OpenSettings(int tab = 0)
    {
        var window = Get("settings", () => new SettingsWindow(session, tab)); window.SelectTab(tab); return window;
    }
    public Window OpenInspector() => Get("inspector", () => new InspectorWindow());
    internal void RequestShutdown()
    {
        if (disposed || shutdownRequested) return;
        shutdownRequested = true;
        Dispatcher.UIThread.Post(async () => { await Login.StopAsync(); Dispose(); shutdown(); });
    }
    private T Get<T>(string key, Func<T> create, bool preserve = false) where T : Window
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        var generation = session.ReadView().Generation;
        if (features.TryGetValue(key, out var entry) && preserve && entry.Generation != generation)
        {
            // Hidden drafts are scoped to the account that created them. Reopening a
            // preserved window after a reset must load the new account's draft.
            entry.Window.Close();
            features.Remove(key); entry = null;
        }
        if (entry is null)
        {
            var window = create(); features.Add(key, entry = new(window, generation));
            var tracked = window;
            window.Closed += (_, _) =>
            {
                if (features.TryGetValue(key, out var current) && ReferenceEquals(current.Window, tracked)) features.Remove(key);
            };
            if (preserve) window.Closing += (_, args) =>
            {
                if (!disposed && session.ReadView().Generation == generation) { args.Cancel = true; tracked.Hide(); }
            };
        }
        if (!entry.Window.IsVisible) entry.Window.Show(Dashboard.IsVisible ? Dashboard : Login);
        entry.Window.Activate(); return (T)entry.Window;
    }
    public void Dispose()
    {
        if (disposed) return; disposed = true;
        foreach (var entry in features.Values.ToArray()) entry.Window.Close();
        features.Clear(); Login.ClearSecrets(); Login.Close(); Dashboard.Close();
    }
    private sealed record FeatureWindow(Window Window, long Generation);
}

internal sealed class InspectorWindow : DesktopWindow
{
    public InspectorWindow() : base("LaLa · 離線封包檢查", 960, 720)
    {
        var inspector = new ProtocolInspectorView(); SetBody(inspector);
        Closed += (_, _) => inspector.CancelInspection();
    }
}
