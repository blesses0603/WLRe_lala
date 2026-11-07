namespace Lala.Android.Platform;

/// <summary>
/// Reduces network observations without retaining Android objects. The monitor
/// serializes access; this class deliberately performs no platform calls.
/// Availability means INTERNET plus VALIDATED, not game-server reachability.
/// </summary>
internal sealed class NetworkAvailability(bool defaultNetworkOnly)
{
    private readonly Dictionary<long, bool> _networks = [];
    private long? _defaultNetwork;
    private bool _receivedCallback;

    public bool IsAvailable => _networks.Values.Any(available => available);

    public void Initialize(long? network, bool hasInternet, bool validated)
    {
        // Register first, then take a snapshot. If callbacks arrived during that
        // query, their ordered observations take precedence over the snapshot.
        if (_receivedCallback)
            return;

        _networks.Clear();
        _defaultNetwork = network;
        if (network is { } identity)
            _networks[identity] = hasInternet && validated;
    }

    public void Available(long network)
    {
        _receivedCallback = true;
        if (defaultNetworkOnly && _defaultNetwork != network)
        {
            _defaultNetwork = network;
            _networks.Clear();
        }

        // onAvailable alone is not evidence of working internet. A duplicate
        // observation must not erase capabilities already supplied for this ID.
        _networks.TryAdd(network, false);
    }

    public void CapabilitiesChanged(long network, bool hasInternet, bool validated)
    {
        _receivedCallback = true;
        // Do not resurrect a lost or superseded network from a late callback.
        if (_networks.ContainsKey(network))
            _networks[network] = hasInternet && validated;
    }

    public void Lost(long network)
    {
        _receivedCallback = true;
        _networks.Remove(network);
        if (_defaultNetwork == network)
            _defaultNetwork = null;
    }
}
