using System.Net;
using System.Net.Sockets;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class AccountNpcSkillReceiveTests
{
    private static readonly TimeSpan Limit = TimeSpan.FromSeconds(10);
    private static Packet Companion()
    {
        var writer = new PacketWriter().U8(1).U16(501).U32(100).U8(2).U32(90).U16(15)
            .U16(5).U16(6).U16(7).U16(8).U16(9).U8(0).U8(100).U8(1).U16(0).U8(0);
        for (byte i = 1; i <= 5; i++) writer.U8(i).U32((uint)(i * 10));
        for (var slot = 1; slot <= 9; slot++) writer.Raw(new byte[52]);
        return new(15, 8, writer.U8(0).U8(0).U8(1).U8(0).U16(0).U8(0).U16(0).Build());
    }

    [Theory]
    [InlineData(1)]
    [InlineData(4096)]
    public async Task HeldReceiveMapsLateNpcSlotsAndWithdrawsWithoutSending(int readSize)
    {
        System.Collections.Immutable.ImmutableDictionary<uint, System.Collections.Immutable.ImmutableArray<uint>>? mapping = null;
        await using var held = await HeldReceive.Create(() => mapping, readSize);
        await held.Send(Companion());
        var early = await held.WaitRevision(1);
        Assert.Empty(early.Companions.Companions[1].Skills);
        Assert.Equal(5, early.Companions.Companions[1].Data.SkillSlots.Length);
        mapping = AccountRuntime.ProjectNpcSkills(new Dictionary<uint, CombatResourceNpc>
            { [501] = new() { Skills = [10, 0, 20, 30, 40] } });
        await held.Send(new Packet(26, 4, new PacketWriter().U32(1).Build()));
        var ready = await held.WaitRevision(2);
        Assert.Equal(4, ready.Companions.Companions[1].Skills.Count);
        Assert.Equal(3, ready.Companions.Companions[1].Skills[20].Level);
        Assert.Equal(30u, ready.Companions.Companions[1].Skills[20].Exp);
        Assert.Empty(early.Companions.Companions[1].Skills);
        mapping = null;
        await held.Send(new Packet(26, 4, new PacketWriter().U32(2).Build()));
        var withdrawn = await held.WaitRevision(3);
        Assert.Empty(withdrawn.Companions.Companions[1].Skills);
        Assert.Equal(4, ready.Companions.Companions[1].Skills.Count);
        held.AssertHeld(withdrawn);
        await held.FinishWithoutOutboundBytes();
    }

    private sealed class HeldReceive : IAsyncDisposable
    {
        private readonly TcpClient peer;
        private readonly NetworkStream peerStream;
        private readonly AccountSession session = new();
        private readonly long generation;
        private readonly ReceiveAttempt attempt;
        private readonly Task<ReceiveResult> run;

        private HeldReceive(TcpClient peer, BoundedTcpTransport transport, Func<System.Collections.Immutable.ImmutableDictionary<uint, System.Collections.Immutable.ImmutableArray<uint>>?> catalog, int readSize)
        {
            this.peer = peer;
            peerStream = peer.GetStream();
            generation = session.Begin("synthetic", "loopback-npc-skills").Generation;
            attempt = Assert.IsType<ReceiveAttempt>(session.AttachHeldReceive(generation, transport, 0xAD,
                () => 123, (_, now) => new(now) { NpcSkills = catalog(), ReconcileNpcSkills = true, ResourceHeld = false }, readSize));
            run = attempt.RunAsync();
        }

        internal static async Task<HeldReceive> Create(Func<System.Collections.Immutable.ImmutableDictionary<uint, System.Collections.Immutable.ImmutableArray<uint>>?> catalog, int readSize = 4096)
        {
            using var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            var transport = new BoundedTcpTransport((IPEndPoint)listener.LocalEndpoint);
            try
            {
                await transport.ConnectAsync().WaitAsync(Limit);
                var peer = await listener.AcceptTcpClientAsync().WaitAsync(Limit);
                try { return new(peer, transport, catalog, readSize); }
                catch { peer.Dispose(); throw; }
            }
            catch { await transport.DisposeAsync(); throw; }
        }

        internal ServiceStateSnapshot Snapshot => attempt.Latest.Snapshot;
        internal async Task Send(params Packet[] packets) => await peerStream.WriteAsync(
            packets.SelectMany(packet => WireCodec.Encode(packet, 0xAD)).ToArray()).AsTask().WaitAsync(Limit);

        internal async Task<ServiceStateSnapshot> WaitRevision(long revision)
        {
            using var deadline = new CancellationTokenSource(Limit);
            while (attempt.Latest.Revision < revision)
            {
                Assert.False(run.IsCompleted, $"Receive ended at revision {attempt.Latest.Revision}: {attempt.Latest.End}");
                await Task.Delay(1, deadline.Token);
            }
            Assert.Equal(revision, attempt.Latest.Revision);
            return Snapshot;
        }

        internal void AssertHeld(ServiceStateSnapshot snapshot)
        {
            Assert.Equal(SessionPhase.Held, session.Snapshot.Phase);
            Assert.Null(session.Snapshot.ResourceVersion);
            Assert.True(attempt.Latest.ResourceHeld);
            Assert.True(snapshot.Observation!.Inputs.ResourceHeld);
            Assert.False(snapshot.IsCompleteState);
            Assert.False(snapshot.PlayerKnowledge.Ready);
            Assert.Empty(snapshot.PlayerKnowledge.Skills);
            Assert.False(session.ConfirmResources(generation, "v", "v", true));
            Assert.False(session.AllowsResourceGate(generation, "walk"));
            Assert.NotNull(session.ReadHeldReceive(generation, attempt.Latest.Attempt));
        }

        internal async Task FinishWithoutOutboundBytes()
        {
            peer.Client.Shutdown(SocketShutdown.Send);
            var result = await run.WaitAsync(Limit);
            Assert.Equal(ReceiveEnd.Completed, result.End);
            Assert.True(result.ResourcesReleased); // Transport cleanup, not resource-gate release.
            AssertHeld(result.Publication.Snapshot);
            Assert.Equal(0, await peerStream.ReadAsync(new byte[1]).AsTask().WaitAsync(Limit));
        }

        public async ValueTask DisposeAsync()
        {
            session.Disconnect();
            try { await attempt.DisposeAsync().AsTask().WaitAsync(Limit); }
            finally { peer.Dispose(); }
        }
    }
}
