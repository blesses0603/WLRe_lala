using System.Collections.Concurrent;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    [Fact]
    public async Task OverlayPublicationAndNextObservationUseTheExactSameImmutableBasis()
    {
        var transport = new PushTransport();
        var publications = new ConcurrentDictionary<long, ReceivePublication>();
        var bases = new ConcurrentDictionary<long, ServiceStateSnapshot>();
        await using var attempt = Attempt(transport, callback: value => publications[value.Revision] = value,
            inputs: (basis, now) => { bases[(long)basis.PacketCount] = basis; return new(now); });
        var run = attempt.RunAsync();
        var packets = new Packet[] { new(11, 10, [16]), new(11, 250, [12, 3, 0]), Ping, new(11, 250, [12, 3, 0]) };
        for (int i = 0; i < packets.Length; i++)
        {
            transport.Push(Wire([packets[i]]));
            using var limit = new CancellationTokenSource(Timeout);
            while (!publications.ContainsKey(i + 1)) await Task.Delay(1, limit.Token);
            Assert.Same(attempt.Latest.Snapshot, publications[i + 1].Snapshot);
        }
        Assert.Same(publications[2].Snapshot, bases[2]);
        Assert.Equal((byte)16, bases[2].Local.Battle.WarStyle);
        Assert.Equal((byte)16, publications[3].Snapshot.Local.Battle.WarStyle);
        Assert.Null(publications[4].Snapshot.Local.Battle.WarStyle);
        Assert.Equal((byte)16, publications[2].Snapshot.Local.Battle.WarStyle);
        Assert.Equal(1, publications[2].Snapshot.Local.Battle.BattleCount);
        await attempt.DisposeAsync(); await run.WaitAsync(Timeout);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task InvalidPayloadOrFailedHookNeverPublishesPartialBattleStart(bool failHook)
    {
        var packets = new Packet[] { new(11, 10, [16]), failHook ? new(11, 250, [12, 3, 0]) : new(11, 250, [12, 3, 1]) };
        await using var attempt = new ReceiveAttempt(new ScriptedTransport([Wire(packets)]), 0xAD, () => 123,
            (_, now) => new(now), beforeCommit: (value, _) =>
                failHook && value is ServerLayoutEvent { Event: BattleStartEvent }
                    ? ValueTask.FromException(new IOException("synthetic rejected hook")) : ValueTask.CompletedTask);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(failHook ? ReceiveEnd.EventHandlerFailed : ReceiveEnd.InvalidPayload, result.End);
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(1, result.Publication.Snapshot.PacketCount);
        Assert.Equal(0, result.Publication.Snapshot.Local.Battle.BattleCount);
        Assert.Equal((byte)16, result.Publication.Snapshot.Local.Battle.WarStyle);
    }

    [Fact]
    public async Task FreshAttemptCannotRecoverAnUnconsumedAnnouncementFromImportedSnapshot()
    {
        await using var first = Attempt(new ScriptedTransport([Wire([new(11, 10, [16])])]));
        var old = await first.RunAsync().WaitAsync(Timeout);
        await using var second = Attempt(new ScriptedTransport([Wire([new(11, 250, [12, 3, 0])])]),
            initial: old.Publication.Snapshot);
        var next = await second.RunAsync().WaitAsync(Timeout);
        Assert.NotEqual(old.Publication.Attempt, next.Publication.Attempt);
        Assert.Null(next.Publication.Snapshot.Local.Battle.WarStyle);
        Assert.Equal((byte)16, old.Publication.Snapshot.Local.Battle.WarStyle);
    }
}
