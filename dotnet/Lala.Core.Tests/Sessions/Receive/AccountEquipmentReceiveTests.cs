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

public sealed class AccountEquipmentReceiveTests
{
    private static readonly TimeSpan Limit = TimeSpan.FromSeconds(10);

    // These internal synthetic details test only the projection/receive composition.
    // No caller-supplied fingerprint, official resource bytes, or source-admission bypass.
    private static CombatKnowledgeCatalog Catalog(params (ushort Id, byte? Fit)[] rows) =>
        Assert.IsType<CombatKnowledgeCatalog>(AccountRuntime.ProjectKnowledgeCatalog(rows.ToDictionary(
            row => row.Id, row => new ItemDataRow(row.Id, "synthetic", 0, 0, 0, 0, 0,
                row.Fit is { } fit ? new ReviewedItemDetails { FitType = fit } : null)), null));

    private static byte[] Equipment(ushort id) => new PacketWriter().U16(id).U8(4).U8(2).U32(999)
        .U16(3).Raw(new byte[16]).U8(1).U8(2).U16(3).U8(4).U16(5).U32(6)
        .U8(7).U16(8).Raw(new byte[9]).U8(1).U8(9).U8(10).Build();
    private static Packet PlayerEquipment(params ushort[] ids) =>
        new(23, 11, ids.SelectMany(Equipment).ToArray());
    private static Packet CompanionEquipment()
    {
        var writer = new PacketWriter().U8(1).U16(501).U32(100).U8(2).U32(90).U16(15)
            .U16(5).U16(6).U16(7).U16(8).U16(9).U8(0).U8(100).U8(1).U16(0)
            .U8(0).Raw(new byte[25]); // Empty name and five raw skill slots.
        for (var slot = 1; slot <= 9; slot++) writer.Raw(Equipment(slot == 3 ? (ushort)42 : slot == 7 ? (ushort)44 : (ushort)0));
        return new(15, 8, writer.U8(0).U8(0).U8(1).U8(0).U16(0).U8(0).U16(0).Build());
    }
    private static Packet Damage(byte npc, byte slot, uint damage) => new(23, 140,
        new PacketWriter().U8(1).U8(npc == 0 ? 2 : 3).U8(slot).U32(damage).U8(npc).Build());
    private static Packet Broken(byte npc, ushort id) => new(23, 35, new PacketWriter().U8(npc).U16(id).Build());

