using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class InventoryPlanningContractTests
{
    private static ItemSave Item(byte index = 1, ushort item = 42, byte count = 10) =>
        new(index, item, count, 9, 7, 1234, 123, 456, 99, -1.25, 1e-100, 2, 3, 17, 18,
            4, 19, 12345, [new(1, 22), new(2, 33), new(3, 44), new(4, 55)], true, 5, 6, 8);
    private static BagReceiveSnapshot Bag() => BagReceiveReducer.Apply(BagReceiveSnapshot.Empty,
        new BagSnapshotEvent(255, [Item(10), Item(2), Item()]));
    private static StorageReservationSnapshot Hold(ushort index = 1, bool exclusive = false, bool uncertain = false) =>
        new(index, new(42, 1234, 7), 2, 2, 10, exclusive, uncertain);
    private static StateValue Row(ushort index = 1, object? count = null) => StateValue.Map(
        ("index", StateValue.Scalar(index)), ("count", StateValue.Scalar(count ?? 1)));

    [Fact]
    public void CandidatesNeverInstallHoldsOrDeductItemsAndPreserveUnrelatedMetadata()
    {
        var bag = Bag() with { Revision = BigInteger.One << 200, UseFailed = true,
            LastUseResult = 4, SyncError = "retained", FieldSupply = StateValue.Map(("value", StateValue.Scalar(3))) };
        var allocation = InventoryPlanning.Allocate(bag, 42, 12, InventoryPlanningContext.Empty);
        Assert.True(allocation.Success);
        Assert.Equal(new ushort[] { 1, 2 }, allocation.Rows.Select(row => row.Index));
        Assert.Equal(new BigInteger[] { 10, 2 }, allocation.Rows.Select(row => row.Count));
        var candidate = InventoryPlanning.PlanReservation(bag, allocation);
        Assert.True(candidate.Success);
        Assert.Same(bag, candidate.ObservedSnapshot);
        Assert.Empty(bag.Holds); Assert.Empty(bag.Reserved);
        var proposed = candidate.ProposedSnapshot!;
        Assert.Same(bag.Items, proposed.Items);
        Assert.Equal(bag.ItemOrder, proposed.ItemOrder);
        Assert.Same(bag.FieldSupply, proposed.FieldSupply);
        Assert.Same(bag.ServerStackable, proposed.ServerStackable);
        Assert.Equal(bag.Revision, proposed.Revision);
        Assert.Equal(bag.SyncError, proposed.SyncError);
        Assert.True(proposed.UseFailed); Assert.Equal((byte)4, proposed.LastUseResult);
        Assert.Equal(10, bag.Items[1].Count);
        Assert.False(proposed.Holds[0].Rows[0].Uncertain);
    }

    [Fact]
    public void AllocationDoesNotConsultWireLockedFlagOrInventCapacityExclusions()
    {
        var state = Bag() with { Capacity = 1 };
        Assert.All(state.Items.Values, item => Assert.True(item.OriginalRecord.Locked));
        var result = InventoryPlanning.Allocate(state, 42, 30, InventoryPlanningContext.Empty);
        Assert.True(result.Success);
        Assert.Equal(new ushort[] { 1, 2, 10 }, result.Rows.Select(row => row.Index));
    }

    [Fact]
    public void NonpositiveSourceAllocationQuirksDoNotAuthorizeReservation()
    {
        var state = Bag() with { ExpeditionSlots = [1, 2, 10] };
        var zero = InventoryPlanning.Allocate(state, 42, 0, InventoryPlanningContext.Empty);
        Assert.True(zero.Success); Assert.Empty(zero.Rows);
        Assert.False(InventoryPlanning.Allocate(state with { Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty },
            42, 0, InventoryPlanningContext.Empty).Success);
        Assert.False(InventoryPlanning.Allocate(state with { AlchemySlots = [1, 2, 10] }, 42, 0, InventoryPlanningContext.Empty).Success);
        var negative = InventoryPlanning.Allocate(state, 42, -3, InventoryPlanningContext.Empty);
        Assert.True(negative.Success);
        Assert.Equal(new InventoryAllocation(1, -3, 42), Assert.Single(negative.Rows));
        var proposal = InventoryPlanning.PlanReservation(state, negative);
        Assert.False(proposal.Success); Assert.Null(proposal.ProposedSnapshot);
        Assert.Equal("背包保留數量必須為正整數", proposal.Error!.Message);
    }

    [Fact]
    public void FailedAllocationIsNotReinterpretedAsEmptyReservation()
    {
        var state = Bag();
        var allocation = InventoryPlanning.Allocate(state, 42, 999, InventoryPlanningContext.Empty);
        var candidate = InventoryPlanning.PlanReservation(state, allocation);
        Assert.False(candidate.Success); Assert.Same(allocation.Error, candidate.Error);
        Assert.Null(candidate.ProposedSnapshot); Assert.Same(state, candidate.ObservedSnapshot);
    }

    [Fact]
    public void NamesRequireExplicitContextAndUnknownNamesHaveOnlyNumericFallback()
    {
        var context = new InventoryPlanningContext
        {
            ItemNames = ImmutableDictionary<BigInteger, string>.Empty.Add(42, "reviewed display only")
        };
        Assert.Equal("reviewed display only數量不足或仍待伺服器扣除", InventoryPlanning.Allocate(
            Bag(), 42, 31, context).Error!.Message);
        var huge = BigInteger.One << 256;
        Assert.Equal($"物品{huge}數量不足或仍待伺服器扣除", InventoryPlanning.Allocate(
            Bag(), huge, 1, context).Error!.Message);
        Assert.Equal("物品42數量不足或仍待伺服器扣除", InventoryPlanning.Allocate(
            Bag(), 42, 31, InventoryPlanningContext.Empty).Error!.Message);
        Assert.Equal("包包資料尚未同步或已失效", InventoryPlanning.Allocate(BagReceiveSnapshot.Empty,
            42, 0, context).Error!.Message);
    }

    [Fact]
    public void EveryBatchIsValidatedBeforePublishingIncludingLateDuplicateFailure()
    {
        var state = Bag();
        var before = InventoryPlanningParityTests.Project(state).ToJsonString();
        var candidate = InventoryPlanning.PlanReservation(state, [Row(2, 3), Row(1, 6), Row(1, 5)]);
        Assert.False(candidate.Success); Assert.Null(candidate.ProposedSnapshot);
        Assert.Equal("包包數量已變更或仍等待操作確認", candidate.Error!.Message);
        Assert.Equal(before, InventoryPlanningParityTests.Project(state).ToJsonString());
        Assert.Empty(state.Holds); Assert.Empty(state.Reserved);
    }

    [Fact]
    public void ExistingOwnerPositionAndDuplicateRowsStayOrderedAndOnlyFirstRowGrows()
    {
        var first = Hold();
        var second = Hold() with { Identity = new(42, 9999, 7), Count = 777 };
        var state = Bag() with { Holds = [new("storage", []), new("battle", [first, second, Hold(2)]), new("crafting", [])] };
        var candidate = InventoryPlanning.PlanReservation(state, [Row(10, 1), Row(1, 1), Row(10, 2)], exclusive: true);
        var result = candidate.ProposedSnapshot!;
        Assert.Equal(new[] { "storage", "battle", "crafting" }, result.Holds.Select(group => group.Owner));
        Assert.Equal(new ushort[] { 1, 1, 2, 10 }, result.Holds[1].Rows.Select(row => row.Index));
        Assert.Equal(new BigInteger(3), result.Holds[1].Rows[0].Count);
        Assert.False(result.Holds[1].Rows[0].Exclusive);
        Assert.Same(second, result.Holds[1].Rows[1]);
        Assert.True(result.Holds[1].Rows[3].Exclusive);
        Assert.Equal(new BigInteger(3), result.Holds[1].Rows[3].Count);
        Assert.Equal(new BigInteger(10), result.Holds[1].Rows[3].Before);
        Assert.Same(first, state.Holds[1].Rows[0]);
    }

    [Theory]
    [InlineData("alchemy")]
    [InlineData("expedition")]
    [InlineData("maintenance")]
    public void EmptyBatchesRebuildOnlyExplicitOwnerSlotProjection(string owner)
    {
        var state = Bag() with { AlchemySlots = [10], ExpeditionSlots = [10], MaintenanceSlots = [10] };
        var candidate = InventoryPlanning.PlanReservation(state, ImmutableArray<StateValue>.Empty, owner);
        Assert.True(candidate.Success);
        var result = candidate.ProposedSnapshot!;
        Assert.Empty(Assert.Single(result.Holds).Rows);
        Assert.Same(state.Reserved, result.Reserved);
        Assert.Equal(owner == "alchemy" ? [] : new ushort[] { 10 }, result.AlchemySlots!.Value);
        Assert.Equal(owner == "expedition" ? [] : new ushort[] { 10 }, result.ExpeditionSlots!.Value);
        Assert.Equal(owner == "maintenance" ? [] : new ushort[] { 10 }, result.MaintenanceSlots!.Value);
        Assert.Equal(new ushort[] { 10 }, state.AlchemySlots!.Value);
    }

    [Theory]
    [InlineData(true, false)]
    [InlineData(false, true)]
    public void UncertaintyAndExclusiveHoldsRemainLockedEvenWhenRemainingIsZero(bool exclusive, bool uncertain)
    {
        var original = Hold(exclusive: exclusive, uncertain: uncertain) with { Remaining = 0 };
        var state = Bag() with { Holds = [new("battle", [original])] };
        var result = InventoryPlanning.PlanReservation(state, [Row()]);
        Assert.False(result.Success); Assert.Null(result.ProposedSnapshot);
        Assert.Same(original, state.Holds[0].Rows[0]);
        Assert.Equal(new BigInteger(2), state.Holds[0].Rows[0].Count);
    }

    [Fact]
    public void SerialMismatchPrecedesOtherOwnersAndAvailabilityAndOwnerPrecedesReadiness()
    {
        var state = Bag() with { Holds = [new("battle", [Hold() with { Identity = new(42, 999, 7) }]),
            new("storage", [Hold(exclusive: true)])] };
        Assert.Equal("包包格位序號已變更", InventoryPlanning.PlanReservation(state, [Row()]).Error!.Message);
        var unknown = InventoryPlanning.PlanReservation(state with { Ready = false }, [Row()], "Battle");
        Assert.Equal(new InventoryPlanningError("ValueError", "未知的背包保留用途"), unknown.Error);
    }

    [Fact]
    public void NonfiniteAndBooleanCountsFailWithoutCoercion()
    {
        foreach (var count in new object[] { double.NaN, double.PositiveInfinity, double.NegativeInfinity, true, false, 1.0, 1m, "1" })
        {
            var result = InventoryPlanning.PlanReservation(Bag(), [Row(count: count)]);
            Assert.Equal("背包保留數量必須為正整數", result.Error!.Message);
            Assert.Null(result.ProposedSnapshot);
        }
    }

    [Fact]
    public void UnboundedCountsArePreservedWithoutRepairingImportedCounters()
    {
        var huge = BigInteger.One << 400;
        var state = Bag() with { Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, -huge),
            Holds = [new("battle", [Hold() with { Count = huge, Remaining = huge, Before = -huge }])] };
        var allocation = InventoryPlanning.Allocate(state, 42, huge, InventoryPlanningContext.Empty);
        Assert.Equal(huge, Assert.Single(allocation.Rows).Count);
        var result = InventoryPlanning.PlanReservation(state, allocation).ProposedSnapshot!;
        Assert.Equal(huge * 2, result.Holds[0].Rows[0].Count);
        Assert.Equal(huge * 2, result.Holds[0].Rows[0].Remaining);
        Assert.Equal(-huge, result.Holds[0].Rows[0].Before);
        Assert.Equal(BigInteger.Zero, result.Reserved[1]);
        Assert.Equal(-huge, state.Reserved[1]);
    }

    [Fact]
    public void RowsContextAndProposedSnapshotsDoNotRetainMutableAliases()
    {
        var rows = new List<StateValue> { Row() };
        var names = new Dictionary<BigInteger, string> { [42] = "old" };
        var context = new InventoryPlanningContext { ItemNames = names.ToImmutableDictionary() };
        var state = Bag();
        var candidate = InventoryPlanning.PlanReservation(state, [.. rows]);
        var allocation = InventoryPlanning.Allocate(state, 42, 1, context);
        rows.Clear(); names[42] = "new";
        Assert.Single(candidate.ProposedSnapshot!.Holds[0].Rows);
        Assert.Equal("old數量不足或仍待伺服器扣除", InventoryPlanning.Allocate(state, 42, 31, context).Error!.Message);
        Assert.Throws<NotSupportedException>(() => ((IList<InventoryAllocation>)allocation.Rows).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, BigInteger>)candidate.ProposedSnapshot.Reserved).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<StorageReservationSnapshot>)candidate.ProposedSnapshot.Holds[0].Rows).Clear());
        Assert.Empty(state.Holds);
    }

    [Fact]
    public void NullAndDefaultInputsFailAtTheExplicitTypedBoundary()
    {
        Assert.Throws<ArgumentNullException>(() => InventoryPlanning.Allocate(null!, 42, 1, InventoryPlanningContext.Empty));
        Assert.Throws<ArgumentNullException>(() => InventoryPlanning.Allocate(Bag(), 42, 1, null!));
        Assert.Throws<ArgumentNullException>(() => InventoryPlanning.PlanReservation(Bag(), ImmutableArray<StateValue>.Empty, null!));
        Assert.Throws<ArgumentException>(() => InventoryPlanning.PlanReservation(Bag(), default(ImmutableArray<StateValue>)));
    }
}
