using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.State;
using Lala.Core.World.Shop;
using Xunit;

namespace Lala.Core.Tests.World.Shop;

public sealed class NpcShopEvidenceContractTests
{
    private static readonly NpcShopObservationContext Ready = new(1,
        new BagReceiveSnapshot { Ready = true, Reliable = true, Revision = 2 },
        new SessionGoldSnapshot { Ready = true, Reliable = true, Amount = 100, Revision = 3 });
    private static ItemSave Item(byte? index = 7, ushort id = 42, byte count = 2) =>
        new(index, id, count, 0, 0, uint.MaxValue, 111, 222, 333, -999, 888, 0, 0, 0, null, 0, 0, 0, [new(255, 65535)], false, 0, 0, null);
    private static ServerEvent Live(LiveDataEvent value) => new ServerLiveDataEvent(value);

    [Fact]
    public void DefaultsAndResultContractNeverClaimSettlement()
    {
        var empty = NpcShopEvidenceSnapshot.Empty;
        Assert.Empty(empty.Events); Assert.Equal(BigInteger.Zero, empty.Revision);
        Assert.Equal("無交易觀測資料（未啟用付款）", empty.Status);
        Assert.Equal("pending", NpcShopEvidence.ClassifyOffline(empty, new("buy", 0, 42, 1, -1)).Status);
        Assert.DoesNotContain(typeof(NpcShopOfflineClassification).GetProperties(), property =>
            property.Name is "Settled" or "Authorized" or "CanRetry" or "Command" or "Success");
    }

