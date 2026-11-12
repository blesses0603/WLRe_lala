using System.Collections.Concurrent;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions.Receive;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed partial class ReceiveAttemptTests
{
    [Fact]
    public async Task HeldFramedReceivePublishesActorsForDetachedChooserAndPreservesHistory()
    {
        var transport = new PushTransport();
        var publications = new ConcurrentDictionary<long, ReceivePublication>();
        await using var attempt = Attempt(transport, callback: value => publications[value.Revision] = value);
        var run = attempt.RunAsync();
        var packets = new[] { World, CoopFightReceiveContextTests.Start(17),
            new Packet(11, 252, new PacketWriter().U32(17).U8(0).U8(1).U16(123).U32(456).Build()),
            new Packet(11, 1, [3, 1]), CoopFightReceiveContextTests.Start(18) };
        for (var i = 0; i < packets.Length; i++)
        {
            var frame = Wire([packets[i]]);
            transport.Push(frame[..1]); transport.Push(frame[1..]);
            using var limit = new CancellationTokenSource(Timeout);
            while (!publications.ContainsKey(i + 1)) await Task.Delay(1, limit.Token);
        }
        var received = publications[3].Snapshot;
        var entries = received.Local.Battle.Actors;
        Assert.Equal(17u, entries.Single().Actor.Pid);
        Assert.Equal(new KnowledgeEquipment(123, 456), entries[0].Actor.Equips[0]);
        // Explicitly synthetic empty catalogs: defend needs no fabricated fight/Lua rows.
        var context = new BattleCommandContext { Resources = new() { Units = entries,
            LocalRoleId = received.Player!.RoleId, Player = received.PlayerKnowledge,
            Companions = received.Companions, Catalog = CombatResourceCatalog.Empty }, NormalCatalog = new([], []) };
        var choice = AutoBattleRuleChooser.Choose(context, entries[0].Actor,
            new() { LowHpEnabled = false, OrderActions = [new() { Id = 60021 }] });
        Assert.Null(choice.Error); Assert.Equal(BattleCommandKind.Defend, choice.Intent!.Kind);
        Assert.Equal(17u, choice.Intent.ActorPid); Assert.Empty(choice.Intent.Allocations);
        Assert.True(publications[4].Snapshot.Local.Battle.Actors[0].Actor.Exited);
        Assert.False(entries[0].Actor.Exited);
        Assert.Equal(18u, attempt.Latest.Snapshot.Local.Battle.Actors[0].Actor.Pid);
        await attempt.DisposeAsync(); var ended = await run.WaitAsync(Timeout);
        Assert.Equal(ReceiveStage.Ended, ended.Publication.Stage);
        Assert.Equal(18u, ended.Publication.Snapshot.Local.Battle.Actors[0].Actor.Pid);
        Assert.Equal(17u, entries[0].Actor.Pid);
        await using var fresh = Attempt(new ScriptedTransport([Wire([Ping])]));
        var next = await fresh.RunAsync().WaitAsync(Timeout);
        Assert.Empty(next.Publication.Snapshot.Local.Battle.Actors);
        Assert.NotEqual(ended.Publication.Attempt, next.Publication.Attempt);
    }

    [Fact]
    public async Task FailedHookCannotPublishNewActorOccupant()
    {
        await using var attempt = new ReceiveAttempt(new ScriptedTransport([Wire([
            CoopFightReceiveContextTests.Start(17), CoopFightReceiveContextTests.Start(18)])]),
            0xAD, () => 123, (_, now) => new(now), beforeCommit: (value, _) =>
                value is ServerLayoutEvent { Event: BattleStartEvent start } && start.Units[0].Pid == 18
                    ? ValueTask.FromException(new IOException("synthetic rejection")) : ValueTask.CompletedTask);
        var result = await attempt.RunAsync().WaitAsync(Timeout);
        Assert.Equal(ReceiveEnd.EventHandlerFailed, result.End);
        Assert.Equal(1, result.Publication.Revision);
        Assert.Equal(17u, result.Publication.Snapshot.Local.Battle.Actors.Single().Actor.Pid);
    }
}
