using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
using Lala.Android.Lifecycle;

namespace Lala.Android.Platform;

/// <summary>One process-wide coordinator holds cleanup across Service instances.</summary>
internal static class ConnectionRuntime
{
    // Replace only this factory when the real Core login/transport adapter exists.
    internal static readonly IConnectionAdapterFactory Factory = new UnavailableConnectionAdapterFactory();
    internal static readonly ConnectionCoordinator Coordinator = new(Factory);
    internal static readonly string ProcessToken = Guid.NewGuid().ToString("N");
    private static readonly ServiceOwnerLease Ownership = new();
    internal static long Acquire() => Ownership.Acquire();
    internal static bool IsOwner(long owner) => Ownership.IsCurrent(owner);
    internal static Task? Invoke(long owner, Func<Task> beginOperation) => Ownership.Invoke(owner, beginOperation);
}

[Service(Name = "io.lala.migration.ConnectionService", Exported = false,
    ForegroundServiceType = ForegroundService.TypeSpecialUse)]
public sealed class ConnectionService : Service
{
    internal const string StartAction = "io.lala.migration.START_CONNECTION";
    internal const string StopAction = "io.lala.migration.STOP_CONNECTION";
    internal const string TicketExtra = "request_ticket";
    internal const string ProcessExtra = "runtime_process";
    internal const string OwnerExtra = "runtime_owner";
    internal const string EpochExtra = "command_epoch";
    private readonly ServiceCommandState _commands = new();
    private Handler? _main;
    private IDisposable? _subscription;
    private AndroidNetworkMonitor? _network;
    private NotificationPolicyReceiver? _notificationReceiver;
    private ServiceBinder? _binder;
    private (string Ticket, ConnectionTarget Target, long Epoch)? _pending;
    private long _owner;
    private long _networkEpoch;
    private int _lastStartId;
    private bool _foreground;
    private bool _notificationStopRequested;
    private bool _notificationObserverReady = true;
    private volatile bool _destroyed;

    internal ConnectionCoordinator Coordinator => ConnectionRuntime.Coordinator;
    internal bool AdapterAvailable => ConnectionRuntime.Factory.IsAvailable;
    internal bool IsCurrentInstance => !_destroyed && ConnectionRuntime.IsOwner(_owner);
    internal HostIssue Issue { get; private set; }
    internal event Action? HostChanged;

    public override void OnCreate()
    {
        base.OnCreate();
        _owner = ConnectionRuntime.Acquire();
        _main = new Handler(Looper.MainLooper!);
        _binder = new ServiceBinder(this);
        RegisterNotificationObserver();
        _subscription = Coordinator.Subscribe(snapshot => Post(() => ApplySnapshot(snapshot)));
        // A new Service never restores a previous selection. These methods change
        // Core state synchronously; their returned Tasks only wait for cleanup.
        BeginOperation(() => Coordinator.StopAsync(ConnectionEndReason.Disposed), _commands.Epoch, stopping: true);
        BeginOperation(() => Coordinator.SetNetworkAvailableAsync(false), _commands.Epoch);
    }

    public override IBinder? OnBind(Intent? intent) => _binder;

    // Main-thread, bound/resumed Activity only. No account data enters an Intent.
    internal string PrepareStart(ConnectionTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        if (!IsCurrentInstance) throw new InvalidOperationException("connection_service_not_current");
        var ticket = Guid.NewGuid().ToString("N");
        var epoch = _commands.BeginStart();
        _pending = (ticket, target, epoch);
        ApplySnapshot(Coordinator.Snapshot);
        return ticket;
    }

    internal void CancelStart(string ticket)
    {
        if (_pending is not { } request || request.Ticket != ticket) return;
        _pending = null;
        _commands.CompleteStart(request.Epoch);
        ApplySnapshot(Coordinator.Snapshot);
    }

