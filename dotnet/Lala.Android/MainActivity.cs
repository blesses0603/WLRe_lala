using Android.App;
using Android.Content.PM;
using Avalonia.Android;
using Lala.Presentation;

namespace Lala.Android;

[Activity(Label = "LaLa 核心驗證", Theme = "@style/LaLaTheme", MainLauncher = true, Exported = true,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.ScreenSize | ConfigChanges.UiMode)]
public sealed class MainActivity : AvaloniaMainActivity<App>
{
    protected override void OnStop()
    {
        // Never retain pending work when the activity goes into the background.
        (Avalonia.Application.Current as App)?.SuspendInspection();
        base.OnStop();
    }
}
