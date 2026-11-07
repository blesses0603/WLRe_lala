using Android.App;
using Android.Content.PM;
using Avalonia.Android;
using Lala.Android.Platform;

namespace Lala.Android;

[Activity(Label = "LaLa 核心驗證", Theme = "@style/LaLaTheme", MainLauncher = true, Exported = true,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.ScreenSize | ConfigChanges.UiMode)]
public sealed class MainActivity : AvaloniaMainActivity
{
    protected override void OnStart()
    {
        base.OnStart();
        ConnectionServiceClient.Instance.Attach(this);
    }

    protected override void OnResume()
    {
        base.OnResume();
        ConnectionServiceClient.Instance.SetResumed(this, true);
    }

    protected override void OnPause()
    {
        ConnectionServiceClient.Instance.SetResumed(this, false);
        base.OnPause();
    }

    protected override void OnStop()
    {
        // Only view-local work is cancelled; a started service owns the session.
        (Avalonia.Application.Current as AndroidApp)?.SuspendInspection();
        ConnectionServiceClient.Instance.Detach(this);
        base.OnStop();
    }

    public override void OnRequestPermissionsResult(int requestCode, string[] permissions, Permission[] grantResults)
    {
        base.OnRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == ConnectionServiceClient.NotificationRequest)
            ConnectionServiceClient.Instance.OnNotificationResult();
    }
}
