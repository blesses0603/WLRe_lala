using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Lala.Android.Platform;
using Lala.Presentation;
using Button = Avalonia.Controls.Button;
using Orientation = Avalonia.Layout.Orientation;

namespace Lala.Android;

internal sealed class AndroidMainView : UserControl
{
    private readonly ProtocolInspectorView _inspector = new();
    private readonly TextBlock _state = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _permission = new() { TextWrapping = TextWrapping.Wrap };
    private readonly Button _stop = new() { Content = "停止連線", MinHeight = 44, IsEnabled = false };
    private IDisposable? _subscription;
    private long _subscriptionGeneration;

    internal AndroidMainView()
    {
        var notifications = new Button { Content = "設定連線通知", MinHeight = 44 };
        var refresh = new Button { Content = "重新讀取狀態", MinHeight = 44 };
        notifications.Click += (_, _) => ConnectionServiceClient.Instance.RequestNotificationsFromUser();
        refresh.Click += (_, _) => ConnectionServiceClient.Instance.RefreshFromUser();
        _stop.Click += (_, _) => ConnectionServiceClient.Instance.StopFromUser();
        var connection = new ScrollViewer
        {
            Content = new StackPanel
            {
                Margin = new Thickness(20), Spacing = 16,
                Children =
                {
                    new TextBlock { Text = "LaLa · Android 連線", FontSize = 26, FontWeight = FontWeight.Bold,
                        Foreground = Brush.Parse("#82CFFF"), TextWrapping = TextWrapping.Wrap },
                    new Border { Padding = new Thickness(16), Background = Brush.Parse("#16314D"),
                        CornerRadius = new CornerRadius(8), Child = _state },
                    _permission,
                    new TextBlock { Text = "共用登入與連線核心仍在建立，目前無法登入遊戲。連線入口將在核心接入後提供。", TextWrapping = TextWrapping.Wrap },
                    new WrapPanel { Orientation = Orientation.Horizontal, Children = { notifications, refresh, _stop } },
                    new TextBlock { Text = "之後由你手動開始連線。切換畫面只重新取得服務狀態；停止會取消重試並釋放連線。程式遭系統結束後不會自動登入。", TextWrapping = TextWrapping.Wrap }
                }
            }
        };
        Content = new TabControl
        {
            ItemsSource = new[]
            {
                new TabItem { Header = "連線狀態", Content = connection },
                new TabItem { Header = "離線封包檢查", Content = _inspector }
            }
        };
        AttachedToVisualTree += (_, _) => AttachHost();
        DetachedFromVisualTree += (_, _) => { DetachHost(); CancelInspection(); };
    }

    private void AttachHost()
    {
        DetachHost();
        var generation = ++_subscriptionGeneration;
        _subscription = ConnectionServiceClient.Instance.Subscribe(snapshot =>
            Dispatcher.UIThread.Post(() =>
            {
                if (generation == _subscriptionGeneration) Render(snapshot);
            }));
    }

    internal void DetachHost()
    {
        ++_subscriptionGeneration;
        _subscription?.Dispose();
        _subscription = null;
    }

    internal void CancelInspection() => _inspector.CancelInspection();

    private void Render(ConnectionHostSnapshot snapshot)
    {
        _state.Text = snapshot.Issue switch
        {
            HostIssue.NotificationRequired => "請先允許連線通知，再手動開始連線。",
            HostIssue.ReturnToApp => "請返回 App 畫面後操作。",
            HostIssue.ServiceStartRejected => "Android 暫時不允許啟動服務，請返回 App 後再試。",
            HostIssue.ServiceDisconnected => "目前未綁定連線服務，可按「重新讀取狀態」。",
            HostIssue.NetworkMonitorUnavailable => "無法取得網路狀態，連線已暫停。",
            HostIssue.RuntimeFailure => "連線工作失敗，已要求停止並清理。",
            HostIssue.PlatformStopped => "Android 已停止連線服務，請手動重新開始。",
            _ when !snapshot.CoreAvailable => "共用連線核心尚未接入；未連線遊戲。",
            _ => ConnectionStatusText.Describe(snapshot.Connection)
        };
        _permission.Text = snapshot.NotificationsAllowed
            ? "連線通知：已允許。允許通知不會自動登入。"
            : "連線通知：尚未允許。背景連線會等待你開啟通知。";
        _stop.IsEnabled = snapshot.Bound && ConnectionService.IsRunning(snapshot.Connection.Phase);
    }
}
