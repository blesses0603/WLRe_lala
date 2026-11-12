using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class AccountReceiveTests
{
    private static readonly TimeSpan Limit = TimeSpan.FromSeconds(10);
    private static ReceiveAttempt? Attach(AccountSession session, long generation, IReceiveTransport transport) =>
        session.AttachHeldReceive(generation, transport, 0xAD, () => 123, (_, now) => new(now));

    [Fact]
    public async Task LoopbackContinuouslyPublishesButNeverAdmitsResources()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var tcp = new BoundedTcpTransport((IPEndPoint)listener.LocalEndpoint);
        await tcp.ConnectAsync().WaitAsync(Limit);
        using var peer = await listener.AcceptTcpClientAsync().WaitAsync(Limit);
        var session = new AccountSession();
        var generation = session.Begin("synthetic", "loopback").Generation;
        await using var attempt = Assert.IsType<ReceiveAttempt>(Attach(session, generation, tcp));
        var running = attempt.RunAsync();
        byte[] packet = WireCodec.Encode(new Packet(1, 23), 0xAD);
        await peer.GetStream().WriteAsync(packet.AsMemory(0, 3));
        await peer.GetStream().WriteAsync(packet.AsMemory(3));
        await WaitRevision(1);
        await peer.GetStream().WriteAsync(packet.Concat(packet).ToArray());
        await WaitRevision(3);
        Assert.False(running.IsCompleted);
        Assert.False(session.ConfirmResources(generation, "v", "v", true));
        Assert.False(session.AllowsResourceGate(generation, "walk"));
        var published = session.ReadHeldReceive(generation, attempt.Latest.Attempt)!;
        Assert.True(published.ResourceHeld);
        Assert.False(published.Snapshot.IsCompleteState);
        session.Disconnect();
        Assert.Null(session.ReadHeldReceive(generation, attempt.Latest.Attempt));
        var result = await running.WaitAsync(Limit);
        Assert.True(result.ResourcesReleased);
        Assert.Equal(TcpTransportStage.Disposed, tcp.Snapshot.Stage);
        async Task WaitRevision(long revision)
        {
            using var deadline = new CancellationTokenSource(Limit);
            while (session.ReadHeldReceive(generation, attempt.Latest.Attempt)!.Revision < revision)
                await Task.Delay(1, deadline.Token);
        }
    }

    [Theory]
    [InlineData("begin")]
    [InlineData("disconnect")]
    [InlineData("hold")]
    public async Task RetirementRevokesPublicationBeforeAwaitingCleanup(string operation)
    {
        var session = new AccountSession();
        var generation = session.Begin("a", "b").Generation;
        var transport = new ControlledTransport();
        var attempt = Attach(session, generation, transport)!;
        var identity = attempt.Latest.Attempt;
        Assert.NotNull(session.ReadHeldReceive(generation, identity));
        Assert.Null(session.ReadHeldReceive(generation, Guid.NewGuid()));
        if (operation == "begin") session.Begin("next", "b");
        else if (operation == "disconnect") session.Disconnect();
        else session.Hold(generation);
        Assert.Null(session.ReadHeldReceive(generation, identity));
        Assert.False(attempt.IsCurrent(identity));
        var next = session.Begin("next", "b");
        var rejected = new ControlledTransport();
        Assert.Null(Attach(session, next.Generation, rejected));
        Assert.Equal(0, rejected.Disposals);
        transport.Cleanup.SetResult();
        await attempt.DisposeAsync().AsTask().WaitAsync(Limit);
        var replacement = Attach(session, next.Generation, rejected);
        Assert.NotNull(replacement);
        rejected.Cleanup.SetResult();
        await replacement!.DisposeAsync();
        Assert.Equal(0, transport.Reads);
    }

    [Fact]
    public async Task FailedCleanupPermanentlyBlocksReplacement()
    {
        var session = new AccountSession();
        var generation = session.Begin("a", "b").Generation;
        var transport = new ControlledTransport();
        var attempt = Attach(session, generation, transport)!;
        var next = session.Begin("next", "b");
        transport.Cleanup.SetException(new IOException("synthetic cleanup"));
        await Assert.ThrowsAsync<ReceiveCleanupException>(() => attempt.DisposeAsync().AsTask());
        Assert.Null(Attach(session, next.Generation, new ControlledTransport()));
        session.Disconnect();
        next = session.Begin("again", "b");
        Assert.Null(Attach(session, next.Generation, new ControlledTransport()));
    }

    [Theory]
    [InlineData("stale")]
    [InlineData("held")]
    [InlineData("verified")]
    [InlineData("disconnected")]
    public void AdmissionRejectsWithoutTakingOwnership(string mode)
    {
        var session = new AccountSession();
        var generation = session.Begin("a", "b").Generation;
        if (mode == "stale") session.Begin("next", "b");
        if (mode == "held") session.Hold(generation);
        if (mode == "verified") session.ConfirmResources(generation, "v", "v", true);
        if (mode == "disconnected") session.Disconnect();
        var source = new ControlledTransport();
        Assert.Null(Attach(session, generation, source));
        Assert.Equal(0, source.Reads);
        Assert.Equal(0, source.Disposals);
    }

    [Fact]
    public async Task DuplicateAttachAndInvalidConstructionDoNotChangeOwner()
    {
        var session = new AccountSession();
        var generation = session.Begin("a", "b").Generation;
        var source = new ControlledTransport();
        Assert.Throws<ProtocolException>(() => session.AttachHeldReceive(generation, source, -1, () => 0, (_, now) => new(now)));
        Assert.Equal(SessionPhase.Preparing, session.Snapshot.Phase);
        var attempt = Attach(session, generation, source)!;
        Assert.Null(Attach(session, generation, new ControlledTransport()));
        source.Cleanup.SetResult();
        await attempt.DisposeAsync();
        Assert.Null(Attach(session, generation, new ControlledTransport()));
    }

    [Fact]
    public async Task LateNoncooperativeReadCannotPublishOrPermitOverlappingReplacement()
    {
        var session = new AccountSession();
        var generation = session.Begin("a", "b").Generation;
        var source = new LateReadTransport();
        var attempt = Attach(session, generation, source)!;
        var running = attempt.RunAsync();
        await source.Started.Task.WaitAsync(Limit);
        var next = session.Begin("next", "b");
        Assert.Null(session.ReadHeldReceive(generation, attempt.Latest.Attempt));
        await source.Disposed.Task.WaitAsync(Limit);
        Assert.False(running.IsCompleted);
        Assert.Null(Attach(session, next.Generation, new ControlledTransport()));
        source.Release.SetResult();
        var result = await running.WaitAsync(Limit);
        await attempt.DisposeAsync();
        Assert.Equal(0, result.Publication.Revision);
        Assert.Equal(ReceiveEnd.Disposed, result.End);
        Assert.True(result.ResourcesReleased);
        var replacementSource = new ControlledTransport();
        var replacement = Assert.IsType<ReceiveAttempt>(Attach(session, next.Generation, replacementSource));
        Assert.Null(session.ReadHeldReceive(next.Generation, attempt.Latest.Attempt));
        replacementSource.Cleanup.SetResult();
        await replacement.DisposeAsync();
    }

    private sealed class LateReadTransport : IReceiveTransport
    {
        internal TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal TaskCompletionSource Disposed { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public async ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken token)
        {
            Started.SetResult();
            await Release.Task;
            var bytes = WireCodec.Encode(new Packet(1, 23), 0xAD);
            bytes.CopyTo(destination);
            return bytes.Length;
        }
        public ValueTask DisposeAsync() { Disposed.TrySetResult(); return ValueTask.CompletedTask; }
    }

    private sealed class ControlledTransport : IReceiveTransport
    {
        internal TaskCompletionSource Cleanup { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal int Reads, Disposals;
        public ValueTask<int> ReadAsync(Memory<byte> destination, CancellationToken token)
        {
            Interlocked.Increment(ref Reads);
            return new(Task.Delay(Timeout.Infinite, token).ContinueWith(_ => 0, TaskScheduler.Default));
        }
        public ValueTask DisposeAsync()
        {
            Interlocked.Increment(ref Disposals);
            return new(Cleanup.Task);
        }
    }
}
