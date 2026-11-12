using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;

namespace Lala.Android;

public sealed class AndroidApp : Avalonia.Application
{
    private AndroidMainView? _view;
    private Preview.MobilePreviewView? _preview;
    private readonly Preview.MobilePreviewState _previewState = new() { Page = 2 };

    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        var theme = new FluentTheme();
        theme.Palettes[ThemeVariant.Dark] = new ColorPaletteResources { Accent = Avalonia.Media.Color.Parse("#35DDE3") };
        Styles.Add(theme);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IActivityApplicationLifetime activity)
            activity.MainViewFactory = CreateView;
        base.OnFrameworkInitializationCompleted();
    }

    private Control CreateView()
    {
        SuspendInspection();
        _view?.DetachHost();
        _preview?.Suspend();
        _view = null;
        var client = Platform.OfficialAndroidClient.Instance;
        var view = _preview = new Preview.MobilePreviewView(_previewState, () => _view = new AndroidMainView(), client);
        if (!client.Snapshot.ResourcesReady && !client.Snapshot.Busy) _ = client.RefreshAsync();
        return view;
    }

    public void SuspendInspection() { _preview?.Suspend(); _view?.CancelInspection(); }
    public void ResumeInspection() => _preview?.Resume();
}
