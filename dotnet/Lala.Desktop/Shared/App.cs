using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;

namespace Lala.Presentation;

public sealed class App : Application
{
    private ProtocolInspectorView? _view;
    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        Styles.Add(new FluentTheme());
    }

    public override void OnFrameworkInitializationCompleted()
    {
        _view = new ProtocolInspectorView();
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new Window
            {
                Title = "LaLa · C#/.NET 移植驗證", Width = 960, Height = 720,
                MinWidth = 400, MinHeight = 480, Content = _view,
                Background = Avalonia.Media.Brush.Parse("#09192E")
            };
            desktop.Exit += (_, _) => SuspendInspection();
        }
        else if (ApplicationLifetime is ISingleViewApplicationLifetime single)
            single.MainView = _view;
        base.OnFrameworkInitializationCompleted();
    }

    // Android calls this on stop; no work or socket survives backgrounding.
    public void SuspendInspection() => _view?.CancelInspection();
}
