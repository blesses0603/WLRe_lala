using System.Collections.Immutable;
using Lala.Core.Automation;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class AutomationSafetyTests
{
    private static AutomationContext Context => AutomationParityTests.SafeContext();
    private static DailyCatalogInput Input => new(AutomationParityTests.Catalog(), "synthetic-A");
    private static TimeCubeState Cube(byte count = 1) => TimeCubeService.Apply(new(), new CubeInfo(0, count, 1, 0), 1, 0);
    private static DailyTaskState Daily()
    {
        var d = DailyTaskService.WorldPlayer(new(), 1);
        d = DailyTaskService.Apply(d, new TaskSnapshot(new(50, 100, 0, 0, 0, 0, 0, 0, 0, 0),
            Enumerable.Repeat((byte)1, 8).ToImmutableArray(), Enumerable.Repeat((byte)1, 12).ToImmutableArray(), true, false));
        d = DailyTaskService.Apply(d, new TaskGroups(1, 2));
        return DailyTaskService.Tick(d, Context with { AutomationEnabled = false }, Input, 0).State;
    }
    [Fact]
    public void DefaultResourceObservationIsFailClosed()
    {
        Assert.True(new AutomationContext().ResourceHeld);
        var held = Context with { ResourceHeld = true };
        Assert.Null(TimeCubeService.Tick(Cube(), held, 1).Candidate);
        Assert.Null(DailyTaskService.Tick(Daily(), held, Input, 1).Candidate);
        Assert.Throws<ProtocolException>(() => TimeCubeService.RequestOpen(Cube(), held, 1));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Request(Daily(), held, Input, DailyClaimAction.ClaimReady, 1));
    }
    [Fact]
    public void StopDuringHoldPreservesOutstandingEvidenceAndDoesNotGrantRetry()
    {
        var c = TimeCubeService.RequestOpen(Cube(), Context, 1).State;
        var d = DailyTaskService.Request(Daily(), Context, Input, DailyClaimAction.ClaimReady, 1).State;
        var cp = c.Pending; var dp = d.Pending;
        c = TimeCubeService.SetAutomatic(c, false, true); d = DailyTaskService.SetAutomatic(d, false, true);
        Assert.Same(cp, c.Pending); Assert.Same(dp, d.Pending);
        Assert.Throws<ProtocolException>(() => TimeCubeService.SetAutomatic(c, true, true));
        Assert.Throws<ProtocolException>(() => DailyTaskService.SetAutomatic(d, true, true));
        var held = Context with { ResourceHeld = true, WorldAcknowledged = false, AutomationEnabled = false };
        Assert.True(TimeCubeService.Tick(c, held, 16).State.Uncertain);
        Assert.True(DailyTaskService.Tick(d, held, Input, 21).State.Uncertain);
    }
    [Fact]
    public void BothManualRequestsRequireWorldAcknowledgement()
    {
        var context = Context with { WorldAcknowledged = false };
        Assert.Throws<ProtocolException>(() => TimeCubeService.RequestOpen(Cube(), context, 0));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Request(Daily(), context, Input, DailyClaimAction.ClaimReady, 0));
    }
    [Fact]
    public void CandidatePlanningDoesNotMutateInputStateOrBag()
    {
        var originalCube = Cube(); var originalDaily = Daily(); var context = Context;
        var cube = TimeCubeService.RequestOpen(originalCube, context, 1);
        var daily = DailyTaskService.Request(originalDaily, context, Input, DailyClaimAction.ClaimReady, 1);
        Assert.Null(originalCube.Pending); Assert.Null(originalDaily.Pending); Assert.Empty(originalDaily.Handled);
        Assert.Empty(context.Bag.Items); Assert.Equal(1, context.Bag.Revision);
        Assert.Equal(new byte[] { 122, 2 }, cube.Candidate!.Body());
        Assert.Equal(new byte[] { 124, 1, 200, 0 }, daily.Candidate!.Body());
    }
    [Fact]
    public void DecoderAndImmutableProgressDoNotAliasInputs()
    {
        var data = new byte[33]; data[2] = 1;
        var p = new Packet(124, 1, data); data[2] = 255;
        var e = Assert.IsType<TaskSnapshot>(DailyTaskProtocol.Decode(p));
        var before = DailyTaskService.Apply(new(), e);
        var after = DailyTaskService.Apply(before, new TaskProgress(1, 1, 9));
        Assert.Equal(1, e.DailyProgress[0]); Assert.Equal(1, before.DailyProgress[0]); Assert.Equal(9, after.DailyProgress[0]);
    }
    [Theory]
    [InlineData(-1)] [InlineData(0)] [InlineData(9)] [InlineData(100)]
    public void NarrowFlagsNeverWrap(int bit) => Assert.False(DailyTaskService.HasFlag(255, bit));
    [Theory]
    [InlineData(1)] [InlineData(8)] [InlineData(9)] [InlineData(12)] [InlineData(16)]
    public void WeeklyFlagsRemainLittleEndian(int bit) => Assert.True(DailyTaskService.HasFlag((ushort)(1 << (bit - 1)), bit, true));
    [Theory]
    [InlineData(1)] [InlineData(2)] [InlineData(6)] [InlineData(12)] [InlineData(28)] [InlineData(29)] [InlineData(30)] [InlineData(31)]
    public void SupportedNonItemAwardsDoNotRequireInventedSlots(int kind) =>
        Assert.Equal(0, DailyTaskService.SlotsNeeded([new((byte)kind, 0, 1)]));
    [Fact]
    public void ItemSlotAccountingDoesNotOverflowOrInferStacking() =>
        Assert.Equal(2L * uint.MaxValue, DailyTaskService.SlotsNeeded([new(10, 100, uint.MaxValue), new(11, 100, uint.MaxValue)]));
    [Fact]
    public void DisabledEventChestAndLargeThresholdCannotBecomeEligible()
    {
        var catalog = Input.Catalog! with { Rewards = [new(2, 1, uint.MaxValue, [new(2, 0, 1)]), new(4, 1, 1, [new(2, 0, 1)])] };
        var rows = DailyTaskService.ChestRows(Daily(), catalog);
        Assert.Single(rows); Assert.False(rows[0].Eligible); Assert.Equal(uint.MaxValue, rows[0].Definition.Value);
    }
    [Fact]
    public void CatalogDuplicatesAndMalformedSlotsFailClosed()
    {
        var c = Input.Catalog!;
        Assert.Throws<ProtocolException>(() => DailyTaskService.Candidates(Daily(), c with { Tasks = c.Tasks.Add(c.Tasks[0]) }));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Candidates(Daily(), c with { Rewards = c.Rewards.Add(c.Rewards[0]) }));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Candidates(Daily(), c with { Tasks = [c.Tasks[0] with { Id = 9 }] }));
    }
    [Theory]
    [InlineData(0, 100, 1)] [InlineData(11, 100, 1)] [InlineData(1, 0, 1)] [InlineData(1, 65536, 1)] [InlineData(1, 100, 0)] [InlineData(1, 100, 256)]
    public void BagObservationMustHaveValidSlotsAndItemCounts(int index, int id, int count)
    {
        var bag = Context.Bag with { Items = [new(index, id, count)] };
        if (index is < 1 or > 10) Assert.NotEqual("", bag.Problem(1));
        else Assert.Null(bag.ItemTotals());
    }
    [Fact]
    public void DuplicateBagSlotsFailEvenWithEnoughCapacity()
    {
        var bag = Context.Bag with { Items = [new(1, 100, 1), new(1, 200, 1)] };
        Assert.NotEqual("", bag.Problem(1));
        Assert.Null(bag.ItemTotals());
        Assert.Throws<ProtocolException>(() => TimeCubeService.RequestOpen(Cube(), Context with { Bag = bag }, 0));
    }
    [Fact]
    public void InvalidDecodedEventCannotChangeOriginalSnapshot()
    {
        var state = Daily(); var cube = Cube();
        Assert.Throws<ProtocolException>(() => DailyTaskService.Apply(state, new TaskProgress(1, 0, 1)));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Apply(state, new TaskSnapshot(state.Marks, [], [], false, false)));
        Assert.Throws<ProtocolException>(() => TimeCubeService.Apply(cube, new CubeInfo(1, 4, 0, 0), 1, 0));
        Assert.True(state.Ready); Assert.Equal((byte?)1, cube.Count);
    }
    [Theory]
    [InlineData(double.NaN)] [InlineData(double.PositiveInfinity)] [InlineData(double.NegativeInfinity)]
    public void InvalidClocksNeverCreateOrCompleteRequests(double now)
    {
        Assert.Throws<ProtocolException>(() => TimeCubeService.Tick(Cube(), Context, now));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Tick(Daily(), Context, Input, now));
    }
    [Fact]
    public void NoCrossServiceCandidateWhileCounterpartHasUncertainResult()
    {
        Assert.Null(TimeCubeService.Tick(Cube(), Context with { DailyTasks = new(Uncertain: true) }, 1).Candidate);
        Assert.Null(DailyTaskService.Tick(Daily(), Context with { TimeCube = new(Uncertain: true) }, Input, 1).Candidate);
    }
    [Fact]
    public void CubeEnabledAloneDoesNotBlockDailyButCheckingDoes()
    {
        Assert.NotNull(DailyTaskService.Tick(Daily(), Context with { TimeCube = new(Enabled: true) }, Input, 1).Candidate);
        Assert.Null(DailyTaskService.Tick(Daily(), Context with { TimeCube = new(Checking: true) }, Input, 1).Candidate);
    }
    [Theory]
    [InlineData(null)] [InlineData("")] [InlineData(" ")]
    public void CatalogWithoutAnIdentityCannotAuthorizeRequests(string? token)
    {
        var input = Input with { Token = token };
        Assert.Throws<ProtocolException>(() => DailyTaskService.Tick(Daily(), Context, input, 1));
        Assert.Throws<ProtocolException>(() => DailyTaskService.Request(Daily() with { CatalogToken = token }, Context, input, DailyClaimAction.ClaimReady, 1));
    }
    [Fact]
    public void DuplicateBagEntriesCannotSupplyAFalseRewardReceipt()
    {
        var input = Input with { Catalog = AutomationParityTests.Catalog("items") };
        var d = DailyTaskService.Request(Daily(), Context, input, DailyClaimAction.ClaimReady, 1).State;
        d = DailyTaskService.Apply(d, new TaskRewardNotice(1, []));
        d = DailyTaskService.Apply(d, new TaskMarksChanged(d.Marks with { DailyDone = 1 }));
        var bag = Context.Bag with { Revision = 2, Items = [new(1, 100, 1), new(1, 100, 2), new(2, 200, 1)] };
        Assert.NotNull(DailyTaskService.Tick(d, Context with { Bag = bag }, input, 2).State.Pending);
    }
}
