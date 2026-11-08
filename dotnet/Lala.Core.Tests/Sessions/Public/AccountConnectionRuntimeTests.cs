using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed class AccountConnectionRuntimeTests
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
        internal async Task CloseSendAndExpectEof()
        {
            socket.Shutdown(SocketShutdown.Send);
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
    private static TaskCompletionSource Signal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private sealed class Source(Func<AccountCredentialRequest, CancellationToken, ValueTask<AccountLoginCredentials?>> acquire)
        : IAccountCredentialSource
    {
        public ValueTask<AccountLoginCredentials?> AcquireAsync(AccountCredentialRequest request, CancellationToken token) => acquire(request, token);
    }
    private static AccountConnectionProfile Profile(Peer verification, Peer formal) =>
        new(verification.Endpoint, formal.Endpoint, 0xAD, 0xAD, 1, 1, 2);
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
    private static async Task WaitFor(Func<bool> condition)
    {
        using var deadline = new CancellationTokenSource(Guard);
        while (!condition()) await Task.Delay(1, deadline.Token);
    }

    [Fact]
    public async Task PublicFacadeOwnsCredentialsAndContinuesReceivingWithoutAuthority()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var finish = Signal(); var ready = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client);
            await client.Send(new Packet(26, 4, [42, 0, 0, 0]), new Packet(1, 23));
            await client.Expect(63, 5); ready.SetResult();
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        AccountCredentialRequest? request = null;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((value, _) => { request = value; return ValueTask.FromResult<AccountLoginCredentials?>(credentials); }));
        Assert.Null(request); Assert.Equal(AccountConnectionPhase.Created, runtime.Snapshot.Phase);
        var run = runtime.RunAsync(); Assert.Same(run, runtime.RunAsync());
        await ready.Task.WaitAsync(Guard);
        await WaitFor(() => runtime.Publication?.Revision == 6 && runtime.Snapshot.Phase == AccountConnectionPhase.ReceivingHeld);
        Assert.True(credentials.IsDisposed);
        Assert.Equal(new AccountCredentialRequest(generation, 1), request);
        Assert.True(runtime.Snapshot.ResourceHeld); Assert.False(runtime.Snapshot.CanSendCommands);
        Assert.True(runtime.Publication!.ResourceHeld); Assert.False(runtime.Publication.State.IsCompleteState);
        Assert.Equal(nameof(AccountReceivePublication), runtime.Publication.ToString());
        Assert.False(session.ConfirmResources(generation, "v", "v", true));
        runtime.Stop(); Assert.Null(runtime.Publication);
        var result = await run.WaitAsync(Guard);
        Assert.Equal(AccountConnectionFailure.CancelledOrHeld, Assert.Single(result.Status.History).Failure);
        Assert.Equal(AccountConnectionEndReason.Stopped, result.Status.EndReason); Assert.True(result.ResourcesReleased);
        finish.SetResult(); await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public async Task RejectedVerificationClearsCredentialsAndStops()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [1, 0]));
            await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        var credentials = new AccountLoginCredentials("synthetic", "fake_password"); int requests = 0;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => { requests++; return ValueTask.FromResult<AccountLoginCredentials?>(credentials); }),
            new() { MaximumAttempts = 3 });
        var result = await runtime.RunAsync().WaitAsync(Guard); await server.WaitAsync(Guard);
        Assert.True(credentials.IsDisposed); Assert.Equal(1, requests);
        Assert.False(formal.HasPending);
        Assert.Equal(AccountConnectionEndReason.ConnectionEnded, result.Status.EndReason);
        Assert.False(Assert.Single(result.Status.History).RetryEligible);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task StopOrAccountReplacementDisposesLateCredentialsWithoutConnecting(bool replace)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var entered = Signal(); var release = Signal();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal), new Source(async (_, _) =>
        {
            entered.SetResult(); await release.Task; return credentials;
        }));
        var run = runtime.RunAsync(); await entered.Task.WaitAsync(Guard);
        if (replace) session.Begin("manual", "other"); else runtime.Stop();
        release.SetResult(); var result = await run.WaitAsync(Guard);
        Assert.True(credentials.IsDisposed);
        Assert.Equal(replace ? AccountConnectionEndReason.Superseded : AccountConnectionEndReason.Stopped, result.Status.EndReason);
        Assert.False(verification.HasPending); Assert.False(formal.HasPending);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task PrecancelOrPredisposeNeverAcquiresCredentials(bool dispose)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation; int requests = 0;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => { requests++; throw new Exception("must not run"); }));
        using var stop = new CancellationTokenSource(); stop.Cancel();
        if (dispose) await runtime.DisposeAsync();
        var result = await runtime.RunAsync(stop.Token).WaitAsync(Guard);
        Assert.Equal(dispose ? AccountConnectionEndReason.Disposed : AccountConnectionEndReason.Cancelled, result.Status.EndReason);
        Assert.Equal(0, requests); Assert.True(result.ResourcesReleased);
    }

    [Fact]
    public async Task PublicRetryRequestsFreshOwnedCredentialsAndRespectsAttemptCap()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var endpoint = (IPEndPoint)listener.LocalEndpoint; listener.Stop();
        var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
        var held = new List<AccountLoginCredentials>(); var requests = new List<AccountCredentialRequest>();
        await using var runtime = new AccountConnectionRuntime(session, generation,
            new(endpoint, endpoint, 0xAD, 0xAD, 1, 1, 2), new Source((request, _) =>
            {
                requests.Add(request); var value = new AccountLoginCredentials("synthetic", "fake_password");
                held.Add(value); return ValueTask.FromResult<AccountLoginCredentials?>(value);
            }), new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) });
        var result = await runtime.RunAsync().WaitAsync(Guard);
        Assert.Equal(AccountConnectionEndReason.AttemptsExhausted, result.Status.EndReason);
        Assert.Equal(new[] { generation, generation + 1 }, requests.Select(r => r.Generation));
        Assert.Equal(new[] { 1, 2 }, requests.Select(r => r.AttemptNumber));
        Assert.All(held, value => Assert.True(value.IsDisposed));
        Assert.All(result.Status.History, h => Assert.Equal(AccountConnectionFailure.ConnectFailed, h.Failure));
    }

    [Fact]
    public void PublicProfileSnapshotsEndpointsAndRedactsInterpolation()
    {
        var verification = new IPEndPoint(IPAddress.Loopback, 1234);
        var formal = new IPEndPoint(IPAddress.Loopback, 2345);
        var profile = new AccountConnectionProfile(verification, formal, 0xAD, 0xAD, 1, 1, 2);
        verification.Port = 1; formal.Port = 2; profile.FormalEndpoint.Port = 3;
        Assert.Equal(1234, profile.VerificationEndpoint.Port); Assert.Equal(2345, profile.FormalEndpoint.Port);
        Assert.Equal(nameof(AccountConnectionProfile), profile.ToString());
        Assert.Throws<ArgumentOutOfRangeException>(() => new AccountConnectionProfile(verification, formal, 0, 0, 0, 0, 0));
        Assert.Throws<ArgumentException>(() => new AccountConnectionProfile(new(IPAddress.Loopback, 0), formal, 0, 0, 1, 0, 0));
    }

    [Fact]
    public async Task SourceErrorsAreSanitizedAndNullDeclinesWithoutRetries()
    {
        foreach (bool fail in new[] { false, true })
        {
            await using var verification = new Peer(); await using var formal = new Peer();
            var session = new AccountSession(); var generation = session.Begin("a", "b").Generation;
            await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal), new Source((_, _) =>
            {
                if (fail) throw new Exception("synthetic-private-error");
                return ValueTask.FromResult<AccountLoginCredentials?>(null);
            }));
            var result = await runtime.RunAsync().WaitAsync(Guard);
            Assert.Equal(fail ? AccountConnectionEndReason.ProviderFailed : AccountConnectionEndReason.CredentialsUnavailable, result.Status.EndReason);
            Assert.DoesNotContain("synthetic-private", result.ToString()); Assert.Empty(result.Status.History);
            Assert.False(verification.HasPending);
        }
    }
}