    public override StartCommandResult OnStartCommand(Intent? intent, StartCommandFlags flags, int startId)
    {
        _lastStartId = startId;
        if (intent?.Action == StopAction)
        {
            // A delayed notification action from a prior command, Service, or
            // process cannot stop the user's replacement session.
            if (intent.GetStringExtra(ProcessExtra) == ConnectionRuntime.ProcessToken &&
                intent.GetLongExtra(OwnerExtra, -1) == _owner &&
                _commands.IsCurrent(intent.GetLongExtra(EpochExtra, -1)))
                RequestStop();
            else if (_commands.CanFinish(IsRunning(Coordinator.Snapshot.Phase)))
                ApplySnapshot(Coordinator.Snapshot);
            return StartCommandResult.NotSticky;
        }

        // Expired start intents still need Android's foreground-start handshake;
        // after promotion they terminate without restoring any account/session.
        if (!Promote()) return StartCommandResult.NotSticky;
        var request = _pending;
        if (intent?.Action != StartAction || request is null ||
            intent.GetStringExtra(TicketExtra) != request.Value.Ticket ||
            !_commands.IsCurrent(request.Value.Epoch))
        {
            ApplySnapshot(Coordinator.Snapshot);
            return StartCommandResult.NotSticky;
        }

        _pending = null;
        var epoch = request.Value.Epoch;
        if (!ConnectionNotification.IsAllowed(this))
        {
            RejectForNotifications();
            return StartCommandResult.NotSticky;
        }
        _notificationStopRequested = false;
        if (!AdapterAvailable)
        {
            SetIssue(HostIssue.CoreUnavailable);
            BeginOperation(() => Coordinator.StartAsync(request.Value.Target), epoch, completingStart: true);
            return StartCommandResult.NotSticky;
        }

        SetIssue(HostIssue.None);
        try
        {
            if (_network is null)
            {
                var monitorEpoch = ++_networkEpoch;
                _network = new AndroidNetworkMonitor(this, available => Post(() =>
                {
                    if (_network is not null && monitorEpoch == _networkEpoch)
                        BeginOperation(() => Coordinator.SetNetworkAvailableAsync(available), _commands.Epoch);
                }));
                _network.Start();
            }
        }
        catch (AndroidNetworkMonitorException)
        {
            DisposeNetworkMonitor();
            SetIssue(HostIssue.NetworkMonitorUnavailable);
            RequestStop();
            return StartCommandResult.NotSticky;
        }
        BeginOperation(() => Coordinator.StartAsync(request.Value.Target), epoch, completingStart: true);
        return StartCommandResult.NotSticky;
    }

    internal void RequestStop(ConnectionEndReason reason = ConnectionEndReason.UserStopped)
    {
        if (!IsCurrentInstance) return;
        _pending = null;
        var epoch = _commands.BeginStop();
        BeginOperation(() => Coordinator.StopAsync(reason), epoch, stopping: true);
    }

    internal void RecheckNotificationPolicy()
    {
        if (!IsCurrentInstance) return;
        if (ConnectionNotification.IsAllowed(this))
        {
            _notificationStopRequested = false;
            if (Issue == HostIssue.NotificationRequired) SetIssue(HostIssue.None);
            return;
        }
        if (_foreground || _commands.StartPending || IsRunning(Coordinator.Snapshot.Phase))
            RejectForNotifications();
    }

    private void RejectForNotifications()
    {
        SetIssue(HostIssue.NotificationRequired);
        if (_notificationStopRequested) return;
        _notificationStopRequested = true;
        RequestStop();
    }

    // No boot receiver, alarm, WorkManager, sticky restart, or saved login.
    // Task removal keeps an already-started service; notification Stop remains.
    public override void OnTaskRemoved(Intent? rootIntent) => base.OnTaskRemoved(rootIntent);

    public override void OnTimeout(int startId)
    {
        StopForPlatform();
        if (OperatingSystem.IsAndroidVersionAtLeast(34)) base.OnTimeout(startId);
    }

    public override void OnTimeout(int startId, ForegroundService fgsType)
    {
        StopForPlatform();
        if (OperatingSystem.IsAndroidVersionAtLeast(35)) base.OnTimeout(startId, fgsType);
    }

    private void StopForPlatform()
    {
        SetIssue(HostIssue.PlatformStopped);
        RequestStop(); // Cancellation is issued synchronously before OS teardown.
        FinishForeground();
        StopStartedService();
    }

