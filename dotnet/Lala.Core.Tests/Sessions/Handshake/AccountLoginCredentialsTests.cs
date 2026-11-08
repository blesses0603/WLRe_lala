using System.Net;
using System.Reflection;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Handshake;
using Xunit;

namespace Lala.Core.Tests.Sessions.Handshake;

public sealed class AccountLoginCredentialsTests
{
    private static byte[] Buffer(AccountLoginCredentials value, string name) =>
        (byte[])typeof(AccountLoginCredentials).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(value)!;
    private static void Cleared(ReadOnlyMemory<byte> bytes) => Assert.All(bytes.ToArray(), b => Assert.Equal(0, b));

    [Theory]
    [InlineData("", "synthetic")]
    [InlineData("synthetic", "")]
    [InlineData("非ASCII", "synthetic")]
    [InlineData("synthetic", "é")]
    public void RejectsInvalidWithoutEchoingInputs(string account, string password)
    {
        var error = Assert.Throws<ArgumentException>(() => new AccountLoginCredentials(account, password));
        Assert.DoesNotContain("synthetic", error.ToString());
        Assert.DoesNotContain("非ASCII", error.ToString());
    }

    [Fact]
    public void BoundsBothFieldsAndAcceptsAsciiBoundary()
    {
        Assert.Throws<ArgumentException>(() => new AccountLoginCredentials(new string('a', 256), "x"));
        Assert.Throws<ArgumentException>(() => new AccountLoginCredentials("x", new string('p', 256)));
        using var credentials = new AccountLoginCredentials(new string('\x7f', 255), new string('p', 255));
        using var provider = credentials.CreateProvider(255, 255);
        using var lease = provider.Create(HandshakeLeg.Verification);
        Assert.Equal(516, lease.Packet.Payload.Length);
    }

    [Fact]
    public void OwnsCopiesRedactsAndClearsOriginalsAfterFormalPacket()
    {
        char[] account = "synthetic_user".ToCharArray(), password = "fake_password".ToCharArray();
        using var credentials = new AccountLoginCredentials(account, password);
        var accountBuffer = Buffer(credentials, "account"); var passwordBuffer = Buffer(credentials, "password");
        Array.Fill(account, 'z'); Array.Fill(password, 'z');
        using var provider = credentials.CreateProvider(1, 2);
        using var verification = provider.Create(HandshakeLeg.Verification);
        Assert.Equal(CandidateCommands.Login("synthetic_user", "fake_password", 0, 1, 2).Payload.ToArray(), verification.Packet.Payload.ToArray());
        Assert.False(credentials.IsDisposed);
        verification.Dispose(); Cleared(verification.Packet.Payload);
        using var formal = provider.Create(HandshakeLeg.Formal);
        Assert.Equal(CandidateCommands.Login("synthetic_user", "fake_password", 2, 1, 2).Payload.ToArray(), formal.Packet.Payload.ToArray());
        Assert.True(credentials.IsDisposed); Cleared(accountBuffer); Cleared(passwordBuffer);
        Assert.Contains("redacted", credentials.ToString());
        Assert.DoesNotContain("synthetic_user", credentials.ToString());
        formal.Dispose(); Cleared(formal.Packet.Payload);
        Assert.Throws<InvalidOperationException>(() => provider.Create(HandshakeLeg.Formal));
    }

    [Fact]
    public void DisposeIsIdempotentAndNeverChangesCallerInput()
    {
        char[] account = ['a'], password = ['p'];
        var credentials = new AccountLoginCredentials(account, password);
        var owned = Buffer(credentials, "password");
        credentials.Dispose(); credentials.Dispose();
        Cleared(owned); Assert.Equal('p', password[0]); Assert.Equal('a', account[0]);
        Assert.Throws<ObjectDisposedException>(() => credentials.CreateProvider(1, 2));
    }

    [Fact]
    public void ProviderIsExclusiveAndUnexpectedLegClearsCredentials()
    {
        using var credentials = new AccountLoginCredentials("synthetic", "fake");
        using var provider = credentials.CreateProvider(1, 2);
        Assert.Throws<InvalidOperationException>(() => credentials.CreateProvider(1, 2));
        Assert.Throws<InvalidOperationException>(() => provider.Create(HandshakeLeg.Formal));
        Assert.True(credentials.IsDisposed); Cleared(Buffer(credentials, "password"));
    }

