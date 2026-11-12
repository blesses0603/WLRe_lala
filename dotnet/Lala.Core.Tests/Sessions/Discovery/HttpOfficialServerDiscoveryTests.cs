using System.Net;
using Lala.Core.Resources;
using Lala.Core.Sessions.Discovery;
using Xunit;
using static Lala.Core.Tests.Sessions.Discovery.DiscoveryTestSupport;

namespace Lala.Core.Tests.Sessions.Discovery;

public sealed class HttpOfficialServerDiscoveryTests
{
    [Fact]
    public async Task Exact_get_between_two_version_observations_disposes_all_bodies_and_has_no_offline_authority()
    {
        var versions = Versions(); var body = new Body(List()); var content = new Content(body); var clock = new Clock();
        var lists = new Handler((request, _) =>
        {
            Assert.Equal(HttpMethod.Get, request.Method); Assert.Equal(Url, request.RequestUri!.OriginalString);
            Assert.Null(request.Headers.Authorization); Assert.False(request.Headers.Contains("Cookie"));
            Assert.Equal("*/*", request.Headers.GetValues("Accept").Single());
            Assert.Equal("no-cache", request.Headers.GetValues("Cache-Control").Single());
            Assert.Equal("WLRe-LaLa-ServerList/1", request.Headers.GetValues("User-Agent").Single());
            Assert.Equal(3, versions.Requests.Count);
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { RequestMessage = request, Content = content });
        });
        var source = new HttpOfficialServerDiscoverySource(versions, lists, clock: clock);
        using (var discovery = OfficialServerDiscovery.CreateForOfflineTests(source))
        {
            Assert.Empty(versions.Requests); Assert.Empty(lists.Requests);
            var result = await discovery.RefreshAsync();
            Assert.Single(result.Lines); Assert.False(result.TlsOriginObserved);
            Assert.Equal(6, versions.Requests.Count); Assert.Single(lists.Requests);
            Assert.Equal(1, content.Disposals); Assert.Equal(1, body.Disposals);
            Assert.Equal(7, clock.Timers.Count);
            Assert.All(clock.Timers, timer => { Assert.Equal(1, timer.Disposals); Assert.Equal(TimeSpan.FromSeconds(12), timer.DueTime); });
        }
        Assert.Equal(1, versions.Disposals); Assert.Equal(1, lists.Disposals);
    }

    [Theory]
    [InlineData(301)] [InlineData(302)] [InlineData(303)] [InlineData(307)] [InlineData(308)]
    [InlineData(304)] [InlineData(200, true)] [InlineData(204)] [InlineData(206)] [InlineData(404)]
    public async Task Redirect_status_and_response_URI_are_rejected_before_body_reads_without_retry(int status, bool wrongUrl = false)
    {
        var body = new Body(List()); var content = new Content(body);
        var lists = Reply(content, (HttpStatusCode)status, response =>
        {
            response.Headers.Location = new Uri(Url);
            if (wrongUrl) response.RequestMessage = new(HttpMethod.Get, Url + "?unexpected");
        });
        using var source = new HttpOfficialServerDiscoverySource(Versions(), lists);
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(DataVersion, default));
        Assert.Equal(wrongUrl ? OfficialServerDiscoveryFailure.InvalidResponse : status is >= 300 and < 400
            ? OfficialServerDiscoveryFailure.Redirect : OfficialServerDiscoveryFailure.Status, failure.Failure);
        Assert.Equal(0, body.Reads); Assert.Equal(0, content.Opens); Assert.Equal(1, content.Disposals);
        Assert.Single(lists.Requests);
    }

    [Theory]
    [InlineData("../bad")] [InlineData("1.3.23?x")] [InlineData("1.3.23/evil")]
    [InlineData("1.3.23\n")] [InlineData("https://example.com")]
    public async Task Invalid_version_cannot_become_an_arbitrary_URL(string version)
    {
        var lists = Reply(new Content(new Body(List())));
        using var source = new HttpOfficialServerDiscoverySource(Versions(), lists);
        await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(version, default));
        Assert.Empty(lists.Requests);
    }

    [Theory]
    [InlineData(null, 0)] [InlineData(null, 65537)] [InlineData("65537", 1)] [InlineData("0", 1)]
    [InlineData("-1", 1)] [InlineData("+1", 1)] [InlineData("1, 1", 1)] [InlineData("1", 2)]
    [InlineData("2", 1)] [InlineData("99999999999999999999", 1)]
    public async Task Declared_and_streamed_lengths_are_independently_bounded(string? declared, int size)
    {
        var body = new Body(new byte[size]); var content = new Content(body);
        var lists = Reply(content, edit: response =>
        { if (declared is not null) response.Content.Headers.TryAddWithoutValidation("Content-Length", declared); });
        using var source = new HttpOfficialServerDiscoverySource(Versions(), lists);
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(DataVersion, default));
        Assert.Equal(OfficialServerDiscoveryFailure.Size, failure.Failure);
        Assert.Equal(1, content.Disposals);
        if (content.Opens != 0) Assert.Equal(1, body.Disposals);
    }

    [Fact]
    public async Task Exactly_64KiB_succeeds_and_unknown_length_remains_bounded()
    {
        var content = new Content(new Body(new byte[65536]));
        using var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(content));
        Assert.Equal(65536, (await source.FetchAsync(DataVersion, default)).Length);
    }

    [Theory]
    [InlineData(true)] [InlineData(false)]
    public async Task Compressed_or_oversized_headers_are_rejected_without_body_acquisition(bool compressed)
    {
        var body = new Body(List()); var content = new Content(body);
        using var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(content, edit: response =>
        {
            if (compressed) response.Content.Headers.ContentEncoding.Add("gzip");
            else response.Headers.TryAddWithoutValidation("X-Test", new string('x', 16385));
        }));
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(DataVersion, default));
        Assert.Equal(OfficialServerDiscoveryFailure.Headers, failure.Failure);
        Assert.Equal(0, content.Opens); Assert.Equal(0, body.Reads); Assert.Equal(1, content.Disposals);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task Caller_cancellation_and_timeout_dispose_body_response_and_timer(bool timeout)
    {
        using var cancellation = new CancellationTokenSource();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var body = new Body(List()) { BeforeRead = async token => { entered.TrySetResult(); await Task.Delay(Timeout.Infinite, token); } };
        var content = new Content(body); var clock = new Clock();
        using var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(content), clock: clock);
        var fetching = source.FetchAsync(DataVersion, cancellation.Token).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        if (timeout) clock.Timers.Single().Fire(); else cancellation.Cancel();
        if (timeout)
            Assert.Equal(OfficialServerDiscoveryFailure.Timeout,
                (await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => fetching.WaitAsync(TimeSpan.FromSeconds(5)))).Failure);
        else await Assert.ThrowsAnyAsync<OperationCanceledException>(() => fetching.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal(1, content.Disposals); Assert.Equal(1, body.Disposals); Assert.Equal(1, clock.Timers.Single().Disposals);
    }

    [Fact]
    public async Task Disposal_cancels_inflight_send_and_no_late_publication_can_escape()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var versions = Versions(); var clock = new Clock();
        var lists = new Handler(async (_, token) => { entered.SetResult(); await Task.Delay(Timeout.Infinite, token); throw new InvalidOperationException(); });
        var source = new HttpOfficialServerDiscoverySource(versions, lists, clock: clock);
        var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var refresh = discovery.RefreshAsync();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        discovery.Dispose();
        await Assert.ThrowsAsync<ObjectDisposedException>(() => refresh.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Null(discovery.Current); Assert.Equal(1, lists.Disposals); Assert.Equal(1, versions.Disposals);
        Assert.All(clock.Timers, timer => Assert.Equal(1, timer.Disposals));
    }
}
