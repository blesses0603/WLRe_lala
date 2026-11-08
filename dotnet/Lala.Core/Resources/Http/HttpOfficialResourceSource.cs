using System.Globalization;
using System.Net;
using System.Runtime.ExceptionServices;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lala.Core.Resources;

internal enum ResourceTransportFailure { InvalidSource, Redirect, Status, Headers, Length, Timeout, Transport, Cleanup }
internal sealed class ResourceTransportException(ResourceTransportFailure failure)
    : IOException("Resource request failed: " + failure)
{
    internal ResourceTransportFailure Failure { get; } = failure;
}

/// <summary>Uninstalled HTTP acquisition. Neither the adapter nor its results confer provenance,
/// readiness, runtime admission or permission to send packets. Test handlers are not trusted origins.</summary>
internal sealed class HttpOfficialResourceSource : IResourceSource, IDisposable
{
    private readonly HttpClient _client;
    private readonly HttpMessageHandler _handler;
    private readonly string _host;
    private readonly TimeProvider _clock;
    private readonly TimeSpan _versionTimeout, _resourceTimeout;
    private readonly CancellationTokenSource _shutdown = new();
    private readonly CancellationToken _shutdownToken;
    private int _disposed;
    private int _cleanupIncomplete;
    internal bool CleanupIncomplete => Volatile.Read(ref _cleanupIncomplete) != 0;
    // Completion of source-owned disposal ATTEMPTS, not a claim that cleanup succeeded.
    internal bool DisposalAttemptsComplete => Volatile.Read(ref _disposed) == 2;
    private static readonly Regex PathPattern = new(@"\A/WLN/TW/(?<data>[0-9]{1,4}(?:\.[0-9]{1,4}){2,3})/ResourcesPC/AssetBundle/(?<file>(?:DataPackage|MainPackage)\.(?:version|hash|bytes)|[A-Za-z0-9][A-Za-z0-9_.-]{0,190}\.bundle)\z", RegexOptions.NonBacktracking);
    private static readonly Regex QueryPattern = new(@"\A[0-9]{1,20}(?:\.[0-9]{1,16})?\z", RegexOptions.NonBacktracking);
    private const int MaximumHeaders = 16 * 1024;
    private const int MaximumRedirects = 3;

    internal HttpOfficialResourceSource(string host = OfficialResourceOrigin.DefaultHost)
        : this(new SocketsHttpHandler { AllowAutoRedirect = false, AutomaticDecompression = DecompressionMethods.None,
            UseCookies = false, Credentials = null, MaxResponseHeadersLength = MaximumHeaders / 1024 }, host) { }

    // Owns the injected handler. This seam exists for offline tests, not source-authority issuance.
    internal HttpOfficialResourceSource(HttpMessageHandler handler, string host = OfficialResourceOrigin.DefaultHost,
        TimeProvider? clock = null, TimeSpan? versionTimeout = null, TimeSpan? resourceTimeout = null)
    {
        _host = OfficialResourceOrigin.SelectHost(host);
        _shutdownToken = _shutdown.Token;
        _clock = clock ?? TimeProvider.System;
        _versionTimeout = versionTimeout ?? TimeSpan.FromSeconds(12);
        _resourceTimeout = resourceTimeout ?? TimeSpan.FromSeconds(20);
        if (_versionTimeout <= TimeSpan.Zero || _resourceTimeout <= TimeSpan.Zero ||
            _versionTimeout > TimeSpan.FromMinutes(1) || _resourceTimeout > TimeSpan.FromMinutes(1))
            throw new ArgumentOutOfRangeException(nameof(versionTimeout));
        _handler = handler;
        // Dispose handler independently: HttpClient cancellation callbacks can throw before it
        // reaches handler disposal. Each separately owned cleanup must still be attempted.
        _client = new HttpClient(handler, disposeHandler: false) { Timeout = Timeout.InfiniteTimeSpan };
    }

