using System.Net;
using Lala.Core.Resources;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class HttpCleanupTests
{
    private const string Url = "https://wlreftpsrc.chinesegamer.net/WLN/TW/1.3.21/ResourcesPC/AssetBundle/DataPackage.hash";
    private const string Hostile = "https://evil.invalid/?token=SECRET";
    private sealed class Clock : TimeProvider
    {
        internal readonly List<Timer> Timers = [];
        internal bool ThrowChange, ThrowTimerDispose;
        public override ITimer CreateTimer(TimerCallback callback, object? state, TimeSpan dueTime, TimeSpan period)
        { var timer = new Timer(callback, state) { ThrowChange = ThrowChange, ThrowDispose = ThrowTimerDispose }; Timers.Add(timer); return timer; }
        internal sealed class Timer(TimerCallback callback, object? state) : ITimer
        {
            internal int Disposals;
            internal bool ThrowChange, ThrowDispose;
            internal readonly TaskCompletionSource DisposalEntered = new(TaskCreationOptions.RunContinuationsAsynchronously);
            public bool Change(TimeSpan dueTime, TimeSpan period) { if (ThrowChange) throw new Exception(Hostile); return true; }
            internal void Fire() => callback(state);
            public void Dispose() { Interlocked.Increment(ref Disposals); DisposalEntered.TrySetResult(); if (ThrowDispose) throw new Exception(Hostile); }
            public ValueTask DisposeAsync() { Dispose(); return ValueTask.CompletedTask; }
        }
    }
    private sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        internal int Disposals;
        internal Action? DuringDispose;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) => send(request, token);
        protected override void Dispose(bool disposing)
        { if (disposing) { Interlocked.Increment(ref Disposals); DuringDispose?.Invoke(); } base.Dispose(disposing); }
    }
    private sealed class Body : MemoryStream
    {
        internal int Disposals, Reads;
        internal bool ThrowRead, ThrowDispose;
        internal Func<CancellationToken, Task>? BeforeRead;
        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            Reads++; if (BeforeRead is not null) await BeforeRead(cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            if (ThrowRead) throw new IOException(Hostile);
            return 0;
        }
        protected override void Dispose(bool disposing)
        { if (disposing) { Disposals++; if (ThrowDispose) throw new InvalidOperationException(Hostile); } base.Dispose(disposing); }
    }
    private sealed class Content(Body body, bool throwDispose) : HttpContent
    {
        internal int Opens, Disposals;
        protected override bool TryComputeLength(out long length) { length = 0; return false; }
        protected override Task SerializeToStreamAsync(Stream stream, TransportContext? context) => throw new NotSupportedException();
        protected override Task<Stream> CreateContentReadStreamAsync() { Opens++; return Task.FromResult<Stream>(body); }
        protected override void Dispose(bool disposing)
        { if (disposing) { Disposals++; if (throwDispose) throw new InvalidOperationException(Hostile); } base.Dispose(disposing); }
    }
    private static Handler Respond(Content content, HttpStatusCode status = HttpStatusCode.OK) => new((request, _) =>
        Task.FromResult(new HttpResponseMessage(status) { RequestMessage = request, Content = content }));
    private static void Cleanup(Action action)
    {
        CleanupException(Record.Exception(action));
    }
    private static void CleanupException(Exception? failure)
    {
        var ex = Assert.IsType<ResourceTransportException>(failure);
        Assert.Equal(ResourceTransportFailure.Cleanup, ex.Failure);
        Assert.Null(ex.InnerException); Assert.DoesNotContain("SECRET", ex.ToString());
    }
    private static void Marked(Exception primary)
    { Assert.Equal("Cleanup", primary.Data[ResourceCleanup.FailureMarker]); Assert.DoesNotContain("SECRET", primary.ToString()); }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task Throwing_shutdown_callback_does_not_skip_client_handler_or_lifetime_cleanup(bool reentrant)
    {
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var hostileCallbackEntered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        int hostileCallbacks = 0;
        var clock = new Clock();
        HttpOfficialResourceSource? source = null;
        var handler = new Handler(async (_, token) =>
        {
            using var callback = token.Register(() =>
            {
                Interlocked.Increment(ref hostileCallbacks);
                hostileCallbackEntered.TrySetResult();
                if (reentrant) source!.Dispose(); else throw new InvalidOperationException(Hostile);
            });
            entered.SetResult();
            try { await Task.Delay(Timeout.Infinite, token); }
            catch (OperationCanceledException)
            {
                // Cancellation is LIFO: Delay's later registration can complete first.
                // Do not let this continuation unregister the hostile callback before it
                // actually runs. Lifetime disposal itself must await its final retirement.
                await hostileCallbackEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
                throw;
            }
            throw new InvalidOperationException();
        }) { DuringDispose = () => throw new InvalidOperationException(Hostile) };
        source = new HttpOfficialResourceSource(handler, clock: clock);
        var operation = source.OpenAsync(Url, default).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Cleanup(source.Dispose);
        var primary = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => operation.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal(1, Volatile.Read(ref hostileCallbacks));
        Marked(primary); Assert.True(source.CleanupIncomplete); Assert.True(source.DisposalAttemptsComplete);
        Assert.Equal(1, handler.Disposals); Assert.Equal(1, clock.Timers.Single().Disposals);
        Cleanup(source.Dispose); Assert.Equal(1, handler.Disposals);
    }

    [Fact]
    public async Task Content_failure_attempts_acquired_body_and_timer_and_repeated_disposal_still_fails()
    {
        var body = new Body(); var content = new Content(body, true); var clock = new Clock();
        var handler = Respond(content); var source = new HttpOfficialResourceSource(handler, clock: clock);
        var response = await source.OpenAsync(Url, default);
        Cleanup(response.Dispose);
        Assert.Equal(1, content.Opens); Assert.Equal(1, content.Disposals); Assert.Equal(1, body.Disposals);
        Assert.Equal(1, clock.Timers.Single().Disposals); Assert.True(source.CleanupIncomplete);
        Cleanup(response.Dispose); Assert.Equal(1, content.Disposals); Assert.Equal(1, body.Disposals);
        Cleanup(source.Dispose); Assert.Equal(1, handler.Disposals);
    }

    [Fact]
    public async Task Rejected_response_preserves_status_and_does_not_read_inaccessible_body_to_cleanup()
    {
        var body = new Body(); var content = new Content(body, true); var clock = new Clock();
        var source = new HttpOfficialResourceSource(Respond(content, HttpStatusCode.Forbidden), clock: clock);
        var primary = await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(Url, default));
        Assert.Equal(ResourceTransportFailure.Status, primary.Failure); Marked(primary);
        Assert.Equal(0, content.Opens); Assert.Equal(0, body.Reads); Assert.Equal(0, body.Disposals);
        Assert.Equal(1, content.Disposals); Assert.Equal(1, clock.Timers.Single().Disposals);
        Cleanup(source.Dispose);
    }

    [Fact]
    public async Task Version_scope_preserves_read_failure_and_reports_throwing_stream_disposal()
    {
        var body = new Body { ThrowRead = true, ThrowDispose = true }; var content = new Content(body, false);
        var clock = new Clock(); var source = new HttpOfficialResourceSource(Respond(content), clock: clock);
        var primary = await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.ObserveAsync(default));
        Assert.Equal(ResourceTransportFailure.Transport, primary.Failure); Marked(primary);
        Assert.True(body.Disposals >= 1); Assert.Equal(1, clock.Timers.Single().Disposals);
        Cleanup(source.Dispose);
    }

    private sealed class InvalidResponseSource(Body body) : IResourceSource
    {
        public ValueTask<OfficialVersionSnapshot> ObserveAsync(CancellationToken token) => ValueTask.FromResult(BundleSourceFixtures.Snapshot());
        public ValueTask<ResourceResponse> OpenAsync(string url, CancellationToken token) => ValueTask.FromResult(new ResourceResponse(url, 500, null, body));
    }
    [Fact]
    public async Task Preparation_scope_preserves_its_own_validation_failure_when_dispose_throws()
    {
        var body = new Body { ThrowDispose = true };
        var primary = await Assert.ThrowsAsync<BundleSourceException>(() => new BundleSourcePreparation().PrepareAsync(new InvalidResponseSource(body)));
        Assert.Equal(BundleSourceFailure.ResponseSource, primary.Failure); Marked(primary);
        Assert.Equal(0, body.Reads); Assert.Equal(1, body.Disposals);
    }

    [Fact]
    public void Throwing_timer_cancellation_callbacks_never_escape_timer_thread_and_cleanup_remains_failed()
    {
        var clock = new Clock(); int failures = 0, callbacks = 0;
        var lifetime = new ResourceRequestLifetime(default, default, TimeSpan.FromSeconds(1), clock, () => failures++);
        using var callback1 = lifetime.Token.Register(() => { callbacks++; throw new Exception(Hostile); });
        using var callback2 = lifetime.Token.Register(() => { callbacks++; throw new Exception(Hostile); });
        Assert.Null(Record.Exception(clock.Timers.Single().Fire)); Assert.Equal(2, callbacks);
        Cleanup(lifetime.Dispose); Assert.True(lifetime.DisposalAttemptsComplete); Assert.True(failures > 0);
        Cleanup(lifetime.Dispose); Assert.Equal(1, clock.Timers.Single().Disposals);
    }

    [Fact]
    public async Task Ordinary_lifetime_disposal_waits_actual_callback_retirement_even_with_racing_caller_cancel()
    {
        var clock = new Clock(); using var caller = new CancellationTokenSource();
        var lifetime = new ResourceRequestLifetime(caller.Token, default, TimeSpan.FromSeconds(1), clock, () => { });
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var callback = lifetime.Token.Register(() => { entered.Set(); release.Wait(); });
        var firing = Task.Run(clock.Timers.Single().Fire);
        Task disposal = Task.CompletedTask;
        try
        {
            Assert.True(entered.Wait(TimeSpan.FromSeconds(5)));
            caller.Cancel(); // Its second Cancel cannot retire the still-active timer callback.
            disposal = Task.Run(lifetime.Dispose);
            await clock.Timers.Single().DisposalEntered.Task.WaitAsync(TimeSpan.FromSeconds(5));
            Assert.False(disposal.IsCompleted); Assert.False(lifetime.DisposalAttemptsComplete);
        }
        finally { release.Set(); }
        await Task.WhenAll(firing, disposal).WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(lifetime.DisposalAttemptsComplete); Assert.False(lifetime.CleanupIncomplete);
        lifetime.Dispose(); Assert.Equal(1, clock.Timers.Single().Disposals);
    }

    [Fact]
    public async Task Same_callback_disposal_fails_explicitly_and_defers_CTS_cleanup_without_self_deadlock()
    {
        var clock = new Clock(); int failures = 0;
        var lifetime = new ResourceRequestLifetime(default, default, TimeSpan.FromSeconds(1), clock, () => failures++);
        Exception? callbackFailure = null; bool? completionInsideCallback = null;
        using var callback = lifetime.Token.Register(() =>
        {
            callbackFailure = Record.Exception(lifetime.Dispose);
            completionInsideCallback = lifetime.DisposalAttemptsComplete;
        });
        await Task.Run(clock.Timers.Single().Fire).WaitAsync(TimeSpan.FromSeconds(5));
        CleanupException(callbackFailure); Assert.Equal(false, completionInsideCallback);
        Assert.True(lifetime.DisposalAttemptsComplete); Assert.True(failures > 0);
        Cleanup(lifetime.Dispose); Assert.Equal(1, clock.Timers.Single().Disposals);
    }

    [Fact]
    public async Task Concurrent_source_dispose_reports_pending_rather_than_false_success_or_duplicate_cleanup()
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        var handler = new Handler((_, _) => throw new InvalidOperationException())
            { DuringDispose = () => { entered.Set(); release.Wait(); } };
        var source = new HttpOfficialResourceSource(handler);
        var disposal = Task.Run(source.Dispose);
        try
        {
            Assert.True(entered.Wait(TimeSpan.FromSeconds(5)));
            Cleanup(source.Dispose); Assert.False(source.DisposalAttemptsComplete);
        }
        finally { release.Set(); }
        await disposal.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(source.DisposalAttemptsComplete); Assert.False(source.CleanupIncomplete);
        source.Dispose(); Assert.Equal(1, handler.Disposals);
    }
    [Fact]
    public async Task Timer_setup_failure_preserves_safe_primary_and_marks_failed_timer_cleanup()
    {
        var clock = new Clock { ThrowChange = true, ThrowTimerDispose = true };
        var handler = new Handler((_, _) => throw new InvalidOperationException("Should not send"));
        var source = new HttpOfficialResourceSource(handler, clock: clock);
        var primary = await Assert.ThrowsAsync<ResourceTransportException>(async () => await source.OpenAsync(Url, default));
        Assert.Equal(ResourceTransportFailure.Transport, primary.Failure); Marked(primary);
        Assert.Equal(1, clock.Timers.Single().Disposals); Assert.True(source.CleanupIncomplete);
        Cleanup(source.Dispose); Assert.Equal(1, handler.Disposals);
    }

    [Fact]
    public async Task Actual_response_disposal_from_its_cancellation_callback_reports_pending_without_deadlock()
    {
        var clock = new Clock(); var body = new Body(); var content = new Content(body, false);
        var source = new HttpOfficialResourceSource(Respond(content), clock: clock);
        var response = await source.OpenAsync(Url, default);
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        Exception? callbackFailure = null;
        var callbackFinished = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        int callbackCalls = 0;
        body.BeforeRead = async token =>
        {
            using var callback = token.Register(() =>
            {
                Interlocked.Increment(ref callbackCalls);
                callbackFailure = Record.Exception(response.Dispose);
                callbackFinished.TrySetResult();
            });
            entered.TrySetResult();
            try { await Task.Delay(Timeout.Infinite, token); }
            catch (OperationCanceledException)
            {
                // Delay registers last and is cancelled first. Its continuation must not
                // unregister the disposal callback before the cancellation thread invokes it.
                await callbackFinished.Task.WaitAsync(TimeSpan.FromSeconds(5));
                throw;
            }
        };
        var reading = response.Body.ReadAsync(new byte[1]).AsTask();
        await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
        await Task.Run(clock.Timers.Single().Fire).WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(1, Volatile.Read(ref callbackCalls));
        CleanupException(callbackFailure);
        var primary = await Assert.ThrowsAsync<ResourceTransportException>(() => reading.WaitAsync(TimeSpan.FromSeconds(5)));
        Assert.Equal(ResourceTransportFailure.Timeout, primary.Failure);
        Cleanup(response.Dispose); Cleanup(source.Dispose);
        Assert.True(source.CleanupIncomplete); Assert.Equal(1, clock.Timers.Single().Disposals);
        Assert.True(body.Disposals >= 1);
    }

    [Fact]
    public void Callback_unregistered_by_later_LIFO_callback_never_runs_and_does_not_create_cleanup_failure()
    {
        var clock = new Clock(); int failures = 0, hostileCallbacks = 0;
        var lifetime = new ResourceRequestLifetime(default, default, TimeSpan.FromSeconds(1), clock, () => failures++);
        using var hostile = lifetime.Token.Register(() => { hostileCallbacks++; throw new Exception(Hostile); });
        // Deterministically reproduce the old test's unregister-before-invocation outcome,
        // without depending on ThreadPool timing or repeatedly retrying a flaky scenario.
        using var removeFirst = lifetime.Token.Register(hostile.Dispose);
        clock.Timers.Single().Fire();
        Assert.Equal(0, hostileCallbacks); Assert.Equal(0, failures);
        lifetime.Dispose(); Assert.False(lifetime.CleanupIncomplete);
        Assert.True(lifetime.DisposalAttemptsComplete);
    }

}