    [Theory]
    [InlineData(1)]
    [InlineData(4096)]
    public async Task ReviewedFitsReachHeldS23AndS15DamageAndBrokenObservationsWithoutSending(int readSize)
    {
        var catalog = Catalog((42, 3), (44, 11), (45, 0), (99, 3), (100, 11));
        await using var held = await HeldReceive.Create(() => catalog, readSize);
        await held.Send(PlayerEquipment(42, 44, 45), CompanionEquipment());
        var initial = await held.WaitRevision(2);
        var player = initial.PlayerKnowledge.Equipment;
        Assert.Equal((ushort)42, player.Equips!.Value[2].ItemId);
        Assert.Equal((ushort)44, player.Equips.Value[6].ItemId);
        Assert.DoesNotContain(player.Equips.Value, item => item.ItemId == 45);
        Assert.Empty(player.UnresolvedEquips!.Value);
        Assert.False(player.EquipmentNeedsSnapshot);
        Assert.Equal((ushort)42, initial.Companions.Companions[1].Data.Equips[2].ItemId);
        Assert.Equal((ushort)44, initial.Companions.Companions[1].Data.Equips[6].ItemId);
        Assert.Null(initial.Companions.Companions[1].EquipmentOverrides);

        await held.Send(new(23, 27, [3, 17]), new(23, 28, [1, 3, 18]),
            Damage(0, 7, uint.MaxValue), Damage(1, 7, uint.MaxValue - 1));
        var damaged = await held.WaitRevision(6);
        Assert.Equal(17u, damaged.PlayerKnowledge.Equipment.Equips!.Value[2].Damage);
        Assert.Equal(uint.MaxValue, damaged.PlayerKnowledge.Equipment.Equips.Value[6].Damage);
        Assert.Equal(18u, damaged.Companions.Companions[1].EquipmentOverrides!.Value[2].Damage);
        Assert.Equal(uint.MaxValue - 1, damaged.Companions.Companions[1].EquipmentOverrides!.Value[6].Damage);

        // S23-35 omits a slot, so both player and companion breaks need the projected fit.
        await held.Send(Broken(0, 99), Broken(1, 100));
        var broken = await held.WaitRevision(8);
        var playerBroken = broken.PlayerKnowledge.Equipment.Equips!.Value[2];
        var companionBroken = broken.Companions.Companions[1].EquipmentOverrides!.Value[6];
        Assert.Equal((ushort)99, playerBroken.ItemId);
        Assert.Equal((ushort)100, companionBroken.ItemId);
        Assert.Equal(250u, playerBroken.Damage);
        Assert.Equal(250u, companionBroken.Damage);
        Assert.Equal((ushort)42, playerBroken.OriginalRecord!.ItemId);
        Assert.Equal((ushort)44, companionBroken.OriginalRecord!.ItemId);
        Assert.Equal(999u, playerBroken.OriginalRecord.Serial);
        Assert.Equal(6u, companionBroken.DesignId);
        Assert.Equal(4u, player.Equips.Value[2].Damage);
        Assert.Equal(4u, player.Equips.Value[6].Damage);
        Assert.Null(initial.Companions.Companions[1].EquipmentOverrides);
        Assert.Equal(18u, damaged.Companions.Companions[1].EquipmentOverrides!.Value[2].Damage);

        await held.Send(CompanionEquipment());
        var replaced = await held.WaitRevision(9);
        Assert.Null(replaced.Companions.Companions[1].EquipmentOverrides);
        Assert.Equal((ushort)44, replaced.Companions.Companions[1].Data.Equips[6].ItemId);
        Assert.Equal((ushort)100, companionBroken.ItemId);
        held.AssertHeld(replaced);
        await held.FinishWithoutOutboundBytes();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task RevokedOrEmptyObservationMappingDoesNotReuseEarlierFits(bool explicitEmpty)
    {
        CombatKnowledgeCatalog? catalog = Catalog((42, 3), (99, 3));
        await using var held = await HeldReceive.Create(() => Volatile.Read(ref catalog));
        await held.Send(PlayerEquipment(42));
        var known = await held.WaitRevision(1);
        Assert.Equal((ushort)42, known.PlayerKnowledge.Equipment.Equips!.Value[2].ItemId);

        Volatile.Write(ref catalog, explicitEmpty ? CombatKnowledgeCatalog.Empty : null);
        await held.Send(PlayerEquipment(42), new(23, 27, [3, 17]), Broken(0, 99), new(26, 4, [1, 0, 0, 0]));
        var unknown = await held.WaitRevision(5);
        var equipment = unknown.PlayerKnowledge.Equipment;
        Assert.Equal((ushort)42, Assert.Single(equipment.UnresolvedEquips!.Value).ItemId);
        Assert.Equal(2, equipment.DeferredEquipUpdates!.Value.Length);
        Assert.All(equipment.Equips!.Value, item => Assert.Equal((ushort)0, item.ItemId));
        Assert.False(equipment.EquipmentNeedsSnapshot);
        Assert.Same(catalog, unknown.Observation!.Inputs.KnowledgeCatalog);
        Assert.Equal((ushort)42, known.PlayerKnowledge.Equipment.Equips.Value[2].ItemId);
        Assert.Equal(4u, known.PlayerKnowledge.Equipment.Equips.Value[2].Damage);
        held.AssertHeld(unknown);
        await held.FinishWithoutOutboundBytes();
    }

    [Fact]
    public async Task LateFitsResolveInitialEquipmentAndReplayDamageAndIndexlessBreakOnNextPacket()
    {
        CombatKnowledgeCatalog? catalog = null;
        await using var held = await HeldReceive.Create(() => Volatile.Read(ref catalog));
        await held.Send(PlayerEquipment(42, 44), new(23, 27, [3, 17]), Broken(0, 100), Damage(0, 7, 31));
        var pending = await held.WaitRevision(4);
        var initial = pending.PlayerKnowledge.Equipment;
        Assert.Equal(2, initial.UnresolvedEquips!.Value.Length);
        Assert.Equal(3, initial.DeferredEquipUpdates!.Value.Length);
        Assert.All(initial.Equips!.Value, item => Assert.Equal((ushort)0, item.ItemId));

        Volatile.Write(ref catalog, Catalog((42, 3), (44, 11), (100, 11)));
        Assert.Same(pending, held.Snapshot);
        await held.Send(new Packet(26, 4, [1, 0, 0, 0]));
        var resolved = await held.WaitRevision(5);
        var current = resolved.PlayerKnowledge.Equipment;
        Assert.Empty(current.UnresolvedEquips!.Value);
        Assert.Null(current.DeferredEquipUpdates);
        Assert.Equal((ushort)42, current.Equips!.Value[2].ItemId);
        Assert.Equal(17u, current.Equips.Value[2].Damage);
        Assert.Equal((ushort)100, current.Equips.Value[6].ItemId);
        Assert.Equal(31u, current.Equips.Value[6].Damage); // Damage follows the queued break.
        Assert.Equal((ushort)44, current.Equips.Value[6].OriginalRecord!.ItemId);
        Assert.Equal((byte)4, current.Equips.Value[6].OriginalRecord!.Damage);
        Assert.Equal(2, initial.UnresolvedEquips.Value.Length);
        Assert.Equal(3, initial.DeferredEquipUpdates.Value.Length);
        Assert.All(initial.Equips.Value, item => Assert.Equal((ushort)0, item.ItemId));
        held.AssertHeld(resolved);
        await held.FinishWithoutOutboundBytes();
    }

    [Fact]
    public async Task UnreviewedRowsStayPendingUntilAnObservationSuppliesReviewedFits()
    {
        CombatKnowledgeCatalog? catalog = Catalog((42, 3), (45, null));
        await using var held = await HeldReceive.Create(() => Volatile.Read(ref catalog));
        await held.Send(PlayerEquipment(42, 45), new(23, 27, [3, 17]));
        var pending = await held.WaitRevision(2);
        Assert.Equal((ushort)45, Assert.Single(pending.PlayerKnowledge.Equipment.UnresolvedEquips!.Value).ItemId);
        Assert.Single(pending.PlayerKnowledge.Equipment.DeferredEquipUpdates!.Value);
        Assert.Equal(4u, pending.PlayerKnowledge.Equipment.Equips!.Value[2].Damage);

        Volatile.Write(ref catalog, Catalog((42, 3), (45, 0)));
        Assert.Same(pending, held.Snapshot); // Catalog selection is not a receive observation.
        await held.Send(new Packet(26, 4, [1, 0, 0, 0]));
        var resolved = await held.WaitRevision(3);
        Assert.Empty(resolved.PlayerKnowledge.Equipment.UnresolvedEquips!.Value);
        Assert.Null(resolved.PlayerKnowledge.Equipment.DeferredEquipUpdates);
        Assert.Equal(17u, resolved.PlayerKnowledge.Equipment.Equips!.Value[2].Damage);
        Assert.DoesNotContain(resolved.PlayerKnowledge.Equipment.Equips.Value, item => item.ItemId == 45);
        Assert.Single(pending.PlayerKnowledge.Equipment.UnresolvedEquips.Value);
        Assert.Equal(4u, pending.PlayerKnowledge.Equipment.Equips.Value[2].Damage);
        held.AssertHeld(resolved);
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

        private HeldReceive(TcpClient peer, BoundedTcpTransport transport, Func<CombatKnowledgeCatalog?> catalog, int readSize)
        {
            this.peer = peer;
            peerStream = peer.GetStream();
            generation = session.Begin("synthetic", "loopback-equipment").Generation;
            attempt = Assert.IsType<ReceiveAttempt>(session.AttachHeldReceive(generation, transport, 0xAD,
                () => 123, (_, now) => new(now) { KnowledgeCatalog = catalog(), ResourceHeld = false }, readSize));
            run = attempt.RunAsync();
        }

        internal static async Task<HeldReceive> Create(Func<CombatKnowledgeCatalog?> catalog, int readSize = 4096)
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
