using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Lala.Core.Social;
using Xunit;

namespace Lala.Core.Tests.Social.GuildActions;

public sealed class GuildActionsContractTests
{
    private static GuildActionsReceiveContext Context(uint? role = 1, uint? serial = 9, bool member = true, uint? gold = 850, bool reliable = true) => new(role,
        new() { Ready = true, Serial = serial, Members = member && role is { } id
            ? ImmutableDictionary<uint, GuildMember>.Empty.Add(id, new(id, "private member")) : ImmutableDictionary<uint, GuildMember>.Empty },
        new() { Ready = true, Reliable = reliable, Amount = gold });
    private static GuildDonationPending Donation(byte index = 7, int count = 2) =>
        new(1, 9, new(true, "private token"), 0, 120, new(150, 4, 8, index, count), 5, 1000);
    private static GuildActionsReceiveSnapshot Bound(GuildActionPending? pending = null) => new()
    { Role = 1, Guild = 9, SignState = 1, Remaining = 5, Allow = true, Pending = pending, Reserved = 150 };

    [Fact]
    public void DefaultsMatchSourceAndEnabledFlagsAreNotAuthority()
    {
        var state = GuildActionsReceiveSnapshot.Empty;
        Assert.True(state.SignEnabled); Assert.True(state.DonateEnabled);
        Assert.Equal((ushort)8, state.SellId); Assert.Equal(3, state.Target); Assert.Equal(450, state.Budget);
        Assert.False(state.Allow); Assert.False(state.CountsReady); Assert.False(state.CatalogReady);
        Assert.Null(state.Pending); Assert.Null(state.Role); Assert.Null(state.Guild);
        Assert.Null(state.SignState); Assert.Null(state.Remaining); Assert.Null(state.CatalogToken);
        Assert.Null(state.Price); Assert.Null(state.Donated); Assert.False(state.Uncertain);
        Assert.Equal(0, state.Epoch); Assert.Equal(0, state.Reserved); Assert.Equal(0, state.Confirmed);
    }

    [Theory]
    [InlineData(null, 9u, true, false)]
    [InlineData(0u, 9u, true, true)]
    [InlineData(1u, null, true, false)]
    [InlineData(1u, 0u, true, false)]
    [InlineData(1u, 9u, false, false)]
    [InlineData(uint.MaxValue, uint.MaxValue, true, true)]
    public void MembershipUsesExplicitReadyNonzeroSerialAndExactPostLocalRole(uint? role, uint? serial, bool member, bool valid)
    {
        var context = Context(role, serial, member);
        Assert.Equal(valid, context.ValidMember);
        Assert.False((context with { Guild = context.Guild with { Ready = false } }).ValidMember);
    }

    [Fact]
    public void GoldReceiptRequiresPostLocalAmountAndDuplicatesBecomeUncertainWithoutRetry()
    {
        var original = Bound(Donation()); var receipt = new GoldDeltaEvent(2, -150, false);
        var accepted = GuildActionsReceiveReducer.Apply(original, receipt, Context(gold: 850));
        Assert.True(Assert.IsType<GuildDonationPending>(accepted.Pending).GoldAck);
        var wrongContext = GuildActionsReceiveReducer.Apply(original, receipt, Context(gold: 1000));
        Assert.True(wrongContext.Uncertain); Assert.Null(wrongContext.Pending);
        var duplicate = GuildActionsReceiveReducer.Apply(accepted, receipt, Context(gold: 700));
        Assert.True(duplicate.Uncertain); Assert.Null(duplicate.Pending); Assert.Equal(150, duplicate.Reserved);
        Assert.Equal(0, duplicate.Confirmed); Assert.Contains("停止重送", duplicate.Status);
        Assert.False(Assert.IsType<GuildDonationPending>(original.Pending).GoldAck);
        Assert.Same(duplicate, GuildActionsReceiveReducer.Apply(duplicate, receipt, Context(gold: 550)));
    }

