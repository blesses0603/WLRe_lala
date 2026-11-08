using System.Globalization;
using System.Net;
using System.Runtime.ExceptionServices;
using System.Text;
using Lala.Core.Resources;

namespace Lala.Core.Sessions.Discovery;

/// <summary>Separate narrow ServerList transport. Existing resource URL access is unchanged.
/// Handler injection is internal and never carries official origin authority.</summary>
internal sealed class HttpOfficialServerDiscoverySource : IOfficialServerDiscoverySource
{
    private const int MaximumHeaders = 16 * 1024;
    private readonly HttpOfficialResourceSource _versions;
    private readonly HttpMessageHandler _handler;
    private readonly HttpClient _client;
    private readonly string _host;
    private readonly TimeProvider _clock;
    private readonly TimeSpan _timeout;
    private readonly CancellationTokenSource _shutdown = new();
    private readonly CancellationToken _shutdownToken;
    private int _disposed, _cleanupIncomplete;
    internal bool CleanupIncomplete => Volatile.Read(ref _cleanupIncomplete) != 0;
    internal bool DisposalAttemptsComplete => Volatile.Read(ref _disposed) == 2;

    internal HttpOfficialServerDiscoverySource(string host)
        : this(new HttpOfficialResourceSource(host), NewHandler(), host) { }

    // Own both injected handlers; no caller-controlled handler reaches the public factory.
    internal HttpOfficialServerDiscoverySource(HttpMessageHandler versionHandler, HttpMessageHandler listHandler,
        string host = OfficialResourceOrigin.DefaultHost, TimeProvider? clock = null, TimeSpan? timeout = null)
        : this(new HttpOfficialResourceSource(versionHandler, host, clock, versionTimeout: timeout), listHandler, host, clock, timeout) { }

    private HttpOfficialServerDiscoverySource(HttpOfficialResourceSource versions, HttpMessageHandler handler,
        string host, TimeProvider? clock = null, TimeSpan? timeout = null)
    {
        _host = OfficialResourceOrigin.SelectHost(host);
        _clock = clock ?? TimeProvider.System;
        _timeout = timeout ?? TimeSpan.FromSeconds(12);
        if (_timeout <= TimeSpan.Zero || _timeout > TimeSpan.FromMinutes(1)) throw new ArgumentOutOfRangeException(nameof(timeout));
        _versions = versions;
        _handler = handler;
        _shutdownToken = _shutdown.Token;
        _client = new HttpClient(handler, disposeHandler: false) { Timeout = Timeout.InfiniteTimeSpan };
    }
    private static SocketsHttpHandler NewHandler() => new()
    {
        AllowAutoRedirect = false, AutomaticDecompression = DecompressionMethods.None,
        UseCookies = false, Credentials = null, MaxResponseHeadersLength = MaximumHeaders / 1024
    };

