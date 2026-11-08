using System.Net;
using System.Net.Sockets;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Handshake;
using Lala.Core.Sessions.Receive;
using Xunit;

namespace Lala.Core.Tests.Sessions.Loopback;

public sealed class HeldConnectionOutcomeTests
{
    private static ReceiveResult Result(ReceiveEnd end, bool released = true) =>
        new(new(Guid.NewGuid(), 0, ReceiveStage.Ended, new(), end), end, released);

    [Theory]
    [InlineData((int)HeldConnectionFailure.ConnectFailed)]
    [InlineData((int)HeldConnectionFailure.ConnectTimedOut)]
    public void ProvenConnectFailuresAreEligible(int code)
    {
        Assert.True(HeldConnectionOutcome.Classify(Result(ReceiveEnd.ReadFailed), false, [(HeldConnectionFailure)code]).CanReconnect);
    }

    [Fact]
    public void EofRequiresHistoricalLoginAndEofEvidence()
    {
        Assert.False(HeldConnectionOutcome.Classify(Result(ReceiveEnd.Completed), false, [HeldConnectionFailure.RemoteEof]).CanReconnect);
        Assert.False(HeldConnectionOutcome.Classify(Result(ReceiveEnd.Completed), true, []).CanReconnect);
        Assert.True(HeldConnectionOutcome.Classify(Result(ReceiveEnd.Completed), true, [HeldConnectionFailure.RemoteEof]).CanReconnect);
        Assert.True(HeldConnectionOutcome.Classify(Result(ReceiveEnd.ReadFailed), true, [HeldConnectionFailure.ReadFailed]).CanReconnect);
    }

    [Fact]
    public void EveryUnsafeFactOverridesBothTransientEvidenceAndItsOrdering()
    {
        var safe = new[] { HeldConnectionFailure.ConnectFailed, HeldConnectionFailure.ConnectTimedOut,
            HeldConnectionFailure.RemoteEof, HeldConnectionFailure.ReadFailed };
        var terminal = Enum.GetValues<HeldConnectionFailure>().Except(safe);
        foreach (var bad in terminal)
            foreach (var good in safe)
                foreach (var end in new[] { ReceiveEnd.Completed, ReceiveEnd.ReadFailed })
                {
                    Assert.False(HeldConnectionOutcome.Classify(Result(end), true, [good, bad]).CanReconnect);
                    Assert.False(HeldConnectionOutcome.Classify(Result(end), true, [bad, good]).CanReconnect);
                }
        var uncertain = HeldConnectionOutcome.Classify(Result(ReceiveEnd.ReadFailed), true,
            [HeldConnectionFailure.ReadFailed, HeldConnectionFailure.WriteFailed, HeldConnectionFailure.WriteUncertain]);
        Assert.Equal(HeldConnectionFailure.WriteUncertain, uncertain.Failure);
    }

    [Fact]
    public void ReceiveFailuresAndCleanupNeverBecomeRetries()
    {
        foreach (var end in Enum.GetValues<ReceiveEnd>().Where(e => e is not (ReceiveEnd.Completed or ReceiveEnd.ReadFailed)))
            Assert.False(HeldConnectionOutcome.Classify(Result(end), true,
                [HeldConnectionFailure.ConnectFailed, HeldConnectionFailure.RemoteEof, HeldConnectionFailure.ReadFailed]).CanReconnect);
        Assert.False(HeldConnectionOutcome.Classify(Result(ReceiveEnd.ReadFailed, false), true,
            [HeldConnectionFailure.ConnectFailed]).CanReconnect);
    }

    private static HeldAccountConnection Attach(IPEndPoint endpoint, Func<HandshakeLeg, Packet> provider)
    {
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback").Generation;
        return Assert.IsType<HeldAccountConnection>(HeldAccountConnection.TryAttach(session, generation,
            endpoint, endpoint, 0xAD, 0xAD, 1, provider, () => 1, (_, now) => new(now)));
    }

    [Fact]
    public async Task RefusedLoopbackConnectHasTypedEvidenceAndNeverCallsProvider()
    {
        // Close the reservation before dialing, as macOS may drop bound non-listener SYNs.
        using var refused = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
        refused.Bind(new IPEndPoint(IPAddress.Loopback, 0));
        int calls = 0;
        await using var owner = Attach((IPEndPoint)refused.LocalEndPoint!, _ => { calls++; throw new Exception(); });
        refused.Dispose();
        Assert.Throws<InvalidOperationException>(() => owner.GetOutcome(Result(ReceiveEnd.ReadFailed)));
        var result = await owner.RunAsync().WaitAsync(TimeSpan.FromSeconds(20));
        var outcome = owner.GetOutcome(result);
        Assert.Equal(0, calls);
        Assert.Equal(HeldConnectionFailure.ConnectFailed, outcome.Failure);
        Assert.True(outcome.CanReconnect); Assert.False(outcome.LoginCompleted);
        Assert.Throws<InvalidOperationException>(() => owner.GetOutcome(result with { }));
    }

    [Fact]
    public async Task ProviderFailureRemainsTerminalAndRedacted()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        try
        {
            await using var owner = Attach((IPEndPoint)listener.LocalEndpoint,
                _ => throw new Exception("synthetic-secret"));
            var result = await owner.RunAsync().WaitAsync(TimeSpan.FromSeconds(20));
            var outcome = owner.GetOutcome(result);
            Assert.Equal(HeldConnectionFailure.ProviderFailed, outcome.Failure);
            Assert.False(outcome.CanReconnect); Assert.DoesNotContain("synthetic-secret", outcome.ToString());
        }
        finally { listener.Stop(); }
    }
}
