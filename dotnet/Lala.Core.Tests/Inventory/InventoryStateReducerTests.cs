using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class InventoryStateReducerTests
{
    private static ItemSave Item(byte? index = 1, ushort item = 42, byte count = 2, uint serial = 1234) =>
        new(index, item, count, 9, 7, serial, 123, 456, 99, -1.25, 1e-100, 2, 3, 17, 18,
            4, 19, 12345, [new(1, 22), new(2, 33), new(3, 44), new(4, 55)], true, 5, 6, 8);
    private static StorageReceiveSnapshot Materials(ushort count = 8) =>
        RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty,
            new StorageMaterialsInitialEvent([new(1, 42, count), new(2, 42, 10), new(3, 43, 6)]));
    private static StorageReservationSnapshot Hold(ushort index = 1, int remaining = 3, bool exclusive = false, bool uncertain = false) =>
        new(index, new(42, null, null), 3, remaining, 8, exclusive, uncertain);

    [Fact]
    public void DefaultsAreUnknownIndependentAndNonAuthorizing()
    {
        var state = StorageReceiveSnapshot.Empty;
        Assert.NotSame(state.Storage.Garage, state.Storage.Materials);
        Assert.False(state.Storage.Garage.Ready); Assert.False(state.Storage.Materials.Ready);
        Assert.True(state.Storage.Garage.Reliable); Assert.True(state.Storage.Materials.Reliable);
        Assert.Null(state.Storage.Garage.Capacity); Assert.Null(state.Storage.Materials.Capacity);
        Assert.Null(state.Storage.MaterialStackLimit); Assert.False(state.Storage.ParametersReady);
        Assert.Null(state.Storage.LastError); Assert.Null(state.Storage.LastResult); Assert.Null(state.Storage.Pending);
        Assert.False(state.Storage.Uncertain); Assert.Equal(BigInteger.Zero, state.Storage.Revision);
        Assert.Equal("等待儲藏空間同步", state.Storage.Status); Assert.Null(state.ServerStackable);
        Assert.Empty(PotionStorageSnapshot.Empty.Resources);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 42));
    }

    [Fact]
    public void GarageAppendsDuplicateBatchesAndPreservesFirstFullIdentityAndMetadata()
    {
        var first = Item();
        var original = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageGarageInitialEvent([first]));
        var next = RoomStorageReducer.Apply(original, new StorageGarageInitialEvent([Item(count: 255, serial: 999)]));
        var again = RoomStorageReducer.Apply(next, new StorageGarageAddEvent(Item(count: 255, serial: 0)));
        var row = again.Storage.Garage.Items[1];
        Assert.Equal(new BigInteger(512), row.Count);
        Assert.Same(first, row.OriginalGarageRecord);
        Assert.Equal(1234u, row.OriginalGarageRecord!.Serial);
        Assert.Equal((byte)7, row.OriginalGarageRecord.SerialVersion);
        Assert.Equal((ushort)55, row.OriginalGarageRecord.Plugins[3].Value);
        Assert.Equal(new BigInteger(2), original.Storage.Garage.Items[1].Count);
        Assert.Equal(new BigInteger(3), again.Storage.Revision);
        Assert.True(again.Storage.Garage.Reliable);
        Assert.Equal(new ushort[] { 1 }, again.Storage.Garage.ItemOrder);
    }

    [Fact]
    public void OnlyItemIdConflictsLatchReliabilityWithoutReplacingTheRow()
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageGarageInitialEvent([Item()]));
        var bad = RoomStorageReducer.Apply(state, new StorageGarageAddEvent(Item(item: 43)));
        Assert.False(bad.Storage.Garage.Reliable);
        Assert.Same(state.Storage.Garage.Items[1], bad.Storage.Garage.Items[1]);
        var after = RoomStorageReducer.Apply(bad, new StorageGarageInitialEvent([Item(count: 1)]));
        Assert.False(after.Storage.Garage.Reliable); Assert.True(after.Storage.Garage.Ready);
        Assert.Equal(new BigInteger(3), after.Storage.Garage.Items[1].Count);
        Assert.True(state.Storage.Garage.Reliable);
    }

    [Theory]
    [InlineData(null, 42, 1)]
    [InlineData((byte)0, 42, 1)]
    [InlineData((byte)1, 0, 1)]
    [InlineData((byte)1, 42, 0)]
    public void InvalidGarageRowsOnlyInvalidateThatBucket(byte? index, ushort item, byte count)
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty,
            new StorageGarageInitialEvent([Item(index, item, count)]));
        Assert.False(state.Storage.Garage.Reliable); Assert.True(state.Storage.Garage.Ready);
        Assert.Empty(state.Storage.Garage.Items); Assert.Empty(state.Storage.Garage.ItemOrder);
        Assert.True(state.Storage.Materials.Reliable); Assert.False(state.Storage.Materials.Ready);
        Assert.Null(state.ServerStackable); Assert.Equal(BigInteger.One, state.Storage.Revision);
    }

    [Theory]
    [InlineData(0, 42, 1, true)]
    [InlineData(1, 0, 1, false)]
    [InlineData(1, 42, 0, false)]
    public void MaterialsRecordStackabilityBeforeSlotValidation(ushort index, ushort item, ushort count, bool observed)
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageMaterialsAddEvent([new(index, item, count)]));
        Assert.False(state.Storage.Materials.Reliable); Assert.False(state.Storage.Materials.Ready);
        Assert.Empty(state.Storage.Materials.Items); Assert.NotNull(state.ServerStackable);
        Assert.Equal(observed, state.ServerStackable.ContainsKey(item));
    }

    [Fact]
    public void EmptyMaterialBatchEstablishesOnlyItsReadinessAndEmptyObservationMap()
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageMaterialsInitialEvent([]));
        Assert.True(state.Storage.Materials.Ready); Assert.False(state.Storage.Garage.Ready);
        Assert.NotNull(state.ServerStackable); Assert.Empty(state.ServerStackable);
        Assert.False(state.Storage.ParametersReady);
        Assert.Equal(BigInteger.Zero, RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 42));
    }

    [Fact]
    public void AddParametersAndReceiptNeverInventInitialReadiness()
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageGarageAddEvent(Item()));
        state = RoomStorageReducer.Apply(state, new StorageMaterialsAddEvent([new(1, 42, 3)]));
        state = RoomStorageReducer.Apply(state, new StorageParametersEvent(255, 65535, 65535));
        state = RoomStorageReducer.Apply(state, new StorageMoveResultEvent(1));
        Assert.False(state.Storage.Garage.Ready); Assert.False(state.Storage.Materials.Ready);
        Assert.True(state.Storage.ParametersReady);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 42));
        Assert.Equal(new BigInteger(3), RoomStorageReducer.Available(state.Storage.Materials, 1));
    }

    [Fact]
    public void MaterialsAccumulateWithoutUshortClampingAndOnlyMatchingOvergrownStackBlocksCount()
    {
        var state = Materials(65535);
        state = RoomStorageReducer.Apply(state, new StorageMaterialsAddEvent([new(1, 42, 1)]));
        Assert.Equal(new BigInteger(65536), state.Storage.Materials.Items[1].Count);
        Assert.True(state.Storage.Materials.Reliable);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 42));
        Assert.Equal(new BigInteger(6), RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 43));
        state = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(1, 1));
        Assert.Equal(new BigInteger(65545), RoomStorageReducer.ConfirmedMaterialCount(state.Storage, 42));
    }

    [Theory]
    [InlineData(1, 0)]
    [InlineData(1, 9)]
    [InlineData(255, 1)]
    public void InvalidDeletePreservesCountsReservationsAndHolds(ushort index, ushort count)
    {
        var state = Materials();
        var bucket = state.Storage.Materials with
        {
            Holds = [new("storage", [Hold(exclusive: true)])],
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 3)
        };
        state = state with { Storage = state.Storage with { Materials = bucket } };
        var result = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(index, count));
        Assert.False(result.Storage.Materials.Reliable);
        Assert.Same(bucket.Items, result.Storage.Materials.Items);
        Assert.Same(bucket.Reserved, result.Storage.Materials.Reserved);
        Assert.Equal(bucket.Holds, result.Storage.Materials.Holds);
    }

    [Fact]
    public void FullDeleteAndReaddPreservePythonItemInsertionOrder()
    {
        var state = Materials();
        state = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(2, 10));
        Assert.Equal(new ushort[] { 1, 3 }, state.Storage.Materials.ItemOrder);
        state = RoomStorageReducer.Apply(state, new StorageMaterialsAddEvent([new(2, 43, 1)]));
        Assert.Equal(new ushort[] { 1, 3, 2 }, state.Storage.Materials.ItemOrder);
        Assert.Equal((ushort)43, state.Storage.Materials.Items[2].ItemId);
        Assert.Equal(BigInteger.Zero, state.Storage.Materials.Reserved[2]);
    }

    [Fact]
    public void ReservationDeductionIsOrderedAndOnlyBattleZeroRowsAreReleased()
    {
        var state = Materials();
        var before = state.Storage.Materials with
        {
            Holds = [new("storage", [Hold(remaining: 2, exclusive: true)]),
                new("battle", [Hold(remaining: 2), Hold(3, remaining: 0, uncertain: true)]),
                new("crafting", [Hold(remaining: 2)])],
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 6)
        };
        state = state with { Storage = state.Storage with { Materials = before } };
        var result = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(1, 4));
        var bucket = result.Storage.Materials;
        Assert.Equal(new[] { "storage", "crafting" }, bucket.Holds.Select(group => group.Owner));
        Assert.Equal(BigInteger.Zero, bucket.Holds[0].Rows[0].Remaining);
        Assert.Equal(new BigInteger(2), bucket.Holds[1].Rows[0].Remaining);
        Assert.Equal(new BigInteger(2), bucket.Reserved[1]);
        Assert.Equal(BigInteger.Zero, RoomStorageReducer.Available(bucket, 1));
        Assert.Equal(new BigInteger(2), before.Holds[0].Rows[0].Remaining);
        Assert.Equal(3, before.Holds.Length);
    }

    [Fact]
    public void ConsumptionDoesNotInventAnIdentityCheckOrReleaseUncertainNonbattleHolds()
    {
        var state = Materials();
        var hold = Hold(remaining: 1, uncertain: true) with { Identity = new(999, 99, 9) };
        var bucket = state.Storage.Materials with { Holds = [new("storage", [hold])] };
        state = state with { Storage = state.Storage with { Materials = bucket } };
        var result = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(1, 1));
        var remaining = Assert.Single(Assert.Single(result.Storage.Materials.Holds).Rows);
        Assert.True(remaining.Uncertain); Assert.Equal(BigInteger.Zero, remaining.Remaining);
        Assert.Equal(hold.Identity, remaining.Identity); Assert.True(result.Storage.Materials.Reliable);
        Assert.Equal(BigInteger.Zero, result.Storage.Materials.Reserved[1]);
    }

    [Theory]
    [InlineData("alchemy")]
    [InlineData("expedition")]
    [InlineData("maintenance")]
    [InlineData("exclusive")]
    [InlineData("uncertain")]
    public void LocksRemainAfterQuantityDeduction(string kind)
    {
        var state = Materials();
        var bucket = state.Storage.Materials;
        bucket = kind switch
        {
            "alchemy" => bucket with { AlchemySlots = [1] },
            "expedition" => bucket with { ExpeditionSlots = [1] },
            "maintenance" => bucket with { MaintenanceSlots = [1] },
            _ => bucket with { Holds = [new("storage", [Hold(remaining: 0, exclusive: kind == "exclusive", uncertain: kind == "uncertain")])] }
        };
        state = state with { Storage = state.Storage with { Materials = bucket } };
        var result = RoomStorageReducer.Apply(state, new StorageMaterialsDeleteEvent(1, 1));
        Assert.Equal(BigInteger.Zero, RoomStorageReducer.Available(result.Storage.Materials, 1));
        Assert.Equal(new BigInteger(10), RoomStorageReducer.ConfirmedMaterialCount(result.Storage, 42));
    }

    [Fact]
    public void ResultsAndErrorsRetainPendingUncertaintyQuantitiesAndEachOthersHistory()
    {
        var state = Materials();
        state = state with { Storage = state.Storage with { Pending = "deposit", Uncertain = true, Status = "waiting", LastError = 99 } };
        var result = RoomStorageReducer.Apply(state, new StorageMoveResultEvent(1));
        Assert.Equal((byte)1, result.Storage.LastResult); Assert.Equal((byte)99, result.Storage.LastError);
        result = RoomStorageReducer.Apply(result, new StorageErrorEvent(1, 3));
        Assert.Equal((byte)1, result.Storage.LastResult); Assert.Equal((byte)3, result.Storage.LastError);
        Assert.Equal("deposit", result.Storage.Pending); Assert.True(result.Storage.Uncertain);
        Assert.Equal("waiting", result.Storage.Status); Assert.Same(state.Storage.Materials, result.Storage.Materials);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(result.Storage, 42));
    }

    [Fact]
    public void ExpansionDoesNotEstablishParametersReadyAndLaterParametersMayReduceCapacities()
    {
        var state = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageExpandedEvent(75, "stack", 65535));
        Assert.False(state.Storage.ParametersReady); Assert.Null(state.Storage.Garage.Capacity);
        state = RoomStorageReducer.Apply(state, new StorageExpandedEvent(73, "garage", 255));
        state = RoomStorageReducer.Apply(state, new StorageExpandedEvent(74, "materials", 65535));
        state = RoomStorageReducer.Apply(state, new StorageParametersEvent(0, 0, 0));
        Assert.True(state.Storage.ParametersReady); Assert.Equal((ushort)0, state.Storage.Garage.Capacity);
        Assert.Equal((ushort)0, state.Storage.Materials.Capacity); Assert.Equal((ushort)0, state.Storage.MaterialStackLimit);
    }

    [Fact]
    public void RevisionAndQuantityAreUnboundedPythonIntegers()
    {
        var huge = BigInteger.One << 100;
        var state = Materials();
        var bucket = state.Storage.Materials with { Items = state.Storage.Materials.Items.SetItem(1,
            state.Storage.Materials.Items[1] with { Count = huge }) };
        state = state with { Storage = state.Storage with { Materials = bucket, Revision = huge } };
        var result = RoomStorageReducer.Apply(state, new StorageMaterialsAddEvent([new(1, 42, 65535)]));
        Assert.Equal(huge + 65535, result.Storage.Materials.Items[1].Count);
        Assert.Equal(huge + 1, result.Storage.Revision);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(result.Storage, 42));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(int.MinValue)]
    [InlineData(int.MaxValue)]
    public void PotionDeltaCannotCreateUnknownBaselineOrRevision(int amount)
    {
        Assert.Same(PotionStorageSnapshot.Empty, RecoveryReducer.Apply(PotionStorageSnapshot.Empty, new PotionBalanceAddEvent("hp", amount)));
        var partial = new PotionStorageSnapshot
        {
            Resources = ImmutableDictionary<string, PotionResourceSnapshot>.Empty.Add("hp", new(null, 19))
        };
        Assert.Same(partial, RecoveryReducer.Apply(partial, new PotionBalanceAddEvent("hp", amount)));
    }

    [Fact]
    public void PotionAbsoluteReplacesButDuplicatesIncrementPerResourceRevision()
    {
        var before = RecoveryReducer.Apply(PotionStorageSnapshot.Empty, new PotionBalanceEvent("hp", 50));
        var state = RecoveryReducer.Apply(before, new PotionBalanceEvent("hp", 50));
        state = RecoveryReducer.Apply(state, new PotionBalanceEvent("sp", 7));
        state = RecoveryReducer.Apply(state, new PotionBalanceEvent("hp", 0));
        Assert.Equal(new PotionResourceSnapshot(0, 3), state.Resources["hp"]);
        Assert.Equal(new PotionResourceSnapshot(7, 1), state.Resources["sp"]);
        Assert.Equal(new PotionResourceSnapshot(50, 1), before.Resources["hp"]);
    }

    [Fact]
    public void PotionDeltasAreUnboundedClampAtZeroAndStillCountWhenClampedOrZero()
    {
        var huge = BigInteger.One << 100;
        var state = new PotionStorageSnapshot
        {
            Resources = ImmutableDictionary<string, PotionResourceSnapshot>.Empty.Add("hp", new(huge, huge))
        };
        state = RecoveryReducer.Apply(state, new PotionBalanceAddEvent("hp", int.MaxValue));
        Assert.Equal(new PotionResourceSnapshot(huge + int.MaxValue, huge + 1), state.Resources["hp"]);
        state = RecoveryReducer.Apply(state, new PotionBalanceEvent("hp", 0));
        state = RecoveryReducer.Apply(state, new PotionBalanceAddEvent("hp", int.MinValue));
        state = RecoveryReducer.Apply(state, new PotionBalanceAddEvent("hp", 0));
        Assert.Equal(new PotionResourceSnapshot(0, huge + 4), state.Resources["hp"]);
    }

    [Fact]
    public void UsedAndItemUpdateReceiptsDoNotDebitCreditOrChangeAnyStorage()
    {
        var state = RecoveryReducer.Apply(PotionStorageSnapshot.Empty, new PotionBalanceEvent("hp", 30));
        foreach (var observation in new InventoryEvent[] { new PotionUsedEvent("hp", [1, 1, 255]),
                     new PotionItemUpdateEvent(1, int.MaxValue, 3, 0), new PotionItemUpdateEvent(1, int.MinValue),
                     new StorageMoveResultEvent(1), new CraftCompletedEvent(1, 100) })
            Assert.Same(state, RecoveryReducer.Apply(state, observation));
        Assert.Same(StorageReceiveSnapshot.Empty, RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new PotionUsedEvent("hp", [1])));
    }

    [Fact]
    public void FreshDomainResetDoesNotCarryBalancesProofErrorsOrReservations()
    {
        var before = Materials();
        before = RoomStorageReducer.Apply(before, new StorageErrorEvent(1, 255));
        var fresh = new StorageReceiveSnapshot();
        Assert.Null(fresh.ServerStackable); Assert.Null(fresh.Storage.LastError);
        Assert.Empty(fresh.Storage.Materials.Items); Assert.Empty(fresh.Storage.Materials.Holds);
        Assert.Null(RoomStorageReducer.ConfirmedMaterialCount(fresh.Storage, 42));
        Assert.Equal((byte)255, before.Storage.LastError); Assert.Equal(3, before.Storage.Materials.Items.Count);
        Assert.Empty(new PotionStorageSnapshot().Resources);
    }

    [Fact]
    public void UnrelatedTypedEventsAndServerEventsAreIdentityNoops()
    {
        var storage = Materials();
        var recovery = RecoveryReducer.Apply(PotionStorageSnapshot.Empty, new PotionBalanceEvent("hp", 1));
        Assert.Same(storage, RoomStorageReducer.Apply(storage, new CraftStartedEvent(1)));
        Assert.Same(recovery, RecoveryReducer.Apply(recovery, new CraftStartedEvent(1)));
        Assert.Same(storage, RoomStorageReducer.Apply(storage, new RoundStartEvent(1)));
        Assert.Same(recovery, RecoveryReducer.Apply(recovery, new RoundStartEvent(1)));
    }

    [Fact]
    public void NullContractsAndUnknownExpansionDoNotPublishPartialResults()
    {
        Assert.Throws<ArgumentNullException>(() => RoomStorageReducer.Apply(null!, new StorageMoveResultEvent(1)));
        Assert.Throws<ArgumentNullException>(() => RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, (InventoryEvent)null!));
        Assert.Throws<ArgumentNullException>(() => RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, (ServerEvent)null!));
        Assert.Throws<ArgumentNullException>(() => RecoveryReducer.Apply(null!, new PotionBalanceEvent("hp", 0)));
        Assert.Throws<ArgumentNullException>(() => RecoveryReducer.Apply(PotionStorageSnapshot.Empty, (InventoryEvent)null!));
        Assert.Throws<ArgumentNullException>(() => RecoveryReducer.Apply(PotionStorageSnapshot.Empty, (ServerEvent)null!));
        Assert.Throws<ArgumentNullException>(() => RoomStorageReducer.ConfirmedMaterialCount(null!, 42));
        Assert.Throws<ArgumentNullException>(() => RoomStorageReducer.Available(null!, 1));
        var before = Materials();
        Assert.Throws<KeyNotFoundException>(() => RoomStorageReducer.Apply(before, new StorageExpandedEvent(73, "other", 4)));
        Assert.Equal(BigInteger.One, before.Storage.Revision);
    }

    [Fact]
    public void SnapshotFormattingDoesNotLeakItemIdentityBalancesOrPendingDetails()
    {
        var item = new StorageItemSnapshot(1, 42, 123456789, Item(serial: 987654321));
        Assert.Equal(nameof(StorageItemSnapshot), item.ToString());
        Assert.Equal(nameof(StorageReservationSnapshot), Hold().ToString());
        Assert.Equal(nameof(StorageReservationIdentity), Hold().Identity.ToString());
        Assert.Equal(nameof(StorageReservationGroup), new StorageReservationGroup("private", [Hold()]).ToString());
        Assert.Equal(nameof(StorageBucketSnapshot), Materials().Storage.Materials.ToString());
        Assert.Equal(nameof(RoomStorageSnapshot), Materials().Storage.ToString());
        Assert.Equal(nameof(StorageReceiveSnapshot), Materials().ToString());
        Assert.Equal(nameof(PotionStorageSnapshot), PotionStorageSnapshot.Empty.ToString());
        Assert.Equal(nameof(PotionResourceSnapshot), new PotionResourceSnapshot(987654321, 1).ToString());
    }
}
