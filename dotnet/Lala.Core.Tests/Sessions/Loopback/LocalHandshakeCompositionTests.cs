using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions.Transport;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed class LocalHandshakeCompositionTests
{
    private static readonly TimeSpan Guard = TimeSpan.FromSeconds(10);
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
        internal async Task CloseSendAndExpectEof()
        {
            socket.Shutdown(SocketShutdown.Send);
            Assert.Empty(pending); decoder.Finish();
            Assert.Equal(0, await socket.ReceiveAsync(new byte[1], SocketFlags.None, token));
        }
    }
    private static Task Verify(Client client) => VerifyCore(client);
    private static async Task VerifyCore(Client client)
    {
        await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [0, 0])); await client.CloseSendAndExpectEof();
    }
    private static void NoAuthority(HarnessResult result)
    {
        Assert.False(result.Handshake.CanSendPackets); Assert.False(result.Handshake.IsLive);
        Assert.All(result.ClosedLegs, leg =>
        {
            Assert.Equal(TcpTransportStage.Disposed, leg.Stage);
            Assert.False(leg.ReadPending); Assert.False(leg.WritePending);
        });
    }

    [Theory]
    [InlineData(1)] [InlineData(4096)]
    public async Task FragmentedAndCoalescedRealLegsPreserveEveryEventAndWriteOrder(int chunk)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var first = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            await client.Raw(new[] { new Packet(1, 23), new Packet(63, 7, [0, 0]) }.SelectMany(p => WireCodec.Encode(p)).ToArray(), chunk);
            await client.Expect(63, 5); await client.CloseSendAndExpectEof();
        });
        var second = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2);
            await client.Raw(new[] { new Packet(63, 7, [0, 2]), Roles, new Packet(1, 23) }.SelectMany(p => WireCodec.Encode(p)).ToArray(), chunk);
            await client.Expect(63, 2, 1); await client.Expect(63, 5);
            await client.Raw(new[] { World, new Packet(1, 23), new Packet(26, 4, [42, 0, 0, 0]), new Packet(1, 11) }
                .SelectMany(p => WireCodec.Encode(p)).ToArray(), chunk);
            await client.Expect(63, 5); await client.Expect(12, 1); await client.Expect(3, 2);
            await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, new(ReadBytes: chunk)).WaitAsync(Guard);
        await Task.WhenAll(first, second).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Complete, result.End); Assert.Equal(HandshakePhase.ScriptedComplete, result.Handshake.Phase);
        Assert.Equal(new[] { "heartbeat_request", "login_result", "login_result", "role_list_available", "heartbeat_request",
            "world_player", "heartbeat_request", "gold_snapshot", "initial_data_complete" }, result.Transcript.Select(x => x.Event.Type));
        Assert.All(result.Transcript.Take(2), e => Assert.Equal(HandshakeLeg.Verification, e.Leg));
        Assert.All(result.Transcript.Skip(2), e => Assert.Equal(HandshakeLeg.Formal, e.Leg));
        Assert.Equal(2, result.ClosedLegs.Length);
        Assert.NotEqual(result.ClosedLegs[0].Connection, result.ClosedLegs[1].Connection);
        NoAuthority(result);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public async Task VerificationRejectsWrongKindForeignLegEvidenceExtraAndPartialTail(int scenario)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        _ = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            var bytes = scenario switch {
                0 => WireCodec.Encode(new Packet(63, 7, [0, 2])), // Formal success on verification connection.
                1 => WireCodec.Encode(Roles),
                2 => WireCodec.Encode(new Packet(63, 7, [0, 0])).Concat(WireCodec.Encode(new Packet(1, 23))).ToArray(),
                _ => WireCodec.Encode(new Packet(63, 7, [0, 0])).Concat(new byte[] { 0x69 }).ToArray()
            };
            await client.Raw(bytes); await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint).WaitAsync(Guard);
        Assert.Equal(scenario < 2 ? HarnessEnd.Protocol : HarnessEnd.TrailingData, result.End);
        Assert.False(formal.WasAccepted); Assert.Single(result.ClosedLegs); NoAuthority(result);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task TerminalFormalTailFailsInsteadOfHandingOffUnreadData(bool partial)
    {
        await using var verification = new Peer(); await using var formal = new Peer(); _ = verification.Run(Verify);
        _ = formal.Run(async client =>
        {
            await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles); await client.Expect(63, 2, 1);
            var bytes = WireCodec.Encode(World).Concat(WireCodec.Encode(new Packet(1, 11)))
                .Concat(partial ? new byte[] { 0x69 } : WireCodec.Encode(new Packet(1, 23))).ToArray();
            await client.Raw(bytes); await client.Expect(12, 1); await client.Expect(3, 2); await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.TrailingData, result.End); Assert.Equal(HandshakePhase.Failed, result.Handshake.Phase);
        Assert.Equal(2, result.ClosedLegs.Length); NoAuthority(result);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task EarlyEofOrTruncatedFrameFails(bool truncated)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        _ = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0); if (truncated) await client.Raw([0x69, 0x6B, 0xAB]);
            await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint).WaitAsync(Guard);
        Assert.Equal(truncated ? HarnessEnd.Protocol : HarnessEnd.EarlyEof, result.End); NoAuthority(result);
    }

    [Theory]
    [InlineData(false, false)] [InlineData(true, false)] [InlineData(false, true)] [InlineData(true, true)]
    public async Task CancellationOrHoldAtEitherLegClosesAllOwners(bool held, bool formalLeg)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        using var cancel = new CancellationTokenSource(); using var hold = new CancellationTokenSource();
        var reached = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        // Keep the send side open until cancellation: a peer-side barrier, not a sleep.
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        async Task Waiting(Client client)
        {
            await client.Expect(63, 7, formalLeg ? (byte)2 : (byte)0); reached.SetResult();
            await client.WaitFor(release.Task); await client.CloseSendAndExpectEof();
        }
        if (formalLeg) { _ = verification.Run(Verify); _ = formal.Run(Waiting); } else _ = verification.Run(Waiting);
        var run = LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, cancellation: cancel.Token, hold: hold.Token);
        await reached.Task.WaitAsync(Guard); if (held) hold.Cancel(); else cancel.Cancel();
        var result = await run.WaitAsync(Guard); release.TrySetResult();
        Assert.Equal(held ? HarnessEnd.Held : HarnessEnd.Cancelled, result.End);
        Assert.Equal(held ? HandshakePhase.Held : HandshakePhase.Cancelled, result.Handshake.Phase);
        Assert.Equal(formalLeg ? 2 : 1, result.ClosedLegs.Length); NoAuthority(result);
    }

    [Theory]
    [InlineData(0)] [InlineData(1)] [InlineData(2)] [InlineData(3)]
    public async Task SyntheticFaultedRealWriteReceiptCannotAdvance(int fault)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        _ = verification.Run(async client => { await client.Expect(63, 7, 0); await client.CloseSendAndExpectEof(); });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, receiptFault: actual => fault switch {
            0 => actual with { Outcome = TcpWriteOutcome.PartialOrUncertain },
            1 => actual with { ConfirmedLocalBytes = 0 },
            2 => actual with { Connection = Guid.NewGuid() },
            _ => actual with { End = TcpTransportEnd.Cancelled }
        }).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Transport, result.End); Assert.Empty(result.Transcript);
        Assert.False(formal.WasAccepted); NoAuthority(result);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task InputAndEventBudgetsFailClosed(bool bytes)
    {
        await using var verification = new Peer(); await using var formal = new Peer(); _ = verification.Run(Verify);
        _ = formal.Run(async client => { await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 2]), Roles); await client.CloseSendAndExpectEof(); });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint,
            bytes ? new(MaximumInput: 1) : new(MaximumEvents: 1)).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Budget, result.End); NoAuthority(result);
    }

    [Fact]
    public async Task MissingTerminalEofTimesOutInsteadOfTransferringSocket()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        _ = verification.Run(async client => { await client.Expect(63, 7, 0); await client.Send(new Packet(63, 7, [0, 0])); await client.Next(); });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, new(DeadlineMilliseconds: 2000)).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Timeout, result.End); Assert.Single(result.Transcript); Assert.False(formal.WasAccepted); NoAuthority(result);
    }

    [Fact]
    public async Task NonLoopbackInputIsRejectedBeforeDial()
        => await Assert.ThrowsAsync<ArgumentException>(() => LocalHandshakeHarness.RunAsync(new(IPAddress.Parse("192.0.2.1"), 1), new(IPAddress.Loopback, 1)));
    [Fact]
    public async Task FormalLegCannotConsumeVerificationSuccess()
    {
        await using var verification = new Peer(); await using var formal = new Peer(); _ = verification.Run(Verify);
        _ = formal.Run(async client => { await client.Expect(63, 7, 2); await client.Send(new Packet(63, 7, [0, 0])); await client.CloseSendAndExpectEof(); });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Protocol, result.End); Assert.Equal(2, result.ClosedLegs.Length); NoAuthority(result);
    }

    [Fact]
    public async Task HoldAfterLocalSendBeforeReceiptPreventsObservation()
    {
        await using var verification = new Peer(); await using var formal = new Peer(); using var hold = new CancellationTokenSource();
        _ = verification.Run(async client => { await client.Expect(63, 7, 0); await client.CloseSendAndExpectEof(); });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, hold: hold.Token,
            receiptFault: actual => { hold.Cancel(); return actual; }).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Held, result.End); Assert.Empty(result.Transcript);
        Assert.False(formal.WasAccepted); NoAuthority(result);
    }

    [Fact]
    public async Task PrecancellationAndPreholdDoNotCreateEitherTransport()
    {
        await using var verification = new Peer(); await using var formal = new Peer(); using var stop = new CancellationTokenSource(); stop.Cancel();
        var cancelled = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, cancellation: stop.Token);
        var held = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, hold: stop.Token);
        Assert.Equal(HarnessEnd.Cancelled, cancelled.End); Assert.Equal(HarnessEnd.Held, held.End);
        Assert.Empty(cancelled.ClosedLegs); Assert.Empty(held.ClosedLegs); NoAuthority(cancelled); NoAuthority(held);
    }

    [Theory]
    [InlineData(1)] [InlineData(4096)]
    public async Task MalformedCoalescedTailCannotEraseEarlierCompleteEvents(int readBytes)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        _ = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            await client.Raw(WireCodec.Encode(new Packet(63, 7, [0, 0])).Concat(new byte[] { 0, 0, 0, 0 }).ToArray());
            await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, new(ReadBytes: readBytes)).WaitAsync(Guard);
        Assert.Equal(HarnessEnd.TrailingData, result.End);
        Assert.IsType<LoginResultEvent>(Assert.Single(result.Transcript).Event); NoAuthority(result);
    }

    [Theory]
    [InlineData(1)] [InlineData(4096)]
    public async Task ValidHeartbeatIsRecordedAndRepliedBeforeLaterMalformedHeader(int readBytes)
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var server = verification.Run(async client =>
        {
            await client.Expect(63, 7, 0);
            await client.Raw(WireCodec.Encode(new Packet(1, 23)).Concat(new byte[] { 0, 0, 0, 0 }).ToArray());
            await client.Expect(63, 5); await client.CloseSendAndExpectEof();
        });
        var result = await LocalHandshakeHarness.RunAsync(verification.Endpoint, formal.Endpoint, new(ReadBytes: readBytes)).WaitAsync(Guard);
        await server.WaitAsync(Guard);
        Assert.Equal(HarnessEnd.Protocol, result.End);
        Assert.IsType<HeartbeatRequestEvent>(Assert.Single(result.Transcript).Event); NoAuthority(result);
    }

}
