using System.Security.Cryptography;
using System.Text;
using Lala.Core.Resources;

namespace Lala.Core.Sessions.Discovery;

internal interface IOfficialServerDiscoverySource : IDisposable
{
    ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token);
    ValueTask<byte[]> FetchAsync(string dataVersion, CancellationToken token);
}

/// <summary>Explicit, read-only server metadata discovery. Construction performs no I/O.
/// No credentials, game socket, default line, verification endpoint, profile or database is used.</summary>
public sealed class OfficialServerDiscovery : IDisposable
{
    private readonly object _gate = new();
    private readonly IOfficialServerDiscoverySource _source;
    private readonly string _host;
    private readonly bool _production;
    private OfficialServerCandidateSnapshot? _current;
    private bool _refreshing, _disposed, _cleanupFailed, _disposalComplete;

    // The public route never accepts a source, handler, clock, URL or claimed origin evidence.
    public static OfficialServerDiscovery Create(string officialHost = OfficialResourceOrigin.DefaultHost)
    {
        string host = OfficialResourceOrigin.SelectHost(officialHost);
        return new(host, new HttpOfficialServerDiscoverySource(host), production: true);
    }
    internal static OfficialServerDiscovery CreateForOfflineTests(IOfficialServerDiscoverySource source,
        string host = OfficialResourceOrigin.DefaultHost)
        => new(OfficialResourceOrigin.SelectHost(host), source, production: false);
    private OfficialServerDiscovery(string host, IOfficialServerDiscoverySource source, bool production)
        => (_host, _source, _production) = (host, source ?? throw new ArgumentNullException(nameof(source)), production);

    /// <summary>Last successful historical snapshot; failed refreshes do not replace it.
    /// No automatic refresh, cache persistence, stale-fresh guarantee or endpoint selection.</summary>
    public OfficialServerCandidateSnapshot? Current { get { lock (_gate) return _current; } }

    /// <summary>One refresh at a time. Observe versions, fetch exact ServerList.txt, observe
    /// versions again, validate all rows, then publish atomically after request cleanup.</summary>
    public async Task<OfficialServerCandidateSnapshot> RefreshAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        lock (_gate)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            if (_cleanupFailed) throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Cleanup);
            if (_refreshing) throw new InvalidOperationException("Server discovery is already refreshing");
            _refreshing = true;
        }
        try
        {
            var before = await _source.ObserveAsync(cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            string url = ExactUrl(_host, before.DataVersion);
            byte[] raw = await _source.FetchAsync(before.DataVersion, cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            var after = await _source.ObserveAsync(cancellationToken).ConfigureAwait(false);
            cancellationToken.ThrowIfCancellationRequested();
            if (!before.HasSameIdentity(after)) throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.VersionChanged);
            var lines = OfficialServerListParser.Parse(raw, cancellationToken);
            string hash = ResourceValidation.Digest(raw, cancellationToken);
            using var identity = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            identity.AppendData(Encoding.ASCII.GetBytes(url));
            identity.AppendData(new byte[] { 0 });
            identity.AppendData(raw);
            var result = new OfficialServerCandidateSnapshot(before, url, hash,
                Convert.ToHexStringLower(identity.GetHashAndReset()), lines, _production);
            lock (_gate)
            {
                cancellationToken.ThrowIfCancellationRequested();
                ObjectDisposedException.ThrowIf(_disposed, this);
                if (_cleanupFailed) throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Cleanup);
                return _current = result;
            }
        }
        catch (OperationCanceledException error) when (cancellationToken.IsCancellationRequested)
        {
            var sanitized = new OperationCanceledException(cancellationToken);
            PreserveCleanup(error, sanitized);
            throw sanitized;
        }
        catch (OfficialServerDiscoveryException error)
        {
            if (error.Failure == OfficialServerDiscoveryFailure.Cleanup || error.Data.Contains(ResourceCleanup.FailureMarker))
                lock (_gate) _cleanupFailed = true;
            throw;
        }
        catch (ObjectDisposedException error)
        {
            var sanitized = new ObjectDisposedException(nameof(OfficialServerDiscovery));
            PreserveCleanup(error, sanitized);
            throw sanitized;
        }
        catch (ResourceValidationException) { throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.InvalidVersion); }
        catch (ResourceTransportException error)
        {
            var failure = error.Failure == ResourceTransportFailure.Timeout ? OfficialServerDiscoveryFailure.Timeout :
                error.Failure == ResourceTransportFailure.Cleanup ? OfficialServerDiscoveryFailure.Cleanup : OfficialServerDiscoveryFailure.Transport;
            var sanitized = new OfficialServerDiscoveryException(failure);
            PreserveCleanup(error, sanitized);
            if (failure == OfficialServerDiscoveryFailure.Cleanup) lock (_gate) _cleanupFailed = true;
            throw sanitized;
        }
        catch (Exception) { throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Transport); }
        finally { lock (_gate) _refreshing = false; }
    }

    private void PreserveCleanup(Exception original, Exception sanitized)
    {
        if (!original.Data.Contains(ResourceCleanup.FailureMarker)) return;
        sanitized.Data[ResourceCleanup.FailureMarker] = "Cleanup";
        lock (_gate) _cleanupFailed = true;
    }

    internal static string ExactUrl(string host, string dataVersion)
    {
        host = OfficialResourceOrigin.SelectHost(host);
        if (!ResourceValidation.DataVersion.IsMatch(dataVersion))
            throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.InvalidVersion);
        return "https://" + host + "/WLN/TW/" + dataVersion + "/ResourcesPC/ServerList.txt";
    }

    /// <summary>Cancels owned HTTP work and attempts all owned cleanup. A running RefreshAsync
    /// must still be awaited by its caller; disposal prevents any subsequent publication.</summary>
    public void Dispose()
    {
        lock (_gate)
        {
            if (_disposed)
            {
                if (!_disposalComplete || _cleanupFailed) throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Cleanup);
                return;
            }
            _disposed = true; _current = null;
        }
        try { _source.Dispose(); }
        catch (Exception)
        {
            lock (_gate) _cleanupFailed = true;
            throw new OfficialServerDiscoveryException(OfficialServerDiscoveryFailure.Cleanup);
        }
        finally { lock (_gate) _disposalComplete = true; }
    }
}
