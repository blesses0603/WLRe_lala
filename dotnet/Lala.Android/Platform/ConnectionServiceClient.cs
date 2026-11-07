using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
using Android.Provider;
using Lala.Android.Lifecycle;

namespace Lala.Android.Platform;

internal enum HostIssue
{
    None, CoreUnavailable, NotificationRequired, ReturnToApp, ServiceStartRejected,
    ServiceDisconnected, NetworkMonitorUnavailable, RuntimeFailure, PlatformStopped
}

internal sealed record ConnectionHostSnapshot(ConnectionSnapshot Connection, bool Bound,
    bool NotificationsAllowed, bool CoreAvailable, HostIssue Issue);

/// <summary>UI-facing main-thread binding. No socket, account state or retry loop lives here.</summary>
internal sealed class ConnectionServiceClient
{
    internal static ConnectionServiceClient Instance { get; } = new();
    internal const int NotificationRequest = 7902;
    private const string PermissionPreferences = "lala.permission_metadata";
    private const string NotificationsRequestedKey = "notifications_requested";
    private Context Context => global::Android.App.Application.Context;
    private WeakReference<MainActivity>? _activity;
    private ConnectionService? _service;
    private Binding? _binding;
    private bool _resumed;
    private HostIssue _issue;
    private ConnectionSnapshot _last = new(0, 0, ConnectionPhase.Stopped, 0, ConnectionEndReason.None);
    private event Action<ConnectionHostSnapshot>? Changed;

    internal ConnectionHostSnapshot Snapshot => new(_service?.Coordinator.Snapshot ?? _last,
        _service?.IsCurrentInstance == true, ConnectionNotification.IsAllowed(Context),
        ConnectionRuntime.Factory.IsAvailable, _issue != HostIssue.None ? _issue : _service?.Issue ?? HostIssue.None);

    internal IDisposable Subscribe(Action<ConnectionHostSnapshot> observer)
    {
        ArgumentNullException.ThrowIfNull(observer);
        Changed += observer;
        try { observer(Snapshot); }
        catch (Exception) { Changed -= observer; }
        return new Subscription(() => Changed -= observer);
    }

    internal void Attach(MainActivity activity)
    {
        if (CurrentActivity() != activity) _resumed = false;
        _activity = new(activity);
        Bind();
    }

    internal void SetResumed(MainActivity activity, bool resumed)
    {
        if (CurrentActivity() != activity) return;
        _resumed = resumed;
        if (resumed)
        {
            _service?.RecheckNotificationPolicy();
            Publish();
        }
    }

    internal void Detach(MainActivity activity)
    {
        if (CurrentActivity() != activity) return;
        _resumed = false;
        _activity = null;
        Unbind(); // Does not stop a started foreground service.
    }

    private MainActivity? CurrentActivity() => _activity?.TryGetTarget(out var activity) == true ? activity : null;

    internal void RefreshFromUser()
    {
        if (!_resumed || CurrentActivity() is null) { SetIssue(HostIssue.ReturnToApp); return; }
        _issue = HostIssue.None;
        if (_service is null) Unbind();
        Bind();
        _service?.RecheckNotificationPolicy();
        Publish();
    }

    private void Bind()
    {
        if (_binding is not null) return;
        var binding = new Binding(this);
        _binding = binding;
        try
        {
            using var intent = new Intent(Context, typeof(ConnectionService));
            if (!Context.BindService(intent, binding, global::Android.Content.Bind.AutoCreate))
            {
                _binding = null;
                _issue = HostIssue.ServiceDisconnected;
            }
        }
        catch (Java.Lang.RuntimeException)
        {
            _binding = null;
            _issue = HostIssue.ServiceStartRejected;
        }
        Publish();
    }

    private void Unbind()
    {
        // Invalidate identity before platform calls: a queued callback from this
        // registration must never attach to a later Activity/binding.
        var binding = _binding;
        _binding = null;
        if (_service is not null)
        {
            _last = _service.Coordinator.Snapshot;
            _service.HostChanged -= Publish;
            _service = null;
        }
        if (binding is not null)
        {
            try { Context.UnbindService(binding); }
            catch (Java.Lang.RuntimeException) { /* Binding already removed by Android. */ }
        }
        _issue = HostIssue.ServiceDisconnected;
        Publish();
    }

    private void Connected(Binding binding, IBinder? binder)
    {
        if (!ReferenceEquals(_binding, binding) || CurrentActivity() is null) return;
        if (binder is not ConnectionService.ServiceBinder local || !local.Service.IsCurrentInstance)
        {
            Unbind();
            SetIssue(HostIssue.ServiceDisconnected);
            return;
        }
        if (_service is not null) _service.HostChanged -= Publish;
        _service = local.Service;
        _service.HostChanged += Publish;
        _issue = HostIssue.None;
        if (_resumed) _service.RecheckNotificationPolicy();
        Publish();
    }

    private void Disconnected(Binding binding, bool mustRebind)
    {
        if (!ReferenceEquals(_binding, binding)) return;
        if (mustRebind) Unbind();
        else if (_service is not null)
        {
            _last = _service.Coordinator.Snapshot;
            _service.HostChanged -= Publish;
            _service = null;
        }
        SetIssue(HostIssue.ServiceDisconnected);
    }

