using System.Collections.Concurrent;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class ReceiveEventHookTests
{
    private static readonly TimeSpan Limit = TimeSpan.FromSeconds(10);
    private static readonly Packet Ping = new(1, 23);
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static ReceiveAttempt Create(IReceiveTransport transport,
        Func<ServerEvent, CancellationToken, ValueTask> hook,
        Action<ReceivePublication>? observer = null,
        Func<ServiceStateSnapshot, double, ServiceObservationInputs>? observe = null) =>
        new(transport, 0xAD, () => 123, observe ?? ((_, now) => new(now)), observer, beforeCommit: hook);

    [Fact]
    public async Task HooksAreLosslessOrderedAndAwaitedBeforeStateOrNextEvent()
    {
        var entered = Signal(); var release = Signal();
        var seen = new ConcurrentQueue<(byte Main, byte Sub, long Revision, Thread Writer)>();
        ReceiveAttempt? attempt = null;
        attempt = Create(new ScriptedTransport([Ping, new(1, 11), new(26, 4, [7, 0, 0, 0])]), async (value, token) =>
        {
            seen.Enqueue((value.Main, value.Sub, attempt!.Latest.Revision, Thread.CurrentThread));
            Assert.True(token.CanBeCanceled);
            if (seen.Count == 1) { entered.TrySetResult(); await release.Task; }
        });
        var run = attempt.RunAsync();
        try
        {
            await entered.Task.WaitAsync(Limit);
            Assert.Single(seen);
            Assert.Equal(0, attempt.Latest.Revision);
            Assert.Equal(0, attempt.Latest.Snapshot.PacketCount);
            Assert.False(run.IsCompleted);
        }
        finally { release.TrySetResult(); }
        var result = await run.WaitAsync(Limit);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        Assert.Equal(3, result.Publication.Revision);
        Assert.Equal(new[] { ((byte)1, (byte)23), ((byte)1, (byte)11), ((byte)26, (byte)4) },
            seen.Select(x => (x.Main, x.Sub)).ToArray());
        Assert.Equal(new long[] { 0, 1, 2 }, seen.Select(x => x.Revision).ToArray());
        var writer = Assert.Single(seen.Select(x => x.Writer).Distinct());
        Assert.False(writer.IsAlive);
        await attempt.DisposeAsync();
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(false, true)]
    [InlineData(true, false)]
    [InlineData(true, true)]
    public async Task RetirementClosesTransportButWaitsForHookAndDiscardsItsLateResult(bool cancel, bool failLate)
    {
        var entered = Signal(); var release = Signal(); var cancelled = Signal();
        var transport = new ScriptedTransport([Ping, Ping]);
        var calls = 0; var publications = 0;
        using var source = new CancellationTokenSource();
        var attempt = Create(transport, async (_, token) =>
        {
            Interlocked.Increment(ref calls);
            using var registration = token.Register(() => cancelled.TrySetResult());
            entered.TrySetResult();
            await release.Task; // Deliberately ignores cancellation until the test releases it.
            if (failLate) throw new IOException("private hook payload");
        }, _ => Interlocked.Increment(ref publications));
        var run = attempt.RunAsync(source.Token);
        Task? cleanup = null;
        try
        {
            await entered.Task.WaitAsync(Limit);
            if (cancel) source.Cancel();
            else cleanup = attempt.DisposeAsync().AsTask();
            Assert.False(attempt.IsCurrent(attempt.Latest.Attempt));
            await transport.Disposed.Task.WaitAsync(Limit);
            await cancelled.Task.WaitAsync(Limit);
            Assert.False(run.IsCompleted);
            cleanup ??= attempt.DisposeAsync().AsTask();
            Assert.False(cleanup.IsCompleted);
            Assert.Equal(0, attempt.Latest.Revision);
        }
        finally { release.TrySetResult(); }
        await cleanup!.WaitAsync(Limit);
        var result = await run.WaitAsync(Limit);
        Assert.Equal(cancel ? ReceiveEnd.Cancelled : ReceiveEnd.Disposed, result.End);
        Assert.Equal(0, result.Publication.Revision);
        Assert.Equal(0, result.Publication.Snapshot.PacketCount);
        Assert.Equal(1, calls);
        Assert.Equal(0, publications);
        Assert.True(result.ResourcesReleased);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task HookFailuresAreTerminalSanitizedAndKeepOnlyPriorCommits(bool asynchronous)
    {
        var entered = Signal(); var release = Signal(); var calls = 0;
        ValueTask Hook(ServerEvent value, CancellationToken token)
        {
            if (++calls != 2) return ValueTask.CompletedTask;
            if (!asynchronous) throw new IOException("private hook payload");
            return FailAsync();
        }
        async ValueTask FailAsync()
        {
            entered.TrySetResult();
            await release.Task;
            throw new IOException("private hook payload");
        }
        await using var attempt = Create(new ScriptedTransport([Ping, Ping, Ping]), Hook);
        var run = attempt.RunAsync();
        if (asynchronous)
        {
            try
            {
                await entered.Task.WaitAsync(Limit);
                Assert.Equal(1, attempt.Latest.Revision);
                Assert.False(run.IsCompleted);
            }
            finally { release.TrySetResult(); }
        }
        var result = await run.WaitAsync(Limit);
        Assert.Equal(ReceiveEnd.EventHandlerFailed, result.End);
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(1, result.Publication.Snapshot.PacketCount);
        Assert.Equal(2, calls);
        Assert.DoesNotContain("private", result.ToString());
    }

    [Fact]
    public async Task RetirementDuringObservationDoesNotAdmitHook()
    {
        var entered = Signal(); using var release = new ManualResetEventSlim(); var calls = 0;
        var attempt = Create(new ScriptedTransport([Ping]), (_, _) =>
        { Interlocked.Increment(ref calls); return ValueTask.CompletedTask; }, observe: (_, now) =>
        { entered.TrySetResult(); Assert.True(release.Wait(Limit)); return new(now); });
        var run = attempt.RunAsync();
        Task cleanup;
        try
        {
            await entered.Task.WaitAsync(Limit);
            cleanup = attempt.DisposeAsync().AsTask();
            Assert.False(cleanup.IsCompleted);
        }
        finally { release.Set(); }
        await cleanup.WaitAsync(Limit);
        Assert.Equal(0, calls);
        Assert.Equal(0, (await run).Publication.Revision);
    }

    [Fact]
    public async Task AccountAttachmentForwardsHookAndDisconnectWaitsForIt()
    {
        var session = new AccountSession();
        var generation = session.Begin("synthetic", "hook").Generation;
        var entered = Signal(); var release = Signal();
        var transport = new ScriptedTransport([Ping]);
        var attempt = Assert.IsType<ReceiveAttempt>(session.AttachHeldReceive(generation, transport, 0xAD,
            () => 123, (_, now) => new(now), beforeCommit: async (_, _) =>
            { entered.TrySetResult(); await release.Task; }));
        var run = attempt.RunAsync();
        try
        {
            await entered.Task.WaitAsync(Limit);
            session.Disconnect();
            await transport.Disposed.Task.WaitAsync(Limit);
            Assert.Null(session.ReadHeldReceive(generation, attempt.Latest.Attempt));
            Assert.False(run.IsCompleted);
        }
        finally { release.TrySetResult(); }
        Assert.Equal(0, (await run.WaitAsync(Limit)).Publication.Revision);
        await attempt.DisposeAsync();
    }

    private sealed class ScriptedTransport(Packet[] packets) : IReceiveTransport
    {
        private readonly byte[] bytes = packets.SelectMany(p => WireCodec.Encode(p, 0xAD)).ToArray();
        private int offset;
        public TaskCompletionSource Disposed { get; } = Signal();
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken token)
        {
            token.ThrowIfCancellationRequested();
            var count = Math.Min(destination.Length, bytes.Length - offset);
            bytes.AsMemory(offset, count).CopyTo(destination);
            offset += count;
            return new(count);
        }
        public ValueTask DisposeAsync() { Disposed.TrySetResult(); return ValueTask.CompletedTask; }
    }
}