    [Fact]
    public void ThreeAcknowledgementsStayPendingUntilAnExplicitFutureObservationStep()
    {
        var state = Bound(Donation());
        state = GuildActionsReceiveReducer.Apply(state, new GoldDeltaEvent(2, -150, false), Context());
        state = GuildActionsReceiveReducer.Apply(state, new GuildDonateStateEvent(4, true), Context());
        state = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(7, 3), Context());
        var pending = Assert.IsType<GuildDonationPending>(state.Pending);
        Assert.True(pending.GoldAck); Assert.True(pending.RemainingAck); Assert.True(pending.SellAck);
        Assert.Equal(150, state.Reserved); Assert.Equal(0, state.Confirmed);
        // No clock or Tick is implicitly run by unrelated receive traffic.
        Assert.Same(state, GuildActionsReceiveReducer.Apply(state, new InitialDataCompleteEvent(), Context()));
    }

    [Fact]
    public void SignResultAndStateRemainSeparateAndNeitherCreatesPendingEvidence()
    {
        var state = Bound(new GuildSignPending(1, 9, null, 0, 120)) with { SignAttempted = true };
        var ack = GuildActionsReceiveReducer.Apply(state, new GuildSignResultEvent(0), Context());
        var completeState = GuildActionsReceiveReducer.Apply(ack, new GuildSignStateEvent(2), Context());
        Assert.True(Assert.IsType<GuildSignPending>(completeState.Pending).SignAck);
        Assert.Equal((byte)2, completeState.SignState); Assert.False(Assert.IsType<GuildSignPending>(state.Pending).SignAck);
        var unsolicited = Bound();
        Assert.Same(unsolicited, GuildActionsReceiveReducer.Apply(unsolicited, new GuildSignResultEvent(0), Context()));
    }

    [Fact]
    public void SellAckCanRemainAfterOldCountButRemainingAckCannot()
    {
        var state = Bound(Donation());
        var sold = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(7, 3), Context());
        var oldCount = GuildActionsReceiveReducer.Apply(sold, new UiSellUpdateEvent(7, 2), Context());
        Assert.True(Assert.IsType<GuildDonationPending>(oldCount.Pending).SellAck);
        Assert.Equal((byte)2, oldCount.Counts[7]); Assert.False(oldCount.Uncertain);
        var acknowledged = GuildActionsReceiveReducer.Apply(state, new GuildDonateStateEvent(4, true), Context());
        var reverted = GuildActionsReceiveReducer.Apply(acknowledged, new GuildDonateStateEvent(5, true), Context());
        Assert.True(reverted.Uncertain); Assert.Null(reverted.Pending);
    }

    [Fact]
    public void SnapshotAndIndexZeroDoNotConfirmSellOrInventReadiness()
    {
        var state = Bound(Donation());
        var counts = new Dictionary<byte, byte> { [7] = 3 }.ToFrozenDictionary();
        var snapshot = GuildActionsReceiveReducer.Apply(state, new UiSellSnapshotEvent(counts), Context());
        Assert.True(snapshot.CountsReady); Assert.False(Assert.IsType<GuildDonationPending>(snapshot.Pending).SellAck);
        Assert.Same(state, GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(0, 3), Context()));
        var incremental = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(7, 3), Context());
        Assert.False(incremental.CountsReady); Assert.True(Assert.IsType<GuildDonationPending>(incremental.Pending).SellAck);
    }

    [Fact]
    public void DayResetDuringPendingKeepsEpochAndMoneyButReplacesAllCounts()
    {
        var token = new GuildActionsCatalogToken(true, "private token");
        var state = Bound(Donation()) with { Epoch = BigInteger.One << 100, Reserved = BigInteger.One << 90,
            Confirmed = BigInteger.One << 80, SignAttempted = true, CatalogToken = token, CatalogReady = true,
            Price = 150, Donated = 2, Counts = ImmutableDictionary<byte, byte>.Empty.Add(255, 7) };
        var reset = GuildActionsReceiveReducer.Apply(state, new UiSellDayResetEvent(), Context());
        Assert.Null(reset.Pending); Assert.True(reset.Uncertain); Assert.Equal(state.Epoch, reset.Epoch);
        Assert.Equal(state.Reserved, reset.Reserved); Assert.Equal(state.Confirmed, reset.Confirmed);
        Assert.True(reset.SignAttempted); Assert.Equal(state.SignState, reset.SignState); Assert.Equal(state.Remaining, reset.Remaining);
        Assert.True(reset.CountsReady); Assert.Equal(100, reset.Counts.Count); Assert.All(reset.Counts, pair => Assert.Equal((byte)0, pair.Value));
        Assert.False(reset.Counts.ContainsKey(0)); Assert.False(reset.Counts.ContainsKey(101)); Assert.False(reset.Counts.ContainsKey(255));
        var idleReset = GuildActionsReceiveReducer.Apply(reset, new UiSellDayResetEvent(), Context());
        Assert.Equal(state.Epoch + 1, idleReset.Epoch); Assert.Equal(0, idleReset.Reserved); Assert.Equal(0, idleReset.Confirmed);
        Assert.True(idleReset.Uncertain); Assert.Null(idleReset.SignState); Assert.Null(idleReset.Remaining);
        Assert.Same(token, idleReset.CatalogToken); Assert.True(idleReset.CatalogReady); Assert.Equal(state.Price, idleReset.Price);
        Assert.Equal(state.Donated, idleReset.Donated); Assert.Equal((byte)7, state.Counts[255]);
    }

    [Fact]
    public void SignStateResetNeverResetsMoneyOrCatalogAndUncertaintyIsLatched()
    {
        var state = Bound() with { SignState = 2, SignAttempted = true, Uncertain = true, Confirmed = 100, Epoch = 7 };
        var reset = GuildActionsReceiveReducer.Apply(state, new GuildSignStateEvent(1), Context());
        Assert.False(reset.SignAttempted); Assert.True(reset.Uncertain); Assert.Equal(150, reset.Reserved);
        Assert.Equal(100, reset.Confirmed); Assert.Equal(7, reset.Epoch);
    }

    [Fact]
    public void DifferentGuildOverwritesStatusButKeepsUncertaintyAndOriginalRoleExactly()
    {
        var state = Bound(Donation()) with { Role = 2, SignAttempted = true };
        var context = Context(serial: 10);
        var roster = new GuildRosterEvent("ignored", "ignored", 10,
            context.Guild.Members.ToFrozenDictionary(), 1);
        var result = GuildActionsReceiveReducer.Apply(state, roster, context);
        Assert.True(result.Uncertain); Assert.Null(result.Pending); Assert.False(result.DonateEnabled);
        Assert.Equal(2u, result.Role); Assert.Equal(10u, result.Guild); Assert.False(result.SignAttempted);
        Assert.Equal("已變更組織，捐獻停用，等待新狀態", result.Status);
    }

    [Fact]
    public void UnboundGuildReceiptsAreIgnoredButGoldAndCountsStillFollowSource()
    {
        var state = Bound(Donation()) with { Guild = null };
        Assert.Same(state, GuildActionsReceiveReducer.Apply(state, new GuildDonateStateEvent(4, true), Context()));
        Assert.Same(state, GuildActionsReceiveReducer.Apply(state, new GuildActionErrorEvent(5), Context()));
        Assert.True(Assert.IsType<GuildDonationPending>(GuildActionsReceiveReducer.Apply(state,
            new GoldDeltaEvent(2, -150, false), Context()).Pending).GoldAck);
        Assert.True(Assert.IsType<GuildDonationPending>(GuildActionsReceiveReducer.Apply(state,
            new UiSellUpdateEvent(7, 3), Context()).Pending).SellAck);
    }

    [Fact]
    public void Count255DoesNotWrapExpectedAcknowledgementToZero()
    {
        var state = Bound(Donation(255, 255));
        var unchanged = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(255, 255), Context());
        Assert.False(Assert.IsType<GuildDonationPending>(unchanged.Pending).SellAck);
        var wrapped = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(255, 0), Context());
        Assert.True(wrapped.Uncertain); Assert.Null(wrapped.Pending);
    }

    [Fact]
    public void BranchesAndNestedPendingRemainImmutableAndDiagnosticsDoNotDiscloseIdentity()
    {
        var state = Bound(Donation()); var original = GuildActionsParityTests.Project(state).ToJsonString();
        var a = GuildActionsReceiveReducer.Apply(state, new UiSellUpdateEvent(7, 3), Context());
        var b = GuildActionsReceiveReducer.Apply(state, new GuildDonateStateEvent(4, true), Context());
        Assert.True(Assert.IsType<GuildDonationPending>(a.Pending).SellAck);
        Assert.False(Assert.IsType<GuildDonationPending>(a.Pending).RemainingAck);
        Assert.False(Assert.IsType<GuildDonationPending>(b.Pending).SellAck);
        Assert.True(Assert.IsType<GuildDonationPending>(b.Pending).RemainingAck);
        Assert.Empty(state.Counts); Assert.Equal(original, GuildActionsParityTests.Project(state).ToJsonString());
        foreach (var text in new[] { state.ToString(), state.Pending!.ToString(), state.Pending.Token!.ToString(), Donation().Quote.ToString(), Context().ToString() })
            Assert.DoesNotContain("private", text);
    }

    [Fact]
    public void NullInputsAreRejectedAtBothTypedBoundaries()
    {
        var state = Bound(); var context = Context(); var observation = new GuildSignStateEvent(1);
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(null!, observation, context));
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(state, (SocialEvent)null!, context));
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(state, observation, null!));
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(null!, new ServerSocialEvent(observation), context));
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(state, (ServerEvent)null!, context));
        Assert.Throws<ArgumentNullException>(() => GuildActionsReceiveReducer.Apply(state, new ServerSocialEvent(observation), null!));
    }
}
