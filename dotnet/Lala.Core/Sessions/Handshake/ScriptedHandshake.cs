using System.Collections.Immutable;
using System.Security.Cryptography;
using Lala.Core.Protocol;

namespace Lala.Core.Sessions.Handshake;

internal enum HandshakeLeg { Verification, Formal }
internal enum HandshakePhase
{
    Created, VerificationWrite, VerificationReply, Verified, FormalWrite, FormalReply,
    Roles, Selection, SelectionWrite, World, MapAckWrite, AppearAckWrite,
    ScriptedComplete, Failed, Cancelled, Held
}
internal enum ScriptedWriteOutcome { Complete, Partial, Uncertain, Failed }
internal sealed record HandshakeView(Guid Attempt, HandshakePhase Phase)
{
    public bool CanSendPackets => false;
    public bool IsLive => false;
}

/// <summary>Caller-owned candidate bytes, never a transport command or credential-safe log value.
/// Dispose after the scripted write; the coordinator retains only a digest, not these bytes.</summary>
internal sealed class ScriptedHandshakeWrite : IDisposable
{
    internal Guid Attempt { get; }
    internal Guid Operation { get; } = Guid.NewGuid();
    internal HandshakeLeg Leg { get; }
    internal byte[] Bytes { get; }
    internal ScriptedHandshakeWrite(Guid attempt, HandshakeLeg leg, byte[] bytes)
        => (Attempt, Leg, Bytes) = (attempt, leg, bytes);
    public void Dispose() => CryptographicOperations.ZeroMemory(Bytes);
    public override string ToString() => "Scripted handshake write (redacted)";
}

/// <summary>
/// Internal handshake state machine. It owns no sockets, credentials in state, runtime admission,
/// Android callbacks or active-session authority. Standalone scripted receipts are assertions;
/// HeldLoginTransport supplies exact bounded-transport receipts without granting live authority.
/// Stronger than Python SessionLogic: authentication, role selection and both completed ACK
/// writes are mandatory; early initialization observations cannot grant completion.
/// All calls are serialized. Pending writes must be completed before another observation;
/// transport composition must serialize/buffer responses, not discard or reorder them.
/// </summary>
internal sealed class ScriptedHandshake : IDisposable
{
    private readonly object gate = new();
    private readonly Guid attempt = Guid.NewGuid();
    private readonly int xor;
    private HandshakePhase phase;
    private HandshakeLeg leg;
    private ImmutableArray<RoleSnapshot> roles = [];
    private bool player, initialized;
    private Guid? pending;
    private byte[]? digest;
    private int length;
    private HandshakePhase afterWrite;

    internal ScriptedHandshake(int txXor) { WireCodec.ValidateKey(txXor); xor = txXor; }
    internal HandshakeView Snapshot { get { lock (gate) return new(attempt, phase); } }
    private bool Terminal => phase is HandshakePhase.ScriptedComplete or HandshakePhase.Failed
        or HandshakePhase.Cancelled or HandshakePhase.Held;

    /// <summary>Fresh transient packet input, normally built with CandidateCommands.Login.
    /// This class never retains the packet or its credentials. Caller owns its lifetime.</summary>
    internal ScriptedHandshakeWrite? BeginLogin(Guid identity, HandshakeLeg connection, Packet packet)
    {
        lock (gate)
        {
            if (!Check(identity) || pending is not null || connection is not (HandshakeLeg.Verification or HandshakeLeg.Formal)) return Fail();
            byte kind = connection == HandshakeLeg.Verification ? (byte)0 : (byte)2;
            if ((connection == HandshakeLeg.Verification && phase != HandshakePhase.Created) ||
                (connection == HandshakeLeg.Formal && phase != HandshakePhase.Verified)) return Fail();
            if (packet is null || packet.Main != 63 || packet.Sub != 7) return Fail();
            // Validate directly over caller-owned bytes; PacketReader would copy credentials.
            var payload = packet.Payload.Span;
            if (payload.Length < 6 || payload[0] != kind || payload[1] != 0) return Fail();
            int offset = 4; // observed platform and language are already bounded bytes
            for (int i = 0; i < 2; i++)
            {
                if (offset >= payload.Length) return Fail();
                int count = payload[offset++];
                if (count == 0 || count > payload.Length - offset) return Fail();
                foreach (byte value in payload.Slice(offset, count)) if (value > 127) return Fail();
                offset += count;
            }
            if (offset != payload.Length) return Fail();
            leg = connection;
            phase = kind == 0 ? HandshakePhase.VerificationWrite : HandshakePhase.FormalWrite;
            return Issue(packet, kind == 0 ? HandshakePhase.VerificationReply : HandshakePhase.FormalReply);
        }
    }

