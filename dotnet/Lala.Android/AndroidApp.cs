using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;

namespace Lala.Android;

public sealed class AndroidApp : Avalonia.Application
{
    private AndroidMainView? _view;

    public override void Initialize()
    {
        RequestedThemeVariant = ThemeVariant.Dark;
        Styles.Add(new FluentTheme());
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
        return _view = new AndroidMainView();
    }

    public void SuspendInspection() => _view?.CancelInspection();
}
