using System.Collections.Immutable;
using System.Net;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions.Transport;

namespace Lala.Core.Tests.Sessions.Loopback;

internal enum HarnessEnd { Complete, Cancelled, Held, Timeout, Protocol, Transport, Budget, TrailingData, EarlyEof }
internal sealed record HarnessObservation(HandshakeLeg Leg, ServerEvent Event);
internal sealed record HarnessResult(HarnessEnd End, HandshakeView Handshake,
    ImmutableArray<HarnessObservation> Transcript, ImmutableArray<TcpTransportView> ClosedLegs);
internal sealed record HarnessLimits(int ReadBytes = 4096, int MaximumInput = 1024 * 1024,
    int MaximumEvents = 4096, int DeadlineMilliseconds = 5000);
internal sealed class HarnessFailure(HarnessEnd end) : Exception
{
    internal HarnessEnd End { get; } = end;
}

/// <summary>TEST ONLY: real-loopback composition, fixed fake login data, no production entry point.
/// Every leg owns its reader/decoder until EOF then disposes. Nothing transfers to ReceiveAttempt.
/// An optional receipt fault injector tests the uncertainty boundary, not OS failure determinism.</summary>
internal static class LocalHandshakeHarness
{
    internal static async Task<HarnessResult> RunAsync(IPEndPoint verification, IPEndPoint formal,
        HarnessLimits? limits = null, CancellationToken cancellation = default, CancellationToken hold = default,
        Func<TcpWriteResult, TcpWriteResult>? receiptFault = null)
    {
        // Snapshot both targets before the first await; callers cannot redirect the later leg.
        verification = CopyEndpoint(verification); formal = CopyEndpoint(formal);
        // Reject before any socket creation; no arbitrary hosts or credential inputs exist.
        if (!IPAddress.IsLoopback(verification.Address) || !IPAddress.IsLoopback(formal.Address))
            throw new ArgumentException("This test harness accepts loopback only.");
        limits ??= new();
        if (limits.ReadBytes is < 1 or > 4096 || limits.MaximumInput is < 1 or > 1048576 ||
            limits.MaximumEvents is < 1 or > 4096 || limits.DeadlineMilliseconds is < 1 or > 30000)
            throw new ArgumentOutOfRangeException(nameof(limits));
        using var handshake = new ScriptedHandshake(0xAD);
        using var held = hold.UnsafeRegister(_ => handshake.Hold(), null);
        using var cancelled = cancellation.UnsafeRegister(_ => handshake.Cancel(), null);
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(cancellation, hold);
        stop.CancelAfter(limits.DeadlineMilliseconds);
        var transcript = ImmutableArray.CreateBuilder<HarnessObservation>();
        var closed = ImmutableArray.CreateBuilder<TcpTransportView>();
        int input = 0;
        HarnessEnd end;
        try
        {
            await Leg(verification, HandshakeLeg.Verification);
            await Leg(formal, HandshakeLeg.Formal);
            stop.Token.ThrowIfCancellationRequested();
            end = HarnessEnd.Complete;
        }
        catch (Exception failure) when (failure is HarnessFailure or ProtocolException or TcpTransportException or OperationCanceledException)
        {
            end = hold.IsCancellationRequested ? HarnessEnd.Held : cancellation.IsCancellationRequested ? HarnessEnd.Cancelled :
                stop.IsCancellationRequested ? HarnessEnd.Timeout : failure switch
                {
                    HarnessFailure problem => problem.End,
                    ProtocolException => HarnessEnd.Protocol,
                    _ => HarnessEnd.Transport
                };
            if (end == HarnessEnd.Held) handshake.Hold();
            else if (end == HarnessEnd.Cancelled) handshake.Cancel();
            else handshake.EndInput();
        }
        var final = handshake.Snapshot;
        if (final.Phase == HandshakePhase.Held) end = HarnessEnd.Held;
        else if (final.Phase == HandshakePhase.Cancelled) end = HarnessEnd.Cancelled;
        return new(end, final, transcript.ToImmutable(), closed.ToImmutable());

        async Task Leg(IPEndPoint endpoint, HandshakeLeg leg)
        {
            stop.Token.ThrowIfCancellationRequested();
            var transport = new BoundedTcpTransport(endpoint, new() { MaximumReadBytes = limits.ReadBytes });
            try
            {
                await transport.ConnectAsync(stop.Token);
                await Flush(handshake.BeginLogin(handshake.Snapshot.Attempt, leg,
                    CandidateCommands.Login("synthetic_user", "fake_password", leg == HandshakeLeg.Verification ? 0 : 2, 1, 2)));
                var decoder = new FrameDecoder(0xAD);
                var buffer = new byte[limits.ReadBytes];
                uint? role = null;
                bool terminal = false;
                while (true)
                {
                    stop.Token.ThrowIfCancellationRequested();
                    int count = await transport.ReadAsync(buffer, stop.Token);
                    if (count == 0)
                    {
                        decoder.Finish();
                        if (!terminal) throw new HarnessFailure(HarnessEnd.EarlyEof);
                        return;
                    }
                    input = checked(input + count);
                    if (input > limits.MaximumInput) throw new HarnessFailure(HarnessEnd.Budget);
                    // Never hand off or silently discard anything following terminal evidence.
                    if (terminal) throw new HarnessFailure(HarnessEnd.TrailingData);
                    // Feed one byte at a time so a malformed later frame cannot make the
                    // bulk decoder throw before already-complete earlier frames are consumed.
                    // The unread suffix remains in this owned read buffer across awaited writes.
                    for (int offset = 0; offset < count; offset++)
                    {
                        if (terminal) throw new HarnessFailure(HarnessEnd.TrailingData);
                        var packets = decoder.Feed(buffer.AsSpan(offset, 1));
                        foreach (var packet in packets)
                        {
                            if (terminal) throw new HarnessFailure(HarnessEnd.TrailingData);
                            if (transcript.Count >= limits.MaximumEvents) throw new HarnessFailure(HarnessEnd.Budget);
                            stop.Token.ThrowIfCancellationRequested();
                            var observation = ServerProtocol.Decode(packet, role);
                            transcript.Add(new(leg, observation));
                            if (observation is ServerLayoutEvent { Event: WorldPlayerEvent world }) role = world.Player.RoleId;
                            await Flush(handshake.Observe(handshake.Snapshot.Attempt, leg, observation));
                            EnsurePhase();
                            if (handshake.Snapshot.Phase == HandshakePhase.Selection)
                                await Flush(handshake.SelectRole(handshake.Snapshot.Attempt, 1));
                            terminal = handshake.Snapshot.Phase == (leg == HandshakeLeg.Verification
                                ? HandshakePhase.Verified : HandshakePhase.ScriptedComplete);
                        }
                    }
                    if (terminal && decoder.BufferedBytes != 0) throw new HarnessFailure(HarnessEnd.TrailingData);
                }
            }
            finally
            {
                await transport.DisposeAsync();
                closed.Add(transport.Snapshot);
            }

            async Task Flush(ScriptedHandshakeWrite? write)
            {
                while (write is not null)
                {
                    ScriptedHandshakeWrite? next;
                    using (write)
                    {
                        stop.Token.ThrowIfCancellationRequested();
                        var receipt = await transport.WriteAsync(write.Bytes, stop.Token);
                        if (receiptFault is not null) receipt = receiptFault(receipt);
                        stop.Token.ThrowIfCancellationRequested();
                        bool exact = receipt.Connection == transport.Snapshot.Connection &&
                            receipt.Outcome == TcpWriteOutcome.Complete && receipt.ConfirmedLocalBytes == write.Bytes.Length && receipt.End is null;
                        next = handshake.CompleteWrite(write.Attempt, write.Leg, write.Operation, write.Bytes,
                            exact ? ScriptedWriteOutcome.Complete : ScriptedWriteOutcome.Uncertain);
                        if (!exact) throw new HarnessFailure(HarnessEnd.Transport);
                    }
                    write = next;
                }
                EnsurePhase();
            }
        }
        void EnsurePhase()
        {
            if (handshake.Snapshot.Phase is HandshakePhase.Failed or HandshakePhase.Cancelled or HandshakePhase.Held)
                throw new HarnessFailure(HarnessEnd.Protocol);
        }
    }
    private static IPEndPoint CopyEndpoint(IPEndPoint endpoint)
    {
        ArgumentNullException.ThrowIfNull(endpoint);
        var address = endpoint.Address;
        return new(address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetworkV6
            ? new IPAddress(address.GetAddressBytes(), address.ScopeId) : new IPAddress(address.GetAddressBytes()), endpoint.Port);
    }

}
