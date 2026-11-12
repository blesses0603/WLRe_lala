using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Threading.Channels;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed partial class AccountConnectionRuntimeTests
{
    [Fact]
    public async Task PublicBattleContextSurvivesStartExitDuplicatesAndActualReconnectWithoutAuthority()
    {
        var verification = new TcpListener(IPAddress.Loopback, 0);
        var formal = new TcpListener(IPAddress.Loopback, 0);
        verification.Start(); formal.Start();
        using var deadline = new CancellationTokenSource(Guard);
        var commands = Channel.CreateUnbounded<Packet[]>();
        var enteredFirst = Signal(); var enteredSecond = Signal(); var finishSecond = Signal();
        var bases = new ConcurrentQueue<ServiceStateSnapshot>();
        var requests = new List<AccountCredentialRequest>();
        var verify = VerifyBoth(); var serve = ServeBoth();
        var session = new AccountSession(); var generation = session.Begin("synthetic", "loopback-battle").Generation;
        await using var runtime = new AccountConnectionRuntime(session, generation,
            new((IPEndPoint)verification.LocalEndpoint, (IPEndPoint)formal.LocalEndpoint, 0xAD, 0xAD, 1, 1, 2),
            new Source((request, _) =>
            {
                requests.Add(request);
                return ValueTask.FromResult<AccountLoginCredentials?>(new("synthetic", "synthetic"));
            }), new() { MaximumAttempts = 2, InitialRetryDelay = TimeSpan.FromMilliseconds(100), MaximumRetryDelay = TimeSpan.FromMilliseconds(100) },
            (basis, now) => { bases.Enqueue(basis); return new(now); });
        var running = runtime.RunAsync();
        try
        {
            await enteredFirst.Task.WaitAsync(Guard);
            await WaitFor(() => runtime.Publication?.Revision == 4);
            long revision = 4;
            var restricted = await Observe(new(11, 10, [16]), BattleStartPacket());
            Assert.Equal((byte)16, restricted.State.Local.Battle.WarStyle);
            Assert.Equal((byte)9, restricted.State.Local.Battle.Units[0].Layout.WarStyle);
            Assert.True(restricted.State.Local.Battle.Active);
            var restriction = CombatResourceActionCandidates.Food(new()
            {
                WarStyle = restricted.State.Local.Battle.WarStyle,
                Inventory = new() { Ready = true, Reliable = true }
            }, new());
            Assert.Equal("此戰鬥類型禁止使用道具", restriction.Error!.Message);
            // Ping's observation callback sees exactly the fully overlaid start snapshot.
            Assert.Contains(bases, basis => basis.PacketCount == restricted.State.PacketCount - 1 &&
                basis.Local.Battle.WarStyle == 16 && basis.Local.Battle.BattleCount == 1);

            var exited = await Observe(new(11, 10, [12]), new(11, 0, new PacketWriter().U32(17).U16(0).Build()));
            Assert.False(exited.State.Local.Battle.Active);
            Assert.Contains(bases, basis => ReferenceEquals(basis, restricted.State));
            var unknown = await Observe(BattleStartPacket());
            Assert.Null(unknown.State.Local.Battle.WarStyle); // First own exit cleared pending 12.
            Assert.Equal(2, unknown.State.Local.Battle.BattleCount);

            await Observe(new Packet(11, 1, [3, 1]));
            var duplicate = await Observe(new(11, 10, [0]), new(11, 0, new PacketWriter().U32(17).U16(0).Build()),
                new(11, 1, [3, 1]), BattleStartPacket());
            Assert.Equal((byte)0, duplicate.State.Local.Battle.WarStyle); // Duplicate exits preserve later zero announcement.
            var next = await Observe(BattleStartPacket());
            Assert.Null(next.State.Local.Battle.WarStyle); // Announcement was consumed once.
            var consumed = await Observe(new(186, 15, [3]), new(11, 10, [16]), BattleStartPacket(),
                new(11, 12, [1]), new(11, 0, new PacketWriter().U32(17).U16(0).Build()));
            Assert.Equal(new System.Numerics.BigInteger(2), consumed.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.NotNull(consumed.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            Assert.Equal(true, consumed.State.Instances.Coop["last_fight_victory"].ScalarValue);
            await Observe(new Packet(11, 10, [16])); // Unconsumed context must not cross the actual retry.
            var firstAttempt = runtime.Publication!.Attempt;
            commands.Writer.Complete();
            await enteredSecond.Task.WaitAsync(Guard);
            await WaitFor(() => runtime.Publication is { Revision: 6 } value && value.Attempt != firstAttempt);
            var reconnected = runtime.Publication!;
            Assert.Null(reconnected.State.Local.Battle.WarStyle);
            Assert.Equal(1, reconnected.State.Local.Battle.BattleCount);
            Assert.Null(reconnected.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Null(reconnected.State.Instances.Coop["fight_consumed_battle"].ScalarValue);
            Assert.Null(reconnected.State.Instances.Coop["last_fight_victory"].ScalarValue);
            Assert.Equal(new System.Numerics.BigInteger(2), consumed.State.Instances.Coop["fight_count"].ScalarValue);
            Assert.Equal((byte)9, Assert.Single(reconnected.State.Local.Battle.Units).Layout.WarStyle);
            Assert.Equal((byte)16, restricted.State.Local.Battle.WarStyle);
            Assert.True(restricted.State.Local.Battle.Active);
            Assert.False(Assert.Single(restricted.State.Local.Battle.Units).Exited);
            Assert.True(reconnected.ResourceHeld); Assert.False(reconnected.State.IsCompleteState);
            Assert.True(runtime.Snapshot.ResourceHeld); Assert.False(runtime.Snapshot.CanSendCommands);
            Assert.False(session.ConfirmResources(runtime.Snapshot.Generation, "same", "same", true));
            runtime.Stop(); finishSecond.SetResult();
            var result = await running.WaitAsync(Guard);
            Assert.True(result.ResourcesReleased);
            Assert.Equal(new[] { 1, 2 }, requests.Select(request => request.AttemptNumber));
            Assert.Equal(new[] { generation, generation + 1 }, requests.Select(request => request.Generation));
            Assert.Equal(AccountConnectionFailure.RemoteEof, result.Status.History[0].Failure);
            await Task.WhenAll(verify, serve).WaitAsync(Guard);

            async Task<AccountReceivePublication> Observe(params Packet[] packets)
            {
                revision += packets.Length + 1;
                await commands.Writer.WriteAsync(packets, deadline.Token);
                await WaitFor(() => runtime.Publication?.Revision == revision);
                return runtime.Publication!;
            }
        }
        finally
        {
            runtime.Stop(); finishSecond.TrySetResult(); commands.Writer.TryComplete();
            deadline.Cancel(); verification.Stop(); formal.Stop();
        }

        async Task VerifyBoth()
        {
            for (int i = 0; i < 2; i++)
            {
                using var socket = await verification.AcceptSocketAsync(deadline.Token);
                await Verify(new(socket, deadline.Token));
            }
        }
        async Task ServeBoth()
        {
            using (var socket = await formal.AcceptSocketAsync(deadline.Token))
            {
                var client = new Client(socket, deadline.Token);
                await EnterWorld(client); enteredFirst.SetResult();
                await foreach (var batch in commands.Reader.ReadAllAsync(deadline.Token))
                {
                    await client.Send([.. batch, new(1, 23)]);
                    await client.Expect(63, 5);
                }
                await client.CloseSendAndExpectEof();
            }
            using (var socket = await formal.AcceptSocketAsync(deadline.Token))
            {
                var client = new Client(socket, deadline.Token);
                await EnterWorld(client); await client.Send(BattleStartPacket(), new(1, 23));
                await client.Expect(63, 5); enteredSecond.SetResult();
                await client.WaitFor(finishSecond.Task); await client.CloseSendAndExpectEof();
            }
        }
    }

    private static Packet BattleStartPacket() => new(11, 250,
        new PacketWriter().U8(12).U8(3).U8(1)
            .U8(9).U8(0).U32(17).U16(2).U32(0).U8(3).U8(1).U32(100).U16(40).U32(90).U16(20)
            .U8(19).U8(2).U8(1).U8(3).U16(0).U16(0).U8(1).U8(2).U32(0).U32(0)
            .U8(0).Raw(new byte[54]).Build());
}