    internal ScriptedHandshakeWrite? Observe(Guid identity, HandshakeLeg connection, ServerEvent observation)
    {
        lock (gate)
        {
            if (!Check(identity) || connection != leg || pending is not null || observation is null) return Fail();
            if (observation is HeartbeatRequestEvent && phase is not (HandshakePhase.Created or HandshakePhase.Verified))
                return Issue(new Packet(63, 5), phase);
            switch (observation)
            {
                case LoginResultEvent result:
                    if (phase == HandshakePhase.VerificationReply && result.LoginKind == 0 && result.Result == 0)
                        phase = HandshakePhase.Verified;
                    else if (phase == HandshakePhase.FormalReply && result.LoginKind == 2 && result.Result == 0)
                        phase = HandshakePhase.Roles;
                    else return Fail();
                    break;
                case ServerLayoutEvent { Event: RoleListAvailableEvent list }:
                    if (phase != HandshakePhase.Roles || list.Roles.IsDefault || list.Roles.Length > 2 ||
                        list.Roles.Any(r => r is null || r.Index is not (1 or 2)) ||
                        list.Roles.Select(r => r.Index).Distinct().Count() != list.Roles.Length) return Fail();
                    roles = list.Roles; phase = HandshakePhase.Selection;
                    break;
                case ServerLayoutEvent { Event: WorldPlayerEvent world }:
                    if (phase != HandshakePhase.World || world.Player is null) return Fail();
                    player = true;
                    break;
                case InitialDataCompleteEvent:
                    if (phase != HandshakePhase.World) return Fail();
                    initialized = true;
                    break;
                default:
                    // Other decoded observations do not advance the handshake.
                    return null;
            }
            if (phase == HandshakePhase.World && player && initialized)
            {
                phase = HandshakePhase.MapAckWrite;
                return Issue(new Packet(12, 1), HandshakePhase.AppearAckWrite);
            }
            return null;
        }
    }

    internal ScriptedHandshakeWrite? SelectRole(Guid identity, int index)
    {
        lock (gate)
        {
            if (!Check(identity) || phase != HandshakePhase.Selection || pending is not null ||
                !roles.Any(r => r.Index == index && !r.Locked)) return Fail();
            roles = []; phase = HandshakePhase.SelectionWrite;
            return Issue(CandidateCommands.SelectRole(index), HandshakePhase.World);
        }
    }

    /// <summary>Exact operation, leg, byte count and byte digest must match. A short, failed,
    /// uncertain or replayed receipt retires the attempt. No retry or replay is generated.</summary>
    internal ScriptedHandshakeWrite? CompleteWrite(Guid identity, HandshakeLeg connection, Guid operation,
        ReadOnlySpan<byte> written, ScriptedWriteOutcome outcome)
    {
        lock (gate)
        {
            if (!Check(identity) || connection != leg || pending != operation || digest is null ||
                outcome != ScriptedWriteOutcome.Complete || written.Length != length) return Fail();
            Span<byte> actualDigest = stackalloc byte[32];
            SHA256.HashData(written, actualDigest);
            bool exact = CryptographicOperations.FixedTimeEquals(actualDigest, digest);
            CryptographicOperations.ZeroMemory(actualDigest);
            if (!exact) return Fail();
            ClearPending(); phase = afterWrite;
            if (phase == HandshakePhase.AppearAckWrite) return Issue(new Packet(3, 2), HandshakePhase.ScriptedComplete);
            return null;
        }
    }

    internal void Cancel() { lock (gate) Retire(HandshakePhase.Cancelled); }
    internal void Hold() { lock (gate) Retire(HandshakePhase.Held); }
    internal void EndInput() { lock (gate) Retire(HandshakePhase.Failed); } // EOF, timeout, malformed frame or payload
    public void Dispose() => Cancel();

    private bool Check(Guid identity) => !Terminal && identity == attempt;
    private ScriptedHandshakeWrite? Fail() { Retire(HandshakePhase.Failed); return null; }
    private void Retire(HandshakePhase end)
    {
        // Cancellation/hold may revoke historical completion; no late input can resurrect it.
        if (phase is HandshakePhase.Failed or HandshakePhase.Cancelled or HandshakePhase.Held) return;
        phase = end; roles = []; player = initialized = false; ClearPending();
    }
    private void ClearPending()
    {
        pending = null; length = 0;
        if (digest is not null) CryptographicOperations.ZeroMemory(digest);
        digest = null;
    }
    private byte[] EncodeOwned(Packet packet)
    {
        // Encode directly into the disposable owned buffer, avoiding plaintext Body()/writer copies.
        int bodyLength = checked(packet.Payload.Length + 2);
        var bytes = new byte[bodyLength + 4];
        bytes[0] = 0xC4; bytes[1] = 0xC6;
        System.Buffers.Binary.BinaryPrimitives.WriteUInt16LittleEndian(bytes.AsSpan(2), checked((ushort)bodyLength));
        bytes[4] = packet.Main; bytes[5] = packet.Sub;
        packet.Payload.Span.CopyTo(bytes.AsSpan(6));
        for (int i = 0; i < bytes.Length; i++) bytes[i] ^= (byte)xor;
        return bytes;
    }
    private ScriptedHandshakeWrite Issue(Packet packet, HandshakePhase next)
    {
        var write = new ScriptedHandshakeWrite(attempt, leg, EncodeOwned(packet));
        pending = write.Operation; digest = SHA256.HashData(write.Bytes); length = write.Bytes.Length;
        afterWrite = next;
        return write;
    }
}
