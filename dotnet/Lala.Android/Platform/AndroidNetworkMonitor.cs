using System.Threading.Channels;
using global::Android.Content;
using global::Android.Net;

namespace Lala.Android.Platform;

public enum AndroidNetworkMonitorFailure
{
    ServiceUnavailable,
    PermissionDenied,
    PlatformFailure,
}

/// <summary>A fixed failure category; no platform exception or sensitive text is retained.</summary>
public sealed class AndroidNetworkMonitorException(AndroidNetworkMonitorFailure failure)
    : Exception("android_network_monitor_start_failed")
{
    public AndroidNetworkMonitorFailure Failure { get; } = failure;
}

/// <summary>
/// Service-owned network observations. Call Start once, and dispose with the
/// service. INTERNET plus VALIDATED is a scheduling hint, not proof that the game
/// server is reachable. Notifications run on a worker and must be short and
/// nonthrowing (enqueue the coordinator command rather than wait for its IO).
/// </summary>
public sealed class AndroidNetworkMonitor : IDisposable
{
    private readonly object _gate = new();
    private readonly Action<bool> _onAvailabilityChanged;
    private readonly Channel<Observation> _observations = Channel.CreateUnbounded<Observation>(
        new UnboundedChannelOptions { SingleReader = true, AllowSynchronousContinuations = false });
    private Context? _context;
    private ConnectivityManager? _manager;
    private Callback? _callback;
    private bool _started;
    private bool _registrationAttempted;
    private int _disposed;

    public AndroidNetworkMonitor(Context context, Action<bool> onAvailabilityChanged)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(onAvailabilityChanged);
        _context = context.ApplicationContext ?? context;
        _onAvailabilityChanged = onAvailabilityChanged;
    }

    public void Start()
    {
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
            if (_started)
                return;

            try
            {
                _manager = _context?.GetSystemService(Context.ConnectivityService) as ConnectivityManager
                    ?? throw new AndroidNetworkMonitorException(AndroidNetworkMonitorFailure.ServiceUnavailable);
                _context = null;
                var defaultNetworkOnly = OperatingSystem.IsAndroidVersionAtLeast(24);
                var state = new NetworkAvailability(defaultNetworkOnly);
                _callback = new Callback(this);
                _registrationAttempted = true;

                if (OperatingSystem.IsAndroidVersionAtLeast(24))
                {
                    _manager.RegisterDefaultNetworkCallback(_callback);
                }
                else
                {
                    // API 23 has no default-network callback. Track every
                    // matching identity so losing Wi-Fi does not erase mobile.
                    using var builder = new NetworkRequest.Builder();
                    builder.AddCapability(NetCapability.Internet);
                    using var request = builder.Build()
                        ?? throw new AndroidNetworkMonitorException(AndroidNetworkMonitorFailure.PlatformFailure);
                    _manager.RegisterNetworkCallback(request, _callback);
                }

                // This one synchronous snapshot is outside Android callbacks.
                // Registration happens first so a concurrent loss cannot leave
                // an old online snapshot without a corresponding callback.
                using var currentNetwork = _manager.ActiveNetwork;
                using var capabilities = currentNetwork is null
                    ? null
                    : _manager.GetNetworkCapabilities(currentNetwork);
                _observations.Writer.TryWrite(new Observation(
                    ObservationKind.Initialize,
                    currentNetwork?.NetworkHandle,
                    capabilities?.HasCapability(NetCapability.Internet) == true,
                    capabilities?.HasCapability(NetCapability.Validated) == true));
                _started = true;
                _ = Task.Run(() => ProcessObservationsAsync(state));
            }
            catch (AndroidNetworkMonitorException)
            {
                Dispose();
                throw;
            }
            catch (Java.Lang.SecurityException)
            {
                Dispose();
                throw new AndroidNetworkMonitorException(AndroidNetworkMonitorFailure.PermissionDenied);
            }
            catch (Java.Lang.RuntimeException)
            {
                Dispose();
                throw new AndroidNetworkMonitorException(AndroidNetworkMonitorFailure.PlatformFailure);
            }
        }
    }

    private async Task ProcessObservationsAsync(NetworkAvailability state)
    {
        bool? lastAvailability = null;
        await foreach (var observation in _observations.Reader.ReadAllAsync().ConfigureAwait(false))
        {
            lock (_gate)
            {
                if (Volatile.Read(ref _disposed) != 0)
                    return;

                switch (observation.Kind)
                {
                    case ObservationKind.Initialize:
                        state.Initialize(observation.Network, observation.HasInternet, observation.Validated);
                        break;
                    case ObservationKind.Available when observation.Network is { } availableNetwork:
                        state.Available(availableNetwork);
                        break;
                    case ObservationKind.Capabilities when observation.Network is { } changedNetwork:
                        state.CapabilitiesChanged(changedNetwork, observation.HasInternet, observation.Validated);
                        break;
                    case ObservationKind.Lost when observation.Network is { } lostNetwork:
                        state.Lost(lostNetwork);
                        break;
                }

                var available = state.IsAvailable;
                if (lastAvailability == available)
                    continue;
                lastAvailability = available;
                // Serialize delivery with Dispose. No action can begin after
                // Dispose returns, including already queued native callbacks.
                try
                {
                    _onAvailabilityChanged(available);
                }
                catch (Exception)
                {
                    // A broken consumer cannot leave an unobserved worker or
                    // retain the Android callback. No exception text is logged.
                    Dispose();
                    return;
                }
            }
        }
    }

    private void Enqueue(Observation observation)
    {
        // Android callbacks only copy primitive values and enqueue; no locks,
        // synchronous ConnectivityManager queries, transport work, or UI work.
        if (Volatile.Read(ref _disposed) == 0)
            _observations.Writer.TryWrite(observation);
    }

    public void Dispose()
    {
        lock (_gate)
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
                return;

            _observations.Writer.TryComplete();
            if (_registrationAttempted && _manager is not null && _callback is not null)
            {
                try
                {
                    _manager.UnregisterNetworkCallback(_callback);
                }
                catch (Java.Lang.IllegalArgumentException)
                {
                    // A failed registration has no callback to unregister.
                }
                catch (Java.Lang.SecurityException)
                {
                    // Permission may have changed; the closed queue still
                    // rejects every callback for this disposed monitor.
                }
                catch (Java.Lang.RuntimeException)
                {
                    // The platform may be shutting down. Dispose still closes
                    // this monitor and must not replace a fixed start failure
                    // with an unsanitized platform exception.
                }
            }

            _context = null;
            _callback = null;
            _manager = null;
        }
    }

    private enum ObservationKind { Initialize, Available, Capabilities, Lost }

    private readonly record struct Observation(
        ObservationKind Kind, long? Network, bool HasInternet = false, bool Validated = false);

    private sealed class Callback(AndroidNetworkMonitor owner) : ConnectivityManager.NetworkCallback
    {
        public override void OnAvailable(Network network)
            => owner.Enqueue(new Observation(ObservationKind.Available, network.NetworkHandle));

        public override void OnCapabilitiesChanged(Network network, NetworkCapabilities networkCapabilities)
            => owner.Enqueue(new Observation(
                ObservationKind.Capabilities,
                network.NetworkHandle,
                networkCapabilities.HasCapability(NetCapability.Internet),
                networkCapabilities.HasCapability(NetCapability.Validated)));

        public override void OnLost(Network network)
            => owner.Enqueue(new Observation(ObservationKind.Lost, network.NetworkHandle));
    }
}
