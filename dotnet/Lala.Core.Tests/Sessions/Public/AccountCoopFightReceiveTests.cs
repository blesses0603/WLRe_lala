using System.Collections.Concurrent;
using System.Numerics;
using System.Text.Json.Nodes;
using System.Threading.Channels;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.Tests.Sessions.Receive;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    [Fact]
    public async Task PublicCoopFightBookkeepingPreservesFullStateGuardsAndUnknownsWithoutSends()
    {
        await using var verification = new Peer(); await using var formal = new Peer();
        var commands = Channel.CreateUnbounded<Packet[]>();
        var entered = Signal(); var finish = Signal();
        var bases = new ConcurrentQueue<ServiceStateSnapshot>();
        var verify = verification.Run(Verify);
        var serve = formal.Run(async client =>
        {
            await EnterWorld(client); entered.SetResult();
            await foreach (var batch in commands.Reader.ReadAllAsync())
            {
                // Real TCP framing fragmentation. Every batch ends in a heartbeat;
                // any unexpected post-battle C20-6 or other send fails Expect.
                await client.Raw(batch.Append(new Packet(1, 23)).SelectMany(packet => WireCodec.Encode(packet)).ToArray(), 3);
                await client.Expect(63, 5);
            }
            await client.WaitFor(finish.Task); await client.CloseSendAndExpectEof();
        });
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback-coop").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation, Profile(verification, formal),
            new Source((_, _) => ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "synthetic"))),
            observationInputs: (basis, now) => { bases.Enqueue(basis); return new(now); });
        var running = runtime.RunAsync();
        try
        {
            await entered.Task.WaitAsync(Guard); await WaitFor(() => runtime.Publication?.Revision == 4);
            long revision = 4;
            var room = new Packet(186, 3, new PacketWriter().U8(0).U8(1).U16(500).U8(1).U8(1).U8(1).U8(1)
                .U32(17).U8(0).U32(1).U32(2).U32(3).U32(4).Build());
            var match = new Packet(186, 2, new PacketWriter().U8(18).U8(1).U32(17).U32(72).Build());
            var started = await Observe(room, match, new(186, 15, [3]), new(11, 10, [16]), BattleStartPacket());
            Assert.Equal("combat", started.State.Instances.Coop["phase"].ScalarValue);
            Assert.Equal(true, started.State.Instances.Coop["battle_active"].ScalarValue);
            var exited = await Observe(CoopFightReceiveContextTests.Exit(17));
            var expected = CoopFightReceiveContextTests.Write(started.State.Instances.Coop)!.AsObject();
            expected["phase"] = "matched"; expected["battle_active"] = false;
            expected["status"] = "協力戰鬥已結束；後續場次與獎勵待伺服器確認";
            expected["fight_count"] = 2; expected["fight_consumed_battle"] = 1;
            expected["last_fight_victory"] = null;
            Assert.True(JsonNode.DeepEquals(expected, CoopFightReceiveContextTests.Write(exited.State.Instances.Coop)));
            Assert.Equal(started.State.Instances.Main, exited.State.Instances.Main);
            Assert.Equal(started.State.Local.Session.EventFlow, exited.State.Local.Session.EventFlow);
            Assert.Contains(bases, basis => basis.PacketCount == exited.State.PacketCount - 1 &&
                basis.Instances.Coop["fight_count"].ScalarValue is BigInteger value && value == 2);

            var duplicate = await Observe(new(11, 12, [1]), new(11, 1, [3, 1]), CoopFightReceiveContextTests.Exit(17));
            Assert.True(JsonNode.DeepEquals(expected, CoopFightReceiveContextTests.Write(duplicate.State.Instances.Coop)));
            Assert.Contains(bases, basis => ReferenceEquals(basis, exited.State));
            var changedRole = await Observe(CoopFightReceiveContextTests.World(72), CoopFightReceiveContextTests.Exit(72));
            Assert.True(JsonNode.DeepEquals(expected, CoopFightReceiveContextTests.Write(changedRole.State.Instances.Coop)));
            var resetReceipt = await Observe(new(186, 15, [5]), CoopFightReceiveContextTests.Exit(72));
            Assert.Equal((byte)5, resetReceipt.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Null(resetReceipt.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            var won = await Observe(new(11, 10, [16]), CoopFightReceiveContextTests.Start(72), new(11, 12, [1]), new(11, 1, [3, 1]));
            Assert.Equal(new BigInteger(4), won.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Equal(true, won.State.Instances.Coop["last_fight_victory"].ScalarValue);
            Assert.Equal(new BigInteger(2), won.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            Assert.True(won.State.Local.Battle.Units[0].Exited);

            var noncoop = await Observe(new(11, 10, [9]), CoopFightReceiveContextTests.Start(72), CoopFightReceiveContextTests.Exit(72));
            Assert.Equal(new BigInteger(4), noncoop.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Equal(new BigInteger(2), noncoop.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            // Source room-exit observer clears count/marker. A later coop exit records
            // this new battle with unknown victory, even when winner evidence exists.
            var unknown = await Observe(new(186, 13), new(11, 10, [16]), CoopFightReceiveContextTests.Start(72),
                new(11, 12, [1]), CoopFightReceiveContextTests.Exit(72));
            Assert.Null(unknown.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Equal(new BigInteger(4), unknown.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            Assert.Null(unknown.State.Instances.Coop["last_fight_victory"].ScalarValue);
            Assert.Equal((byte)3, started.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.True(started.State.Local.Battle.Active);
            Assert.True(runtime.Snapshot.ResourceHeld); Assert.False(runtime.Snapshot.CanSendCommands);
            Assert.True(unknown.ResourceHeld); Assert.False(unknown.State.IsCompleteState);
            Assert.False(session.ConfirmResources(generation, "same", "same", true));
            runtime.Stop(); commands.Writer.TryComplete(); finish.TrySetResult();
            Assert.True((await running.WaitAsync(Guard)).ResourcesReleased);
            await Task.WhenAll(verify, serve).WaitAsync(Guard);

            async Task<AccountReceivePublication> Observe(params Packet[] packets)
            {
                revision += packets.Length + 1;
                await commands.Writer.WriteAsync(packets);
                await WaitFor(() => runtime.Publication?.Revision == revision);
                return runtime.Publication!;
            }
        }
        finally { runtime.Stop(); commands.Writer.TryComplete(); finish.TrySetResult(); }
    }
}
