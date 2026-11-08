using System.Collections.Concurrent;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    [Fact]
    public async Task CoopBookkeepingPublicationAndNextInputsShareExactFullState()
    {
        var transport = new PushTransport();
        var publications = new ConcurrentDictionary<long, ReceivePublication>();
        var bases = new ConcurrentDictionary<long, ServiceStateSnapshot>();
        await using var attempt = Attempt(transport, callback: value => publications[value.Revision] = value,
            inputs: (basis, now) => { bases[(long)basis.PacketCount] = basis; return new(now); });
        var run = attempt.RunAsync();
        var packets = new Packet[] { World, new(186, 15, [3]), new(11, 10, [16]),
            CoopFightReceiveContextTests.Start(17), new(11, 12, [1]), CoopFightReceiveContextTests.Exit(17), Ping,
            new(11, 1, [3, 1]), CoopFightReceiveContextTests.World(72), CoopFightReceiveContextTests.Exit(72), Ping };
        for (int i = 0; i < packets.Length; i++)
        {
            transport.Push(Wire([packets[i]]));
            using var limit = new CancellationTokenSource(Timeout);
            while (!publications.ContainsKey(i + 1)) await Task.Delay(1, limit.Token);
            Assert.Same(attempt.Latest.Snapshot, publications[i + 1].Snapshot);
        }
        Assert.Same(publications[6].Snapshot, bases[6]);
        Assert.Equal(new BigInteger(2), bases[6].Instances.Coop["fight_count"].ScalarValue);
        Assert.Equal(true, bases[6].Instances.Coop["last_fight_victory"].ScalarValue);
        Assert.Equal(new BigInteger(1), bases[6].Instances.Coop["fight_consumed_battle"].ScalarValue);
        Assert.Equal((byte)3, publications[5].Snapshot.Instances.Coop["fight_count"].ScalarValue);
        Assert.Null(publications[5].Snapshot.Instances.Coop["fight_consumed_battle"].ScalarValue);
        Assert.Equal(publications[5].Snapshot.Local.Session.EventFlow, publications[6].Snapshot.Local.Session.EventFlow);
        Equivalent(publications[6].Snapshot.Instances, publications[11].Snapshot.Instances);
        Assert.True(publications[11].Snapshot.Observation!.Inputs.ResourceHeld);
        Assert.False(publications[11].Snapshot.IsCompleteState);
        await attempt.DisposeAsync(); await run.WaitAsync(Timeout);
    }

    [Theory]
    [InlineData(false)] [InlineData(true)]
    public async Task RejectedOwnExitDoesNotPublishPartialConsumption(bool failHook)
    {
        var packets = new Packet[] { World, new(186, 15, [3]), new(11, 10, [16]),
            CoopFightReceiveContextTests.Start(17), new(11, 12, [1]),
            failHook ? CoopFightReceiveContextTests.Exit(17) : new(11, 0, [17]) };
        await using var attempt = new ReceiveAttempt(new ScriptedTransport([Wire(packets)]), 0xAD, () => 123,
            (_, now) => new(now), beforeCommit: (value, _) => failHook && value is FightExitEvent
                ? ValueTask.FromException(new IOException("synthetic rejected exit hook")) : ValueTask.CompletedTask);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(failHook ? ReceiveEnd.EventHandlerFailed : ReceiveEnd.InvalidPayload, result.End);
        Assert.Equal(5, result.Publication.Revision); Assert.Equal(5, result.Publication.Snapshot.PacketCount);
        var coop = result.Publication.Snapshot.Instances.Coop;
        Assert.Equal((byte)3, coop["fight_count"].ScalarValue);
        Assert.Null(coop["fight_consumed_battle"].ScalarValue); Assert.Null(coop["last_fight_victory"].ScalarValue);
    }

    [Fact]
    public async Task FreshAttemptRetainsImportedConsumedMarkerWithoutReusingPrivateExitKey()
    {
        await using var first = Attempt(new ScriptedTransport([Wire([World, new(186, 15, [3]), new(11, 10, [16]),
            CoopFightReceiveContextTests.Start(17), new(11, 12, [1]), CoopFightReceiveContextTests.Exit(17)])]));
        var old = await first.RunAsync().WaitAsync(Timeout);
        await using var second = Attempt(new ScriptedTransport([Wire([CoopFightReceiveContextTests.Exit(17)])]),
            initial: old.Publication.Snapshot);
        var next = await second.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.Completed, next.End);
        Assert.NotEqual(old.Publication.Attempt, next.Publication.Attempt);
        Assert.Equal(new BigInteger(2), next.Publication.Snapshot.Instances.Coop["fight_count"].ScalarValue);
        Assert.Equal(true, next.Publication.Snapshot.Instances.Coop["last_fight_victory"].ScalarValue);
        Equivalent(old.Publication.Snapshot.Instances, next.Publication.Snapshot.Instances);
    }
}
