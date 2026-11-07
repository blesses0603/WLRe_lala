using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class ReservationPlanningContractTests
{
    private static ItemSave Item(byte index = 1, ushort item = 42) =>
        new(index, item, 10, 9, 7, 1234, 123, 456, 99, -1.25, 1e-100, 2, 3, 17, 18,
            4, 19, 12345, [new(1, 22), new(2, 33), new(3, 44), new(4, 55)], true, 5, 6, 8);
    private static BagReceiveSnapshot Bag() => BagReceiveReducer.Apply(BagReceiveSnapshot.Empty,
        new BagSnapshotEvent(255, [Item(), Item(2)]));
    private static StorageReservationSnapshot Hold(ushort index = 1, int remaining = 2) =>
        new(index, new(42, 1234, 7), 2, remaining, 10, false, false);

    [Fact]
    public void ReleaseProposalClampsEachDuplicateInOrderAndDoesNotRepairOtherHolds()
    {
        var retained = Hold(remaining: 99) with { Exclusive = true };
        var state = Bag() with { Ready = false, Reliable = false,
            Holds = [new("before", []), new("legacy", [Hold(remaining: 3), Hold(remaining: -5), Hold(remaining: 2)]),
                new("after", [retained])], Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 1) };
        var result = InventoryReservationPlanning.PlanRelease(state, "legacy");
        Assert.True(result.Success); Assert.Same(state, result.ObservedSnapshot);
        var proposed = result.ProposedSnapshot!;
        Assert.Equal(new BigInteger(3), proposed.Reserved[1]);
        Assert.Equal(new[] { "before", "after" }, proposed.Holds.Select(group => group.Owner));
        Assert.Same(retained, proposed.Holds[1].Rows[0]);
        Assert.False(proposed.Ready); Assert.False(proposed.Reliable);
        Assert.Same(state.Items, proposed.Items); Assert.Equal(state.Revision, proposed.Revision);
        Assert.Equal(3, state.Holds.Length); Assert.Equal(BigInteger.One, state.Reserved[1]);
    }

    [Fact]
    public void ReleaseUncertainHoldIsOnlyHypotheticalAndDoesNotClearReliabilityOrErrors()
    {
        var uncertain = Hold() with { Uncertain = true };
        var state = Bag() with { Holds = [new("battle", [uncertain])], Reliable = false,
            SyncError = "still uncertain", Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 2) };
        var proposed = InventoryReservationPlanning.PlanRelease(state, "battle").ProposedSnapshot!;
        Assert.Empty(proposed.Holds); Assert.False(proposed.Reliable);
        Assert.Equal("still uncertain", proposed.SyncError);
        Assert.True(state.Holds[0].Rows[0].Uncertain);
        Assert.Equal(new BigInteger(2), state.Reserved[1]);
        Assert.Equal(10, proposed.Items[1].Count);
    }

    [Theory]
    [InlineData("alchemy")]
    [InlineData("expedition")]
    [InlineData("maintenance")]
    public void ReleasingMissingOwnerClearsOnlyItsStaleSlots(string owner)
    {
        var state = Bag() with { AlchemySlots = [1, 1], ExpeditionSlots = [2, 2], MaintenanceSlots = [65535] };
        var result = InventoryReservationPlanning.PlanRelease(state, owner).ProposedSnapshot!;
        Assert.Empty(result.Holds); Assert.Same(state.Reserved, result.Reserved);
        Assert.Equal(owner == "alchemy" ? [] : new ushort[] { 1, 1 }, result.AlchemySlots!.Value);
        Assert.Equal(owner == "expedition" ? [] : new ushort[] { 2, 2 }, result.ExpeditionSlots!.Value);
        Assert.Equal(owner == "maintenance" ? [] : new ushort[] { 65535 }, result.MaintenanceSlots!.Value);
        var unknown = InventoryReservationPlanning.PlanRelease(state, "Alchemy").ProposedSnapshot!;
        Assert.Equal(state.AlchemySlots, unknown.AlchemySlots);
        Assert.Equal(state.ExpeditionSlots, unknown.ExpeditionSlots);
        Assert.Equal(state.MaintenanceSlots, unknown.MaintenanceSlots);
    }

    [Fact]
    public void ReleaseUsesUnboundedRemainingAndAddsMissingReservedKeysEvenForZero()
    {
        var huge = BigInteger.One << 400;
        var state = Bag() with { Holds = [new("battle", [Hold() with { Remaining = huge },
            Hold(2) with { Remaining = -huge }, Hold(65535, 0)])] };
        var result = InventoryReservationPlanning.PlanRelease(state, "battle").ProposedSnapshot!;
        Assert.Equal(BigInteger.Zero, result.Reserved[1]);
        Assert.Equal(huge, result.Reserved[2]);
        Assert.True(result.Reserved.ContainsKey(65535)); Assert.Equal(BigInteger.Zero, result.Reserved[65535]);
        Assert.Empty(state.Reserved);
    }

    [Fact]
    public void UncertainOnlyMarksRowsIncludingZeroAndUnknownOwnersWithoutProjectingSlots()
    {
        var row = Hold(remaining: 0) with { Before = -3, Count = BigInteger.One << 200 };
        var unaffected = Hold(2);
        var state = Bag() with { Holds = [new("legacy", [row]), new("other", [unaffected])],
            AlchemySlots = [255], Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 0) };
        var result = InventoryReservationPlanning.PlanUncertain(state, "legacy").ProposedSnapshot!;
        var marked = result.Holds[0].Rows[0];
        Assert.True(marked.Uncertain); Assert.True(result.Reliable);
        Assert.Equal(row with { Uncertain = true }, marked);
        Assert.Same(row.Identity, marked.Identity); Assert.Same(unaffected, result.Holds[1].Rows[0]);
        Assert.Same(state.Reserved, result.Reserved); Assert.Equal(state.AlchemySlots, result.AlchemySlots);
        Assert.Equal(state.SyncError, result.SyncError); Assert.False(row.Uncertain);
        Assert.True(InventoryReservationPlanning.Locked(result, 1));
        var absent = InventoryReservationPlanning.PlanUncertain(state, "absent");
        Assert.Same(state, absent.ProposedSnapshot);
    }

    [Fact]
    public void CheckpointContainsOnlyFiveFieldsAndNormalizesOnlyAbsentSlotDefaults()
    {
        var state = Bag() with { Holds = [new("battle", [Hold()])],
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, -2), AlchemySlots = [2, 2, 65535],
            ExpeditionSlots = null, MaintenanceSlots = null };
        var saved = InventoryReservationPlanning.Checkpoint(state);
        Assert.Equal(new[] { "AlchemySlots", "ExpeditionSlots", "Holds", "MaintenanceSlots", "Reserved" },
            typeof(InventoryReservationCheckpoint).GetProperties().Select(property => property.Name).Order());
        Assert.Equal(new ushort[] { 2, 2, 65535 }, saved.AlchemySlots);
        Assert.Empty(saved.ExpeditionSlots); Assert.Empty(saved.MaintenanceSlots);
        Assert.Equal(new BigInteger(-2), saved.Reserved[1]);
        Assert.Null(state.ExpeditionSlots); Assert.Null(state.MaintenanceSlots);
        Assert.Equal(new[] { "holds", "reserved", "alchemy_slots", "expedition_slots", "maintenance_slots" },
            ReservationPlanningParityTests.ProjectCheckpoint(saved).Select(entry => entry.Key));
    }

    [Fact]
    public void RestoreOnlyReplacesSavedFieldsWithoutIdentityValidationOrProjection()
    {
        var old = Bag() with { Holds = [new("alchemy", [Hold()])],
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, -5), AlchemySlots = [255, 255] };
        var saved = InventoryReservationPlanning.Checkpoint(old);
        var current = BagReceiveReducer.Apply(old, new BagSnapshotEvent(255, [Item() with { Serial = 999 }]));
        current = current with { Ready = false, Revision = BigInteger.One << 200, UseFailed = true, LastUseResult = 4,
            FieldSupply = StateValue.Map(("keep", StateValue.List(StateValue.Scalar(1)))),
            ServerStackable = ImmutableDictionary<ushort, bool>.Empty.Add(42, true), SyncError = "current failure" };
        var proposed = InventoryReservationPlanning.PlanRestore(current, saved).ProposedSnapshot!;
        Assert.Equal(old.Holds, proposed.Holds); Assert.Same(old.Reserved, proposed.Reserved);
        Assert.Equal(new ushort[] { 255, 255 }, proposed.AlchemySlots!.Value);
        Assert.Empty(proposed.ExpeditionSlots!.Value); Assert.Empty(proposed.MaintenanceSlots!.Value);
        Assert.Same(current.Items, proposed.Items); Assert.Equal(current.ItemOrder, proposed.ItemOrder);
        Assert.Equal(current.Revision, proposed.Revision); Assert.Equal(current.Ready, proposed.Ready);
        Assert.Equal(current.Reliable, proposed.Reliable); Assert.Equal(current.Capacity, proposed.Capacity);
        Assert.Equal(current.UseFailed, proposed.UseFailed); Assert.Equal(current.LastUseResult, proposed.LastUseResult);
        Assert.Equal("current failure", proposed.SyncError); Assert.Same(current.FieldSupply, proposed.FieldSupply);
        Assert.Same(current.ServerStackable, proposed.ServerStackable);
        Assert.False(proposed.Holds[0].Rows[0].Uncertain); Assert.True(current.Holds[0].Rows[0].Uncertain);
        Assert.Equal(1234u, proposed.Holds[0].Rows[0].Identity.Serial); Assert.Equal(999u, proposed.Items[1].OriginalRecord.Serial);
    }

    [Fact]
    public void CheckpointAndRepeatedRestoresRemainDeeplyImmutable()
    {
        var state = Bag() with { Holds = [new("battle", [Hold()])], AlchemySlots = [1],
            Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 2) };
        var saved = InventoryReservationPlanning.Checkpoint(state);
        var before = ReservationPlanningParityTests.ProjectCheckpoint(saved).ToJsonString();
        var marked = InventoryReservationPlanning.PlanUncertain(state, "battle").ProposedSnapshot!;
        var released = InventoryReservationPlanning.PlanRelease(marked, "battle").ProposedSnapshot!;
        var restored = InventoryReservationPlanning.PlanRestore(released, saved).ProposedSnapshot!;
        var deducted = BagReceiveReducer.Apply(restored, new BagDeleteEvent(1, 2, 0));
        Assert.Equal(before, ReservationPlanningParityTests.ProjectCheckpoint(saved).ToJsonString());
        Assert.False(saved.Holds[0].Rows[0].Uncertain); Assert.True(marked.Holds[0].Rows[0].Uncertain);
        Assert.Empty(released.Holds); Assert.Empty(deducted.Holds);
        Assert.Equal(new BigInteger(2), restored.Holds[0].Rows[0].Remaining);
        Assert.Throws<NotSupportedException>(() => ((IList<StorageReservationGroup>)saved.Holds).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<StorageReservationSnapshot>)saved.Holds[0].Rows).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)saved.AlchemySlots).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, BigInteger>)saved.Reserved).Clear());
        var builder = saved.Holds.ToBuilder(); builder.Clear();
        Assert.Single(saved.Holds); Assert.Equal(before, ReservationPlanningParityTests.ProjectCheckpoint(saved).ToJsonString());
    }

    [Fact]
    public void SlotsUseFirstOccurrencesWithoutFilteringZeroUncertainOrMismatchedRows()
    {
        var state = Bag() with { Holds = [new("alchemy", [Hold(10, 0), Hold(1) with { Uncertain = true },
            Hold(10, -3), Hold(65535) with { Identity = new(43, null, null) }])], AlchemySlots = [2] };
        var projected = InventoryReservationPlanning.ProjectSlots(state, "alchemy");
        Assert.Equal(new ushort[] { 10, 1, 65535 }, projected.AlchemySlots!.Value);
        Assert.Equal(state.Holds, projected.Holds); Assert.Same(state.Reserved, projected.Reserved);
        Assert.Equal(state.ExpeditionSlots, projected.ExpeditionSlots); Assert.Equal(state.MaintenanceSlots, projected.MaintenanceSlots);
        Assert.Same(state, InventoryReservationPlanning.ProjectSlots(state, "Alchemy"));
    }

    [Fact]
    public void LockedIsIndependentOfCountsReadinessAndItemPresenceAndDoesNotCoerceRawIndices()
    {
        var state = BagReceiveSnapshot.Empty with { AlchemySlots = [0], MaintenanceSlots = [65535],
            Holds = [new("legacy", [Hold() with { Remaining = 0, Uncertain = true }, Hold(2, 0)])] };
        Assert.True(InventoryReservationPlanning.Locked(state, 0));
        Assert.True(InventoryReservationPlanning.Locked(state, 1));
        Assert.True(InventoryReservationPlanning.Locked(state, 65535));
        Assert.False(InventoryReservationPlanning.Locked(state, 2));
        Assert.True(InventoryReservationPlanning.Locked(state, StateValue.Scalar("1")));
        foreach (var raw in new[] { StateValue.Scalar(true), StateValue.Scalar(false), StateValue.Scalar(1.0),
                     StateValue.Scalar("01"), StateValue.Scalar("+1"), StateValue.Scalar(" 1"), StateValue.Null,
                     StateValue.List(), StateValue.Map(), StateValue.Scalar(BigInteger.One << 128) })
            Assert.False(InventoryReservationPlanning.Locked(state, raw));
        Assert.Equal(BigInteger.Zero, BagReceiveReducer.Available(state, 1));
    }

    [Fact]
    public void IdentityIsOnlyItemSerialAndSerialVersionNotCurrentSlotQuantityOrDamage()
    {
        var item = new BagItemSnapshot(Item(), 255, -100, 0xffffffff);
        var expected = new StorageReservationIdentity(42, 1234, 7);
        Assert.Equal(expected, InventoryReservationPlanning.Identity(item));
        Assert.Equal(expected, InventoryReservationPlanning.Identity(item with { Index = 0, Count = int.MaxValue, Damage = 0 }));
        Assert.NotEqual(expected, InventoryReservationPlanning.Identity(item with { OriginalRecord = Item() with { SerialVersion = 8 } }));
    }

    [Fact]
    public void TypedBoundaryRejectsNullWithoutReplacingAnySnapshot()
    {
        var state = Bag();
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.Identity(null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.Locked(null!, (ushort)1));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.Locked(state, (StateValue)null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanRelease(null!, "battle"));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanRelease(state, null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanUncertain(null!, "battle"));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanUncertain(state, null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.Checkpoint(null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanRestore(state, null!));
        Assert.Throws<ArgumentNullException>(() => InventoryReservationPlanning.PlanRestore(null!, InventoryReservationPlanning.Checkpoint(state)));
        Assert.Empty(state.Holds);
    }
}