    [Fact]
    public void ContextUsesPostLocalHandlerStateIncludingInvalidReceiptsAndGoldLimits()
    {
        var bag = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(40, []));
        var session = SessionEventReducer.Apply(new(), new GoldSnapshotEvent(100));
        var invalid = Live(new BagDeleteEvent(7, 1, 0));
        bag = BagReceiveReducer.Apply(bag, invalid);
        Assert.False(bag.Reliable);
        var evidence = NpcShopEvidence.Observe(NpcShopEvidenceSnapshot.Empty, invalid, new(1, bag, session.Gold));
        var entry = Assert.Single(evidence.Events);
        Assert.False(entry.InventoryReliable); Assert.True(entry.GoldReliable);
        Assert.Equal(bag.Revision, entry.InventoryRevision);
        var limit = new GoldLimitEvent();
        session = SessionEventReducer.Apply(session, limit);
        evidence = NpcShopEvidence.Observe(evidence, limit, new(2, bag, session.Gold));
        Assert.False(evidence.Events[1].GoldReliable);
        Assert.Equal(session.Gold.Revision, evidence.Events[1].GoldRevision);
        Assert.Equal("uncertain", NpcShopEvidence.ClassifyOffline(evidence, new("buy", 0, 42, 1, -1)).Status);
        Assert.True(entry.GoldReliable); // The retained earlier snapshot is unchanged.
    }

    [Fact]
    public void SaleGoldFieldDoesNotMutateBalanceOrReplaceMissingS26Evidence()
    {
        var bag = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(40, [Item()]));
        var session = SessionEventReducer.Apply(new(), new GoldSnapshotEvent(100));
        var sale = ServerProtocol.Decode(new Packet(27, 6, [0xff, 0xff, 0xff, 0xff, 7, 2]));
        bag = BagReceiveReducer.Apply(bag, sale);
        session = SessionEventReducer.Apply(session, sale);
        var evidence = NpcShopEvidence.Observe(NpcShopEvidenceSnapshot.Empty, sale, new(1, bag, session.Gold));
        Assert.Equal((uint)100, session.Gold.Amount); Assert.Empty(bag.Items);
        Assert.Equal(uint.MaxValue, evidence.Events[0].S27GoldField);
        Assert.Null(evidence.Events[0].Amount); Assert.Null(evidence.Events[0].Delta);
        var notice = ServerProtocol.Decode(new Packet(27, 8, [1]));
        evidence = NpcShopEvidence.Observe(evidence, notice, new(2, bag, session.Gold));
        var order = new NpcShopOfflineOrder("sell", 0, 42, 2, 8, 7);
        Assert.Equal("pending", NpcShopEvidence.ClassifyOffline(evidence, order).Status);
        var delta = ServerProtocol.Decode(new Packet(26, 1, [8, 0, 0, 0, 0]));
        session = SessionEventReducer.Apply(session, delta);
        evidence = NpcShopEvidence.Observe(evidence, delta, new(3, bag, session.Gold));
        var result = NpcShopEvidence.ClassifyOffline(evidence, order);
        Assert.Equal("observed_consistent", result.Status);
        Assert.Contains("缺少伺服器交易識別碼", result.Reason);
        Assert.Equal((uint)108, session.Gold.Amount);
    }

    [Fact]
    public void CallerContextIsRequiredAndNotReconstructedFromIncomingPackets()
    {
        var snapshot = NpcShopEvidenceSnapshot.Empty;
        Assert.Throws<ArgumentNullException>(() => NpcShopEvidence.Observe(snapshot, new GoldSnapshotEvent(100), null!));
        var next = NpcShopEvidence.Observe(snapshot, new GoldSnapshotEvent(100), Ready with
        { Inventory = new(), Gold = new() });
        Assert.False(next.Events[0].InventoryReliable); Assert.False(next.Events[0].GoldReliable);
        Assert.Equal(BigInteger.Zero, next.Events[0].GoldRevision);
        Assert.Equal((uint)100, next.Events[0].Amount);
    }

    [Fact]
    public void LoginAnyResultAndRoleListResetBeforeInspectingNestedContext()
    {
        var state = NpcShopEvidence.Observe(NpcShopEvidenceSnapshot.Empty, new GoldLimitEvent(), Ready);
        var unusable = new NpcShopObservationContext(0, null!, null!);
        foreach (var reset in new ServerEvent[] { new LoginResultEvent(0, 0), new LoginResultEvent(255, 0), new ServerLayoutEvent(new RoleListAvailableEvent([])) })
            Assert.Same(NpcShopEvidenceSnapshot.Empty, NpcShopEvidence.Observe(state, reset, unusable));
        Assert.Single(state.Events);
        Assert.Same(state, NpcShopEvidence.Observe(state, new EventEndEvent(), unusable));
        Assert.Same(state, NpcShopEvidence.Observe(state, new UnsupportedServerDecoderEvent(27, 1, "unknown", 0), unusable));
    }

    [Fact]
    public void ObservationRetainsOnlyListedScalarsAndPreservesNullIndexVersusZero()
    {
        foreach (var index in new byte?[] { null, 0, 255 })
        {
            var state = NpcShopEvidence.Observe(NpcShopEvidenceSnapshot.Empty, Live(new BagAddEvent(Item(index), 65535)), Ready);
            var entry = state.ToOfflineData()["events"][0].MapValue;
            Assert.Equal(9, entry.Count);
            Assert.Equal(index, state.Events[0].Index);
            Assert.DoesNotContain("source", entry.Keys); Assert.DoesNotContain("serial", entry.Keys);
            Assert.DoesNotContain("plugins", entry.Keys); Assert.DoesNotContain("amount", entry.Keys);
            Assert.Equal(index is null, entry["index"].ScalarValue is null);
        }
    }

    [Fact]
    public void AllCountersRemainArbitraryPrecisionAndObserverDoesNotInventMonotonicity()
    {
        var huge = BigInteger.One << 300;
        var before = NpcShopEvidenceSnapshot.Empty with { Revision = huge };
        var context = Ready with { PacketCount = -huge, Inventory = Ready.Inventory with { Revision = huge + 1 }, Gold = Ready.Gold with { Revision = huge + 2 } };
        var after = NpcShopEvidence.Observe(before, new GoldDeltaEvent(1, long.MinValue, false), context);
        Assert.Equal(huge + 1, after.Revision); Assert.Equal(huge, before.Revision);
        Assert.Equal(-huge, after.Events[0].Packet); Assert.Equal(huge + 1, after.Events[0].InventoryRevision);
        Assert.Equal(huge + 2, after.Events[0].GoldRevision); Assert.Equal(long.MinValue, after.Events[0].Delta);
    }

    [Fact]
    public void BoundaryKeepsExactly96AndIgnoredPacketsDoNotEvictEvidence()
    {
        var histories = new List<NpcShopEvidenceSnapshot>();
        var state = NpcShopEvidenceSnapshot.Empty;
        for (var i = 1; i <= 150; i++)
        {
            state = NpcShopEvidence.Observe(state, new GoldLimitEvent(), Ready with { PacketCount = i });
            histories.Add(state);
        }
        Assert.Equal(96, histories[95].Events.Length); Assert.Equal(BigInteger.One, histories[95].Events[0].Packet);
        Assert.Equal(96, histories[96].Events.Length); Assert.Equal(new BigInteger(2), histories[96].Events[0].Packet);
        Assert.Equal(new BigInteger(55), state.Events[0].Packet); Assert.Equal(new BigInteger(150), state.Revision);
        Assert.Same(state, NpcShopEvidence.Observe(state, new EventEndEvent(), Ready));
        Assert.Equal("uncertain", NpcShopEvidence.ClassifyOffline(state, new("buy", 0, 42, 1, -1)).Status);
    }

    [Fact]
    public void ImportedOversizedTypedEvidenceIsRejectedNotSilentlyClassified()
    {
        var entry = new NpcShopEvidenceEntry(1, "gold_limit", 0, true, 0, true);
        var imported = new NpcShopEvidenceSnapshot { Events = [.. Enumerable.Repeat(entry, 97)] };
        Assert.Throws<ProtocolException>(() => NpcShopEvidence.ClassifyOffline(imported, new("buy", 0, 42, 1, -1)));
        var observed = NpcShopEvidence.Observe(imported, new GoldLimitEvent(), Ready);
        Assert.Equal(96, observed.Events.Length); Assert.Equal(97, imported.Events.Length);
    }

    [Theory]
    [InlineData("buy", -4294967295L, null)]
    [InlineData("sell", 4294967295L, 255)]
    public void FullDescriptorIntegerRangesAndSlotZeroRemainValid(string kind, long delta, int? slot)
    {
        var order = new NpcShopOfflineOrder(kind, BigInteger.One << 200, 65535, 255, delta, slot);
        Assert.Equal("pending", NpcShopEvidence.ClassifyOffline(NpcShopEvidenceSnapshot.Empty, order).Status);
        if (kind == "sell") Assert.Equal("pending", NpcShopEvidence.ClassifyOffline(NpcShopEvidenceSnapshot.Empty, order with { BagSlot = 0 }).Status);
    }

    [Fact]
    public void RawStateValueFreezesCallerCollectionsAtBoundary()
    {
        var rows = new List<StateValue> { StateValue.Map(("packet", StateValue.Scalar(1)), ("type", StateValue.Scalar("sale_notice")), ("result", StateValue.Scalar(1))) };
        var evidence = StateValue.Map(("events", StateValue.List(rows)));
        rows.Clear();
        var result = NpcShopEvidence.ClassifyOfflineData(evidence, NpcShopEvidenceParityTests.Data(System.Text.Json.Nodes.JsonNode.Parse(
            "{\"kind\":\"buy\",\"start_packet\":0,\"item_id\":42,\"count\":1,\"expected_gold_delta\":-1}")));
        Assert.Equal("uncertain", result.Status); Assert.Single(evidence["events"].SequenceValue);
    }

    [Fact]
    public void DescriptorValidationPrecedesMalformedEvidenceAndDoesNotCoerceBooleans()
    {
        var invalid = StateValue.Map(("kind", StateValue.Scalar("buy")), ("start_packet", StateValue.Scalar(true)));
        var error = Assert.Throws<ProtocolException>(() => NpcShopEvidence.ClassifyOfflineData(StateValue.Null, invalid));
        Assert.Equal("離線交易對帳的項目、數量或金額非法", error.Message);
    }
}