    private bool Promote()
    {
        try
        {
            if (!_notificationObserverReady) throw new InvalidOperationException("notification_observer_unavailable");
            ConnectionNotification.EnsureChannel(this);
            using var notification = ConnectionNotification.Build(this, Coordinator.Snapshot, _owner, _commands.Epoch);
            if (OperatingSystem.IsAndroidVersionAtLeast(34))
                StartForeground(ConnectionNotification.NotificationId, notification, ForegroundService.TypeSpecialUse);
            else
                StartForeground(ConnectionNotification.NotificationId, notification);
            _foreground = true;
            return true;
        }
        catch (Exception error) when (error is Java.Lang.RuntimeException or InvalidOperationException)
        {
            SetIssue(HostIssue.ServiceStartRejected);
            RequestStop();
            FinishForeground();
            StopStartedService();
            return false;
        }
    }

    private void ApplySnapshot(ConnectionSnapshot snapshot)
    {
        if (!IsCurrentInstance || snapshot != Coordinator.Snapshot) return;
        NotifyHost();
        if (!IsRunning(snapshot.Phase))
        {
            if (!_commands.CanFinish(connectionRunning: false)) return;
            DisposeNetworkMonitor();
            FinishForeground();
            StopStartedService();
            return;
        }
        if (!_foreground) return;
        if (!ConnectionNotification.IsAllowed(this))
        {
            RejectForNotifications();
            return;
        }
        try
        {
            using var notification = ConnectionNotification.Build(this, snapshot, _owner, _commands.Epoch);
            var manager = (NotificationManager?)GetSystemService(NotificationService)
                ?? throw new InvalidOperationException("notification_service_unavailable");
            manager.Notify(ConnectionNotification.NotificationId, notification);
        }
        catch (Exception error) when (error is Java.Lang.RuntimeException or InvalidOperationException)
        {
            RejectForNotifications();
        }
    }

    internal static bool IsRunning(ConnectionPhase phase) => phase is ConnectionPhase.WaitingForNetwork
        or ConnectionPhase.Connecting or ConnectionPhase.Active or ConnectionPhase.RetryWaiting
        or ConnectionPhase.Stopping or ConnectionPhase.CleanupBlocked;

    private void BeginOperation(Func<Task> beginOperation, long epoch, bool completingStart = false, bool stopping = false)
    {
        if (!IsCurrentInstance || !_commands.IsCurrent(epoch)) return;
        try
        {
            // Do not use an async delegate here: the mutation must occur inside
            // the lease check. Only the returned cleanup Task is observed later.
            var operation = ConnectionRuntime.Invoke(_owner, beginOperation);
            if (operation is not null)
                _ = ObserveOperationAsync(operation, epoch, completingStart, stopping);
        }
        catch (Exception)
        {
            HandleOperationFailure(epoch, stopping);
            CompleteOperation(epoch, completingStart);
        }
    }

    private async Task ObserveOperationAsync(Task operation, long epoch, bool completingStart, bool stopping)
    {
        try { await operation.ConfigureAwait(false); }
        catch (Exception) { Post(() => HandleOperationFailure(epoch, stopping)); }
        finally { Post(() => CompleteOperation(epoch, completingStart)); }
    }

    private void CompleteOperation(long epoch, bool completingStart)
    {
        if (!_commands.IsCurrent(epoch)) return;
        if (completingStart) _commands.CompleteStart(epoch);
        ApplySnapshot(Coordinator.Snapshot);
    }

    private void HandleOperationFailure(long epoch, bool stopping)
    {
        if (!_commands.IsCurrent(epoch)) return;
        SetIssue(HostIssue.RuntimeFailure);
        if (!stopping)
            RequestStop(ConnectionEndReason.AdapterFailure);
        else
        {
            // One recovery attempt only; never recursively queue failing stops.
            _commands.BeginStop();
            _pending = null;
            FinishForeground();
            StopStartedService();
        }
    }

    private void DisposeNetworkMonitor()
    {
        ++_networkEpoch;
        _network?.Dispose();
        _network = null;
    }

