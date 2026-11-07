using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;
using Window = Avalonia.Controls.Window;

namespace Lala.Presentation;

public sealed class App : Avalonia.Application
{
    private ProtocolInspectorView? _view;
    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        Styles.Add(new FluentTheme());
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new Window
            {
                Title = "LaLa · C#/.NET 移植驗證", Width = 960, Height = 720,
                MinWidth = 400, MinHeight = 480, Content = CreateMainView(),
                Background = Avalonia.Media.Brush.Parse("#09192E")
            };
            desktop.Exit += (_, _) => SuspendInspection();
        }
        else if (ApplicationLifetime is IActivityApplicationLifetime activity)
            activity.MainViewFactory = CreateMainView;
        else if (ApplicationLifetime is ISingleViewApplicationLifetime single)
            single.MainView = CreateMainView();
        base.OnFrameworkInitializationCompleted();
    }

    private Control CreateMainView()
    {
        SuspendInspection();
        return _view = new ProtocolInspectorView();
    }

    // Android calls this on stop; no work or socket survives backgrounding.
    public void SuspendInspection() => _view?.CancelInspection();
}
