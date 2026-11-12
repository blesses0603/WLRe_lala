using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions.Receive;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed class HeldAccountReconnectObservationTests
{
    private static readonly TimeSpan Guard = TimeSpan.FromSeconds(30);
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static HeldAccountReconnect Controller(AccountSession session, long generation,
        Func<int, CancellationToken, ValueTask<Func<HandshakeLeg, Packet>?>> credentials) =>
        new(session, generation, new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1),
            0xAD, 0xAD, 1, credentials, () => 123, (_, now) => new(now));

    [Fact]
    public async Task EqualButDistinctViewReturnsCurrentIdentityImmediately()
    {
        var session = new AccountSession(); var initial = session.Begin("synthetic", "loopback");
        int requests = 0;
        await using var controller = Controller(session, initial.Generation, (_, _) =>
        {
            requests++;
            return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(null);
        });
        var expected = controller.Snapshot;
        var equal = expected with { };
        Assert.Equal(expected, equal);
        Assert.NotSame(expected, equal);
        var changed = controller.WaitForChangeAsync(equal);
        Assert.True(changed.IsCompletedSuccessfully);
        Assert.Same(expected, await changed);
        Assert.Equal(0, requests);
        Assert.Same(initial, session.Snapshot);
    }

    [Fact]
    public async Task WaiterCancellationIsInertAndDoesNotCancelSharedSignal()
    {
        var session = new AccountSession(); var initial = session.Begin("synthetic", "loopback");
        int requests = 0;
        await using var controller = Controller(session, initial.Generation, (_, _) =>
        {
            requests++;
            return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(null);
        });
        var expected = controller.Snapshot;
        using var cancellation = new CancellationTokenSource();
        var canceled = controller.WaitForChangeAsync(expected, cancellation.Token);
        var surviving = controller.WaitForChangeAsync(expected);
        Assert.False(canceled.IsCompleted);
        Assert.False(surviving.IsCompleted);
        cancellation.Cancel();
        var error = await Assert.ThrowsAnyAsync<OperationCanceledException>(() => canceled);
        Assert.Equal(cancellation.Token, error.CancellationToken);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            controller.WaitForChangeAsync(expected, cancellation.Token));
        Assert.False(surviving.IsCompleted);
        Assert.Same(expected, controller.Snapshot);
        Assert.Same(initial, session.Snapshot);
        Assert.Equal(0, requests);

        controller.Stop();
        var ending = await surviving.WaitAsync(Guard);
        Assert.Equal(ReconnectPhase.Ending, ending.Phase);
        Assert.Equal(ReconnectEnd.Stopped, ending.End);
        // A changed identity is already available even when the caller's token was canceled.
        Assert.Same(ending, await controller.WaitForChangeAsync(expected, cancellation.Token));
        Assert.Equal(0, requests);
    }

    [Fact]
    public async Task ChangeBetweenSnapshotAndWaitReturnsLatestIncludingTerminalView()
    {
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var controller = Controller(session, generation, (_, _) =>
            throw new InvalidOperationException("An observation must not request credentials."));
        var created = controller.Snapshot;
        controller.Stop();
        var ending = controller.Snapshot;
        var changed = controller.WaitForChangeAsync(created);
        Assert.True(changed.IsCompletedSuccessfully);
        Assert.Same(ending, await changed);

        var terminal = controller.WaitForChangeAsync(ending);
        Assert.False(terminal.IsCompleted);
        await controller.DisposeAsync();
        var ended = await terminal.WaitAsync(Guard);
        Assert.Equal(ReconnectPhase.Ended, ended.Phase);
        Assert.Equal(ReconnectEnd.Stopped, ended.End);
        Assert.Same(ended, controller.Snapshot);
        Assert.Same(ended, await controller.WaitForChangeAsync(created));
        Assert.Same(ended, await controller.WaitForChangeAsync(ending));

        using var cancellation = new CancellationTokenSource();
        var unchanged = controller.WaitForChangeAsync(ended, cancellation.Token);
        Assert.False(unchanged.IsCompleted);
        controller.Stop();
        await controller.DisposeAsync();
        Assert.False(unchanged.IsCompleted);
        cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => unchanged);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task StopOrDisposeSignalsImmediatelyAndEndWaitsForCredentialCleanup(bool dispose)
    {
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        var entered = Signal(); var release = Signal();
        await using var controller = Controller(session, generation, async (_, _) =>
        {
            entered.SetResult();
            await release.Task;
            return null;
        });
        var acquisition = controller.WaitForChangeAsync(controller.Snapshot);
        var run = controller.RunAsync();
        await entered.Task.WaitAsync(Guard);
        var acquiring = await acquisition.WaitAsync(Guard);
        Assert.Equal(ReconnectPhase.AcquiringCredentials, acquiring.Phase);
        var stopping = controller.WaitForChangeAsync(acquiring);
        Task? cleanup = null;
        try
        {
            if (dispose) cleanup = controller.DisposeAsync().AsTask();
            else controller.Stop();
            Assert.True(stopping.IsCompletedSuccessfully);
            var ending = await stopping;
            Assert.Equal(ReconnectPhase.Ending, ending.Phase);
            Assert.Equal(dispose ? ReconnectEnd.Disposed : ReconnectEnd.Stopped, ending.End);
            Assert.False(run.IsCompleted);
            Assert.Null(controller.Publication);
            var endingWait = controller.WaitForChangeAsync(ending);
            Assert.False(endingWait.IsCompleted);
            release.TrySetResult();
            var ended = await endingWait.WaitAsync(Guard);
            var result = await run.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Ended, ended.Phase);
            Assert.Same(ended, result.View);
            Assert.True(result.ResourcesReleased);
            if (cleanup is not null) await cleanup.WaitAsync(Guard);
        }
        finally { release.TrySetResult(); }
    }

    [Fact]
    public async Task ObserverContinuationIsNotInvokedInlineByStop()
    {
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var controller = Controller(session, generation, (_, _) =>
            ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(null));
        using var insideStop = new ThreadLocal<bool>(() => false);
        var changed = controller.WaitForChangeAsync(controller.Snapshot);
        var continuation = changed.ContinueWith(_ => insideStop.Value, CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        insideStop.Value = true;
        try { controller.Stop(); }
        finally { insideStop.Value = false; }
        Assert.False(await continuation.WaitAsync(Guard));
    }

    [Fact]
    public async Task ConcurrentStopAndSubscriptionNeverLoseWake()
    {
        for (int iteration = 0; iteration < 32; iteration++)
        {
            var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
            await using var controller = Controller(session, generation, (_, _) =>
                ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(null));
            var expected = controller.Snapshot;
            var start = Signal();
            var wait = Task.Run(async () =>
            {
                await start.Task;
                return await controller.WaitForChangeAsync(expected);
            });
            var stopping = Task.Run(async () => { await start.Task; controller.Stop(); });
            start.SetResult();
            await stopping.WaitAsync(Guard);
            var changed = await wait.WaitAsync(Guard);
            Assert.Same(controller.Snapshot, changed);
            Assert.Equal(ReconnectPhase.Ending, changed.Phase);
        }
    }

    [Fact]
    public async Task LoginHistoryBackoffAndReplacementAssignmentsWakeObservers()
    {
        using var guard = new CancellationTokenSource(Guard);
        using var verification = new TcpListener(IPAddress.Loopback, 0);
        using var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        var credentials = Signal(); var verify = Signal(); var disconnect = Signal();
        var delayEntered = Signal(); var retry = Signal(); var secondEntered = Signal(); var secondRelease = Signal();
        var firstPeer = VerifyAsync(verification, verify.Task, guard.Token);
        var secondPeer = EnterWorldAsync(formal, disconnect.Task, guard.Token);
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var controller = new HeldAccountReconnect(session, generation,
            (IPEndPoint)verification.LocalEndpoint, (IPEndPoint)formal.LocalEndpoint, 0xAD, 0xAD, 1,
            async (number, token) =>
            {
                if (number == 1)
                {
                    await credentials.Task.WaitAsync(token);
                    return leg => CandidateCommands.Login("synthetic", "fake",
                        leg == HandshakeLeg.Verification ? 0 : 2, 1, 2);
                }
                secondEntered.SetResult();
                await secondRelease.Task.WaitAsync(token);
                return null;
            }, () => 123, (_, now) => new(now), delay: async (_, token) =>
            {
                delayEntered.SetResult();
                await retry.Task.WaitAsync(token);
            });
        try
        {
            var acquisition = controller.WaitForChangeAsync(controller.Snapshot);
            var run = controller.RunAsync();
            var acquiring = await acquisition.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.AcquiringCredentials, acquiring.Phase);
            Assert.Equal(1, acquiring.Attempts);
            var connection = controller.WaitForChangeAsync(acquiring);
            credentials.SetResult();
            var connecting = await connection.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Connecting, connecting.Phase);
            var reception = controller.WaitForChangeAsync(connecting);
            verify.SetResult();
            var receiving = await reception.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Receiving, receiving.Phase);
            Assert.Empty(receiving.History);
            var drainingWait = controller.WaitForChangeAsync(receiving);
            disconnect.SetResult();
            var draining = await drainingWait.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Draining, draining.Phase);
            Assert.Empty(draining.History);
            await delayEntered.Task.WaitAsync(Guard);
            var waiting = await controller.WaitForChangeAsync(draining).WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Waiting, waiting.Phase);
            Assert.Single(waiting.History);
            Assert.NotNull(waiting.NextDelay);

            var replacementWait = controller.WaitForChangeAsync(waiting);
            retry.SetResult();
            var replacement = await replacementWait.WaitAsync(Guard);
            Assert.Equal(generation + 1, replacement.Generation);
            Assert.Equal(ReconnectPhase.AcquiringCredentials, replacement.Phase);
            Assert.Equal(1, replacement.Attempts);
            var nextAcquisition = await controller.WaitForChangeAsync(replacement).WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.AcquiringCredentials, nextAcquisition.Phase);
            Assert.Equal(2, nextAcquisition.Attempts);
            await secondEntered.Task.WaitAsync(Guard);
            var endingWait = controller.WaitForChangeAsync(nextAcquisition);
            secondRelease.SetResult();
            var ending = await endingWait.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Ending, ending.Phase);
            Assert.Equal(ReconnectEnd.CredentialsUnavailable, ending.End);
            var ended = await controller.WaitForChangeAsync(ending).WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Ended, ended.Phase);
            Assert.Same(ended, (await run.WaitAsync(Guard)).View);
            await Task.WhenAll(firstPeer, secondPeer).WaitAsync(Guard);
        }
        finally
        {
            controller.Stop();
            credentials.TrySetResult(); verify.TrySetResult(); disconnect.TrySetResult();
            retry.TrySetResult(); secondRelease.TrySetResult();
            guard.Cancel();
            try { await Task.WhenAll(firstPeer, secondPeer).WaitAsync(Guard); }
            catch (Exception error) when (error is OperationCanceledException or SocketException or IOException) { }
        }
    }

    [Theory]
    [InlineData("eof")]
    [InlineData("dispose")]
    [InlineData("read-failure")]
    public async Task ReceiveRetiringSignalsBeforeNoncooperativeReadOrCleanupFinishes(string ending)
    {
        var transport = new CleanupBarrierTransport();
        await using var attempt = new ReceiveAttempt(transport, 0xAD, () => 123, (_, now) => new(now));
        var retiring = attempt.Retiring;
        Assert.Same(retiring, attempt.Retiring);
        Assert.False(retiring.IsCompleted);
        var run = attempt.RunAsync();
        try
        {
            await transport.ReadEntered.Task.WaitAsync(Guard);
            Task? disposal = null;
            if (ending == "dispose")
            {
                disposal = attempt.DisposeAsync().AsTask();
                Assert.True(retiring.IsCompletedSuccessfully);
                Assert.False(transport.ReadResult.Task.IsCompleted);
            }
            else if (ending == "read-failure") transport.ReadResult.SetException(new IOException("Synthetic read failed."));
            else transport.ReadResult.SetResult(0);
            await retiring.WaitAsync(Guard);
            await transport.CleanupEntered.Task.WaitAsync(Guard);
            Assert.Equal(ReceiveStage.Ending, attempt.Latest.Stage);
            Assert.False(run.IsCompleted);
            Assert.False(transport.CleanupRelease.Task.IsCompleted);
            transport.ReadResult.TrySetResult(0);
            transport.CleanupRelease.SetResult();
            var result = await run.WaitAsync(Guard);
            Assert.Equal(ending switch
            {
                "dispose" => ReceiveEnd.Disposed,
                "read-failure" => ReceiveEnd.ReadFailed,
                _ => ReceiveEnd.Completed
            }, result.End);
            Assert.True(result.ResourcesReleased);
            Assert.Same(retiring, attempt.Retiring);
            if (disposal is not null) await disposal.WaitAsync(Guard);
        }
        finally { transport.ReadResult.TrySetResult(0); transport.CleanupRelease.TrySetResult(); }
    }

    [Fact]
    public async Task ReceiveDisposalBeforeRunSignalsWithoutReadOrInlineContinuation()
    {
        var transport = new CleanupBarrierTransport();
        await using var attempt = new ReceiveAttempt(transport, 0xAD, () => 123, (_, now) => new(now));
        using var insideDispose = new ThreadLocal<bool>(() => false);
        var continuation = attempt.Retiring.ContinueWith(_ => insideDispose.Value, CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
        try
        {
            insideDispose.Value = true;
            Task cleanup;
            try { cleanup = attempt.DisposeAsync().AsTask(); }
            finally { insideDispose.Value = false; }
            Assert.True(attempt.Retiring.IsCompletedSuccessfully);
            Assert.False(await continuation.WaitAsync(Guard));
            await transport.CleanupEntered.Task.WaitAsync(Guard);
            Assert.False(transport.ReadEntered.Task.IsCompleted);
            Assert.False(cleanup.IsCompleted);
            transport.CleanupRelease.SetResult();
            await cleanup.WaitAsync(Guard);
        }
        finally { transport.ReadResult.TrySetResult(0); transport.CleanupRelease.TrySetResult(); }
    }

    [Fact]
    public async Task ReceiveRetirementPublishesDrainingBeforeHeldProviderCleanupCompletes()
    {
        using var guard = new CancellationTokenSource(Guard);
        using var verification = new TcpListener(IPAddress.Loopback, 0);
        using var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        var firstPeer = VerifyAsync(verification, Task.CompletedTask, guard.Token);
        async Task FormalAsync()
        {
            using var socket = await formal.AcceptSocketAsync(guard.Token);
            var peer = new Peer(socket, guard.Token);
            await peer.ExpectAsync(63, 7);
            await peer.ExpectEofAsync();
        }
        var secondPeer = FormalAsync();
        using var providerRelease = new ManualResetEventSlim();
        var provider = new CleanupBarrierProvider(providerRelease);
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var controller = new HeldAccountReconnect(session, generation,
            (IPEndPoint)verification.LocalEndpoint, (IPEndPoint)formal.LocalEndpoint, 0xAD, 0xAD, 1,
            null, () => 123, (_, now) => new(now),
            ownedCredentials: (_, _) => ValueTask.FromResult<IHandshakeLoginProvider?>(provider));
        try
        {
            var run = controller.RunAsync();
            await provider.CleanupEntered.Task.WaitAsync(Guard);
            var connecting = controller.Snapshot;
            Assert.Equal(ReconnectPhase.Connecting, connecting.Phase);
            var drainingWait = controller.WaitForChangeAsync(connecting);
            Assert.True(session.Hold(generation));
            var draining = await drainingWait.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Draining, draining.Phase);
            Assert.Empty(draining.History);
            Assert.False(run.IsCompleted);
            Assert.Null(controller.Publication);
            var historyWait = controller.WaitForChangeAsync(draining);
            provider.CleanupRelease.Set();
            var history = await historyWait.WaitAsync(Guard);
            Assert.Equal(ReconnectPhase.Draining, history.Phase);
            Assert.Single(history.History);
            var result = await run.WaitAsync(Guard);
            Assert.Equal(ReconnectEnd.ConnectionEnded, result.View.End);
            Assert.True(result.ResourcesReleased);
            Assert.Equal(1, result.View.Attempts);
            Assert.Equal(1, provider.CleanupCalls);
            await Task.WhenAll(firstPeer, secondPeer).WaitAsync(Guard);
        }
        finally
        {
            provider.CleanupRelease.Set();
            controller.Stop();
            guard.Cancel();
            try { await Task.WhenAll(firstPeer, secondPeer).WaitAsync(Guard); }
            catch (Exception error) when (error is OperationCanceledException or SocketException or IOException) { }
        }
    }

    private sealed class CleanupBarrierTransport : IReceiveTransport
    {
        internal TaskCompletionSource ReadEntered { get; } = Signal();
        internal TaskCompletionSource<int> ReadResult { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource CleanupEntered { get; } = Signal();
        internal TaskCompletionSource CleanupRelease { get; } = Signal();
        public async ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken token)
        {
            ReadEntered.SetResult();
            return await ReadResult.Task; // Deliberately ignores retirement and cancellation.
        }
        public async ValueTask DisposeAsync()
        {
            CleanupEntered.SetResult();
            await CleanupRelease.Task;
        }
    }

    private sealed class CleanupBarrierProvider(ManualResetEventSlim release) : IHandshakeLoginProvider
    {
        internal TaskCompletionSource CleanupEntered { get; } = Signal();
        internal ManualResetEventSlim CleanupRelease => release;
        internal int CleanupCalls;
        public LoginPacketLease Create(HandshakeLeg leg) => new(CandidateCommands.Login("synthetic", "fake",
            leg == HandshakeLeg.Verification ? 0 : 2, 1, 2));
        public void Dispose()
        {
            Interlocked.Increment(ref CleanupCalls);
            CleanupEntered.SetResult();
            Assert.True(CleanupRelease.Wait(Guard));
        }
    }

    private static async Task VerifyAsync(TcpListener listener, Task release, CancellationToken token)
    {
        using var socket = await listener.AcceptSocketAsync(token);
        var peer = new Peer(socket, token);
        await peer.ExpectAsync(63, 7);
        await release.WaitAsync(token);
        await peer.SendAsync(new Packet(63, 7, [0, 0]));
        await peer.CloseAsync();
    }

    private static async Task EnterWorldAsync(TcpListener listener, Task disconnect, CancellationToken token)
    {
        using var socket = await listener.AcceptSocketAsync(token);
        var peer = new Peer(socket, token);
        await peer.ExpectAsync(63, 7);
        var roles = new Packet(63, 1, new PacketWriter().U8(1).U8(0).U8(1).U8(1)
            .U32(1).U32(1).U32(1).U32(1).Raw(new byte[8]).U32(0).U8(0).U8(0).U32(0).U32(0)
            .U8(0).U8(0).U16(1).Raw(new byte[8]).U8(0).Raw(new byte[34]).Build());
        await peer.SendAsync(new Packet(63, 7, [0, 2]), roles);
        await peer.ExpectAsync(63, 2);
        var world = new Packet(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
            .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
        await peer.SendAsync(world, new Packet(1, 11));
        await peer.ExpectAsync(12, 1); await peer.ExpectAsync(3, 2);
        await disconnect.WaitAsync(token);
        await peer.CloseAsync();
    }

    private sealed class Peer(Socket socket, CancellationToken token)
    {
        private readonly FrameDecoder decoder = new();
        private readonly Queue<Packet> pending = new();
        internal async Task ExpectAsync(int main, int sub)
        {
            while (pending.Count == 0)
            {
                var bytes = new byte[4096];
                int count = await socket.ReceiveAsync(bytes, SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic peer closed.");
                foreach (var packet in decoder.Feed(bytes.AsSpan(0, count))) pending.Enqueue(packet);
            }
            var packetReceived = pending.Dequeue();
            Assert.Equal(main, packetReceived.Main); Assert.Equal(sub, packetReceived.Sub);
        }
        internal async Task SendAsync(params Packet[] packets)
        {
            var bytes = packets.SelectMany(packet => WireCodec.Encode(packet)).ToArray();
            int offset = 0;
            while (offset < bytes.Length)
            {
                int count = await socket.SendAsync(bytes.AsMemory(offset), SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic send closed.");
                offset += count;
            }
        }
        internal async Task CloseAsync()
        {
            socket.Shutdown(SocketShutdown.Send);
            await ExpectEofAsync();
        }
        internal async Task ExpectEofAsync()
        {
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
}
