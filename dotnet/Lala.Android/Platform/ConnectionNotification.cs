using Android.App;
using Android.Content;
using Android.Content.PM;
using Lala.Android.Lifecycle;

namespace Lala.Android.Platform;

internal static class ConnectionNotification
{
    internal const string ChannelId = "lala.connection";
    internal const int NotificationId = 7901;

    internal static bool IsAllowed(Context context)
    {
        try
        {
            if (OperatingSystem.IsAndroidVersionAtLeast(33) &&
                context.CheckSelfPermission(global::Android.Manifest.Permission.PostNotifications) != Permission.Granted)
                return false;
            // Already supplied by Avalonia's AndroidX.Core dependency. Compat
            // also checks app-wide blocking on our minimum supported API 23.
            using var compat = global::AndroidX.Core.App.NotificationManagerCompat.From(context);
            if (compat is null || !compat.AreNotificationsEnabled()) return false;
            var manager = (NotificationManager?)context.GetSystemService(Context.NotificationService);
            if (manager is null) return false;
            if (OperatingSystem.IsAndroidVersionAtLeast(26))
            {
                using var channel = manager.GetNotificationChannel(ChannelId);
                if (channel?.Importance == NotificationImportance.None) return false;
            }
            return true;
        }
        catch (Java.Lang.RuntimeException)
        {
            // Fail closed without surfacing platform exception text in the UI.
            return false;
        }
    }

    internal static void EnsureChannel(Context context)
    {
        if (!OperatingSystem.IsAndroidVersionAtLeast(26)) return;
        var manager = (NotificationManager?)context.GetSystemService(Context.NotificationService)
            ?? throw new InvalidOperationException("Notification service unavailable.");
        using var channel = new NotificationChannel(ChannelId, "LaLa 連線狀態", NotificationImportance.Low)
        {
            Description = "顯示使用者啟動的連線狀態，並提供停止操作。",
            LockscreenVisibility = NotificationVisibility.Private
        };
        manager.CreateNotificationChannel(channel);
    }

    internal static Notification Build(Context context, ConnectionSnapshot snapshot, long owner, long epoch)
    {
        using var openIntent = new Intent(context, typeof(MainActivity))
            .SetFlags(ActivityFlags.SingleTop | ActivityFlags.ClearTop);
        using var stopIntent = new Intent(context, typeof(ConnectionService)).SetAction(ConnectionService.StopAction)
            .PutExtra(ConnectionService.ProcessExtra, ConnectionRuntime.ProcessToken)
            .PutExtra(ConnectionService.OwnerExtra, owner)
            .PutExtra(ConnectionService.EpochExtra, epoch);
        var immutable = PendingIntentFlags.UpdateCurrent | PendingIntentFlags.Immutable;
        var open = PendingIntent.GetActivity(context, 0, openIntent, immutable);
        var stop = PendingIntent.GetService(context, 1, stopIntent, immutable);
        using var builder = OperatingSystem.IsAndroidVersionAtLeast(26)
            ? new Notification.Builder(context, ChannelId)
            : CreateLegacyBuilder(context);
        builder.SetContentTitle("LaLa 連線")
            .SetContentText(ConnectionStatusText.Describe(snapshot))
            .SetSmallIcon(Resource.Drawable.ic_connection)
            .SetVisibility(NotificationVisibility.Private)
            .SetOngoing(true)
            .SetOnlyAlertOnce(true)
            .SetContentIntent(open)
            .SetCategory(Notification.CategoryService);
        // No account IDs, endpoints, credentials, payloads or exception messages.
        using var icon = global::Android.Graphics.Drawables.Icon.CreateWithResource(context, Resource.Drawable.ic_connection);
        using var actionBuilder = new Notification.Action.Builder(icon, "停止連線", stop);
        using var action = actionBuilder.Build();
        builder.AddAction(action);
        return builder.Build();
    }

    [System.Diagnostics.CodeAnalysis.SuppressMessage("Interoperability", "CA1422",
        Justification = "API 23-25 fallback; channel constructor requires API 26.")]
    private static Notification.Builder CreateLegacyBuilder(Context context) => new(context);
}
