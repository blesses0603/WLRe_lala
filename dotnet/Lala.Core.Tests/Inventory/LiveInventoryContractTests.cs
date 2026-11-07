using System.Collections.Immutable;
using System.Numerics;
using System.Text;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class LiveInventoryContractTests
{
    private static ItemSave Item(byte? index = 1, ushort id = 42, byte count = 1) =>
        new(index, id, count, 0, 2, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, [new(1, 2)], false, 0, 0, 0);
    private static CompanionSnapshot Companion(byte? index = 1, uint npc = 42) =>
        new(index, npc, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2, 3, "synthetic", [new(1, 10)], [Item()], 0, 1, 2, 3, 4, 5, 6);
    private static readonly ImmutableDictionary<ushort, bool> Stackable = ImmutableDictionary<ushort, bool>.Empty.Add(42, true);

    [Fact]
    public void InitialSnapshotsDoNotInventReadinessAuthorityOrCatalogs()
    {
        var bag = BagReceiveSnapshot.Empty;
        Assert.False(bag.Ready); Assert.False(bag.Reliable); Assert.Null(bag.Capacity);
        Assert.Null(bag.ServerStackable); Assert.Null(bag.FieldSupply);
        Assert.False(CompanionReceiveSnapshot.Empty.Ready); Assert.Null(CompanionReceiveSnapshot.Empty.ActiveNpcId);
        var added = BagReceiveReducer.Apply(bag, new BagAddEvent(Item(), 0));
        Assert.Single(added.Items); Assert.False(added.Ready); Assert.False(added.Reliable);
    }

    [Fact]
    public void UnknownStackRulesFailExceptSingleExplicitFreeSlot()
    {
        var empty = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(2, []));
        Assert.True(BagReceiveReducer.Apply(empty, new BagAddEvent(Item(), 0)).Reliable);
        Assert.False(BagReceiveReducer.Apply(empty, new BagAddEvent(Item(0), 0)).Reliable);
        Assert.False(BagReceiveReducer.Apply(empty, new BagAddEvent(Item(3), 0)).Reliable);
        Assert.False(BagReceiveReducer.Apply(empty, new BagAddEvent(Item(count: 2), 0)).Reliable);
        Assert.False(BagReceiveReducer.Apply(empty, new BagAddEvent(Item(null), 0)).Reliable);
    }

    [Fact]
    public void SlotMetadataAndFirstInsertionOrderSurviveStackUpdates()
    {
        var seed = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(5, [Item(3, count: 2), Item(1, count: 3)]));
        var next = BagReceiveReducer.Apply(seed, new BagAddEvent(Item(0) with { Serial = 99, SerialVersion = 8 }, 0), Stackable);
        Assert.Equal(new byte[] { 3, 1 }, next.ItemOrder);
        Assert.Equal(3, next.Items[3].Count); Assert.Equal(3, next.Items[1].Count);
        Assert.Equal(9U, next.Items[3].OriginalRecord.Serial); Assert.Equal((byte)2, next.Items[3].OriginalRecord.SerialVersion);
        Assert.Equal(2, seed.Items[3].Count);
    }

    [Fact]
    public void FailedAddRollsBackItemsButLatchesReliabilityAndRevision()
    {
        var seed = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(1, [Item(count: 199)]));
        var failed = BagReceiveReducer.Apply(seed, new BagAddEvent(Item(count: 2), 0), Stackable);
        Assert.Same(seed.Items, failed.Items); Assert.Equal(199, failed.Items[1].Count);
        Assert.False(failed.Reliable); Assert.Equal(seed.Revision + 1, failed.Revision);
    }

    [Fact]
    public void InvalidSnapshotDiscardsPartialRowsButRecoversOnNextValidSnapshot()
    {
        var invalid = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(2, [Item(), Item()]));
        Assert.True(invalid.Ready); Assert.False(invalid.Reliable); Assert.Empty(invalid.Items);
        var fresh = BagReceiveReducer.Apply(invalid, new BagSnapshotEvent(2, [Item(2)]));
        Assert.True(fresh.Reliable); Assert.Null(fresh.SyncError); Assert.Single(fresh.Items);
    }

    [Fact]
    public void StorageEvidenceMustBeExplicitlyImportedAndOverridesCatalogProjection()
    {
        var storage = RoomStorageReducer.Apply(StorageReceiveSnapshot.Empty, new StorageMaterialsAddEvent([new(1, 42, 2)]));
        var bag = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(5, []));
        var rules = ImmutableDictionary<ushort, bool>.Empty.Add(42, false);
        var separate = BagReceiveReducer.Apply(bag, new BagAddEvent(Item(count: 2), 0), rules);
        Assert.Equal(2, separate.Items.Count);
        var imported = BagReceiveReducer.Apply(bag with { ServerStackable = storage.ServerStackable }, new BagAddEvent(Item(count: 2), 0), rules);
        Assert.Single(imported.Items); Assert.Equal(2, imported.Items[1].Count);
        var refreshed = BagReceiveReducer.Apply(imported, new BagSnapshotEvent(5, []));
        Assert.Same(storage.ServerStackable, refreshed.ServerStackable);
    }

    [Fact]
    public void InvalidDeductionStillConsumesOnlyReceiveReservationCounters()
    {
        var row = new StorageReservationSnapshot(1, new(42, 9, 2), 5, 5, 10, true, false);
        var bag = BagReceiveSnapshot.Empty with
        {
            Holds = [new("crafting", [row])], Reserved = ImmutableDictionary<ushort, BigInteger>.Empty.Add(1, 5),
            AlchemySlots = [1]
        };
        var next = BagReceiveReducer.Apply(bag, new BagDeleteEvent(1, 3, 0));
        Assert.False(next.Reliable); Assert.Equal(new BigInteger(2), next.Reserved[1]);
        Assert.Equal(new BigInteger(2), next.Holds[0].Rows[0].Remaining);
        Assert.True(next.Holds[0].Rows[0].Exclusive); Assert.Equal(bag.AlchemySlots, next.AlchemySlots);
        Assert.Equal(BigInteger.Zero, BagReceiveReducer.Available(next, 1));
    }

    [Fact]
    public void ItemUseFailureIsLatchedUntilFullBagSnapshotAndNeverInfersConsumption()
    {
        var seed = BagReceiveReducer.Apply(BagReceiveSnapshot.Empty, new BagSnapshotEvent(2, [Item()]));
        var failed = BagReceiveReducer.Apply(seed, new ItemUseResultEvent(3, null, null));
        var acknowledged = BagReceiveReducer.Apply(failed, new ItemUseResultEvent(0, null, null));
        Assert.True(acknowledged.UseFailed); Assert.Same(seed.Items, acknowledged.Items); Assert.Equal(seed.Revision, acknowledged.Revision);
        var fresh = BagReceiveReducer.Apply(acknowledged, new BagSnapshotEvent(2, [Item()]));
        Assert.False(fresh.UseFailed); Assert.Null(fresh.LastUseResult);
    }

    [Fact]
    public void FieldSupplyAndDeepCollectionsAreImmutableAcrossRefresh()
    {
        var supplied = StateValue.Map(("pending", StateValue.Scalar(true)), ("nested", StateValue.List(StateValue.Scalar(1))));
        var seed = BagReceiveSnapshot.Empty with { FieldSupply = supplied };
        var fresh = BagReceiveReducer.Apply(seed, new BagSnapshotEvent(2, [Item()]));
        Assert.Same(supplied, fresh.FieldSupply);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<byte, BagItemSnapshot>)fresh.Items).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)fresh.ItemOrder).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)fresh.Items[1].OriginalRecord.Plugins).Clear());
        Assert.Empty(seed.Items);
    }

    [Fact]
    public void CompanionAddRequiresReadinessAndMatchingExplicitRole()
    {
        var add = new CompanionAddEvent(7, Companion(null), 0);
        Assert.Same(CompanionReceiveSnapshot.Empty, CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, add, 7));
        var ready = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([]));
        Assert.Same(ready, CompanionReceiveReducer.Apply(ready, add));
        Assert.Same(ready, CompanionReceiveReducer.Apply(ready, add, 8));
        var next = CompanionReceiveReducer.Apply(ready, add, 7);
        Assert.Single(next.Companions); Assert.Equal((byte)1, next.Companions[1].Data.Index);
        Assert.Empty(next.Companions[1].Skills); Assert.Single(next.Companions[1].Data.SkillSlots);
    }

    [Fact]
    public void CompanionSnapshotsAppendAndSlotReassignmentClearsOnlyThatAttributeBuffer()
    {
        var buffered = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new AttributeSetEvent(2, "follow:1", 4, 1, 25, "hp", 1, 999, 0));
        var first = CompanionReceiveReducer.Apply(buffered, new CompanionSnapshotEvent([Companion()]));
        Assert.Equal(999, first.Companions[1].StatOverrides["hp"]);
        var same = CompanionReceiveReducer.Apply(first, new CompanionSnapshotEvent([Companion(2), Companion()]));
        Assert.Equal(2, same.Companions.Count); Assert.Equal(999, same.Companions[1].StatOverrides["hp"]);
        var different = CompanionReceiveReducer.Apply(same, new CompanionSnapshotEvent([Companion(npc: 43)]));
        Assert.Equal(2, different.Companions.Count); Assert.Empty(different.Companions[1].StatOverrides);
        Assert.False(different.Attributes.ContainsKey(1)); Assert.True(first.Attributes.ContainsKey(1));
    }

    [Fact]
    public void CompanionDeleteDoesNotInferActiveCompanionChangeAndPreservesOtherOwners()
    {
        var state = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([Companion()]));
        state = CompanionReceiveReducer.Apply(state, new ActiveCompanionEvent(1, 42));
        Assert.Same(state, CompanionReceiveReducer.Apply(state, new CompanionDeleteEvent(8, 1, 0), 7));
        var next = CompanionReceiveReducer.Apply(state, new CompanionDeleteEvent(7, 1, 0), 7);
        Assert.Empty(next.Companions); Assert.Equal(42U, next.ActiveNpcId); Assert.True(next.Ready);
    }

    [Fact]
    public void CompanionCollectionsAndRawEquipmentRemainDeeplyImmutable()
    {
        var state = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([Companion()]));
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, CompanionProfileSnapshot>)state.Companions).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<CompanionSkillSlot>)state.Companions[1].Data.SkillSlots).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemSave>)state.Companions[1].Data.Equips).Clear());
        Assert.Throws<ArgumentException>(() => CompanionReceiveReducer.Apply(state, new CompanionSnapshotEvent([Companion(null)])));
    }

    [Fact]
    public void OutOfScopeKnowledgeAndSessionEventsDoNotSilentlyBecomeSupported()
    {
        var bag = BagReceiveSnapshot.Empty;
        var companions = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([Companion()]));
        foreach (LiveDataEvent observation in new LiveDataEvent[] { new StarInfoEvent(1, 2, 3), new PlayerEquipDataEvent([Item()]),
            new EquipDamageEvent(28, 1, 1, 50), new BattleEquipEvent(7, 1, 1, 99, 1), new ShopPurchaseResultEvent(0) })
        {
            Assert.Same(bag, BagReceiveReducer.Apply(bag, observation));
            Assert.Same(companions, CompanionReceiveReducer.Apply(companions, observation, 7));
        }
        Assert.Same(bag, BagReceiveReducer.Apply(bag, new InitialDataCompleteEvent()));
        Assert.Same(companions, CompanionReceiveReducer.Apply(companions, new InitialDataCompleteEvent()));
    }

    [Fact]
    public void SourceFingerprintCanonicalizesOnlyCrLfAndStillDetectsContentChanges()
    {
        var unix = Encoding.UTF8.GetBytes("first\nsecond\n");
        var windows = Encoding.UTF8.GetBytes("first\r\nsecond\r\n");
        Assert.Equal(LiveInventoryParityTests.CanonicalSourceHash(unix), LiveInventoryParityTests.CanonicalSourceHash(windows));
        Assert.NotEqual(LiveInventoryParityTests.CanonicalSourceHash(unix), LiveInventoryParityTests.CanonicalSourceHash(Encoding.UTF8.GetBytes("first\nchanged\n")));
    }

    [Fact]
    public void SourceFingerprintRetainsInvalidUtf8BytesBomAndBareCarriageReturn()
    {
        Assert.NotEqual(LiveInventoryParityTests.CanonicalSourceHash([0x80]), LiveInventoryParityTests.CanonicalSourceHash([0x81]));
        Assert.NotEqual(LiveInventoryParityTests.CanonicalSourceHash([0x0d]), LiveInventoryParityTests.CanonicalSourceHash([0x0a]));
        Assert.NotEqual(LiveInventoryParityTests.CanonicalSourceHash([0xef, 0xbb, 0xbf, 0x61]), LiveInventoryParityTests.CanonicalSourceHash([0x61]));
        Assert.Equal(LiveInventoryParityTests.CanonicalSourceHash([0x80, 0x0a, 0x81]), LiveInventoryParityTests.CanonicalSourceHash([0x80, 0x0d, 0x0a, 0x81]));
    }

}