    [Fact]
    public void RepeatedVerificationFailsClosed()
    {
        using var credentials = new AccountLoginCredentials("synthetic", "fake");
        using var provider = credentials.CreateProvider(1, 2);
        using var lease = provider.Create(HandshakeLeg.Verification);
        Assert.Throws<InvalidOperationException>(() => provider.Create(HandshakeLeg.Verification));
        Assert.True(credentials.IsDisposed);
    }

    [Fact]
    public void LegacyLeaseNeverClearsCallerPacket()
    {
        var packet = CandidateCommands.Login("synthetic", "fake", 0, 1, 2);
        var original = packet.Payload.ToArray();
        using (var provider = new DelegateHandshakeLoginProvider(_ => packet))
        using (var lease = provider.Create(HandshakeLeg.Verification)) Assert.Same(packet, lease.Packet);
        Assert.Equal(original, packet.Payload.ToArray());
    }

    [Fact]
    public void EncodedWriteSurvivesPacketLeaseAndThenClears()
    {
        using var credentials = new AccountLoginCredentials("synthetic", "fake");
        using var provider = credentials.CreateProvider(1, 2);
        using var handshake = new ScriptedHandshake(0xAD);
        var lease = provider.Create(HandshakeLeg.Verification);
        using var write = handshake.BeginLogin(handshake.Snapshot.Attempt, HandshakeLeg.Verification, lease.Packet);
        Assert.NotNull(write); lease.Dispose(); Cleared(lease.Packet.Payload);
        Assert.Equal(WireCodec.Encode(CandidateCommands.Login("synthetic", "fake", 0, 1, 2)), write.Bytes);
        write.Dispose(); Cleared(write.Bytes);
    }

    [Fact]
    public async Task UnstartedTransportDisposalClearsOwnedCredentials()
    {
        using var credentials = new AccountLoginCredentials("synthetic", "fake");
        var provider = credentials.CreateProvider(1, 2);
        var transport = new HeldLoginTransport(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1),
            0xAD, 0xAD, 1, null, ownedProvider: provider);
        await transport.DisposeAsync();
        Assert.True(credentials.IsDisposed); Cleared(Buffer(credentials, "account")); Cleared(Buffer(credentials, "password"));
    }

    [Fact]
    public async Task AlreadyCancelledReadClearsOwnedCredentials()
    {
        using var credentials = new AccountLoginCredentials("synthetic", "fake");
        await using var transport = new HeldLoginTransport(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1),
            0xAD, 0xAD, 1, null, ownedProvider: credentials.CreateProvider(1, 2));
        using var stop = new CancellationTokenSource(); stop.Cancel();
        await Assert.ThrowsAsync<HeldLoginException>(async () => await transport.ReadAsync(new byte[1], stop.Token));
        Assert.True(credentials.IsDisposed); Cleared(Buffer(credentials, "password"));
    }

    private sealed class ThrowingDisposeProvider : IHandshakeLoginProvider
    {
        public int DisposeCalls { get; private set; }
        public LoginPacketLease Create(HandshakeLeg leg) => throw new InvalidOperationException("Unexpected provider call.");
        public void Dispose()
        {
            DisposeCalls++;
            throw new InvalidOperationException("synthetic-private-cleanup-error");
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ProviderCleanupFailureRemainsStickyAfterInitializationOrIdleDisposal(bool initialize)
    {
        var provider = new ThrowingDisposeProvider();
        var transport = new HeldLoginTransport(new(IPAddress.Loopback, 1), new(IPAddress.Loopback, 1),
            0xAD, 0xAD, 1, null, ownedProvider: provider);
        if (initialize)
        {
            using var stop = new CancellationTokenSource(); stop.Cancel();
            await Assert.ThrowsAsync<HeldLoginException>(async () => await transport.ReadAsync(new byte[1], stop.Token));
            Assert.Equal(1, provider.DisposeCalls);
        }
        var first = transport.DisposeAsync().AsTask();
        var error = await Assert.ThrowsAsync<HeldLoginCleanupException>(() => first);
        Assert.DoesNotContain("synthetic-private", error.ToString());
        var second = transport.DisposeAsync().AsTask();
        Assert.Same(first, second);
        await Assert.ThrowsAsync<HeldLoginCleanupException>(() => second);
        Assert.Equal(1, provider.DisposeCalls);
    }

}
