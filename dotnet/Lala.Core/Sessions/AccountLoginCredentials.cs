using System.Security.Cryptography;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Handshake;

namespace Lala.Core.Sessions;

/// <summary>
/// Single-attempt transient ASCII credentials. Copies caller input and never persists it.
/// Dispose promptly; the connection also clears these buffers after constructing formal login
/// or when its attempt ends. Caller input remains caller-owned and must be cleared separately.
/// TCP/XOR login traffic is not encrypted and must only use a trusted network.
/// </summary>
public sealed class AccountLoginCredentials : IDisposable
{
    private readonly object gate = new();
    private readonly byte[] account, password;
    private bool disposed, transferred;
    public bool IsDisposed { get { lock (gate) return disposed; } }

    public AccountLoginCredentials(ReadOnlySpan<char> account, ReadOnlySpan<char> password)
    {
        Validate(account, nameof(account)); Validate(password, nameof(password));
        this.account = new byte[account.Length];
        try
        {
            this.password = new byte[password.Length];
            for (int i = 0; i < account.Length; i++) this.account[i] = (byte)account[i];
            for (int i = 0; i < password.Length; i++) this.password[i] = (byte)password[i];
        }
        catch
        {
            CryptographicOperations.ZeroMemory(this.account);
            if (this.password is not null) CryptographicOperations.ZeroMemory(this.password);
            throw;
        }
    }

    private static void Validate(ReadOnlySpan<char> value, string name)
    {
        if (value.Length is < 1 or > 255) throw new ArgumentException("Credentials must contain 1 to 255 ASCII characters.", name);
        foreach (char c in value)
            if (c > 127) throw new ArgumentException("Credentials must contain only ASCII characters.", name);
    }

    internal IHandshakeLoginProvider CreateProvider(byte platform, byte language)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (transferred) throw new InvalidOperationException("Credentials already belong to a connection attempt.");
            var provider = new OwnedProvider(this, platform, language);
            transferred = true;
            return provider;
        }
    }

    private LoginPacketLease CreatePacket(HandshakeLeg leg, byte platform, byte language)
    {
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            // A bounded stack buffer avoids immutable strings and heap writer copies.
            Span<byte> payload = stackalloc byte[6 + account.Length + password.Length];
            try
            {
                if (leg is not (HandshakeLeg.Verification or HandshakeLeg.Formal))
                    throw new ArgumentOutOfRangeException(nameof(leg));
                payload[0] = leg == HandshakeLeg.Verification ? (byte)0 : (byte)2;
                payload[1] = 0; payload[2] = platform; payload[3] = language;
                payload[4] = (byte)account.Length;
                account.CopyTo(payload[5..]);
                payload[5 + account.Length] = (byte)password.Length;
                password.CopyTo(payload[(6 + account.Length)..]);
                var packet = new Packet(63, 7, payload);
                try { return new LoginPacketLease(packet, ownsPayload: true); }
                catch { packet.ClearSensitivePayload(); throw; }
            }
            catch { Dispose(); throw; }
            finally
            {
                CryptographicOperations.ZeroMemory(payload);
                if (leg == HandshakeLeg.Formal) Dispose();
            }
        }
    }

    public void Dispose()
    {
        lock (gate)
        {
            CryptographicOperations.ZeroMemory(account);
            CryptographicOperations.ZeroMemory(password);
            disposed = true;
        }
    }
    public override string ToString() => "Account login credentials (redacted)";

    private sealed class OwnedProvider(AccountLoginCredentials credentials, byte platform, byte language) : IHandshakeLoginProvider
    {
        private readonly object gate = new();
        private int nextLeg;
        public LoginPacketLease Create(HandshakeLeg leg)
        {
            lock (gate)
            {
                try
                {
                    if ((nextLeg == 0 && leg != HandshakeLeg.Verification) ||
                        (nextLeg == 1 && leg != HandshakeLeg.Formal) || nextLeg > 1)
                        throw new InvalidOperationException("Unexpected credential login leg.");
                    nextLeg++;
                    return credentials.CreatePacket(leg, platform, language);
                }
                catch { credentials.Dispose(); throw; }
            }
        }
        public void Dispose() { lock (gate) { nextLeg = 2; credentials.Dispose(); } }
        public override string ToString() => "Login provider (redacted)";
    }
}
