using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Xunit;

namespace Lala.Core.Tests.Sessions.Transport;

public sealed class BoundedTcpTransportTests
{
    private static readonly TimeSpan Deadline = TimeSpan.FromSeconds(10);
    private sealed class Pair(TcpListener listener, BoundedTcpTransport client, Socket server) : IAsyncDisposable
    {
        internal BoundedTcpTransport Client { get; } = client;
        internal Socket Server { get; } = server;
        public async ValueTask DisposeAsync()
        {
            Server.Dispose(); listener.Stop();
            await Client.DisposeAsync().AsTask().WaitAsync(Deadline);
        }
    }
    private static async Task<Pair> Open(TcpTransportLimits? limits = null)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Server.ReceiveBufferSize = 1024;
        listener.Start(4);
        var client = new BoundedTcpTransport((IPEndPoint)listener.LocalEndpoint, limits);
        try
        {
            var accept = listener.AcceptSocketAsync();
            await client.ConnectAsync().WaitAsync(Deadline);
            var server = await accept.WaitAsync(Deadline);
            server.ReceiveBufferSize = 1024;
            return new(listener, client, server);
        }
        catch { listener.Stop(); await client.DisposeAsync(); throw; }
    }
    private static async Task<byte[]> ReadExact(Socket socket, int count)
    {
        var bytes = new byte[count]; int offset = 0;
        while (offset < count)
        {
            int read = await socket.ReceiveAsync(bytes.AsMemory(offset), SocketFlags.None).AsTask().WaitAsync(Deadline);
            Assert.True(read > 0); offset += read;
        }
        return bytes;
    }
    private static async Task SendExact(Socket socket, ReadOnlyMemory<byte> bytes)
    {
        int offset = 0;
        while (offset < bytes.Length)
        {
            int sent = await socket.SendAsync(bytes[offset..], SocketFlags.None).AsTask().WaitAsync(Deadline);
            Assert.True(sent > 0); offset += sent;
        }
    }
    private static async Task<Task<TcpWriteResult>> FillUntilPending(BoundedTcpTransport client, CancellationToken token = default)
    {
        // Bounded synthetic loopback pressure, not retransmission by the transport.
        for (int i = 0; i < 128; i++)
        {
            var write = client.WriteAsync(new byte[65539], token);
            if (!write.IsCompleted) return write;
            Assert.Equal(TcpWriteOutcome.Complete, (await write).Outcome);
        }
        throw new InvalidOperationException("Loopback send queue did not fill within the test budget.");
    }

    [Fact]
    public async Task ReadWriteUsesRealLoopbackAndLocalCompletionOnly()
    {
        await using var pair = await Open(new() { SendChunkBytes = 3 });
        byte[] payload = [1, 2, 3, 4, 5, 6, 7];
        var received = ReadExact(pair.Server, payload.Length);
        var result = await pair.Client.WriteAsync(payload).WaitAsync(Deadline);
        Assert.Equal(TcpWriteOutcome.Complete, result.Outcome);
        Assert.Equal(payload.Length, result.ConfirmedLocalBytes);
        Assert.Equal(payload, await received);
        await SendExact(pair.Server, new byte[] { 9, 8, 7 });
        var buffer = new byte[3]; int total = 0;
        while (total < 3) total += await pair.Client.ReadAsync(buffer.AsMemory(total), default);
        Assert.Equal(new byte[] { 9, 8, 7 }, buffer);
        Assert.Equal(TcpTransportStage.Connected, pair.Client.Snapshot.Stage);
    }

    [Fact]
    public async Task EndpointIsSnapshottedAndConnectIsOneShot()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var endpoint = (IPEndPoint)listener.LocalEndpoint;
        await using var client = new BoundedTcpTransport(endpoint);
        endpoint.Port = 1; // Mutating caller object cannot redirect the captured target.
        try
        {
            var accept = listener.AcceptSocketAsync();
            var first = client.ConnectAsync();
            using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
            Assert.Same(first, client.ConnectAsync(cancelled.Token));
            await first.WaitAsync(Deadline);
            using var server = await accept.WaitAsync(Deadline);
            Assert.Same(first, client.ConnectAsync());
        }
        finally { listener.Stop(); }
    }

    [Fact]
    public async Task DisposeBeforeConnectNeverDialsAndIsIdempotent()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        await using var client = new BoundedTcpTransport((IPEndPoint)listener.LocalEndpoint);
        try
        {
            var first = client.DisposeAsync().AsTask(); var second = client.DisposeAsync().AsTask();
            Assert.Same(first, second); await first.WaitAsync(Deadline);
            var error = await Assert.ThrowsAsync<TcpTransportException>(() => client.ConnectAsync());
            Assert.Equal(TcpTransportEnd.Disposed, error.Reason);
            Assert.False(listener.Pending());
            Assert.Equal(TcpTransportStage.Disposed, client.Snapshot.Stage);
        }
        finally { listener.Stop(); }
    }

    [Fact]
    public async Task PrecancelledConnectNeverDialsOrRetries()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        await using var client = new BoundedTcpTransport((IPEndPoint)listener.LocalEndpoint);
        try
        {
            using var stop = new CancellationTokenSource(); stop.Cancel();
            var first = client.ConnectAsync(stop.Token);
            var error = await Assert.ThrowsAsync<TcpTransportException>(() => first);
            Assert.Equal(TcpTransportEnd.Cancelled, error.Reason);
            Assert.Same(first, client.ConnectAsync()); Assert.False(listener.Pending());
        }
        finally { listener.Stop(); }
    }

    [Fact]
    public async Task PeerEofRetiresAndPreventsWrites()
    {
        await using var pair = await Open(); pair.Server.Shutdown(SocketShutdown.Send);
        Assert.Equal(0, await pair.Client.ReadAsync(new byte[4], default));
        Assert.Equal(TcpTransportEnd.EndOfStream, pair.Client.Snapshot.End);
        Assert.Throws<TcpTransportException>(() => { _ = pair.Client.WriteAsync(new byte[] { 1 }); });
    }

    [Fact]
    public async Task ReadBoundLeavesUnusedDestinationUntouched()
    {
        await using var pair = await Open(new() { MaximumReadBytes = 2 });
        await SendExact(pair.Server, new byte[] { 1, 2, 3, 4 });
        var destination = Enumerable.Repeat((byte)99, 8).ToArray();
        int read = await pair.Client.ReadAsync(destination, default);
        Assert.InRange(read, 1, 2);
        Assert.All(destination.Skip(read), value => Assert.Equal(99, value));
    }

    [Fact]
    public async Task InvalidAndConcurrentOperationsAreNotQueued()
    {
        await using var pair = await Open(new() { MaximumWriteBytes = 2 });
        Assert.Throws<ArgumentException>(() => pair.Client.ReadAsync(Memory<byte>.Empty, default));
        Assert.Throws<ArgumentOutOfRangeException>(() => { _ = pair.Client.WriteAsync(ReadOnlyMemory<byte>.Empty); });
        Assert.Throws<ArgumentOutOfRangeException>(() => { _ = pair.Client.WriteAsync(new byte[3]); });
        var read = pair.Client.ReadAsync(new byte[1], default).AsTask();
        Assert.Throws<InvalidOperationException>(() => pair.Client.ReadAsync(new byte[1], default));
        await SendExact(pair.Server, new byte[] { 42 });
        Assert.Equal(1, await read.WaitAsync(Deadline));
    }

    [Fact]
    public async Task ReadAndWriteCanRunConcurrently()
    {
        await using var pair = await Open(); var readBuffer = new byte[1];
        var read = pair.Client.ReadAsync(readBuffer, default).AsTask();
        var result = await pair.Client.WriteAsync(new byte[] { 21 }).WaitAsync(Deadline);
        Assert.Equal(TcpWriteOutcome.Complete, result.Outcome);
        Assert.Equal(new byte[] { 21 }, await ReadExact(pair.Server, 1));
        await SendExact(pair.Server, new byte[] { 34 });
        Assert.Equal(1, await read.WaitAsync(Deadline)); Assert.Equal(34, readBuffer[0]);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task ReadCancellationAndTimeoutRetire(bool cancel)
    {
        await using var pair = await Open(new() { ReadTimeout = cancel ? Deadline : TimeSpan.FromMilliseconds(50) });
        using var stop = new CancellationTokenSource();
        var read = pair.Client.ReadAsync(new byte[1], stop.Token).AsTask();
        if (cancel) stop.Cancel();
        var error = await Assert.ThrowsAsync<TcpTransportException>(() => read.WaitAsync(Deadline));
        Assert.Equal(cancel ? TcpTransportEnd.Cancelled : TcpTransportEnd.TimedOut, error.Reason);
        Assert.Equal(TcpTransportStage.Retired, pair.Client.Snapshot.Stage);
        Assert.Throws<TcpTransportException>(() => pair.Client.ReadAsync(new byte[1], default));
    }

    [Fact]
    public async Task DisposeWaitsForActualReadTask()
    {
        await using var pair = await Open(); var read = pair.Client.ReadAsync(new byte[1], default).AsTask();
        Assert.True(pair.Client.Snapshot.ReadPending);
        var dispose = pair.Client.DisposeAsync().AsTask();
        Assert.Same(dispose, pair.Client.DisposeAsync().AsTask());
        await dispose.WaitAsync(Deadline);
        Assert.True(read.IsCompleted);
        var error = await Assert.ThrowsAsync<TcpTransportException>(() => read);
        Assert.Equal(TcpTransportEnd.Disposed, error.Reason);
        Assert.Equal(TcpTransportStage.Disposed, pair.Client.Snapshot.Stage);
    }

    [Fact]
    public async Task PrecancelledWriteIsNotStartedAndRetires()
    {
        await using var pair = await Open(); using var stop = new CancellationTokenSource(); stop.Cancel();
        var result = await pair.Client.WriteAsync(new byte[] { 1 }, stop.Token);
        Assert.Equal(TcpWriteOutcome.NotStarted, result.Outcome);
        Assert.Equal(0, result.ConfirmedLocalBytes); Assert.Equal(TcpTransportEnd.Cancelled, result.End);
        Assert.Equal(0, await pair.Server.ReceiveAsync(new byte[1].AsMemory(), SocketFlags.None).AsTask().WaitAsync(Deadline));
    }

    [Fact]
    public async Task CallerMutationCannotChangePendingWrite()
    {
        await using var pair = await Open(new() { SendChunkBytes = 7, SocketBufferBytes = 1024 });
        var input = Enumerable.Repeat((byte)53, 65539).ToArray();
        var write = pair.Client.WriteAsync(input); Array.Fill(input, (byte)99);
        var received = await ReadExact(pair.Server, input.Length);
        Assert.All(received, value => Assert.Equal(53, value));
        Assert.Equal(TcpWriteOutcome.Complete, (await write.WaitAsync(Deadline)).Outcome);
    }

    [Fact]
    public async Task ResetAfterKnownPrefixNeverImpliesNoBytesOrReplays()
    {
        await using var pair = await Open(new() { SendChunkBytes = 1, SocketBufferBytes = 1024 });
        var write = pair.Client.WriteAsync(new byte[65539]);
        await ReadExact(pair.Server, 1); // Peer prefix barrier, not proof that local send remains pending.
        pair.Server.LingerState = new LingerOption(true, 0); pair.Server.Dispose();
        var result = await write.WaitAsync(Deadline);
        Assert.InRange(result.ConfirmedLocalBytes, 0, 65539);
        if (result.Outcome == TcpWriteOutcome.Complete)
        {
            Assert.Equal(65539, result.ConfirmedLocalBytes);
            // All local sends may win the race; peer rejection is still discovered by reading.
            await Assert.ThrowsAsync<TcpTransportException>(async () => await pair.Client.ReadAsync(new byte[1], default));
        }
        else Assert.Equal(TcpWriteOutcome.PartialOrUncertain, result.Outcome);
        Assert.Throws<TcpTransportException>(() => { _ = pair.Client.WriteAsync(new byte[] { 1 }); });
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)]
    public async Task BackpressuredWriteCancellationTimeoutAndDisposalAreTerminal(int reason)
    {
        await using var pair = await Open(new() { SocketBufferBytes = 1024,
            WriteTimeout = reason == 1 ? TimeSpan.FromMilliseconds(100) : Deadline });
        using var stop = new CancellationTokenSource();
        var write = await FillUntilPending(pair.Client, stop.Token);
        if (reason == 0) stop.Cancel();
        else if (reason == 2) await pair.Client.DisposeAsync().AsTask().WaitAsync(Deadline);
        var result = await write.WaitAsync(Deadline);
        // IsCompleted=false is only an observation, not a persistent backpressure barrier.
        // If a send wins the race, keep filling only for the timeout scenario; cancelled
        // next admission must stop before sending. Disposed transports admit nothing.
        if (reason == 0 && result.Outcome == TcpWriteOutcome.Complete)
            result = await pair.Client.WriteAsync(new byte[] { 1 }, stop.Token);
        if (reason == 1)
        {
            for (int i = 0; result.Outcome == TcpWriteOutcome.Complete && i < 128; i++)
                result = await pair.Client.WriteAsync(new byte[65539]).WaitAsync(Deadline);
            Assert.Equal(TcpWriteOutcome.PartialOrUncertain, result.Outcome);
        }
        if (reason != 2)
            Assert.Equal(reason == 0 ? TcpTransportEnd.Cancelled : TcpTransportEnd.TimedOut, result.End);
        await pair.Client.DisposeAsync().AsTask().WaitAsync(Deadline);
        Assert.True(write.IsCompleted); Assert.False(pair.Client.Snapshot.WritePending);
        Assert.Equal(reason switch { 0 => TcpTransportEnd.Cancelled, 1 => TcpTransportEnd.TimedOut, _ => TcpTransportEnd.Disposed }, pair.Client.Snapshot.End);
    }

    [Fact]
    public async Task OverlappingWriteIsRejectedOrStartsOnlyAfterPriorTaskCompleted()
    {
        await using var pair = await Open(new() { SocketBufferBytes = 1024 });
        var first = await FillUntilPending(pair.Client);
        Task<TcpWriteResult>? second = null;
        try
        {
            second = pair.Client.WriteAsync(new byte[] { 1 });
            Assert.True(first.IsCompleted); // A completed prior operation may free the lane.
        }
        catch (InvalidOperationException) { } // Still pending: rejected synchronously, never queued.
        await pair.Client.DisposeAsync().AsTask().WaitAsync(Deadline);
        Assert.True(first.IsCompleted);
        if (second is not null) Assert.True(second.IsCompleted);
    }

    [Fact]
    public async Task DisposeWaitsForSimultaneousReadAndBackpressuredWrite()
    {
        await using var pair = await Open(new() { SocketBufferBytes = 1024 });
        var read = pair.Client.ReadAsync(new byte[1], default).AsTask();
        var write = await FillUntilPending(pair.Client);
        await pair.Client.DisposeAsync().AsTask().WaitAsync(Deadline);
        Assert.True(read.IsCompleted); Assert.True(write.IsCompleted);
        await Assert.ThrowsAsync<TcpTransportException>(() => read);
        Assert.Contains((await write).Outcome, new[] { TcpWriteOutcome.Complete, TcpWriteOutcome.PartialOrUncertain });
    }

    [Fact]
    public async Task ReceiveAttemptConsumesLoopbackButStaysResourceHeld()
    {
        await using var pair = await Open(new() { MaximumReadBytes = 1 });
        await using var attempt = new ReceiveAttempt(pair.Client, 0xAD, () => 123, (_, now) => new(now));
        var receive = attempt.RunAsync();
        var bytes = WireCodec.Encode(new Packet(63, 7, [0, 2]));
        foreach (byte value in bytes) await SendExact(pair.Server, new byte[] { value });
        pair.Server.Shutdown(SocketShutdown.Send);
        var result = await receive.WaitAsync(Deadline);
        Assert.Equal(ReceiveEnd.Completed, result.End); Assert.True(result.ResourcesReleased);
        Assert.True(result.Publication.ResourceHeld); Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(TcpTransportStage.Disposed, pair.Client.Snapshot.Stage);
    }

    [Fact]
    public async Task ReceiveAttemptRejectsTruncatedLoopbackFrame()
    {
        await using var pair = await Open();
        await using var attempt = new ReceiveAttempt(pair.Client, 0xAD, () => 123, (_, now) => new(now));
        var receive = attempt.RunAsync();
        await SendExact(pair.Server, WireCodec.Encode(new Packet(1, 23)).AsMemory(0, 3));
        pair.Server.Shutdown(SocketShutdown.Send);
        var result = await receive.WaitAsync(Deadline);
        Assert.Equal(ReceiveEnd.TruncatedFrame, result.End); Assert.True(result.Publication.ResourceHeld);
        Assert.True(result.ResourcesReleased);
    }

    [Fact]
    public async Task LinuxConnectTimeoutAndDisposalUseOnlySaturatedLoopbackBacklog()
    {
        // Backlog admission is OS-specific. Portable cancellation/disposal tests above
        // still run everywhere; this Linux-only adverse experiment claims no other OS coverage.
        if (!OperatingSystem.IsLinux()) return;
        using var listener = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        listener.Bind(new IPEndPoint(IPAddress.Loopback, 0)); listener.Listen(1);
        var endpoint = (IPEndPoint)listener.LocalEndPoint!;
        var fillers = new List<Socket>(); bool saturated = false;
        try
        {
            for (int i = 0; i < 64; i++)
            {
                var filler = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp); fillers.Add(filler);
                using var timeout = new CancellationTokenSource(TimeSpan.FromMilliseconds(100));
                try { await filler.ConnectAsync(endpoint, timeout.Token); }
                catch (OperationCanceledException) { saturated = true; break; }
                catch (SocketException) when (timeout.IsCancellationRequested) { saturated = true; break; }
            }
            Assert.True(saturated);
            await using var client = new BoundedTcpTransport(endpoint, new() { ConnectTimeout = TimeSpan.FromMilliseconds(50) });
            var error = await Assert.ThrowsAsync<TcpTransportException>(() => client.ConnectAsync().WaitAsync(Deadline));
            Assert.Equal(TcpTransportEnd.TimedOut, error.Reason);
            await using var disposed = new BoundedTcpTransport(endpoint);
            var pending = disposed.ConnectAsync();
            await disposed.DisposeAsync().AsTask().WaitAsync(Deadline);
            Assert.True(pending.IsCompleted);
            var cancelled = await Assert.ThrowsAsync<TcpTransportException>(() => pending);
            Assert.Equal(TcpTransportEnd.Disposed, cancelled.Reason);
        }
        finally { foreach (var filler in fillers) filler.Dispose(); }
    }

    [Theory]
    [InlineData(0)] [InlineData(-1)] [InlineData(65537)]
    public void InvalidReadLimitsAreRejectedBeforeDial(int size)
        => Assert.Throws<ArgumentOutOfRangeException>(() => new BoundedTcpTransport(new(IPAddress.Loopback, 1), new() { MaximumReadBytes = size }));

    [Fact]
    public void InvalidTimeoutAndEndpointAreRejectedBeforeDial()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => new BoundedTcpTransport(new(IPAddress.Loopback, 1), new() { WriteTimeout = TimeSpan.Zero }));
        Assert.Throws<ArgumentException>(() => new BoundedTcpTransport(new(IPAddress.Loopback, 0)));
    }
    [Fact]
    public async Task RefusedLoopbackConnectionIsTerminalWithoutRetry()
    {
        using var reserved = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        reserved.Bind(new IPEndPoint(IPAddress.Loopback, 0));
        await using var client = new BoundedTcpTransport((IPEndPoint)reserved.LocalEndPoint!);
        // A bound non-listener can silently drop SYNs on macOS rather than refuse them.
        // Close our reservation immediately before dialing the captured endpoint. As with
        // any real closed-port fixture, another process could reuse the port after release.
        reserved.Dispose();
        var first = client.ConnectAsync();
        var error = await Assert.ThrowsAsync<TcpTransportException>(() => first.WaitAsync(Deadline));
        Assert.Equal(TcpTransportEnd.ConnectFailed, error.Reason);
        Assert.Same(first, client.ConnectAsync());
        Assert.Equal(TcpTransportStage.Retired, client.Snapshot.Stage);
    }

    [Fact]
    public async Task ResetDuringPendingReadIsSanitizedAndRetires()
    {
        await using var pair = await Open();
        var read = pair.Client.ReadAsync(new byte[1], default).AsTask();
        pair.Server.LingerState = new LingerOption(true, 0); pair.Server.Dispose();
        var error = await Assert.ThrowsAsync<TcpTransportException>(() => read.WaitAsync(Deadline));
        Assert.Equal(TcpTransportEnd.ReadFailed, error.Reason);
        Assert.Null(error.InnerException);
        Assert.Equal("TCP transport ended: ReadFailed", error.Message);
    }

    [Fact]
    public async Task ConcurrentAdmissionAndDisposalCannotLeaveOwnedOperationsRunning()
    {
        for (int iteration = 0; iteration < 20; iteration++)
        {
            await using var pair = await Open();
            var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var read = Task.Run(async () =>
            {
                await release.Task;
                try { await pair.Client.ReadAsync(new byte[1], default); }
                catch (TcpTransportException) { }
            });
            var write = Task.Run(async () =>
            {
                await release.Task;
                try { await pair.Client.WriteAsync(new byte[] { 1 }); }
                catch (TcpTransportException) { }
            });
            var dispose = Task.Run(async () => { await release.Task; await pair.Client.DisposeAsync(); });
            release.SetResult();
            await Task.WhenAll(read, write, dispose).WaitAsync(Deadline);
            Assert.Equal(TcpTransportStage.Disposed, pair.Client.Snapshot.Stage);
            Assert.False(pair.Client.Snapshot.ReadPending); Assert.False(pair.Client.Snapshot.WritePending);
        }
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public void OtherBoundsAreValidatedBeforeDial(int invalid)
    {
        var limits = invalid switch {
            0 => new TcpTransportLimits { MaximumWriteBytes = 65540 },
            1 => new TcpTransportLimits { SendChunkBytes = 0 },
            2 => new TcpTransportLimits { SocketBufferBytes = 65537 },
            _ => new TcpTransportLimits { ConnectTimeout = TimeSpan.FromMinutes(6) }
        };
        Assert.Throws<ArgumentOutOfRangeException>(() => new BoundedTcpTransport(new(IPAddress.Loopback, 1), limits));
    }

}