    /// <summary>Future login UI calls this only after its own resource/account checks.
    /// A target contains an opaque account reference, never a password/token.
    /// Binding, resume, and permission callbacks never start a connection.</summary>
    internal bool StartFromUser(ConnectionTarget target)
    {
        ArgumentNullException.ThrowIfNull(target);
        var activity = CurrentActivity();
        if (!_resumed || activity is null) { SetIssue(HostIssue.ReturnToApp); return false; }
        var service = _service;
        if (service?.IsCurrentInstance != true) { SetIssue(HostIssue.ServiceDisconnected); return false; }
        if (!service.AdapterAvailable) { SetIssue(HostIssue.CoreUnavailable); return false; }
        if (!ConnectionNotification.IsAllowed(Context)) { SetIssue(HostIssue.NotificationRequired); return false; }
        _issue = HostIssue.None;
        string? ticket = null;
        try
        {
            ticket = service.PrepareStart(target);
            using var intent = new Intent(activity, typeof(ConnectionService))
                .SetAction(ConnectionService.StartAction).PutExtra(ConnectionService.TicketExtra, ticket);
            if (OperatingSystem.IsAndroidVersionAtLeast(26)) activity.StartForegroundService(intent);
            else activity.StartService(intent);
            Publish();
            return true; // Request accepted, not proof of connection or login.
        }
        catch (Exception error) when (error is Java.Lang.RuntimeException or InvalidOperationException)
        {
            if (ticket is not null) service.CancelStart(ticket);
            SetIssue(HostIssue.ServiceStartRejected);
            return false;
        }
    }

    internal void StopFromUser()
    {
        if (_service?.IsCurrentInstance != true) { SetIssue(HostIssue.ServiceDisconnected); return; }
        _issue = HostIssue.None;
        _service.RequestStop();
        Publish();
    }

    internal void RequestNotificationsFromUser()
    {
        var activity = CurrentActivity();
        if (!_resumed || activity is null) { SetIssue(HostIssue.ReturnToApp); return; }
        try
        {
            if (OperatingSystem.IsAndroidVersionAtLeast(33) &&
                activity.CheckSelfPermission(global::Android.Manifest.Permission.PostNotifications) != Permission.Granted)
            {
                using var preferences = Context.GetSharedPreferences(PermissionPreferences, FileCreationMode.Private);
                var canExplainAndRequest = activity.ShouldShowRequestPermissionRationale(
                    global::Android.Manifest.Permission.PostNotifications);
                // Rationale=false can mean a first request or a dialog Android
                // will suppress. Retain only this UX flag, never account data.
                // If metadata is unavailable, the settings route remains usable.
                if (canExplainAndRequest || preferences?.GetBoolean(NotificationsRequestedKey, false) == false)
                {
                    using var editor = preferences?.Edit();
                    editor?.PutBoolean(NotificationsRequestedKey, true);
                    editor?.Apply();
                    activity.RequestPermissions([global::Android.Manifest.Permission.PostNotifications], NotificationRequest);
                    return;
                }
                // Already requested with no rationale: open settings instead of
                // repeatedly invoking a dialog that may never appear.
            }
            using var intent = OperatingSystem.IsAndroidVersionAtLeast(26)
                ? new Intent(Settings.ActionAppNotificationSettings).PutExtra(Settings.ExtraAppPackage, Context.PackageName)
                : new Intent(Settings.ActionApplicationDetailsSettings,
                    global::Android.Net.Uri.Parse("package:" + Context.PackageName));
            activity.StartActivity(intent);
        }
        catch (Java.Lang.RuntimeException) { SetIssue(HostIssue.NotificationRequired); }
    }

    internal void OnNotificationResult()
    {
        // Permission approval never starts or restores a connection.
        _issue = ConnectionNotification.IsAllowed(Context) ? HostIssue.None : HostIssue.NotificationRequired;
        _service?.RecheckNotificationPolicy();
        Publish();
    }

    private void SetIssue(HostIssue issue) { _issue = issue; Publish(); }

    private void Publish()
    {
        var snapshot = Snapshot;
        _last = snapshot.Connection;
        if (Changed is null) return;
        foreach (Action<ConnectionHostSnapshot> observer in Changed.GetInvocationList())
        {
            try { observer(snapshot); }
            catch (Exception) { /* A detached UI cannot interrupt service ownership. */ }
        }
    }

    // A fresh instance per registration gives every callback an unambiguous
    // identity, including late callbacks after rotation or process teardown.
    private sealed class Binding(ConnectionServiceClient owner) : Java.Lang.Object, IServiceConnection
    {
        public void OnServiceConnected(ComponentName? name, IBinder? binder) => owner.Connected(this, binder);
        public void OnServiceDisconnected(ComponentName? name) => owner.Disconnected(this, mustRebind: false);
        public void OnBindingDied(ComponentName? name) => owner.Disconnected(this, mustRebind: true);
        public void OnNullBinding(ComponentName? name) => owner.Disconnected(this, mustRebind: true);
    }

    private sealed class Subscription(Action unsubscribe) : IDisposable
    {
        private Action? _unsubscribe = unsubscribe;
        public void Dispose() => Interlocked.Exchange(ref _unsubscribe, null)?.Invoke();
    }
}
