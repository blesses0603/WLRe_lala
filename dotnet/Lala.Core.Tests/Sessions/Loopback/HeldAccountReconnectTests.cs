using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed class HeldAccountReconnectTests
{
    private static readonly TimeSpan Guard = TimeSpan.FromSeconds(30);
    private static Packet Roles => new(63, 1, new PacketWriter().U8(1).U8(0).U8(1).U8(1)
        .U32(1).U32(1).U32(1).U32(1).Raw(new byte[8]).U32(0).U8(0).U8(0).U32(0).U32(0)
        .U8(0).U8(0).U16(1).Raw(new byte[8]).U8(0).Raw(new byte[34]).Build());
    private static Packet World => new(3, 1, new PacketWriter().U32(17).U8(0).U16(101).U16(20).U16(30)
        .Raw(new byte[13]).U8(0).U8(0).Raw(new byte[8]).U8(0).U16(0).Build());
    private sealed class Peer : IAsyncDisposable
    {
        private readonly TcpListener listener = new(IPAddress.Loopback, 0);
        private readonly CancellationTokenSource stop = new(Guard);
        private Task? running;
        private Socket? accepted;
        internal Peer() => listener.Start();
        internal IPEndPoint Endpoint => (IPEndPoint)listener.LocalEndpoint;
        internal bool WasAccepted { get; private set; }
        internal bool HasPending => listener.Pending();
        internal Task Run(Func<Client, Task> script) => RunMany(1, (_, client) => script(client));
        internal Task RunMany(int count, Func<int, Client, Task> script) => running = Work(count, script);
        private async Task Work(int count, Func<int, Client, Task> script)
        {
            for (int i = 1; i <= count; i++)
            {
                accepted = await listener.AcceptSocketAsync(stop.Token);
                WasAccepted = true;
                using (accepted) await script(i, new(accepted, stop.Token));
            }
        }
        public async ValueTask DisposeAsync()
        {
            stop.Cancel(); accepted?.Dispose(); listener.Stop();
            if (running is not null)
                try { await running.WaitAsync(Guard); }
                catch (Exception error) when (error is SocketException or IOException or OperationCanceledException or ObjectDisposedException) { }
            stop.Dispose();
        }
    }
    private sealed class Client(Socket socket, CancellationToken token)
    {
        private readonly FrameDecoder decoder = new();
        private readonly Queue<Packet> pending = new();
        internal async Task<Packet> Next()
        {
            while (pending.Count == 0)
            {
                var bytes = new byte[4096]; int count = await socket.ReceiveAsync(bytes, SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic peer closed.");
                foreach (var packet in decoder.Feed(bytes.AsSpan(0, count))) pending.Enqueue(packet);
            }
            return pending.Dequeue();
        }
        internal async Task Expect(int main, int sub, byte? first = null)
        {
            var packet = await Next(); Assert.Equal(main, packet.Main); Assert.Equal(sub, packet.Sub);
            if (first is not null) Assert.Equal(first.Value, packet.Payload.Span[0]);
        }
        internal Task WaitFor(Task signal) => signal.WaitAsync(token);
        internal Task Send(params Packet[] packets) => Raw(packets.SelectMany(p => WireCodec.Encode(p)).ToArray());
        internal async Task Raw(byte[] bytes, int chunk = 4096)
        {
            int offset = 0;
            while (offset < bytes.Length)
            {
                int count = await socket.SendAsync(bytes.AsMemory(offset, Math.Min(chunk, bytes.Length - offset)), SocketFlags.None, token);
                if (count == 0) throw new IOException("Synthetic send closed.");
                offset += count;
            }
        }
        internal async Task ExpectEof()
        {
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
        internal async Task CloseSendAndExpectEof()
        {
            socket.Shutdown(SocketShutdown.Send);
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static IPEndPoint ClosedEndpoint()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var endpoint = (IPEndPoint)listener.LocalEndpoint; listener.Stop(); return endpoint;
    }
    private static Func<HandshakeLeg, Packet> Provider() => leg =>
        CandidateCommands.Login("synthetic", "fake", leg == HandshakeLeg.Verification ? 0 : 2, 1, 2);
    private static HeldAccountReconnect Controller(AccountSession session, long generation, IPEndPoint endpoint,
        Func<int, CancellationToken, ValueTask<Func<HandshakeLeg, Packet>?>>? credentials = null,
        Func<TimeSpan, CancellationToken, Task>? delay = null, ReconnectLimits? limits = null) =>
        new(session, generation, endpoint, endpoint, 0xAD, 0xAD, 1,
            credentials ?? ((_, _) => ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider())),
            () => 123, (_, now) => new(now), limits: limits ?? new()
            { InitialDelay = TimeSpan.FromMilliseconds(100), MaximumDelay = TimeSpan.FromMilliseconds(150) }, delay: delay);
    private static async Task Verify(Client client)
    {
        await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [0, 0]));
        await client.CloseSendAndExpectEof();
    }
    private static async Task EnterWorld(Client client)
    {
        await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles);
        await client.Expect(63, 2, 1); await client.Send(World, new Packet(1, 11));
        await client.Expect(12, 1); await client.Expect(3, 2);
    }

    // Prebuffer startup before the credential callback returns, so a slow peer task
    // cannot spend the short timeout intended for the later silent formal read.
    private sealed class BufferedTimeoutLogin(int attempts)
    {
        private readonly TaskCompletionSource[] verificationReady = Enumerable.Range(0, attempts).Select(_ => Signal()).ToArray();
        private readonly TaskCompletionSource[] formalReady = Enumerable.Range(0, attempts).Select(_ => Signal()).ToArray();
        internal static byte[] IncompleteHeader => WireCodec.Encode(new Packet(1, 11))[..3];
        internal Packet Credential(int number, HandshakeLeg leg)
        {
            var ready = leg == HandshakeLeg.Verification ? verificationReady : formalReady;
            ready[number - 1].Task.WaitAsync(Guard).GetAwaiter().GetResult();
            return Provider()(leg);
        }
        internal async Task Verify(int number, Client client)
        {
            await client.Send(new Packet(63, 7, [0, 0]));
            verificationReady[number - 1].SetResult();
            await client.Expect(63, 7, 0); await client.CloseSendAndExpectEof();
        }
        internal async Task Formal(int number, Client client, bool completeLogin = true)
        {
            if (completeLogin)
            {
                await client.Send(new Packet(63, 7, [0, 2]), Roles, World, new Packet(1, 11));
                // With readSize=1 and bufferedChunks=1, only two bytes can be read
                // ahead while the writer handles the final login event. These three
                // bytes keep the next socket read nonempty until that handler returns.
                // They cannot form an event, trigger a write, or add a state commit.
                await client.Raw(IncompleteHeader);
            }
            formalReady[number - 1].SetResult();
            await client.Expect(63, 7, 2);
            if (completeLogin)
            {
                await client.Expect(63, 2, 1);
                await client.Expect(12, 1); await client.Expect(3, 2);
            }
            await client.ExpectEof();
        }
    }
    private static async Task AwaitSignal(Task signal, Task<ReconnectResult> run, params Task[] peers)
    {
        var pending = peers.ToList();
        while (!signal.IsCompleted)
        {
            var completed = await Task.WhenAny(pending.Append(signal).Append(run)).WaitAsync(Guard);
            if (completed == run)
            {
                var result = await run;
                Assert.Fail($"Reconnect ended before the expected signal: {result.View.End}; " +
                    string.Join(", ", result.View.History.Select(h => $"{h.End}/{h.Outcome}")));
            }
            if (pending.Remove(completed)) await completed;
        }
        await signal;
        foreach (var peer in peers.Where(p => p.IsFaulted || p.IsCanceled)) await peer;
    }

    [Fact]
    public void TimeoutFixtureSuffixCannotCommitAnEventAndEofStillRejectsIt()
    {
        var decoder = new FrameDecoder();
        Assert.Equal(new byte[] { 0x69, 0x6B, 0xAF }, BufferedTimeoutLogin.IncompleteHeader);
        Assert.Empty(decoder.Feed(BufferedTimeoutLogin.IncompleteHeader));
        Assert.Equal(3, decoder.BufferedBytes);
        Assert.Throws<ProtocolException>(decoder.Finish);
    }

    [Fact]
    public async Task RefusedConnectsUseFreshRequestsBoundedBackoffAndNewGenerations()
    {
        var session = new AccountSession(); var initial = session.Begin("a", "b");
        var requested = new List<int>(); var delays = new List<TimeSpan>(); int packets = 0;
        await using var controller = Controller(session, initial.Generation, ClosedEndpoint(), credentials: (number, _) =>
        {
            requested.Add(number);
            return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(_ => { packets++; throw new Exception(); });
        }, delay: (duration, _) => { delays.Add(duration); return Task.CompletedTask; });
        var run = controller.RunAsync(); Assert.Same(run, controller.RunAsync());
        var result = await run.WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Equal(ReconnectEnd.AttemptsExhausted, result.View.End);
        Assert.Equal(new[] { 1, 2, 3 }, requested); Assert.Equal(0, packets);
        Assert.Equal(new[] { TimeSpan.FromMilliseconds(100), TimeSpan.FromMilliseconds(150) }, delays);
        Assert.Equal(new[] { initial.Generation, initial.Generation + 1, initial.Generation + 2 }, result.View.History.Select(h => h.Generation));
        Assert.Equal(3, result.View.History.Select(h => h.Attempt).Distinct().Count());
        Assert.All(result.View.History, h => Assert.True(h.Outcome.CanReconnect));
        Assert.True(result.View.ResourceHeld); Assert.False(result.View.CanSendCommands);
        Assert.False(session.AllowsResourceGate(session.Snapshot.Generation, "walk"));
    }

    [Fact]
    public async Task CompletedLoginDisconnectReconnectsWithFreshStateAndProviders()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.RunMany(2, (_, client) => Verify(client));
        var second = formal.RunMany(2, async (_, client) => { await EnterWorld(client); await client.CloseSendAndExpectEof(); });
        var session = new AccountSession(); var initial = session.Begin("synthetic", "loopback");
        var providers = new List<(int Number, HandshakeLeg Leg)>();
        await using var controller = new HeldAccountReconnect(session, initial.Generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            (number, _) => ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(leg =>
            {
                providers.Add((number, leg)); return Provider()(leg);
            }), () => 123, (_, now) => new(now), limits: new() { MaximumAttempts = 2 },
            delay: (_, _) => Task.CompletedTask);
        var result = await controller.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.AttemptsExhausted, result.View.End);
        Assert.Equal(2, result.View.History.Length);
        Assert.All(result.View.History, h =>
        {
            Assert.True(h.Outcome.LoginCompleted); Assert.True(h.Outcome.CanReconnect);
            Assert.Equal(HeldConnectionFailure.RemoteEof, h.Outcome.Failure);
        });
        Assert.Equal(new[] { (1, HandshakeLeg.Verification), (1, HandshakeLeg.Formal),
            (2, HandshakeLeg.Verification), (2, HandshakeLeg.Formal) }, providers);
        Assert.Equal(initial.Generation + 1, session.Snapshot.Generation);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task CompletedLoginTimeoutRetriesOnlyAfterCleanupWithFreshCredentialsAndGeneration(bool slowLogin)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var firstClosed = Signal(); var delayEntered = Signal(); var release = Signal();
        var loginEntered = Signal(); using var resumeLogin = new ManualResetEventSlim();
        var script = new BufferedTimeoutLogin(2);
        var first = verification.RunMany(2, script.Verify);
        var second = formal.RunMany(2, async (number, client) =>
        {
            await script.Formal(number, client);
            if (number == 1) firstClosed.SetResult();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        var providers = new List<(int Number, HandshakeLeg Leg)>(); int requests = 0, observations = 0;
        await using var controller = new HeldAccountReconnect(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            (number, _) =>
            {
                requests++;
                return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(leg =>
                { providers.Add((number, leg)); return script.Credential(number, leg); });
            }, () => 123, (_, now) =>
            {
                if (Interlocked.Increment(ref observations) == 4 && slowLogin)
                {
                    loginEntered.SetResult();
                    Assert.True(resumeLogin.Wait(Guard));
                }
                return new(now);
            },
            loginLimits: new() { Tcp = new() { ReadTimeout = TimeSpan.FromSeconds(1) } },
            limits: new() { MaximumAttempts = 2 }, readSize: 1, bufferedChunks: 1,
            delay: (_, _) => { delayEntered.SetResult(); return release.Task; });
        var run = controller.RunAsync();
        try
        {
            if (slowLogin)
            {
                await AwaitSignal(loginEntered.Task, run, first, second);
                // Exercise scheduling delay longer than the TCP deadline, while
                // backpressure keeps the silent read behind completed login.
                await AwaitSignal(Task.Delay(TimeSpan.FromSeconds(2)), run, first, second);
                Assert.False(delayEntered.Task.IsCompleted);
                Assert.Equal(ReconnectPhase.Connecting, controller.Snapshot.Phase);
                Assert.Equal(ReceiveStage.Running, controller.Publication?.Stage);
                resumeLogin.Set();
            }
            await AwaitSignal(delayEntered.Task, run, first, second);
            await AwaitSignal(firstClosed.Task, run, first, second);
            Assert.Equal(1, requests); Assert.False(verification.HasPending); Assert.False(formal.HasPending);
            Assert.Null(controller.Publication);
            Assert.Equal(ReconnectPhase.Waiting, controller.Snapshot.Phase);
            Assert.Equal(generation, session.Snapshot.Generation);
            release.SetResult();
            var result = await run.WaitAsync(Guard);
            await Task.WhenAll(first, second).WaitAsync(Guard);
            Assert.True(result.ResourcesReleased); Assert.Equal(ReconnectEnd.AttemptsExhausted, result.View.End);
            Assert.Equal(2, requests); Assert.Equal(2, result.View.History.Length);
            Assert.Equal(8, observations); // Four startup events per attempt, no suffix event.
            Assert.All(result.View.History, h =>
            {
                Assert.Equal(ReceiveEnd.ReadFailed, h.End);
                Assert.Equal(HeldConnectionFailure.ReadTimedOut, h.Outcome.Failure);
                Assert.True(h.Outcome.LoginCompleted); Assert.True(h.Outcome.CanReconnect);
            });
            Assert.Equal(new[] { generation, generation + 1 }, result.View.History.Select(h => h.Generation));
            Assert.Equal(2, result.View.History.Select(h => h.Attempt).Distinct().Count());
            Assert.Equal(new[] { (1, HandshakeLeg.Verification), (1, HandshakeLeg.Formal),
                (2, HandshakeLeg.Verification), (2, HandshakeLeg.Formal) }, providers);
            Assert.True(result.View.ResourceHeld); Assert.False(result.View.CanSendCommands);
            Assert.False(session.AllowsResourceGate(session.Snapshot.Generation, "walk"));
        }
        finally { resumeLogin.Set(); release.TrySetResult(); controller.Stop(); }
    }

    [Fact]
    public async Task FormalReadTimeoutBeforeLoginNeverRetries()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var script = new BufferedTimeoutLogin(1);
        var first = verification.Run(client => script.Verify(1, client));
        var second = formal.Run(client => script.Formal(1, client, completeLogin: false));
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        int requests = 0;
        await using var controller = new HeldAccountReconnect(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            (number, _) => { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(leg => script.Credential(number, leg)); },
            () => 123, (_, now) => new(now),
            loginLimits: new() { Tcp = new() { ReadTimeout = TimeSpan.FromSeconds(1) } });
        var result = await controller.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.True(result.ResourcesReleased); Assert.Equal(ReconnectEnd.ConnectionEnded, result.View.End);
        Assert.Equal(1, requests); Assert.Equal(generation, session.Snapshot.Generation);
        var history = Assert.Single(result.View.History);
        Assert.Equal(ReceiveEnd.ReadFailed, history.End);
        Assert.Equal(HeldConnectionFailure.ReadTimedOut, history.Outcome.Failure);
        Assert.False(history.Outcome.LoginCompleted); Assert.False(history.Outcome.CanReconnect);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task StopOrHoldDuringReadTimeoutRetryDelayCannotReconnect(bool hold)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var script = new BufferedTimeoutLogin(1);
        var first = verification.Run(client => script.Verify(1, client));
        var second = formal.Run(client => script.Formal(1, client));
        var entered = Signal(); var release = Signal(); int requests = 0;
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var controller = new HeldAccountReconnect(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            (number, _) => { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(leg => script.Credential(number, leg)); },
            () => 123, (_, now) => new(now),
            loginLimits: new() { Tcp = new() { ReadTimeout = TimeSpan.FromSeconds(1) } },
            readSize: 1, bufferedChunks: 1,
            delay: (_, _) => { entered.SetResult(); return release.Task; });
        var run = controller.RunAsync();
        try
        {
            await AwaitSignal(entered.Task, run, first, second);
            await Task.WhenAll(first, second).WaitAsync(Guard);
            Assert.Equal(HeldConnectionFailure.ReadTimedOut, Assert.Single(controller.Snapshot.History).Outcome.Failure);
            if (hold) Assert.True(session.Hold(generation)); else controller.Stop();
            var expected = session.Snapshot;
            release.SetResult(); var result = await run.WaitAsync(Guard);
            Assert.Equal(hold ? ReconnectEnd.Superseded : ReconnectEnd.Stopped, result.View.End);
            Assert.True(result.ResourcesReleased); Assert.Equal(1, requests);
            Assert.Equal(expected, session.Snapshot); Assert.Null(controller.Publication);
            Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        }
        finally { release.TrySetResult(); controller.Stop(); }
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task ManualStopOrDisposeWaitsNoncooperativeDelayWithoutRetry(bool dispose)
    {
        var session = new AccountSession(); var initial = session.Begin("a", "b");
        var entered = Signal(); var release = Signal(); int requests = 0;
        var controller = Controller(session, initial.Generation, ClosedEndpoint(),
            credentials: (_, _) => { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider()); },
            delay: (_, _) => { entered.SetResult(); return release.Task; });
        var run = controller.RunAsync(); await entered.Task.WaitAsync(Guard);
        Task cleanup;
        if (dispose) cleanup = controller.DisposeAsync().AsTask();
        else { controller.Stop(); cleanup = controller.DisposeAsync().AsTask(); }
        Assert.Equal(ReconnectPhase.Ending, controller.Snapshot.Phase);
        Assert.False(cleanup.IsCompleted); Assert.Null(controller.Publication);
        release.SetResult(); await cleanup.WaitAsync(Guard);
        var result = await run;
        Assert.Equal(dispose ? ReconnectEnd.Disposed : ReconnectEnd.Stopped, result.View.End);
        Assert.Equal(1, requests); Assert.Equal(initial.Generation, session.Snapshot.Generation);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task AccountReplacementOrExplicitHoldCannotBeUndoneByRetry(bool hold)
    {
        var session = new AccountSession(); var initial = session.Begin("a", "b");
        var entered = Signal(); var release = Signal(); int requests = 0;
        await using var controller = Controller(session, initial.Generation, ClosedEndpoint(),
            credentials: (_, _) => { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider()); },
            delay: (_, _) => { entered.SetResult(); return release.Task; });
        var run = controller.RunAsync(); await entered.Task.WaitAsync(Guard);
        if (hold) session.Hold(initial.Generation); else session.Begin("manual", "other");
        var expected = session.Snapshot;
        release.SetResult(); var result = await run.WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.Superseded, result.View.End);
        Assert.Equal(expected, session.Snapshot); Assert.Equal(1, requests);
    }

    [Fact]
    public async Task MissingCredentialsAndProviderFaultDoNotRetryOrLeakDetails()
    {
        foreach (bool fail in new[] { false, true })
        {
            var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
            int requests = 0;
            await using var controller = Controller(session, generation, ClosedEndpoint(), credentials: (_, _) =>
            {
                requests++; if (fail) throw new Exception("synthetic-sensitive-message");
                return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(null);
            });
            var result = await controller.RunAsync().WaitAsync(Guard);
            Assert.Equal(fail ? ReconnectEnd.ProviderFailed : ReconnectEnd.CredentialsUnavailable, result.View.End);
            Assert.Equal(1, requests); Assert.Empty(result.View.History);
            Assert.DoesNotContain("synthetic-sensitive", result.ToString());
        }
    }

    [Fact]
    public async Task StopDuringCredentialAcquisitionWaitsAndNeverUsesLateProvider()
    {
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        var entered = Signal(); var release = Signal(); int calls = 0;
        var controller = Controller(session, generation, ClosedEndpoint(), credentials: async (_, _) =>
        {
            entered.SetResult(); await release.Task;
            return _ => { calls++; throw new Exception(); };
        });
        var run = controller.RunAsync(); await entered.Task.WaitAsync(Guard);
        controller.Stop(); var cleanup = controller.DisposeAsync().AsTask();
        Assert.False(cleanup.IsCompleted);
        release.SetResult(); await cleanup.WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.Stopped, (await run).View.End); Assert.Equal(0, calls);
    }

    [Fact]
    public async Task RecoveryDeadlineCancelsCredentialWaitWithoutNetworkAttempt()
    {
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var controller = Controller(session, generation, ClosedEndpoint(), credentials: async (_, token) =>
        {
            await Task.Delay(Timeout.Infinite, token); return Provider();
        }, limits: new() { MaximumRecoveryTime = TimeSpan.FromMilliseconds(100) });
        var result = await controller.RunAsync().WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.Deadline, result.View.End); Assert.Empty(result.View.History);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task CancellationOrDisposalBeforeRunIsInert(bool dispose)
    {
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation; int requests = 0;
        await using var controller = Controller(session, generation, ClosedEndpoint(), credentials: (_, _) =>
        { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider()); });
        using var stop = new CancellationTokenSource(); stop.Cancel();
        if (dispose) await controller.DisposeAsync();
        var result = await controller.RunAsync(stop.Token).WaitAsync(Guard);
        Assert.Equal(dispose ? ReconnectEnd.Disposed : ReconnectEnd.Cancelled, result.View.End);
        Assert.Equal(0, requests); Assert.Empty(result.View.History);
    }

    [Fact]
    public async Task RejectedVerificationNeverRequestsAnotherProvider()
    {
        await using var verification = new Peer(); int requests = 0;
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [1, 0]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var controller = Controller(session, generation, verification.Endpoint, credentials: (_, _) =>
        { requests++; return ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider()); });
        var result = await controller.RunAsync().WaitAsync(Guard); await server.WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.ConnectionEnded, result.View.End); Assert.Equal(1, requests);
        Assert.False(Assert.Single(result.View.History).Outcome.CanReconnect);
    }
    [Fact]
    public async Task HealthyConnectionIsNotStoppedByRecoveryDeadline()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var ready = Signal(); var finish = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client); ready.SetResult();
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var controller = new HeldAccountReconnect(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            (_, _) => ValueTask.FromResult<Func<HandshakeLeg, Packet>?>(Provider()),
            () => 123, (_, now) => new(now), limits: new() { MaximumRecoveryTime = TimeSpan.FromSeconds(3) });
        var run = controller.RunAsync(); await ready.Task.WaitAsync(Guard);
        await Task.Delay(TimeSpan.FromSeconds(4));
        Assert.False(run.IsCompleted); Assert.Equal(ReconnectPhase.Receiving, controller.Snapshot.Phase);
        controller.Stop(); var result = await run.WaitAsync(Guard);
        Assert.Equal(ReconnectEnd.Stopped, result.View.End);
        finish.SetResult(); await Task.WhenAll(first, second).WaitAsync(Guard);
    }
    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task StopOrReplacementDuringSecondAcquisitionNeverOpensAnotherSocket(bool replace)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client => { await EnterWorld(client); await client.CloseSendAndExpectEof(); });
        var entered = Signal(); var release = Signal(); int lateCalls = 0;
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var controller = new HeldAccountReconnect(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            async (number, _) =>
            {
                if (number == 1) return Provider();
                entered.SetResult(); await release.Task;
                return _ => { lateCalls++; throw new Exception(); };
            }, () => 123, (_, now) => new(now), delay: (_, _) => Task.CompletedTask);
        var run = controller.RunAsync(); await entered.Task.WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        if (replace) session.Begin("manual", "other"); else controller.Stop();
        var expected = session.Snapshot;
        release.SetResult(); var result = await run.WaitAsync(Guard);
        Assert.Equal(replace ? ReconnectEnd.Superseded : ReconnectEnd.Stopped, result.View.End);
        Assert.Single(result.View.History); Assert.Equal(2, result.View.Attempts);
        Assert.Equal(0, lateCalls); Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        Assert.Equal(expected, session.Snapshot);
    }
}