    private void FinishForeground()
    {
        if (!_foreground) return;
        _foreground = false;
        if (!ConnectionRuntime.IsOwner(_owner)) return;
        try
        {
            if (OperatingSystem.IsAndroidVersionAtLeast(24)) StopForeground(StopForegroundFlags.Remove);
            else RemoveForegroundOnApi23();
        }
        catch (Java.Lang.RuntimeException) { /* Platform already ended this service. */ }
    }

    [System.Diagnostics.CodeAnalysis.SuppressMessage("Interoperability", "CA1422",
        Justification = "API 23 fallback; flags overload requires API 24.")]
    private void RemoveForegroundOnApi23() => StopForeground(true);

    private void StopStartedService()
    {
        if (!ConnectionRuntime.IsOwner(_owner) || _lastStartId == 0) return;
        try { StopSelfResult(_lastStartId); }
        catch (Java.Lang.RuntimeException) { /* The OS may already be stopping it. */ }
    }

    private void SetIssue(HostIssue issue)
    {
        Issue = issue;
        NotifyHost();
    }

    private void NotifyHost()
    {
        if (HostChanged is null) return;
        foreach (Action observer in HostChanged.GetInvocationList())
        {
            try { observer(); }
            catch (Exception) { /* UI observer failures cannot interrupt cleanup. */ }
        }
    }

    private void Post(Action action)
    {
        if (_destroyed) return;
        try { _main?.Post(() => { if (IsCurrentInstance) action(); }); }
        catch (ObjectDisposedException) { /* Teardown won a race with this post. */ }
        catch (Java.Lang.RuntimeException) { /* Handler/looper no longer available. */ }
    }

    private void RegisterNotificationObserver()
    {
        if (!OperatingSystem.IsAndroidVersionAtLeast(28)) return;
        var receiver = new NotificationPolicyReceiver(this);
        try
        {
            using var filter = new IntentFilter(NotificationManager.ActionAppBlockStateChanged);
            filter.AddAction(NotificationManager.ActionNotificationChannelBlockStateChanged);
            if (OperatingSystem.IsAndroidVersionAtLeast(33)) RegisterReceiver(receiver, filter, ReceiverFlags.NotExported);
            else RegisterReceiver(receiver, filter);
            _notificationReceiver = receiver;
        }
        catch (Java.Lang.RuntimeException)
        {
            receiver.Dispose();
            _notificationObserverReady = false;
        }
    }

    public override void OnDestroy()
    {
        _destroyed = true;
        _commands.BeginStop();
        _pending = null;
        _subscription?.Dispose();
        DisposeNetworkMonitor();
        HostChanged = null;
        if (_notificationReceiver is { } receiver)
        {
            try { UnregisterReceiver(receiver); }
            catch (Java.Lang.RuntimeException) { /* Already removed by the OS. */ }
            _notificationReceiver = null;
        }
        FinishForeground();
        // Issue cancellation before returning from OnDestroy. A later completion
        // only observes this Task; it never issues a stale Stop to a new owner.
        try
        {
            var cleanup = ConnectionRuntime.Invoke(_owner, () => Coordinator.StopAsync(ConnectionEndReason.Disposed));
            if (cleanup is not null) _ = ObserveShutdownAsync(cleanup);
        }
        catch (Exception) { /* Fixed host state only, never platform/error text. */ }
        _binder?.Dispose();
        var handler = _main;
        _main = null;
        handler?.RemoveCallbacksAndMessages(null);
        handler?.Dispose();
        base.OnDestroy();
    }

    private static async Task ObserveShutdownAsync(Task cleanup)
    {
        try { await cleanup.ConfigureAwait(false); }
        catch (Exception) { /* Observe failures without retaining a Service. */ }
    }

    private sealed class NotificationPolicyReceiver(ConnectionService owner) : BroadcastReceiver
    {
        public override void OnReceive(Context? context, Intent? intent) => owner.RecheckNotificationPolicy();
    }

    internal sealed class ServiceBinder(ConnectionService service) : Binder
    {
        internal ConnectionService Service { get; } = service;
    }
}
