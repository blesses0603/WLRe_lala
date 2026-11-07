using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class HttpResourceSourceTests
{
    private const string Root = "https://wlreftpsrc.chinesegamer.net/WLN/TW/";
    private const string HashUrl = Root + "1.3.21/ResourcesPC/AssetBundle/DataPackage.hash";
    private const string Map = "[{\"ExeVer\":\"1.3.0\",\"DataVer\":\"1.3.21\"}]";
    private sealed class Handler(Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        internal readonly List<string> Requests = [];
        internal bool Disposed;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Null(request.Headers.Authorization);
            Assert.Equal("no-cache", request.Headers.GetValues("Cache-Control").Single());
            Requests.Add(request.RequestUri!.OriginalString);
            return send(request, Requests.Count, token);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
    private sealed class Tracking(byte[] bytes) : MemoryStream(bytes, writable: false)
    {
        internal int Reads;
        internal bool Disposed;
        internal Func<CancellationToken, Task>? BeforeRead;
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken token = default)
        {
            Reads++; if (BeforeRead is not null) await BeforeRead(token);
            return await base.ReadAsync(buffer[..Math.Min(buffer.Length, 37)], token);
        }
        protected override void Dispose(bool disposing) { Disposed = true; base.Dispose(disposing); }
    }
    private static HttpResponseMessage Reply(HttpRequestMessage request, byte[] bytes, HttpStatusCode status = HttpStatusCode.OK)
        => new(status) { RequestMessage = request, Content = new StreamContent(new Tracking(bytes)) };
    private static Handler Simple(Func<HttpRequestMessage, int, HttpResponseMessage> send) => new((r, n, _) => Task.FromResult(send(r, n)));
    private static byte[] Ascii(string s) => Encoding.UTF8.GetBytes(s);

    public static IEnumerable<object?[]> ParserCases => HttpPythonVectors.Cases();
    [Theory, MemberData(nameof(ParserCases))]
    public void Actual_python_raw_parser_parity(string kind, string name, string encoded, string? expected)
    {
        _ = name;
        byte[] raw = Convert.FromBase64String(encoded);
        string[] Parse() => kind == "map" ? MapResult() : [RawOfficialVersionParser.ParsePackage(raw)];
        string[] MapResult() { var p = RawOfficialVersionParser.ParseMap(raw, "1.3.0"); return [p.DataVersion, p.ExeVersion]; }
        if (expected is null) Assert.Throws<ResourceValidationException>(() => Parse());
        else Assert.Equal(JsonSerializer.Deserialize<string[]>(expected), Parse());
    }
    [Fact]
    public void Oracle_source_hashes_are_pinned_with_crlf_only_normalization()
    {
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !Directory.Exists(Path.Combine(root.FullName, "wlre"))) root = root.Parent;
        Assert.NotNull(root);
        foreach (var (path, hash) in HttpPythonVectors.Sources)
        {
            byte[] bytes = File.ReadAllBytes(Path.Combine(root.FullName, path));
            string source = Encoding.UTF8.GetString(bytes).Replace("\r\n", "\n", StringComparison.Ordinal);
            Assert.Equal(hash, Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(source))));
        }
    }
    [Theory]
    [InlineData("http://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.hash")]
    [InlineData("https://wlreftpsrc.chinesegamer.net:443/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.hash")]
    [InlineData("https://wlreftp.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.hash")]
    [InlineData(HashUrl + "?123")]
    [InlineData(HashUrl + "#x")]
    [InlineData(Root + "%2e%2e/DataPackage.hash")]
    [InlineData(Root + "1.3.21/ResourcesPC/AssetBundle/../DataPackage.hash")]
    public async Task Invalid_original_urls_never_reach_handler(string url)
    {
        var handler = Simple((r, _) => Reply(r, Ascii("12345678")));
        using var source = new HttpOfficialResourceSource(handler);
        Assert.Equal(ResourceTransportFailure.InvalidSource, (await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(url, default))).Failure);
        Assert.Empty(handler.Requests);
    }
    [Theory]
    [InlineData(301)] [InlineData(302)] [InlineData(303)] [InlineData(307)] [InlineData(308)] [InlineData(204)] [InlineData(206)] [InlineData(304)]
    public async Task Resource_bad_status_never_reads_body_or_retries(int status)
    {
        var stream = new Tracking(Ascii("secret"));
        var handler = Simple((r, _) => new((HttpStatusCode)status) { RequestMessage = r, Content = new StreamContent(stream) });
        using var source = new HttpOfficialResourceSource(handler);
        await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(HashUrl, default));
        Assert.Equal(0, stream.Reads); Assert.True(stream.Disposed); Assert.Single(handler.Requests);
    }
    [Theory]
    [InlineData("9", "12345678")]
    [InlineData("-1", "12345678")]
    [InlineData("7", "12345678")]
    [InlineData(null, "123456789")]
    [InlineData("8", "1234567")]
    [InlineData(null, "")]
    public async Task Header_and_stream_bounds_fail_closed(string? declared, string body)
    {
        var handler = Simple((r, _) =>
        {
            var response = Reply(r, Ascii(body));
            if (declared is not null) response.Content.Headers.TryAddWithoutValidation("Content-Length", declared);
            return response;
        });
        using var source = new HttpOfficialResourceSource(handler);
        await Assert.ThrowsAsync<ResourceTransportException>(async () =>
        {
            using var response = await source.OpenAsync(HashUrl, default);
            await response.Body.CopyToAsync(Stream.Null);
        });
    }
    [Fact]
    public async Task One_canonical_retry_then_same_path_numeric_redirect_is_manual()
    {
        var handler = Simple((r, n) =>
        {
            if (n == 1) return Reply(r, [], HttpStatusCode.Forbidden);
            if (n == 2)
            {
                Assert.DoesNotContain('?', r.RequestUri!.OriginalString);
                var redirect = Reply(r, [], HttpStatusCode.Found);
                redirect.Headers.Location = new Uri(Root + "ResourcePath_PC.dat?123.45"); return redirect;
            }
            return Reply(r, Ascii(r.RequestUri!.AbsolutePath.EndsWith(".dat", StringComparison.Ordinal) ? Map : BundleSourceFixtures.Snapshot().Packages["DataPackage"]));
        });
        using var source = new HttpOfficialResourceSource(handler);
        var result = await source.ObserveAsync(default);
        Assert.Equal(5, handler.Requests.Count); Assert.False(result.AssetsReady); Assert.Equal("1.3.21", result.DataVersion);
    }
    [Fact]
    public async Task Redirect_loops_and_cross_host_redirects_are_bounded()
    {
        foreach (bool cross in new[] { false, true })
        {
            var handler = Simple((r, _) =>
            {
                var response = Reply(r, [], HttpStatusCode.Found);
                response.Headers.Location = new Uri((cross ? "https://wlreftp.chinesegamer.net/WLN/TW/" : Root) + "ResourcePath_PC.dat?1");
                return response;
            });
            using var source = new HttpOfficialResourceSource(handler);
            await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.ObserveAsync(default));
            Assert.Equal(cross ? 1 : 4, handler.Requests.Count);
        }
    }
    [Fact]
    public async Task Cancellation_and_timeout_cover_response_body_and_dispose_ownership()
    {
        foreach (bool cancel in new[] { true, false })
        {
            var stream = new Tracking(Ascii("12345678")) { BeforeRead = token => Task.Delay(Timeout.Infinite, token) };
            var handler = Simple((r, _) => new(HttpStatusCode.OK) { RequestMessage = r, Content = new StreamContent(stream) });
            using var source = new HttpOfficialResourceSource(handler, resourceTimeout: TimeSpan.FromMilliseconds(100));
            using var cts = new CancellationTokenSource();
            using (var response = await source.OpenAsync(HashUrl, cts.Token))
            {
                if (cancel) cts.Cancel();
                if (cancel) await Assert.ThrowsAnyAsync<OperationCanceledException>(() => response.Body.CopyToAsync(Stream.Null));
                else Assert.Equal(ResourceTransportFailure.Timeout, (await Assert.ThrowsAsync<ResourceTransportException>(() => response.Body.CopyToAsync(Stream.Null))).Failure);
            }
            Assert.True(stream.Disposed);
        }
    }
    [Fact]
    public async Task Transport_errors_redact_remote_messages_and_precancel_never_sends()
    {
        var handler = new Handler((_, _, _) => throw new HttpRequestException("https://evil/?token=SECRET"));
        using var source = new HttpOfficialResourceSource(handler);
        var error = await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(HashUrl, default));
        Assert.DoesNotContain("SECRET", error.ToString()); Assert.Null(error.InnerException);
        using var cts = new CancellationTokenSource(); cts.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () => await source.OpenAsync(HashUrl, cts.Token));
        Assert.Single(handler.Requests);
    }
    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public async Task Full_http_fake_handler_flow_and_final_source_drift(int failure)
    {
        var bundles = new Dictionary<string, byte[]> { ["all-ten.bundle"] = RuntimeFlowFixtures.Read("all-ten.bundle") };
        byte[] data = RuntimeFlowFixtures.Manifest(bundles), main = BundleSourceFixtures.Bytes("main-valid");
        int observations = 0;
        using var cancellation = new CancellationTokenSource();
        var streams = new List<Tracking>();
        var handler = Simple((r, _) =>
        {
            string name = r.RequestUri!.AbsolutePath.Split('/')[^1];
            if (name == "ResourcePath_PC.dat")
            {
                observations++;
                if (observations == 5 && failure == 2)
                    data = RuntimeFlowFixtures.Manifest(new Dictionary<string, byte[]>(bundles) { ["unrelated.bundle"] = [1, 2, 3] });
                if (observations == 5 && failure == 3) cancellation.Cancel();
            }
            byte[] body = name switch
            {
                "ResourcePath_PC.dat" => Ascii(Map),
                "DataPackage.version" => Ascii(failure == 1 && observations >= 5 ? "1276_2026_01_02_03_04_05_06" : RuntimeFlowFixtures.Version),
                "MainPackage.version" => Ascii(BundleSourceFixtures.Snapshot().Packages["MainPackage"]),
                "DataPackage.bytes" => data, "MainPackage.bytes" => main,
                "DataPackage.hash" => Ascii(ManifestIdentity.Crc32LittleEndian(data)),
                "MainPackage.hash" => Ascii(ManifestIdentity.Crc32LittleEndian(main)),
                "all-ten.bundle" => bundles[name],
                _ => throw new InvalidOperationException("Unexpected fake request")
            };
            var stream = new Tracking(body); streams.Add(stream);
            return new(HttpStatusCode.OK) { RequestMessage = r, Content = new StreamContent(stream) };
        });
        using var source = new HttpOfficialResourceSource(handler);
        if (failure == 3)
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source, cancellationToken: cancellation.Token));
        else if (failure != 0)
            Assert.Equal(failure == 1 ? BundleSourceFailure.VersionsChanged : BundleSourceFailure.ManifestChanged, (await Assert.ThrowsAsync<BundleSourceException>(() => new OfflineBundleRuntimePreparation().PrepareAsync(source))).Failure);
        else
        {
            var result = await new OfflineBundleRuntimePreparation().PrepareAsync(source);
            Assert.Equal(6, observations); Assert.True(result.Candidate.RequiredTablesStructurallyComplete);
            Assert.False(result.Candidate.HasVerifiedProvenance); Assert.False(result.Candidate.AssetsReady);
            Assert.False(result.Candidate.RuntimeAdmitted); Assert.False(result.Candidate.CanSendPackets);
        }
        Assert.All(streams, s => Assert.True(s.Disposed));
    }
    [Fact]
    public async Task Alternate_host_is_bound_and_mismatched_preparation_sends_nothing()
    {
        var handler = Simple((r, _) => Reply(r, Ascii("12345678")));
        using var source = new HttpOfficialResourceSource(handler, "wlreftp.chinesegamer.net");
        await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(source));
        Assert.Empty(handler.Requests);
        using (var response = await source.OpenAsync(HashUrl.Replace("wlreftpsrc", "wlreftp", StringComparison.Ordinal), default))
            await response.Body.CopyToAsync(Stream.Null);
        Assert.Single(handler.Requests);
    }

    [Theory]
    [InlineData("oversized-header")] [InlineData("duplicate-length")] [InlineData("encoding")] [InlineData("final-url")]
    public async Task Invalid_headers_or_location_rejected_before_read(string kind)
    {
        var stream = new Tracking(Ascii("12345678"));
        var handler = Simple((r, _) =>
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK) { RequestMessage = r, Content = new StreamContent(stream) };
            if (kind == "oversized-header") response.Headers.TryAddWithoutValidation("X-Remote", new string('x', 16385));
            if (kind == "duplicate-length") response.Content.Headers.TryAddWithoutValidation("Content-Length", new[] { "8", "8" });
            if (kind == "encoding") response.Content.Headers.TryAddWithoutValidation("Content-Encoding", "gzip");
            if (kind == "final-url") response.RequestMessage = new HttpRequestMessage(HttpMethod.Get, "https://evil.invalid/SECRET");
            return response;
        });
        using var source = new HttpOfficialResourceSource(handler);
        var error = await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(HashUrl, default));
        Assert.Equal(0, stream.Reads); Assert.True(stream.Disposed); Assert.DoesNotContain("SECRET", error.ToString());
    }

    [Theory]
    [InlineData(400, 2)] [InlineData(403, 2)] [InlineData(404, 2)] [InlineData(500, 1)] [InlineData(429, 1)]
    public async Task Version_status_retries_only_once_for_three_supported_codes(int status, int requests)
    {
        var handler = Simple((r, _) => Reply(r, [], (HttpStatusCode)status));
        using var source = new HttpOfficialResourceSource(handler);
        await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.ObserveAsync(default));
        Assert.Equal(requests, handler.Requests.Count);
    }

    [Fact]
    public async Task Pending_headers_timeout_cancellation_and_handler_ownership()
    {
        foreach (bool cancel in new[] { true, false })
        {
            var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var handler = new Handler(async (_, _, token) =>
            {
                entered.SetResult(); await Task.Delay(Timeout.Infinite, token); throw new InvalidOperationException();
            });
            var source = new HttpOfficialResourceSource(handler, resourceTimeout: TimeSpan.FromMilliseconds(100));
            using var cts = new CancellationTokenSource();
            var pending = source.OpenAsync(HashUrl, cts.Token).AsTask();
            await entered.Task;
            if (cancel) cts.Cancel();
            if (cancel) await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
            else Assert.Equal(ResourceTransportFailure.Timeout, (await Assert.ThrowsAsync<ResourceTransportException>(() => pending)).Failure);
            source.Dispose(); source.Dispose(); Assert.True(handler.Disposed);
        }
    }

    [Fact]
    public async Task Source_disposal_cancels_pending_body_without_leaking_response()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var stream = new Tracking(Ascii("12345678")) { BeforeRead = async token =>
            { entered.SetResult(); await Task.Delay(Timeout.Infinite, token); } };
        var handler = Simple((r, _) => new(HttpStatusCode.OK) { RequestMessage = r, Content = new StreamContent(stream) });
        using var source = new HttpOfficialResourceSource(handler);
        using (var response = await source.OpenAsync(HashUrl, default))
        {
            var pending = response.Body.CopyToAsync(Stream.Null);
            await entered.Task; source.Dispose();
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() => pending);
        }
        Assert.True(stream.Disposed); Assert.True(handler.Disposed);
    }

}