    public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        EnsureAvailable();
        var result = await _versions.ObserveAsync(token).ConfigureAwait(false);
        token.ThrowIfCancellationRequested();
        EnsureAvailable();
        return result;
    }

    public async ValueTask<byte[]> FetchAsync(string dataVersion, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        string url = OfficialServerDiscovery.ExactUrl(_host, dataVersion);
        EnsureAvailable();
        var lifetime = new ResourceRequestLifetime(token, _shutdownToken, _timeout, _clock, MarkCleanupIncomplete);
        HttpResponseMessage? response = null;
        Stream? body = null;
        Exception? primary = null;
        try
        {
            lifetime.Token.ThrowIfCancellationRequested();
            using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(url, UriKind.Absolute));
            request.Headers.TryAddWithoutValidation("Accept", "*/*");
            request.Headers.TryAddWithoutValidation("Cache-Control", "no-cache");
            request.Headers.TryAddWithoutValidation("User-Agent", "WLRe-LaLa-ServerList/1");
            response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, lifetime.Token).ConfigureAwait(false);
            lifetime.Token.ThrowIfCancellationRequested();
            if (response.RequestMessage?.RequestUri?.OriginalString != url) throw Error(OfficialServerDiscoveryFailure.InvalidResponse);
            ValidateHeaders(response);
            int status = (int)response.StatusCode;
            if (status is >= 300 and < 400) throw Error(OfficialServerDiscoveryFailure.Redirect);
            if (status != 200) throw Error(OfficialServerDiscoveryFailure.Status);
            if (response.Content.Headers.ContentEncoding.Count != 0) throw Error(OfficialServerDiscoveryFailure.Headers);
            long? declared = null;
            if (response.Content.Headers.TryGetValues("Content-Length", out var lengths))
            {
                string[] values = lengths.ToArray();
                if (values.Length != 1 || values[0].Length is < 1 or > 20 || values[0].Any(c => c is < '0' or > '9') ||
                    !long.TryParse(values[0], NumberStyles.None, CultureInfo.InvariantCulture, out long length) ||
                    length is < 1 or > OfficialServerListParser.MaximumBytes) throw Error(OfficialServerDiscoveryFailure.Size);
                declared = length;
            }
            body = await response.Content.ReadAsStreamAsync(lifetime.Token).ConfigureAwait(false);
            lifetime.Token.ThrowIfCancellationRequested();
            byte[] buffer = new byte[OfficialServerListParser.MaximumBytes + 1];
            int count = 0;
            while (true)
            {
                lifetime.Token.ThrowIfCancellationRequested();
                int n = await body.ReadAsync(buffer.AsMemory(count, buffer.Length - count), lifetime.Token).ConfigureAwait(false);
                lifetime.Token.ThrowIfCancellationRequested();
                if (n < 0 || n > buffer.Length - count) throw Error(OfficialServerDiscoveryFailure.Size);
                if (n == 0) break;
                count += n;
                if (count > OfficialServerListParser.MaximumBytes || declared is not null && count > declared)
                    throw Error(OfficialServerDiscoveryFailure.Size);
            }
            if (count == 0 || declared is not null && count != declared) throw Error(OfficialServerDiscoveryFailure.Size);
            EnsureAvailable();
            return buffer.AsSpan(0, count).ToArray();
        }
        catch (Exception error)
        {
            primary = error is OperationCanceledException
                ? token.IsCancellationRequested ? new OperationCanceledException(token)
                    : _shutdownToken.IsCancellationRequested ? new ObjectDisposedException(nameof(OfficialServerDiscovery))
                    : Error(OfficialServerDiscoveryFailure.Timeout)
                : error is OfficialServerDiscoveryException ? error : Error(OfficialServerDiscoveryFailure.Transport);
            ExceptionDispatchInfo.Capture(primary).Throw();
            throw;
        }
        finally
        {
            bool failed = false;
            if (response is not null)
            {
                failed = !AttemptCleanup(response.Dispose);
                if (failed && body is not null) AttemptCleanup(body.Dispose);
            }
            else if (body is not null) failed = !AttemptCleanup(body.Dispose);
            failed |= !AttemptCleanup(lifetime.Dispose);
            ReportCleanup(failed || CleanupIncomplete, primary);
        }
    }
    private static void ValidateHeaders(HttpResponseMessage response)
    {
        int count = 0;
        foreach (var header in response.Headers.Concat(response.Content.Headers))
        {
            count += Encoding.UTF8.GetByteCount(header.Key);
            if (count > MaximumHeaders) throw Error(OfficialServerDiscoveryFailure.Headers);
            foreach (string value in header.Value)
            {
                int size = Encoding.UTF8.GetByteCount(value);
                if (size > MaximumHeaders - count) throw Error(OfficialServerDiscoveryFailure.Headers);
                count += size;
            }
        }
    }
    private void EnsureAvailable()
    {
        if (CleanupIncomplete || _versions.CleanupIncomplete) throw Error(OfficialServerDiscoveryFailure.Cleanup);
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
    }
    private static OfficialServerDiscoveryException Error(OfficialServerDiscoveryFailure failure) => new(failure);
    private void MarkCleanupIncomplete() => Interlocked.Exchange(ref _cleanupIncomplete, 1);
    private bool AttemptCleanup(Action cleanup)
    {
        try { cleanup(); return true; }
        catch (Exception) { MarkCleanupIncomplete(); return false; }
    }
    private static void ReportCleanup(bool failed, Exception? primary = null)
    {
        if (!failed) return;
        if (primary is null) throw Error(OfficialServerDiscoveryFailure.Cleanup);
        primary.Data[ResourceCleanup.FailureMarker] = "Cleanup";
    }
    public void Dispose()
    {
        int prior = Interlocked.CompareExchange(ref _disposed, 1, 0);
        if (prior != 0) { ReportCleanup(prior != 2 || CleanupIncomplete); return; }
        try
        {
            AttemptCleanup(_shutdown.Cancel);
            AttemptCleanup(_versions.Dispose);
            AttemptCleanup(_client.Dispose);
            AttemptCleanup(_handler.Dispose);
            AttemptCleanup(_shutdown.Dispose);
        }
        finally { Volatile.Write(ref _disposed, 2); }
        ReportCleanup(CleanupIncomplete);
    }
}
