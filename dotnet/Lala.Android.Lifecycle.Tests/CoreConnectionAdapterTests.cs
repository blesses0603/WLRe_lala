using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Android.Lifecycle.Tests;

public sealed class CoreConnectionAdapterTests
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
        : IAccountCredentialSource, IAsyncDisposable
    {
        public int Disposals { get; private set; }
        public ValueTask DisposeAsync() { Disposals++; return ValueTask.CompletedTask; }
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

    private sealed class Resolver(Func<ConnectionTarget, CancellationToken, ValueTask<CoreConnectionSelection?>> resolve)
        : ICoreConnectionSelectionResolver
    {
        public ValueTask<CoreConnectionSelection?> ResolveAsync(ConnectionTarget target, CancellationToken token) => resolve(target, token);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task RealCoreLoginReceivesHeldAndStopOrNetworkLossClosesOwner(bool networkLoss)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var ready = Signal();
        var first = verification.Run(Verify);
        var second = formal.Run(async client =>
        {
            await EnterWorld(client);
            await client.Send(new Packet(26, 4, [42, 0, 0, 0]), new Packet(1, 23));
            await client.Expect(63, 5); ready.SetResult();
            // Closing an owned socket can surface as EOF or a TCP reset on Windows.
            var ended = await Record.ExceptionAsync(() => client.Next());
            Assert.True(ended is IOException or SocketException, $"Expected connection closure, received {ended?.GetType().Name ?? "a packet"}.");
        });
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        int resolves = 0, acquisitions = 0;
        var factory = new CoreConnectionAdapterFactory(new Resolver((_, _) =>
        {
            Interlocked.Increment(ref resolves);
            return ValueTask.FromResult<CoreConnectionSelection?>(new(Profile(verification, formal), new Source((_, _) =>
            {
                Interlocked.Increment(ref acquisitions);
                return ValueTask.FromResult<AccountLoginCredentials?>(credentials);
            })));
        }));
        await using (var unused = factory.Create(new("opaque", "selection"))) Assert.Equal(0, resolves);
        var delay = new ControlledDelay();
        await using var owner = new ConnectionCoordinator(factory, new ConnectionPolicy
        {
            ConnectTimeout = LifecycleFixture.ConnectTimeout, CleanupTimeout = LifecycleFixture.CleanupTimeout
        }, delay);
        bool active = false;
        using var subscription = owner.Subscribe(s => { if (s.Phase == ConnectionPhase.Active) active = true; });
        await owner.SetNetworkAvailableAsync(true); await owner.StartAsync(new("opaque", "selection"));
        await LifecycleFixture.PhaseAsync(owner, ConnectionPhase.ReceivingHeld);
        await ready.Task.WaitAsync(Guard);
        Assert.Equal(ConnectionEndReason.ResourceHeld, owner.Snapshot.Reason);
        Assert.True(credentials.IsDisposed); Assert.Equal(1, resolves); Assert.Equal(1, acquisitions);
        // A held connection has completed login: its connect watchdog cannot stop it.
        delay.CompleteAll();
        Assert.Equal(ConnectionPhase.ReceivingHeld, owner.Snapshot.Phase);
        if (networkLoss)
        {
            await owner.SetNetworkAvailableAsync(false);
            Assert.Equal(ConnectionPhase.WaitingForNetwork, owner.Snapshot.Phase);
        }
        else
        {
            await owner.StopAsync(); Assert.Equal(ConnectionPhase.Stopped, owner.Snapshot.Phase);
        }
        Assert.False(active);
        await Task.WhenAll(first, second).WaitAsync(Guard);
    }

    [Fact]
    public async Task SwitchingSelectionWaitsForLateSourceAndNeverConnectsOldOwner()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var entered = Signal(); var release = Signal();
        var credentials = new AccountLoginCredentials("synthetic", "fake_password");
        var seen = new List<string>();
        var factory = new CoreConnectionAdapterFactory(new Resolver((target, _) =>
        {
            lock (seen) seen.Add(target.AccountKey);
            return ValueTask.FromResult<CoreConnectionSelection?>(new(Profile(verification, formal), new Source(async (_, _) =>
            {
                if (target.AccountKey == "old") { entered.SetResult(); await release.Task; return credentials; }
                return null;
            })));
        }));
        await using var owner = new ConnectionCoordinator(factory);
        await owner.SetNetworkAvailableAsync(true); await owner.StartAsync(new("old", "opaque"));
        await entered.Task.WaitAsync(Guard);
        var replace = owner.StartAsync(new("new", "opaque"));
        Assert.False(replace.IsCompleted); lock (seen) Assert.Single(seen);
        release.SetResult(); await replace.WaitAsync(Guard);
        await LifecycleFixture.PhaseAsync(owner, ConnectionPhase.Failed);
        Assert.True(credentials.IsDisposed); Assert.False(verification.HasPending); Assert.False(formal.HasPending);
        lock (seen) Assert.Equal(new[] { "old", "new" }, seen);
        Assert.Equal(ConnectionEndReason.AdapterFailure, owner.Snapshot.Reason);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task ResolverAndSourceFailuresAreSanitizedAndTerminal(bool sourceFailure)
    {
        await using var verification = new Peer(); await using var formal = new Peer(); int count = 0;
        var factory = new CoreConnectionAdapterFactory(new Resolver((_, _) =>
        {
            count++;
            if (!sourceFailure) throw new InvalidOperationException("synthetic-secret");
            return ValueTask.FromResult<CoreConnectionSelection?>(new(Profile(verification, formal),
                new Source((_, _) => throw new InvalidOperationException("synthetic-secret"))));
        }));
        await using var owner = new ConnectionCoordinator(factory);
        await owner.SetNetworkAvailableAsync(true); await owner.StartAsync(new("opaque", "selection"));
        var result = await LifecycleFixture.PhaseAsync(owner, ConnectionPhase.Failed);
        Assert.Equal(ConnectionEndReason.AdapterFailure, result.Reason); Assert.Equal(1, count);
        Assert.DoesNotContain("secret", result.ToString()); Assert.False(verification.HasPending);
    }

    [Theory]
    [InlineData(AccountConnectionFailure.WriteUncertain, AccountConnectionEndReason.ConnectionEnded)]
    [InlineData(AccountConnectionFailure.WriteFailed, AccountConnectionEndReason.ConnectionEnded)]
    [InlineData(AccountConnectionFailure.IncompleteLoginOrUnknown, AccountConnectionEndReason.ConnectionEnded)]
    [InlineData(AccountConnectionFailure.WriteUncertain, AccountConnectionEndReason.Cancelled)]
    [InlineData(AccountConnectionFailure.WriteFailed, AccountConnectionEndReason.Cancelled)]
    [InlineData(AccountConnectionFailure.IncompleteLoginOrUnknown, AccountConnectionEndReason.Cancelled)]
    public void UnsafeOutcomesNeverRetry(AccountConnectionFailure failure, AccountConnectionEndReason end)
    {
        var result = new AccountConnectionResult(new(Guid.NewGuid(), 1, 1, AccountConnectionPhase.Ended,
            end, null,
            [new(1, Guid.NewGuid(), failure, false, false)]), true);
        Assert.Equal(ConnectionEndReason.AdapterFailure, CoreConnectionAdapterFactory.MapResult(result));
    }

    [Fact]
    public async Task CoreAttemptBudgetIsOneEvenWhenCallerOptionsRequestMore()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        var endpoint = (IPEndPoint)listener.LocalEndpoint; listener.Stop(); int acquisitions = 0;
        var factory = new CoreConnectionAdapterFactory(new Resolver((_, _) =>
            ValueTask.FromResult<CoreConnectionSelection?>(new(new(endpoint, endpoint, 0xAD, 0xAD, 1, 1, 2),
                new Source((_, _) => { acquisitions++; return ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "fake_password")); })))),
            new() { MaximumAttempts = 10 });
        await using var adapter = factory.Create(new("opaque", "selection"));
        var result = await adapter.RunAsync(() => throw new Exception("Must never activate"), default).WaitAsync(Guard);
        Assert.Equal(ConnectionEndReason.TransientNetworkFailure, result); Assert.Equal(1, acquisitions);
    }
    private sealed class LateHeldAdapter : IHeldConnectionAdapter
    {
        internal readonly TaskCompletionSource Started = Signal();
        internal readonly TaskCompletionSource Finish = Signal();
        internal Action? Held, Retiring;
        internal ConnectionEndReason Result = ConnectionEndReason.UserStopped;
        public Task<ConnectionEndReason> RunAsync(Action active, CancellationToken token)
            => throw new InvalidOperationException("Held path must be used.");
        public async Task<ConnectionEndReason> RunHeldAsync(Action held, Action retiring, CancellationToken token)
        {
            Held = held; Retiring = retiring; Started.SetResult(); await Finish.Task;
            return Result;
        }
        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }
    private sealed class SingleFactory(LateHeldAdapter adapter) : IConnectionAdapterFactory
    {
        public bool IsAvailable => true;
        internal int Creations;
        public IConnectionAdapter Create(ConnectionTarget target) { Creations++; return adapter; }
    }
    [Fact]
    public async Task LateHeldCallbacksCannotResurrectStoppedGeneration()
    {
        var adapter = new LateHeldAdapter();
        await using var owner = new ConnectionCoordinator(new SingleFactory(adapter));
        await owner.SetNetworkAvailableAsync(true); await owner.StartAsync(new("opaque", "selection"));
        await adapter.Started.Task.WaitAsync(Guard);
        var stopped = owner.StopAsync(); adapter.Held!();
        Assert.Equal(ConnectionPhase.Stopping, owner.Snapshot.Phase);
        adapter.Finish.SetResult(); await stopped.WaitAsync(Guard);
        adapter.Held(); Assert.Equal(ConnectionPhase.Stopped, owner.Snapshot.Phase);
    }
    [Fact]
    public async Task SourceLifetimeRemainsCallerOwnedAndDisposedAdapterCannotResolve()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        int resolves = 0;
        var source = new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(null));
        var factory = new CoreConnectionAdapterFactory(new Resolver((_, _) =>
        {
            resolves++;
            return ValueTask.FromResult<CoreConnectionSelection?>(new(Profile(verification, formal), source));
        }));
        var adapter = factory.Create(new("opaque", "selection"));
        Assert.Equal(ConnectionEndReason.AdapterFailure, await adapter.RunAsync(() => { }, default));
        await adapter.DisposeAsync(); await adapter.DisposeAsync(); Assert.Equal(0, source.Disposals);
        var unused = factory.Create(new("opaque", "selection")); await unused.DisposeAsync();
        Assert.Equal(ConnectionEndReason.UserStopped, await unused.RunAsync(() => { }, default));
        Assert.Equal(1, resolves); Assert.False(verification.HasPending);
        await source.DisposeAsync(); Assert.Equal(1, source.Disposals);
    }
    [Fact]
    public void HeldPhaseKeepsForegroundOwnerAliveWithoutClaimingActive()
    {
        Assert.True(ConnectionPhaseState.IsRunning(ConnectionPhase.ReceivingHeld));
        Assert.False(ConnectionPhaseState.IsRunning(ConnectionPhase.Stopped));
        var description = Platform.ConnectionStatusText.Describe(new(1, 1, ConnectionPhase.ReceivingHeld, 0, ConnectionEndReason.ResourceHeld));
        Assert.Contains("不能執行遊戲操作", description);
        Assert.DoesNotContain("會話啟用", description);
    }
    [Fact]
    public async Task SynchronouslyBlockedResolverCannotHoldDisposalGateOrConnectAfterStop()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        using var release = new ManualResetEventSlim(); var entered = Signal();
        int acquired = 0;
        var factory = new CoreConnectionAdapterFactory(new Resolver((_, _) =>
        {
            entered.SetResult(); release.Wait(Guard);
            return ValueTask.FromResult<CoreConnectionSelection?>(new(Profile(verification, formal),
                new Source((_, _) => { acquired++; return ValueTask.FromResult<AccountLoginCredentials?>(null); })));
        }));
        var adapter = factory.Create(new("opaque", "selection"));
        var run = adapter.RunAsync(() => { }, default);
        try
        {
            await entered.Task.WaitAsync(Guard);
            // Dispose returns an incomplete task rather than blocking on the resolver's gate.
            var disposing = adapter.DisposeAsync().AsTask();
            Assert.False(disposing.IsCompleted); release.Set();
            await disposing.WaitAsync(Guard);
            Assert.Equal(ConnectionEndReason.UserStopped, await run.WaitAsync(Guard));
            Assert.Equal(0, acquired); Assert.False(verification.HasPending);
        }
        finally { release.Set(); await adapter.DisposeAsync(); }
    }
    [Fact]
    public async Task NaturalRetirementStartsCleanupWatchdogWithoutRetryOrFalseRelease()
    {
        var adapter = new LateHeldAdapter { Result = ConnectionEndReason.TransientNetworkFailure };
        var factory = new SingleFactory(adapter); var delay = new ControlledDelay();
        await using var owner = new ConnectionCoordinator(factory, new ConnectionPolicy
        {
            ConnectTimeout = LifecycleFixture.ConnectTimeout, CleanupTimeout = LifecycleFixture.CleanupTimeout
        }, delay);
        await owner.SetNetworkAvailableAsync(true); await owner.StartAsync(new("opaque", "selection"));
        await adapter.Started.Task.WaitAsync(Guard); adapter.Held!();
        Assert.Equal(ConnectionPhase.ReceivingHeld, owner.Snapshot.Phase);
        adapter.Retiring!(); Assert.Equal(ConnectionPhase.Stopping, owner.Snapshot.Phase);
        Assert.False(adapter.Finish.Task.IsCompleted); // A natural drain is not a cancellation/result.
        var watchdog = await delay.TakeAsync(LifecycleFixture.CleanupTimeout); watchdog.Complete();
        await LifecycleFixture.PhaseAsync(owner, ConnectionPhase.CleanupBlocked);
        Assert.Equal(1, factory.Creations);
        adapter.Held(); adapter.Retiring();
        Assert.Equal(ConnectionPhase.CleanupBlocked, owner.Snapshot.Phase);
        adapter.Finish.SetResult();
        await LifecycleFixture.PhaseAsync(owner, ConnectionPhase.Stopped);
        Assert.Equal(ConnectionEndReason.TransientNetworkFailure, owner.Snapshot.Reason);
        Assert.Equal(1, factory.Creations); // Timed-out cleanup cannot silently resume retries.
        adapter.Retiring(); Assert.Equal(ConnectionPhase.Stopped, owner.Snapshot.Phase);
    }
}
