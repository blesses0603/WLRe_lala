using System.Net;
using Lala.Core.Resources;
using Lala.Core.Sessions.Discovery;
using Xunit;
using static Lala.Core.Tests.Sessions.Discovery.DiscoveryTestSupport;

namespace Lala.Core.Tests.Sessions.Discovery;

public sealed class OfficialServerDiscoveryCleanupTests
{
    private static void Safe(Exception failure)
    {
        Assert.Null(failure.InnerException);
        Assert.DoesNotContain("SECRET", failure.ToString());
    }
    private static void FailedDispose(Action dispose)
    {
        var failure = Assert.Throws<OfficialServerDiscoveryException>(dispose);
        Assert.Equal(OfficialServerDiscoveryFailure.Cleanup, failure.Failure); Safe(failure);
    }

    [Fact]
    public async Task Throwing_content_cleanup_attempts_body_and_timer_then_taints_source_and_owner()
    {
        var body = new Body(List()); var content = new Content(body, throwDispose: true); var clock = new Clock();
        var versions = Versions(); var lists = Reply(content);
        var source = new HttpOfficialServerDiscoverySource(versions, lists, clock: clock);
        var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => discovery.RefreshAsync());
        Assert.Equal(OfficialServerDiscoveryFailure.Cleanup, failure.Failure); Safe(failure);
        Assert.Null(discovery.Current); Assert.Equal(1, content.Disposals); Assert.Equal(1, body.Disposals);
        Assert.All(clock.Timers, timer => Assert.Equal(1, timer.Disposals));
        Assert.Equal(3, versions.Requests.Count); Assert.True(source.CleanupIncomplete);
        Assert.Equal(OfficialServerDiscoveryFailure.Cleanup,
            (await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => discovery.RefreshAsync())).Failure);
        Assert.Single(lists.Requests);
        FailedDispose(discovery.Dispose); FailedDispose(discovery.Dispose);
        Assert.Equal(1, lists.Disposals); Assert.Equal(1, versions.Disposals);
    }

    [Fact]
    public async Task Rejected_response_does_not_open_body_to_cleanup_and_preserves_primary_status()
    {
        var body = new Body(List()); var content = new Content(body, throwDispose: true); var clock = new Clock();
        var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(content, HttpStatusCode.Forbidden), clock: clock);
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(DataVersion, default));
        Assert.Equal(OfficialServerDiscoveryFailure.Status, failure.Failure); Safe(failure);
        Assert.Equal("Cleanup", failure.Data[ResourceCleanup.FailureMarker]);
        Assert.Equal(0, content.Opens); Assert.Equal(0, body.Reads); Assert.Equal(0, body.Disposals);
        Assert.Equal(1, content.Disposals); Assert.Equal(1, clock.Timers.Single().Disposals);
        FailedDispose(source.Dispose);
    }

    [Fact]
    public async Task Body_failure_and_cleanup_failure_are_sanitized_without_losing_primary_failure()
    {
        var body = new Body(List()) { ThrowRead = true, ThrowDispose = true };
        var content = new Content(body); var clock = new Clock();
        var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(content), clock: clock);
        var failure = await Assert.ThrowsAsync<OfficialServerDiscoveryException>(async () => await source.FetchAsync(DataVersion, default));
        Assert.Equal(OfficialServerDiscoveryFailure.Transport, failure.Failure); Safe(failure);
        Assert.Equal("Cleanup", failure.Data[ResourceCleanup.FailureMarker]);
        Assert.True(body.Disposals >= 1); Assert.Equal(1, content.Disposals);
        Assert.Equal(1, clock.Timers.Single().Disposals); FailedDispose(source.Dispose);
    }

    [Fact]
    public async Task Cancelled_refresh_preserves_cleanup_marker_and_blocks_reuse()
    {
        using var cancellation = new CancellationTokenSource();
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var body = new Body(List())
        {
            ThrowDispose = true,
            BeforeRead = async token => { entered.TrySetResult(); await Task.Delay(Timeout.Infinite, token); }
        };
        var source = new HttpOfficialServerDiscoverySource(Versions(), Reply(new Content(body)));
        var discovery = OfficialServerDiscovery.CreateForOfflineTests(source);
        var refresh = discovery.RefreshAsync(cancellation.Token);
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5)); cancellation.Cancel();
        var failure = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => refresh.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal(cancellation.Token, failure.CancellationToken);
        Assert.Equal("Cleanup", failure.Data[ResourceCleanup.FailureMarker]); Safe(failure);
        Assert.Equal(OfficialServerDiscoveryFailure.Cleanup,
            (await Assert.ThrowsAsync<OfficialServerDiscoveryException>(() => discovery.RefreshAsync())).Failure);
        FailedDispose(discovery.Dispose);
    }

    [Fact]
    public async Task Shutdown_callback_and_handler_failures_do_not_skip_other_owned_cleanup()
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var callbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var clock = new Clock(); var versions = Versions();
        var lists = new Handler(async (_, token) =>
        {
            using var callback = token.Register(() => { callbackEntered.TrySetResult(); throw new IOException("SECRET callback failure"); });
            entered.SetResult();
            try { await Task.Delay(Timeout.Infinite, token); }
            catch (OperationCanceledException) { await callbackEntered.Task.WaitAsync(TimeSpan.FromSeconds(5)); throw; }
            throw new InvalidOperationException();
        }) { OnDispose = () => throw new IOException("SECRET handler cleanup failure") };
        var source = new HttpOfficialServerDiscoverySource(versions, lists, clock: clock);
        var pending = source.FetchAsync(DataVersion, default).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        FailedDispose(source.Dispose);
        var failure = await Assert.ThrowsAsync<ObjectDisposedException>(() => pending.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal("Cleanup", failure.Data[ResourceCleanup.FailureMarker]); Safe(failure);
        Assert.True(source.DisposalAttemptsComplete); Assert.True(source.CleanupIncomplete);
        Assert.Equal(1, lists.Disposals); Assert.Equal(1, versions.Disposals);
        Assert.Equal(1, clock.Timers.Single().Disposals); FailedDispose(source.Dispose);
    }
}
