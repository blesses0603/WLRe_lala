using System.Net;
using System.Net.Sockets;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Sessions.Receive;
using Lala.Core.Sessions.Transport;
using Lala.Core.State;
using Lala.Core.Tests.Sessions.Public;
using Xunit;

namespace Lala.Core.Tests.Sessions.Receive;

public sealed class AccountCraftingScheduleReceiveTests
{
    private static readonly TimeSpan Limit = TimeSpan.FromSeconds(10);
    private static Packet Snapshot(byte active, params (byte Index, ushort Identity)[] rows) =>
        new(64, 1, rows.SelectMany(row => AccountCraftingScheduleFixtures.Record(row.Index, row.Identity))
            .Append(active).ToArray());
    private static Packet Added(byte index, ushort identity) =>
        new(64, 16, AccountCraftingScheduleFixtures.Record(index, identity));
    private static CraftingScheduleContext Catalog(bool keyed) => Assert.IsType<CraftingScheduleContext>(
        AccountRuntime.ProjectCraftingSchedules(AccountCraftingScheduleFixtures.Parse(keyed)));

    [Theory]
    [InlineData(false, 1)]
    [InlineData(false, 4096)]
    [InlineData(true, 1)]
    [InlineData(true, 4096)]
    public async Task ParsedSchemasReachFramedSnapshotAndAddWithoutSending(bool keyed, int readSize)
    {
        var catalog = Catalog(keyed);
        await using var held = await HeldReceive.Create(() => catalog, readSize);
        await held.Send(Snapshot(1, (1, keyed ? (ushort)42 : (ushort)500),
            (2, keyed ? (ushort)43 : (ushort)501)));
        var initial = await held.WaitRevision(1);
        var craft = initial.Crafting.Crafting;
        Assert.True(craft.Ready);
        Assert.True(craft.Running);
        Assert.Equal((byte)1, craft.Active);
        Assert.Equal("S64-1", craft.SyncSource);
        Assert.Equal(2, craft.Queue.Count);
        Assert.Equal((ushort)500, craft.Queue[1].ItemId);
        Assert.Equal(keyed ? (ushort)500 : (ushort)501, craft.Queue[2].ItemId);
        Assert.Equal(keyed ? (ushort?)42 : null, craft.Queue[1].RecipeId);
        Assert.Equal(keyed ? (ushort?)43 : null, craft.Queue[2].RecipeId);
        Assert.Equal(2.5, craft.Queue[1].Elapsed);
        Assert.Equal((byte)2, craft.Queue[1].Count);
        Assert.Equal(60u, craft.Queue[1].BaseTime);
        Assert.Equal(123d, craft.StartedAt);
        Assert.Same(catalog, initial.Observation!.Inputs.CraftingSchedules);

        await held.Send(Added(3, keyed ? (ushort)44 : (ushort)500));
        var added = await held.WaitRevision(2);
        Assert.Equal(3, added.Crafting.Crafting.Queue.Count);
        Assert.Equal(keyed ? (ushort)501 : (ushort)500, added.Crafting.Crafting.Queue[3].ItemId);
        Assert.Equal(keyed ? (ushort?)44 : null, added.Crafting.Crafting.Queue[3].RecipeId);
        Assert.Equal(new byte[] { 1, 2, 3 }, added.Crafting.Crafting.QueueOrder);
        Assert.Equal(2, craft.Queue.Count); // Earlier publications are immutable.
        held.AssertHeld(added);
        await held.FinishWithoutOutboundBytes();
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task MissingLateAndRevokedCatalogNeverGuessLayoutOrReplayEarlierPackets(bool keyed)
    {
        CraftingScheduleContext? catalog = null;
        await using var held = await HeldReceive.Create(() => Volatile.Read(ref catalog));
        ushort identity = keyed ? (ushort)42 : (ushort)500;
        await held.Send(Snapshot(1, (1, identity)));
        var earlySnapshot = await held.WaitRevision(1);
        Assert.Equal("unsupported_decoder", earlySnapshot.Observation!.EventType);
        Assert.Empty(earlySnapshot.Crafting.Crafting.Queue);
        Assert.False(earlySnapshot.Crafting.Crafting.Ready);
        Assert.True(earlySnapshot.Crafting.Crafting.Uncertain);
        await held.Send(new Packet(1, 11));
        var barrier = await held.WaitRevision(2);
        Assert.False(barrier.Crafting.Crafting.Ready);
        Assert.True(barrier.Crafting.Crafting.Uncertain);
        await held.Send(Added(2, identity));
        var earlyAdd = await held.WaitRevision(3);
        Assert.Equal("unsupported_decoder", earlyAdd.Observation!.EventType);
        Assert.Null(earlyAdd.Observation.Inputs.CraftingSchedules);
        Assert.Empty(earlyAdd.Crafting.Crafting.Queue);
        Assert.False(earlyAdd.Crafting.Crafting.Ready);

        Volatile.Write(ref catalog, Catalog(keyed));
        Assert.Same(earlyAdd, held.Snapshot);
        await held.Send(new Packet(26, 4, [1, 0, 0, 0]));
        var late = await held.WaitRevision(4);
        Assert.Same(catalog, late.Observation!.Inputs.CraftingSchedules);
        Assert.Empty(late.Crafting.Crafting.Queue); // No deferred S64 buffer or backfill.
        Assert.False(late.Crafting.Crafting.Ready);
        await held.Send(Added(3, identity), new Packet(1, 11));
        var delta = await held.WaitRevision(6);
        Assert.Equal((byte)3, Assert.Single(delta.Crafting.Crafting.Queue).Key);
        Assert.False(delta.Crafting.Crafting.Ready); // A fresh delta is not the missing full snapshot.
        Assert.True(delta.Crafting.Crafting.Uncertain);
        await held.Send(Snapshot(1, (1, identity)));
        var current = await held.WaitRevision(7);
        Assert.Single(current.Crafting.Crafting.Queue);
        Assert.Equal((ushort)500, current.Crafting.Crafting.Queue[1].ItemId);
        Assert.True(current.Crafting.Crafting.Ready);
        Assert.True(current.Crafting.Crafting.Running);
        Assert.False(current.Crafting.Crafting.Uncertain);

        Volatile.Write(ref catalog, null);
        await held.Send(Snapshot(0)); // Same snapshot shape must not select legacy after revocation.
        var revokedSnapshot = await held.WaitRevision(8);
        Assert.Equal("unsupported_decoder", revokedSnapshot.Observation!.EventType);
        Assert.Null(revokedSnapshot.Observation.Inputs.CraftingSchedules);
        Assert.Same(current.Crafting.Crafting.Queue, revokedSnapshot.Crafting.Crafting.Queue);
        Assert.False(revokedSnapshot.Crafting.Crafting.Ready);
        Assert.True(revokedSnapshot.Crafting.Crafting.Uncertain);
        Assert.False(revokedSnapshot.Crafting.Crafting.Running);
        Assert.Null(revokedSnapshot.Crafting.Crafting.StartedAt);
        await held.Send(Added(2, identity));
        var revokedAdd = await held.WaitRevision(9);
        Assert.Equal("unsupported_decoder", revokedAdd.Observation!.EventType);
        Assert.Null(revokedAdd.Observation.Inputs.CraftingSchedules);
        Assert.Same(current.Crafting.Crafting.Queue, revokedAdd.Crafting.Crafting.Queue);
        Assert.False(revokedAdd.Crafting.Crafting.Ready);
        Assert.True(revokedAdd.Crafting.Crafting.Uncertain);
        await held.Send(new Packet(1, 11));
        var revokedBarrier = await held.WaitRevision(10);
        Assert.False(revokedBarrier.Crafting.Crafting.Ready);
        Assert.True(revokedBarrier.Crafting.Crafting.Uncertain);
        Assert.NotNull(current.Observation!.Inputs.CraftingSchedules); // Historical only.
        Assert.True(current.Crafting.Crafting.Ready);
        Assert.True(current.Crafting.Crafting.Running);
        Assert.Empty(earlyAdd.Crafting.Crafting.Queue);
        held.AssertHeld(revokedBarrier);
        await held.FinishWithoutOutboundBytes();
    }

    [Theory]
    [InlineData(1, 1)]
    [InlineData(1, 4096)]
    [InlineData(16, 1)]
    [InlineData(16, 4096)]
    public async Task UnknownRecipeRejectsWholePacketWithoutPartialCommitOrLegacyFallback(int sub, int readSize)
    {
        var catalog = Catalog(true);
        await using var held = await HeldReceive.Create(() => catalog, readSize);
        await held.Send(Snapshot(1, (1, 42)));
        var before = await held.WaitRevision(1);
        // The snapshot includes a valid preceding row to prove atomic decode failure.
        await held.Send(sub == 1 ? Snapshot(2, (2, 43), (3, 500)) : Added(2, 500));
        var result = await held.FinishInvalidWithoutOutboundBytes();
        Assert.Equal(1, result.Publication.Revision);
        Assert.Same(before, result.Publication.Snapshot);
        Assert.Single(before.Crafting.Crafting.Queue);
        Assert.Equal((ushort)500, before.Crafting.Crafting.Queue[1].ItemId);
        Assert.Equal((ushort?)42, before.Crafting.Crafting.Queue[1].RecipeId);
    }

    private sealed class HeldReceive : IAsyncDisposable
    {
        private readonly TcpClient peer;
        private readonly NetworkStream peerStream;
        private readonly AccountSession session = new();
        private readonly long generation;
        private readonly ReceiveAttempt attempt;
        private readonly Task<ReceiveResult> run;

        private HeldReceive(TcpClient peer, BoundedTcpTransport transport, Func<CraftingScheduleContext?> catalog, int readSize)
        {
            this.peer = peer;
            peerStream = peer.GetStream();
            generation = session.Begin("synthetic", "loopback-crafting").Generation;
            attempt = Assert.IsType<ReceiveAttempt>(session.AttachHeldReceive(generation, transport, 0xAD,
                () => 123, (_, now) => new(now) { CraftingSchedules = catalog(), TrackUnsupportedCraftingSchedules = true, ResourceHeld = false }, readSize));
            run = attempt.RunAsync();
        }

        internal static async Task<HeldReceive> Create(Func<CraftingScheduleContext?> catalog, int readSize = 4096)
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
            Assert.False(snapshot.Crafting.Crafting.AutoContinue);
            Assert.False(snapshot.Crafting.Crafting.CompletionRequested);
            Assert.False(session.ConfirmResources(generation, "v", "v", true));
            Assert.False(session.AllowsResourceGate(generation, "craft"));
        }

        internal async Task FinishWithoutOutboundBytes()
        {
            peer.Client.Shutdown(SocketShutdown.Send);
            var result = await run.WaitAsync(Limit);
            Assert.Equal(ReceiveEnd.Completed, result.End);
            await AssertNoOutbound(result);
        }

        internal async Task<ReceiveResult> FinishInvalidWithoutOutboundBytes()
        {
            var result = await run.WaitAsync(Limit);
            Assert.Equal(ReceiveEnd.InvalidPayload, result.End);
            await AssertNoOutbound(result);
            return result;
        }

        private async Task AssertNoOutbound(ReceiveResult result)
        {
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
