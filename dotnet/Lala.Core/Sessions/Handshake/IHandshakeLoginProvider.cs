using Lala.Core.Protocol;

namespace Lala.Core.Sessions.Handshake;

internal interface IHandshakeLoginProvider : IDisposable
{
    LoginPacketLease Create(HandshakeLeg leg);
}

/// <summary>Only privately constructed credential packets grant clearing ownership.</summary>
internal sealed class LoginPacketLease(Packet packet, bool ownsPayload = false) : IDisposable
{
    internal Packet Packet { get; } = packet;
    public void Dispose() { if (ownsPayload) Packet.ClearSensitivePayload(); }
    public override string ToString() => "Login packet lease (redacted)";
}

/// <summary>Legacy callers retain ownership of their packets; never clear caller buffers.</summary>
internal sealed class DelegateHandshakeLoginProvider(Func<HandshakeLeg, Packet> provider) : IHandshakeLoginProvider
{
    private Func<HandshakeLeg, Packet>? callback = provider;
    public LoginPacketLease Create(HandshakeLeg leg)
        => new((callback ?? throw new ObjectDisposedException(nameof(DelegateHandshakeLoginProvider)))(leg));
    public void Dispose() => callback = null;
}
