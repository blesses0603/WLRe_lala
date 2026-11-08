using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed class HeldAccountConnectionTests
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
        internal Task Run(Func<Client, Task> script) => running = Work(script);
        private async Task Work(Func<Client, Task> script)
        {
            accepted = await listener.AcceptSocketAsync(stop.Token);
            WasAccepted = true;
            using (accepted) await script(new(accepted, stop.Token));
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
        internal Task ExpectClosedAfterRetirement() => RetiredPeerClosure.AssertAsync(pending, decoder,
            () => socket.ReceiveAsync(new Memory<byte>(new byte[1]), SocketFlags.None, token));

        internal async Task CloseSendAndExpectEof()
        {
            socket.Shutdown(SocketShutdown.Send);
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static HeldAccountConnection Attach(AccountSession session, long generation, Peer verification, Peer formal,
        int readSize = 4096, Func<HandshakeLeg, Packet>? credentials = null, HeldLoginLimits? limits = null) =>
        Assert.IsType<HeldAccountConnection>(HeldAccountConnection.TryAttach(session, generation,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            credentials ?? (leg => CandidateCommands.Login("synthetic_user", "fake_password", leg == HandshakeLeg.Verification ? 0 : 2, 1, 2)),
            () => 123, (_, now) => new(now), limits, readSize));
    private static async Task Verify(Client client)
    {
        await client.Expect(63, 7, 0);
        await client.Send(new Packet(1, 23));
        await client.Expect(63, 5);
        await client.Send(new Packet(63, 7, [0, 0]));
        // Production composition closes verification on its matching result, not peer EOF.
        await client.CloseSendAndExpectEof();
    }
    private static async Task EnterWorld(Client client)
    {
        await client.Expect(63, 7, 2);
        await client.Send(new Packet(63, 7, [0, 2]), Roles);
        await client.Expect(63, 2, 1);
        await client.Send(World, new Packet(1, 11));
        await client.Expect(12, 1); await client.Expect(3, 2);
    }
    private static async Task WaitRevision(HeldAccountConnection owner, long revision)
    {
        using var stop = new CancellationTokenSource(Guard);
        while (owner.Publication?.Revision < revision) await Task.Delay(1, stop.Token);
        Assert.NotNull(owner.Publication);
    }

    [Theory]
    [InlineData(1)] [InlineData(4096)]
    public async Task SameDecoderPreservesCoalescedLoginTailAndContinuousState(int chunk)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var finish = Signal(); var tailReceived = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2);
            await client.Raw(new[] { new Packet(63, 7, [0, 2]), Roles }.SelectMany(p => WireCodec.Encode(p)).ToArray(), chunk);
            await client.Expect(63, 2, 1);
            await client.Raw(new[] { World, new Packet(1, 11), new Packet(26, 4, [42, 0, 0, 0]), new Packet(1, 23) }
                .SelectMany(p => WireCodec.Encode(p)).ToArray(), chunk);
            await client.Expect(12, 1); await client.Expect(3, 2); await client.Expect(63, 5);
            tailReceived.SetResult();
            await client.WaitFor(finish.Task);
            await client.Send(new Packet(26, 4, [43, 0, 0, 0]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        await using var owner = Attach(session, generation, verification, formal, chunk);
        var run = owner.RunAsync();
        Assert.Same(run, owner.RunAsync());
        Assert.Equal(HandshakePhase.ScriptedComplete, (await owner.Login.WaitAsync(Guard)).Phase);
        await tailReceived.Task.WaitAsync(Guard); await WaitRevision(owner, 6);
        Assert.False(run.IsCompleted);
        Assert.Equal(6, owner.Publication!.Revision);
        Assert.False(owner.Publication.Snapshot.IsCompleteState);
        Assert.True(owner.ResourceHeld); Assert.False(owner.CanSendCommands);
        Assert.False(session.ConfirmResources(generation, "v", "v", true));
        Assert.False(session.AllowsResourceGate(generation, "walk"));
        finish.SetResult();
        var result = await run.WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        Assert.Equal(7, result.Publication.Revision);
        Assert.True(result.ResourcesReleased);
        Assert.Equal(2, owner.Connections.Count);
        Assert.All(owner.Connections, c => Assert.Equal(TcpTransportStage.Disposed, c.Stage));
    }

    [Theory]
    [InlineData(1, 0)] [InlineData(0, 2)]
    public async Task RejectedOrWrongKindVerificationNeverDialsFormal(int resultCode, int loginKind)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            await client.Send(new Packet(63, 7, [(byte)resultCode, (byte)loginKind]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        int providers = 0;
        await using var owner = Attach(session, generation, verification, formal, credentials: leg =>
        {
            Interlocked.Increment(ref providers);
            return CandidateCommands.Login("synthetic", "fake", leg == HandshakeLeg.Verification ? 0 : 2, 1, 2);
        });
        var result = await owner.RunAsync().WaitAsync(Guard);
        await first.WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.ReadFailed, result.End);
        Assert.Equal(HandshakePhase.Failed, (await owner.Login).Phase);
        Assert.Equal(1, providers); Assert.Single(owner.Connections);
    }

    [Fact]
    public async Task DisconnectDuringVerificationCancelsWithoutFormalLogin()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var request = Signal(); var stopPeer = Signal();
        var first = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0); request.SetResult();
            await client.WaitFor(stopPeer.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal);
        var running = owner.RunAsync(); await request.Task.WaitAsync(Guard);
        session.Disconnect();
        Assert.Null(owner.Publication);
        var result = await running.WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.Disposed, result.End); Assert.True(result.ResourcesReleased);
        Assert.NotEqual(HandshakePhase.ScriptedComplete, (await owner.Login).Phase);
        Assert.Single(owner.Connections);
        stopPeer.SetResult(); await first.WaitAsync(Guard);
    }

    [Fact]
    public async Task NewGenerationReconnectsWithFreshProviderOnlyAfterOldCompletion()
    {
        var session = new AccountSession(); Guid? previous = null;
        for (int cycle = 0; cycle < 2; cycle++)
        {
            await using var verification = new Peer(); await using var formal = new Peer();
            var finish = Signal(); var ready = Signal();
            var first = verification.Run(Verify);
            var second = formal.Run(async client =>
            {
                await EnterWorld(client); ready.SetResult();
                await client.WaitFor(finish.Task); await client.ExpectClosedAfterRetirement();
            });
            var generation = session.Begin("synthetic", "loopback").Generation;
            int providers = 0;
            await using var owner = Attach(session, generation, verification, formal, credentials: leg =>
            {
                Interlocked.Increment(ref providers);
                return CandidateCommands.Login("synthetic", "fake", leg == HandshakeLeg.Verification ? 0 : 2, 1, 2);
            });
            Assert.NotEqual(previous, owner.Attempt); previous = owner.Attempt;
            var run = owner.RunAsync();
            await ready.Task.WaitAsync(Guard); await owner.Login.WaitAsync(Guard);
            session.Disconnect();
            await run.WaitAsync(Guard); await owner.DisposeAsync();
            Assert.Null(owner.Publication); Assert.Equal(2, providers);
            finish.SetResult(); await Task.WhenAll(first, second).WaitAsync(Guard);
        }
    }

    [Fact]
    public async Task DisposeBeforeRunNeverCallsProviderOrOpensSocket()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        int calls = 0;
        var owner = Attach(session, generation, verification, formal, credentials: _ => { calls++; throw new Exception(); });
        await owner.DisposeAsync(); var result = await owner.RunAsync();
        Assert.Equal(0, calls); Assert.Empty(owner.Connections);
        Assert.Equal(ReceiveEnd.Disposed, result.End);
        Assert.NotEqual(HandshakePhase.ScriptedComplete, (await owner.Login).Phase);
    }

    [Fact]
    public async Task ProviderExceptionIsSanitizedAndPreventsFurtherAttempts()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal,
            credentials: _ => throw new Exception("synthetic-secret-must-not-escape"));
        var result = await owner.RunAsync().WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.ReadFailed, result.End);
        Assert.DoesNotContain("synthetic-secret", result.ToString());
        Assert.Single(owner.Connections);
        Assert.NotEqual(HandshakePhase.ScriptedComplete, (await owner.Login).Phase);
    }
    [Fact]
    public async Task EofBeforeWorldAcksFailsLoginAfterDrainingCompleteFrames()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2);
            await client.Send(new Packet(63, 7, [0, 2]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal);
        var result = await owner.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.Completed, result.End); // source EOF, not successful login
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(HandshakePhase.Failed, (await owner.Login).Phase);
        Assert.False(owner.CanSendCommands);
    }

    [Fact]
    public async Task LoginDeadlineEndsSilentFormalLegWithoutAutomaticRetry()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var stopPeer = Signal(); var request = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); request.SetResult();
            await client.WaitFor(stopPeer.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal,
            limits: new() { LoginTimeout = TimeSpan.FromSeconds(3) });
        var run = owner.RunAsync(); await request.Task.WaitAsync(Guard);
        var result = await run.WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.ReadFailed, result.End);
        Assert.Equal(HandshakePhase.Failed, (await owner.Login).Phase);
        Assert.Equal(2, owner.Connections.Count);
        stopPeer.SetResult(); await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public async Task SecondLoginEpochAfterCompletionFailsWithoutPublishingIt()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client);
            await client.Send(new Packet(63, 7, [0, 2]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal);
        var result = await owner.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.EventHandlerFailed, result.End);
        Assert.Equal(4, result.Publication.Revision);
        Assert.False(owner.CanSendCommands);
    }
    [Fact]
    public async Task CompletedLoginDisablesDeadlineForAlreadyPendingRead()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client);
            await Task.Delay(TimeSpan.FromSeconds(4));
            await client.Send(new Packet(1, 23));
            await client.Expect(63, 5);
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal,
            limits: new() { LoginTimeout = TimeSpan.FromSeconds(3) });
        var run = owner.RunAsync();
        Assert.Equal(HandshakePhase.ScriptedComplete, (await owner.Login.WaitAsync(Guard)).Phase);
        var result = await run.WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(ReceiveEnd.Completed, result.End);
        Assert.Equal(5, result.Publication.Revision);
    }

    [Fact]
    public async Task BlockedCredentialProviderPreventsReplacementUntilCleanup()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var entered = Signal(); var release = Signal(); var finish = Signal();
        var peer = verification.Run(async client =>
        {
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal, credentials: leg =>
        {
            entered.SetResult(); release.Task.GetAwaiter().GetResult();
            return CandidateCommands.Login("synthetic", "fake", 0, 1, 2);
        });
        var run = owner.RunAsync(); await entered.Task.WaitAsync(Guard);
        var next = session.Begin("next", "b").Generation;
        int freshCalls = 0;
        HeldAccountConnection? Replacement() => HeldAccountConnection.TryAttach(session, next,
            verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1,
            _ => { freshCalls++; throw new Exception(); }, () => 123, (_, now) => new(now));
        Assert.Equal(HandshakePhase.Cancelled, owner.Handshake.Phase); // synchronous, before cancellation workers run
        Assert.Null(Replacement()); Assert.False(run.IsCompleted); Assert.Null(owner.Publication);
        release.SetResult();
        var result = await run.WaitAsync(Guard); await owner.DisposeAsync();
        Assert.True(result.ResourcesReleased);
        Assert.Single(owner.Connections);
        Assert.Equal(HandshakePhase.Cancelled, (await owner.Login).Phase);
        await using var replacement = Assert.IsType<HeldAccountConnection>(Replacement());
        Assert.Equal(0, freshCalls);
        finish.SetResult(); await peer.WaitAsync(Guard);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task MalformedOrTruncatedFormalSuffixPreservesEarlierCommits(bool truncated)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client);
            var valid = WireCodec.Encode(new Packet(26, 4, [42, 0, 0, 0]));
            var tail = truncated ? WireCodec.Encode(new Packet(1, 23))[..3] : new byte[] { 0, 0, 0, 0 };
            await client.Raw(valid.Concat(tail).ToArray());
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var owner = Attach(session, generation, verification, formal);
        var result = await owner.RunAsync().WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(truncated ? ReceiveEnd.TruncatedFrame : ReceiveEnd.InvalidFrame, result.End);
        Assert.Equal(5, result.Publication.Revision);
        Assert.True(result.ResourcesReleased);
    }
}