    public string? SelectedHost => _host;
    public async ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken cancellationToken)
    {
        var map = RawOfficialVersionParser.ParseMap(await VersionBytesAsync($"https://{_host}/WLN/TW/ResourcePath_PC.dat", cancellationToken),
            ResourceCompatibility.Shipped.OfficialGameExeVersion, cancellationToken);
        var packages = new Dictionary<string, string>();
        foreach (string package in ResourceValidation.Packages)
        {
            var version = RawOfficialVersionParser.ParsePackage(await VersionBytesAsync(
                $"https://{_host}/WLN/TW/{map.DataVersion}/ResourcesPC/AssetBundle/{package}.version", cancellationToken), cancellationToken);
            if (!ResourceValidation.Manifest.IsMatch(version)) throw new ResourceValidationException("Invalid complete manifest version");
            packages.Add(package, version);
        }
        cancellationToken.ThrowIfCancellationRequested();
        EnsureCleanupSucceeded();
        return OfficialVersionSnapshot.Parse(JsonSerializer.SerializeToUtf8Bytes(new
        {
            schema_version = 1, origin = "official_pc_version_endpoint", data_ver = map.DataVersion,
            exe_version = map.ExeVersion, packages, checked_at_utc = _clock.GetUtcNow().ToString("yyyy-MM-dd'T'HH:mm:sszzz", CultureInfo.InvariantCulture), assets_ready = false
        }), cancellationToken);
    }

    public ValueTask<ResourceResponse> OpenAsync(string exactUrl, CancellationToken cancellationToken)
    {
        var path = Validate(exactUrl, version: false);
        long limit = path.EndsWith(".hash", StringComparison.Ordinal) ? 8 :
            path.EndsWith(".bytes", StringComparison.Ordinal) ? ManifestIdentity.MaximumManifestBytes : BundleSourcePreparation.MaximumRetainedBytes;
        return OpenCoreAsync(exactUrl, version: false, limit, cancellationToken);
    }

    private async Task<byte[]> VersionBytesAsync(string canonical, CancellationToken token)
    {
        Validate(canonical, version: true);
        string query = _clock.GetUtcNow().ToUnixTimeMilliseconds().ToString(CultureInfo.InvariantCulture);
        string target = canonical + "?" + query;
        using var output = new MemoryStream();
        var response = await OpenCoreAsync(target, version: true, RawOfficialVersionParser.MaximumBytes, token, canonical);
        Exception? primary = null;
        try { await response.Body.CopyToAsync(output, token); }
        catch (Exception ex) { primary = ex; throw; }
        finally { ResourceCleanup.DisposePreservingFailure(response, primary); }
        token.ThrowIfCancellationRequested();
        EnsureCleanupSucceeded();
        return output.ToArray();
    }

    // Original-string validation precedes Uri normalization (which can hide ports, escapes or traversal).
    private string Validate(string url, bool version)
    {
        string prefix = "https://" + _host;
        if (url is null || !url.StartsWith(prefix + "/", StringComparison.Ordinal) ||
            url.Any(c => char.IsWhiteSpace(c) || c is '%' or '\\' or '#')) throw Error(ResourceTransportFailure.InvalidSource);
        string rest = url[prefix.Length..];
        int q = rest.IndexOf('?');
        string path = q < 0 ? rest : rest[..q];
        if (q >= 0 && (!version || !QueryPattern.IsMatch(rest[(q + 1)..]))) throw Error(ResourceTransportFailure.InvalidSource);
        var match = PathPattern.Match(path);
        bool map = path == "/WLN/TW/ResourcePath_PC.dat";
        if (version ? !(map || (match.Success && path.EndsWith(".version", StringComparison.Ordinal))) :
            !(match.Success && !path.EndsWith(".version", StringComparison.Ordinal))) throw Error(ResourceTransportFailure.InvalidSource);
        return path;
    }

    private async ValueTask<ResourceResponse> OpenCoreAsync(string url, bool version, long maximum, CancellationToken caller, string? canonical = null)
    {
        caller.ThrowIfCancellationRequested();
        string path = Validate(url, version);
        EnsureCleanupSucceeded();
        ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
        var lifetime = new ResourceRequestLifetime(caller, _shutdownToken,
            version ? _versionTimeout : _resourceTimeout, _clock, MarkCleanupIncomplete);
        HttpResponseMessage? response = null;
        Stream? acquiredBody = null;
        bool transferred = false, retried = false;
        Exception? primary = null;
        int redirects = 0;
        try
        {
            while (true)
            {
                lifetime.Token.ThrowIfCancellationRequested();
                using var request = new HttpRequestMessage(HttpMethod.Get, new Uri(url, UriKind.Absolute));
                request.Headers.TryAddWithoutValidation("User-Agent", version ? "WLRe-LaLa-VersionCheck/1" :
                    path.EndsWith(".bundle", StringComparison.Ordinal) ? "WLRe-LaLa-OfficialSync/1" : "WLRe-LaLa-ManifestSync/1");
                request.Headers.TryAddWithoutValidation("Accept", "*/*");
                request.Headers.TryAddWithoutValidation("Cache-Control", "no-cache");
                request.Headers.TryAddWithoutValidation("Pragma", "no-cache");
                response = await _client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, lifetime.Token).ConfigureAwait(false);
                lifetime.Token.ThrowIfCancellationRequested();
                // A fake/injected handler must report the request too; no implicit trusted location.
                if (response.RequestMessage?.RequestUri?.OriginalString != url) throw Error(ResourceTransportFailure.InvalidSource);
                ValidateHeaders(response);
                int status = (int)response.StatusCode;
                if (status is 301 or 302 or 303 or 307 or 308)
                {
                    if (!version || ++redirects > MaximumRedirects) throw Error(ResourceTransportFailure.Redirect);
                    string? location = response.Headers.Location?.OriginalString;
                    // Resolve only constrained relative forms before validation, never normalized traversal.
                    if (location is not null && location.StartsWith("/", StringComparison.Ordinal)) location = "https://" + _host + location;
                    else if (location is not null && location.StartsWith("?", StringComparison.Ordinal)) location = "https://" + _host + path + location;
                    else if (location is not null && !location.Contains('/') && !location.Contains(':')) location = "https://" + _host + path[..(path.LastIndexOf('/') + 1)] + location;
                    if (location is null || Validate(location, version: true) != path) throw Error(ResourceTransportFailure.Redirect);
                    var rejected = response; response = null;
                    CleanupResponse(rejected, null); EnsureCleanupSucceeded();
                    url = location; continue;
                }
                if (version && !retried && canonical is not null && status is 400 or 403 or 404)
                {
                    retried = true; var rejected = response; response = null;
                    CleanupResponse(rejected, null); EnsureCleanupSucceeded();
                    url = canonical; continue;
                }
                if (status != 200) throw Error(ResourceTransportFailure.Status);
                string? length = null;
                if (response.Content.Headers.TryGetValues("Content-Length", out var values))
                {
                    var list = values.ToArray();
                    if (list.Length != 1) throw Error(ResourceTransportFailure.Length);
                    length = list[0];
                    if (length.Length is 0 or > 20 || length.Any(c => c is < '0' or > '9') ||
                        !long.TryParse(length, NumberStyles.None, CultureInfo.InvariantCulture, out long n) || n > maximum)
                        throw Error(ResourceTransportFailure.Length);
                }
                if (response.Content.Headers.ContentEncoding.Count != 0 &&
                    !(version && path == "/WLN/TW/ResourcePath_PC.dat" && response.Content.Headers.ContentEncoding.SequenceEqual(new[] { "gzip" })))
                    throw Error(ResourceTransportFailure.Headers);
                Stream body = acquiredBody = await response.Content.ReadAsStreamAsync(lifetime.Token).ConfigureAwait(false);
                lifetime.Token.ThrowIfCancellationRequested();
                var owned = new ResponseStream(body, response, lifetime, caller, _shutdownToken, maximum,
                    length is null ? null : long.Parse(length, CultureInfo.InvariantCulture), this);
                transferred = true;
                return new ResourceResponse(url, status, length, owned);
            }
        }
        catch (Exception ex)
        {
            primary = ex is OperationCanceledException
                ? caller.IsCancellationRequested ? new OperationCanceledException(caller)
                    : _shutdownToken.IsCancellationRequested ? new OperationCanceledException(_shutdownToken)
                    : Error(ResourceTransportFailure.Timeout)
                : ex is ResourceTransportException ? ex : Error(ResourceTransportFailure.Transport);
            ExceptionDispatchInfo.Capture(primary).Throw();
            throw; // Unreachable; keeps the original safe exception's dispatch information.
        }
        finally
        {
            if (!transferred)
            {
                bool failed = !CleanupResponse(response, acquiredBody);
                failed |= !AttemptCleanup(lifetime.Dispose);
                ResourceCleanup.Report(failed, primary);
            }
        }
    }
    private static ResourceTransportException Error(ResourceTransportFailure kind) => new(kind);
    private static void ValidateHeaders(HttpResponseMessage response)
    {
        int length = 0;
        foreach (var header in response.Headers.Concat(response.Content.Headers))
        {
            length += Encoding.UTF8.GetByteCount(header.Key);
            foreach (string value in header.Value)
            {
                int bytes = Encoding.UTF8.GetByteCount(value);
                if (bytes > MaximumHeaders - length) throw Error(ResourceTransportFailure.Headers);
                length += bytes;
            }
            if (length > MaximumHeaders) throw Error(ResourceTransportFailure.Headers);
        }
    }
    private bool AttemptCleanup(Action cleanup)
    {
        try { cleanup(); return true; }
        catch (Exception)
        {
            // No remote exception text or inner exception escapes this boundary.
            MarkCleanupIncomplete();
            return false;
        }
    }
    private void MarkCleanupIncomplete() => Interlocked.Exchange(ref _cleanupIncomplete, 1);
    private bool CleanupResponse(HttpResponseMessage? response, Stream? acquiredBody)
    {
        // A response normally owns its content/body. If that disposal throws, explicitly
        // attempt the acquired body as a fallback. It may have been partially disposed already.
        if (response is null) return acquiredBody is null || AttemptCleanup(acquiredBody.Dispose);
        bool success = AttemptCleanup(response.Dispose);
        if (!success && acquiredBody is not null) AttemptCleanup(acquiredBody.Dispose);
        return success;
    }
    private void EnsureCleanupSucceeded()
    {
        if (CleanupIncomplete) throw Error(ResourceTransportFailure.Cleanup);
    }
    public void Dispose()
    {
        // Reentrant/concurrent callers do not run the same cleanup twice. While the winner
        // is running, DisposalAttemptsComplete remains false; there is no success claim.
        int prior = Interlocked.CompareExchange(ref _disposed, 1, 0);
        if (prior != 0)
        {
            ResourceCleanup.Report(prior != 2 || CleanupIncomplete);
            return;
        }
        try
        {
            AttemptCleanup(_shutdown.Cancel);
            AttemptCleanup(_client.Dispose);
            AttemptCleanup(_handler.Dispose);
            AttemptCleanup(_shutdown.Dispose);
        }
        finally { Volatile.Write(ref _disposed, 2); }
        ResourceCleanup.Report(CleanupIncomplete);
    }

    private sealed class ResponseStream(Stream body, HttpResponseMessage response, ResourceRequestLifetime lifetime,
        CancellationToken caller, CancellationToken shutdown, long maximum, long? declared, HttpOfficialResourceSource owner) : Stream
    {
        private long _length;
        private int _disposed;
        private bool _cleanupIncomplete;
        private readonly CancellationToken _lifetimeToken = lifetime.Token;
        public override bool CanRead => Volatile.Read(ref _disposed) == 0;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            ObjectDisposedException.ThrowIf(Volatile.Read(ref _disposed) != 0, this);
            using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _lifetimeToken);
            try
            {
                linked.Token.ThrowIfCancellationRequested();
                if (buffer.Length == 0) return 0;
                int n = await body.ReadAsync(buffer[..(int)Math.Min(buffer.Length, maximum - _length + 1)], linked.Token).ConfigureAwait(false);
                linked.Token.ThrowIfCancellationRequested();
                if (n < 0 || n > buffer.Length) throw Error(ResourceTransportFailure.Length);
                _length += n;
                if (_length > maximum || (declared.HasValue && _length > declared.Value) ||
                    (n == 0 && (_length == 0 || (declared.HasValue && _length != declared.Value)))) throw Error(ResourceTransportFailure.Length);
                return n;
            }
            catch (OperationCanceledException) { caller.ThrowIfCancellationRequested(); cancellationToken.ThrowIfCancellationRequested(); shutdown.ThrowIfCancellationRequested(); throw Error(ResourceTransportFailure.Timeout); }
            catch (Exception ex) when (ex is IOException or HttpRequestException or InvalidOperationException)
            { if (ex is ResourceTransportException) throw; throw Error(ResourceTransportFailure.Transport); }
        }
        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken token) => ReadAsync(buffer.AsMemory(offset, count), token).AsTask();
        public override int Read(byte[] buffer, int offset, int count) => ReadAsync(buffer.AsMemory(offset, count)).AsTask().GetAwaiter().GetResult();
        protected override void Dispose(bool disposing)
        {
            if (!disposing) return;
            int prior = Interlocked.CompareExchange(ref _disposed, 1, 0);
            if (prior != 0)
            {
                ResourceCleanup.Report(prior != 2 || _cleanupIncomplete);
                return;
            }
            try
            {
                _cleanupIncomplete |= !owner.CleanupResponse(response, body);
                _cleanupIncomplete |= !owner.AttemptCleanup(lifetime.Dispose);
                _cleanupIncomplete |= !owner.AttemptCleanup(() => base.Dispose(disposing));
            }
            finally { Volatile.Write(ref _disposed, 2); }
            ResourceCleanup.Report(_cleanupIncomplete);
        }
        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
