using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CraftingReducerTests
{
    private static CraftScheduleRow Row(byte index = 1, ushort item = 42, double elapsed = 1.25, ushort? recipe = null) =>
        new(index, item, elapsed, 2, 20, recipe);
    private static FurnitureRecord Furniture(ushort index = 7, ushort item = 39053) =>
        new(index, item, 1, 2, 3, 4, 65535, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 255, 0);
    private static CraftingReceiveSnapshot Apply(CraftingReceiveSnapshot state, InventoryEvent observation, double at = 100.25, uint? role = 100) =>
        CraftingReducer.Apply(state, observation, role, at);
    private static CraftingReceiveSnapshot Barrier(CraftingReceiveSnapshot state, uint? role = 100) =>
        CraftingReducer.Apply(state, new InitialDataCompleteEvent(), role, 100.25);

    [Fact]
    public void DefaultsAreColdAndResetIsExplicitNotAnIncomingSnapshot()
    {
        var state = CraftingReceiveSnapshot.Empty;
        Assert.False(state.Crafting.Ready); Assert.False(state.Furniture.Ready);
        Assert.Empty(state.Crafting.Queue); Assert.Empty(state.Furniture.Items);
        Assert.Equal(0, state.Crafting.Active); Assert.Null(state.Crafting.StartedAt);
        Assert.False(state.Crafting.Running); Assert.False(state.Crafting.AutoContinue);
        Assert.Null(state.Crafting.Pending); Assert.False(state.Crafting.CompletionRequested);
        Assert.Equal(BigInteger.Zero, state.Crafting.Completed); Assert.Equal(BigInteger.Zero, state.Crafting.Revision);
        Assert.False(state.Crafting.Uncertain); Assert.Null(state.Crafting.SyncSource);
        Assert.Null(state.Furniture.Owner); Assert.Null(state.Furniture.CurrentOwner); Assert.Null(state.Furniture.PersonalBatch);
        var next = Apply(state, new CraftSnapshotEvent([], 0));
        Assert.True(next.Crafting.Ready); Assert.Equal(100.25, next.Crafting.StartedAt);
        Assert.False(next.Crafting.Running); Assert.False(new CraftingReceiveSnapshot().Crafting.Ready);
        Assert.False(state.Crafting.Ready);
    }

    [Fact]
    public void InitialBarrierKeepsIncrementalQueueAndRepeatedBarrierDoesNotReviseReadyCrafting()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftAddedEvent(Row(255)));
        Assert.False(state.Crafting.Ready);
        var ready = Barrier(state);
        Assert.True(ready.Crafting.Ready); Assert.Equal("S1-11", ready.Crafting.SyncSource);
        Assert.Same(state.Crafting.Queue, ready.Crafting.Queue);
        Assert.Equal(state.Crafting.Revision + 1, ready.Crafting.Revision);
        Assert.Same(ready, Barrier(ready));
    }

    [Theory]
    [InlineData("add", false)] [InlineData(null, true)]
    public void BarrierNeverResolvesPendingOrUncertainState(string? pending, bool uncertain)
    {
        var state = new CraftingReceiveSnapshot { Crafting = new() { Pending = pending, Uncertain = uncertain } };
        Assert.Same(state, Barrier(state));
    }

    [Fact]
    public void MissingActiveBarrierSetsUncertaintyWithoutMakingReady()
    {
        var state = new CraftingReceiveSnapshot { Crafting = new() { Active = 7, Running = true, StartedAt = 1 } };
        var next = Barrier(state);
        Assert.True(next.Crafting.Uncertain); Assert.False(next.Crafting.Ready);
        Assert.True(next.Crafting.Running); Assert.Equal(7, next.Crafting.Active);
        Assert.Equal(1, next.Crafting.StartedAt); Assert.Equal(BigInteger.One, next.Crafting.Revision);
        Assert.Same(next, Barrier(next));
    }

    [Fact]
    public void SnapshotReplacesQueueAndClearsUncertaintyOnlyWhenActiveIsPresent()
    {
        var state = new CraftingReceiveSnapshot { Crafting = new()
        {
            Queue = ImmutableDictionary<byte, CraftScheduleRow>.Empty.Add(9, Row(9)), QueueOrder = [9], Pending = "add",
            AutoContinue = true, Uncertain = true, Completed = 9, CompletionRequested = true, HumanIndex = 7, HumanId = 42
        } };
        var missing = Apply(state, new CraftSnapshotEvent([Row(1)], 255));
        Assert.True(missing.Crafting.Ready); Assert.True(missing.Crafting.Uncertain); Assert.False(missing.Crafting.Running);
        Assert.Equal(255, missing.Crafting.Active); Assert.Equal(100.25, missing.Crafting.StartedAt);
        var valid = Apply(missing, new CraftSnapshotEvent([Row(2, recipe: 100)], 2));
        Assert.False(valid.Crafting.Uncertain); Assert.True(valid.Crafting.Running);
        Assert.Equal("S64-1", valid.Crafting.SyncSource); Assert.Equal(new byte[] { 2 }, valid.Crafting.Queue.Keys);
        Assert.Equal((ushort)100, valid.Crafting.Queue[2].RecipeId);
        Assert.Equal("add", valid.Crafting.Pending); Assert.True(valid.Crafting.AutoContinue);
        Assert.Equal(new BigInteger(9), valid.Crafting.Completed); Assert.Equal(7, valid.Crafting.HumanIndex);
        Assert.False(valid.Crafting.CompletionRequested); Assert.Equal(42u, valid.Crafting.HumanId);
        Assert.True(state.Crafting.CompletionRequested); Assert.Contains((byte)9, state.Crafting.Queue.Keys);
    }

    [Fact]
    public void MissingStartPreservesExistingRunningAnchorAndDoesNotClearPending()
    {
        var running = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row()], 1));
        running = running with { Crafting = running.Crafting with { AutoContinue = true, Pending = "start", CompletionRequested = true } };
        var next = Apply(running, new CraftStartedEvent(255), 900);
        Assert.True(next.Crafting.Uncertain); Assert.True(next.Crafting.Running); Assert.Equal(1, next.Crafting.Active);
        Assert.Equal(running.Crafting.StartedAt, next.Crafting.StartedAt); Assert.True(next.Crafting.AutoContinue);
        Assert.Equal("start", next.Crafting.Pending); Assert.True(next.Crafting.CompletionRequested);
    }

    [Fact]
    public void RepeatedStartReanchorsElapsedAndPauseAccumulatesOnlyForTheActiveRow()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row(), Row(2)], 1), 100);
        var restarted = Apply(state, new CraftStartedEvent(1), 150);
        Assert.Equal(11.25, CraftingReducer.Elapsed(restarted.Crafting, restarted.Crafting.Queue[1], 160));
        var paused = Apply(restarted, new CraftPausedEvent(1), 160);
        Assert.Equal(11.25, paused.Crafting.Queue[1].Elapsed); Assert.Null(paused.Crafting.StartedAt);
        Assert.Equal(1.25, state.Crafting.Queue[1].Elapsed);
        var repeated = Apply(paused, new CraftPausedEvent(1), 999);
        Assert.Equal(11.25, repeated.Crafting.Queue[1].Elapsed);
        var other = Apply(state, new CraftPausedEvent(2), 200);
        Assert.Equal(1.25, other.Crafting.Queue[2].Elapsed); Assert.False(other.Crafting.Running);
    }

    [Fact]
    public void CompletionRequiresRunningMatchingRowAndNeverProvesInventoryReceipt()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row(7), Row(3, 50), Row(255, 99)], 7));
        state = state with { Crafting = state.Crafting with { Pending = "complete", Uncertain = true, AutoContinue = true } };
        var wrong = Apply(state, new CraftCompletedEvent(3, 500));
        Assert.Equal(BigInteger.Zero, wrong.Crafting.Completed); Assert.Same(state.Crafting.Queue, wrong.Crafting.Queue);
        var complete = Apply(wrong, new CraftCompletedEvent(7, 500));
        Assert.Equal(BigInteger.One, complete.Crafting.Completed); Assert.False(complete.Crafting.Running);
        Assert.Equal((ushort)50, complete.Crafting.Queue[1].ItemId); Assert.Equal((ushort)99, complete.Crafting.Queue[2].ItemId);
        Assert.Equal("complete", complete.Crafting.Pending); Assert.True(complete.Crafting.Uncertain); Assert.True(complete.Crafting.AutoContinue);
        Assert.Contains("等待確認產物", complete.Crafting.Status);
        var duplicate = Apply(complete, new CraftCompletedEvent(1, 500));
        Assert.Same(complete.Crafting.Queue, duplicate.Crafting.Queue); Assert.Equal(complete.Crafting.Completed, duplicate.Crafting.Completed);
        Assert.Equal(complete.Crafting.Revision + 1, duplicate.Crafting.Revision);
    }

    [Theory]
    [InlineData(6, "包包空間不足")] [InlineData(7, "住宅空間不足")] [InlineData(8, "器具數量已達上限")]
    public void FailureClearsOnlySourceFieldsAndDoesNotResolveUnknownOutcome(byte sub, string reason)
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row()], 1));
        state = state with { Crafting = state.Crafting with { Pending = "complete", Uncertain = true, AutoContinue = true, CompletionRequested = true } };
        var failed = Apply(state, new CraftFailedEvent(sub, 255, 65535, reason));
        Assert.False(failed.Crafting.Running); Assert.Equal(0, failed.Crafting.Active); Assert.False(failed.Crafting.AutoContinue);
        Assert.False(failed.Crafting.CompletionRequested); Assert.Equal(reason, failed.Crafting.Status);
        Assert.Equal("complete", failed.Crafting.Pending); Assert.True(failed.Crafting.Uncertain);
        Assert.Equal(state.Crafting.StartedAt, failed.Crafting.StartedAt); Assert.Same(state.Crafting.Queue, failed.Crafting.Queue);
    }

    [Fact]
    public void DeletionAndSwapsDoNotRepairActiveIndicesOrInventMissingRows()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row(7), Row(3, 50), Row(255, 99)], 255));
        var deleted = Apply(state, new CraftDeletedEvent(0));
        Assert.Equal(new byte[] { 1, 2, 3 }, deleted.Crafting.Queue.Keys.Order());
        Assert.Equal(255, deleted.Crafting.Active); Assert.True(deleted.Crafting.Running);
        var swapped = Apply(deleted, new CraftSwappedEvent(true, 1, 3));
        Assert.Equal((ushort)99, swapped.Crafting.Queue[1].ItemId); Assert.Equal((ushort)50, swapped.Crafting.Queue[3].ItemId);
        Assert.Equal(1, swapped.Crafting.Queue[1].Index); Assert.Equal(3, swapped.Crafting.Queue[3].Index);
        var missing = Apply(swapped, new CraftSwappedEvent(true, 1, 255));
        Assert.Same(swapped.Crafting.Queue, missing.Crafting.Queue); Assert.Equal("製作順序已更新", missing.Crafting.Status);
        Assert.Equal((ushort)50, deleted.Crafting.Queue[1].ItemId);
    }

    [Fact]
    public void FurnitureSnapshotPreservesPersonalFurnitureWhileVisitingAnotherOwner()
    {
        var personal = Apply(CraftingReceiveSnapshot.Empty, new FurnitureSnapshotEvent(100, [Furniture()]));
        var visitor = Apply(personal, new FurnitureSnapshotEvent(200, [Furniture(9)]));
        Assert.Equal(200u, visitor.Furniture.CurrentOwner); Assert.Equal(100u, visitor.Furniture.Owner);
        Assert.True(visitor.Furniture.Ready); Assert.Same(personal.Furniture.Items, visitor.Furniture.Items);
        var ignored = Apply(visitor, new FurnitureRemovedEvent(7));
        Assert.Same(visitor.Furniture.Items, ignored.Furniture.Items); Assert.Equal(visitor.Furniture.Revision + 1, ignored.Furniture.Revision);
        var replaced = Apply(ignored, new FurnitureSnapshotEvent(100, []));
        Assert.True(replaced.Furniture.Ready); Assert.Empty(replaced.Furniture.Items);
    }

    [Fact]
    public void PersonalBatchBecomesReadyOnlyAtOwnedInitialBarrier()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new FurnitureAddedEvent(2, Furniture()));
        Assert.False(state.Furniture.Ready); Assert.True(state.Furniture.PersonalBatch); Assert.Equal(100u, state.Furniture.Owner);
        Assert.Null(state.Furniture.CurrentOwner);
        var wrongRole = Barrier(state, 200); Assert.False(wrongRole.Furniture.Ready);
        var rightRole = Barrier(state); Assert.True(rightRole.Furniture.Ready);
        Assert.Equal(state.Furniture.Revision + 1, rightRole.Furniture.Revision);
        var again = Barrier(rightRole); Assert.Equal(rightRole.Furniture.Revision + 1, again.Furniture.Revision);
    }

    [Fact]
    public void ToolNoticeCreatesSparseRecordAndRetainDoesNotMutateEarlierSnapshots()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new FurnitureSnapshotEvent(100, [Furniture()]));
        var tool = Apply(state, new FurnitureToolEvent(1, 7, 42, 55));
        var row = tool.Furniture.Items[7]; Assert.Null(row.X); Assert.Null(row.Y); Assert.Null(row.Z);
        Assert.Null(row.Direction); Assert.Null(row.Contents); Assert.Equal(0, row.Floor); Assert.Equal(0, row.Status);
        Assert.NotNull(state.Furniture.Items[7].Contents);
        var retained = Apply(tool, new FurnitureRetainedEvent(7));
        Assert.Equal(1, retained.Furniture.Items[7].Status); Assert.Equal(0, tool.Furniture.Items[7].Status);
        var removed = Apply(retained, new FurnitureToolEvent(2, 7, 99, 77), role: 200);
        Assert.Empty(removed.Furniture.Items); Assert.Equal(100u, removed.Furniture.Owner);
    }

    [Fact]
    public void FurnitureInsertionOrderSurvivesDuplicatesReplacementRemovalAndReinsertion()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new FurnitureSnapshotEvent(100,
            [Furniture(9), Furniture(2), Furniture(9, 42)]));
        Assert.Equal(new ushort[] { 9, 2 }, state.Furniture.ItemOrder);
        var replaced = Apply(state, new FurnitureAddedEvent(1, Furniture(9)));
        Assert.Equal(state.Furniture.ItemOrder, replaced.Furniture.ItemOrder);
        // Source tools() would select index 2 for this duplicate item ID, not numeric max 9.
        Assert.Equal((ushort)2, replaced.Furniture.ItemOrder.Last(index => replaced.Furniture.Items[index].ItemId == 39053));
        var removed = Apply(replaced, new FurnitureRemovedEvent(9));
        var readded = Apply(removed, new FurnitureToolEvent(1, 9, 39053, 55));
        Assert.Equal(new ushort[] { 2, 9 }, readded.Furniture.ItemOrder);
        Assert.Equal(new ushort[] { 9, 2 }, state.Furniture.ItemOrder);
        var visiting = Apply(readded, new FurnitureSnapshotEvent(200, [Furniture(7)]));
        Assert.Equal(readded.Furniture.ItemOrder, visiting.Furniture.ItemOrder);
    }

    [Fact]
    public void QueueInsertionOrderSurvivesReplacementsAndSwapsUntilExplicitCompaction()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row(9), Row(2), Row(9, 50)], 0));
        Assert.Equal(new byte[] { 9, 2 }, state.Crafting.QueueOrder);
        var replaced = Apply(state, new CraftAddedEvent(Row(9, 99)));
        var added = Apply(replaced, new CraftAddedEvent(Row(7)));
        var swapped = Apply(added, new CraftSwappedEvent(true, 9, 2));
        Assert.Equal(new byte[] { 9, 2, 7 }, swapped.Crafting.QueueOrder);
        var compacted = Apply(swapped, new CraftDeletedEvent(0));
        Assert.Equal(new byte[] { 1, 2, 3 }, compacted.Crafting.QueueOrder);
        Assert.Equal((ushort)99, compacted.Crafting.Queue[1].ItemId);
        Assert.Equal(new byte[] { 9, 2 }, state.Crafting.QueueOrder);
    }

    [Fact]
    public void AbsentPlayerIdentityUsesNullableSourceComparisonWithoutClaimingOwnership()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new FurnitureToolEvent(1, 7, 42, 55), role: null);
        Assert.Single(state.Furniture.Items); Assert.Null(state.Furniture.Owner); Assert.False(state.Furniture.Ready);
        var ignored = Apply(CraftingReceiveSnapshot.Empty, new FurnitureToolEvent(1, 7, 42, 55), role: 0);
        Assert.Empty(ignored.Furniture.Items);
    }

    [Fact]
    public void ExplicitLayoutIsStillRequiredAndReadyStateNeverSelectsIt()
    {
        var state = Barrier(CraftingReceiveSnapshot.Empty);
        var packet = new Packet(64, 16, new PacketWriter().U8(1).U16(42).U32(0).U8(1).U32(0).Build());
        Assert.Throws<InvalidOperationException>(() => CraftingDecoder.Decode(packet));
        Assert.IsType<UnsupportedServerDecoderEvent>(ServerProtocol.Decode(packet));
        var context = CraftingScheduleContext.FromRuntimeRows([new(42, 65535)]);
        var next = Apply(state, CraftingDecoder.Decode(packet, context)!);
        Assert.Equal((ushort)42, next.Crafting.Queue[1].RecipeId); Assert.Equal((ushort)65535, next.Crafting.Queue[1].ItemId);
        Assert.Empty(state.Crafting.Queue);
        Assert.Throws<ProtocolException>(() => CraftingDecoder.Decode(packet,
            CraftingScheduleContext.FromRuntimeRows([new(1, 500)])));
    }

    [Fact]
    public void LargeTimeQueryDoesNotCompleteOrRequestAnything()
    {
        var state = Apply(CraftingReceiveSnapshot.Empty, new CraftSnapshotEvent([Row()], 1));
        Assert.True(CraftingReducer.Elapsed(state.Crafting, state.Crafting.Queue[1], 1e100) > state.Crafting.Queue[1].BaseTime);
        Assert.True(state.Crafting.Running); Assert.Equal(BigInteger.Zero, state.Crafting.Completed);
        Assert.False(state.Crafting.CompletionRequested); Assert.Null(state.Crafting.Pending);
        Assert.Equal(1.25, CraftingReducer.Elapsed(state.Crafting, state.Crafting.Queue[1], -1000));
    }

    [Theory]
    [InlineData(double.NaN)] [InlineData(double.PositiveInfinity)] [InlineData(double.NegativeInfinity)]
    public void NonfiniteCallerTimeCannotEnterRunningState(double time)
    {
        var state = CraftingReceiveSnapshot.Empty;
        Assert.Throws<ArgumentOutOfRangeException>(() => Apply(state, new CraftSnapshotEvent([Row()], 1), time));
        var added = Apply(state, new CraftAddedEvent(Row()));
        Assert.Throws<ArgumentOutOfRangeException>(() => Apply(added, new CraftStartedEvent(1), time));
        Assert.False(added.Crafting.Running); Assert.Null(added.Crafting.StartedAt);
    }

    private sealed record NamedEvent(string Name) : InventoryEvent(0, 0) { public override string Type => Name; }

    [Fact]
    public void UnknownCraftNoticeCountsButUnsupportedServerAndUnrelatedEventsAreNoOps()
    {
        var state = CraftingReceiveSnapshot.Empty;
        var future = Apply(state, new NamedEvent("craft_future"));
        Assert.Equal(BigInteger.One, future.Crafting.Revision); Assert.Same(state.Crafting.Queue, future.Crafting.Queue);
        Assert.Same(state, Apply(state, new NamedEvent("bag_add")));
        Assert.Same(state, CraftingReducer.Apply(state, new UnsupportedServerDecoderEvent(64, 1, "crafting", 1), 100, 1));
        Assert.Same(state, CraftingReducer.Apply(state, new HeartbeatRequestEvent(), 100, 1));
    }
}
