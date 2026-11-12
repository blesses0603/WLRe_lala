using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.Social.Ark;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Social.Ark;

public sealed class ArkReceiveContractTests
{
    private static readonly ArkCatalogToken Token = new(true, new string('a', 64));
    private static readonly ArkEventRow Row = new(1, 123, 3, 1, false);
    private static readonly ArkAward Award = new(6, 8, 5);
    private static readonly ArkQuestionEvent QuestionEvent = new(101, Award, [201, 202, 203, 204]);
    private static readonly ArkRuntimeObservation Runtime = new(true, Token,
        new Dictionary<uint, string> { [101] = "請問1+1=?", [201] = "1", [202] = "2", [203] = "3", [204] = "4" }.ToImmutableDictionary());
    private static ArkReceiveContext Context => new(17, 8, Runtime);
    private static ArkPendingObservation Pending => new("question", 17, Token, 8) { Due = 123, Event = Row };
    private static ArkReceiveSnapshot Seed => new() { Role = 17, Pending = Pending, Generation = 42 };
    private static ArkQuestionSnapshot Question => new(101, Award, [201, 202, 203, 204], "請問1+1=?", ["1", "2", "3", "4"])
    { Selected = 2, KnownAnswer = 202, AnswerKind = "reviewed_candidate", AnswerSource = "synthetic candidate" };

    [Fact]
    public void DeferredIsNotStorageFailureAndDoesNotRunObviousArithmetic()
    {
        var result = ArkReceiveReducer.Apply(Seed, QuestionEvent, Context);
        Assert.Equal(ArkReceiveReducer.DeferredMemoryStatus, result.State.QuestionStoreStatus);
        Assert.NotEqual(ArkReceiveReducer.UnavailableMemoryStatus, result.State.QuestionStoreStatus);
        Assert.Null(result.State.Question!.KnownAnswer);
        Assert.Equal("", result.State.Question.AnswerKind);
        Assert.Empty(result.State.Answers);
        Assert.Null(result.State.Pending!.Due);
        Assert.False(result.State.Pending.Result);
        Assert.NotNull(result.MemoryIntent);
        Assert.Equal(ArkQuestionMemoryOperation.Observe, result.MemoryIntent.Operation);
        Assert.Null(result.MemoryIntent.SelectedAnswer);
        Assert.Null(result.MemoryIntent.Question.Selected);
        Assert.False(result.State.Uncertain);
    }

    [Fact]
    public void ExplicitUnavailableBoundaryUsesSourceFailureStatus()
    {
        var result = ArkReceiveReducer.Apply(Seed, QuestionEvent,
            Context with { MemoryAvailability = ArkQuestionMemoryAvailability.Unavailable });
        Assert.Equal(ArkReceiveReducer.UnavailableMemoryStatus, result.State.QuestionStoreStatus);
        Assert.Equal(ArkQuestionMemoryOperation.Observe, result.MemoryIntent!.Operation);
    }

    [Fact]
    public void ServerCorrectReceiptIsAnUnexecutedConfirmIntentNotAnAcceptedAnswer()
    {
        var state = Seed with { Question = Question, Answers = ImmutableDictionary<string, uint>.Empty.Add("old", 204) };
        var result = ArkReceiveReducer.Apply(state, new ArkAnswerResultEvent(true, 2), Context);
        Assert.True(result.State.Pending!.Result);
        Assert.NotNull(result.State.Pending);
        Assert.False(result.State.Pending.Complete);
        Assert.Equal("答案正確，等待事件完成", result.State.Status);
        Assert.Null(result.State.Question!.KnownAnswer);
        Assert.Same(state.Answers, result.State.Answers);
        Assert.False(result.State.Answers.ContainsValue(202));
        Assert.Equal(ArkQuestionMemoryOperation.Confirm, result.MemoryIntent!.Operation);
        Assert.Equal((uint)202, result.MemoryIntent.SelectedAnswer);
        Assert.Same(state.Question, result.MemoryIntent.Question);
        Assert.Equal((uint)202, state.Question.KnownAnswer);
        Assert.False(state.Pending!.Result);
    }

    [Fact]
    public void WrongReceiptNeverUsesTheReportedAnswerToGuessACorrectOption()
    {
        var result = ArkReceiveReducer.Apply(Seed with { Question = Question }, new ArkAnswerResultEvent(false, 4), Context);
        Assert.Equal(ArkQuestionMemoryOperation.Reject, result.MemoryIntent!.Operation);
        Assert.Equal((uint)202, result.MemoryIntent.SelectedAnswer);
        Assert.True(result.MemoryIntent.RejectedCandidate);
        Assert.Null(result.State.Question!.KnownAnswer);
        Assert.Empty(result.State.Answers);
        Assert.Equal("答案錯誤，等待事件完成", result.State.Status);
    }

    [Theory]
    [InlineData("computed", true)]
    [InlineData("reviewed_candidate", true)]
    [InlineData("server_confirmed", false)]
    [InlineData("", false)]
    public void RejectionPreservesCandidateProvenance(string kind, bool expected)
    {
        var result = ArkReceiveReducer.Apply(Seed with { Question = Question with { AnswerKind = kind } },
            new ArkAnswerResultEvent(false, 4), Context);
        Assert.Equal(expected, result.MemoryIntent!.RejectedCandidate);
        var claimed = ArkReceiveReducer.Apply(Seed with { Question = Question with { AnswerKind = kind, KnownAnswer = null, SelectedCandidate = true } },
            new ArkAnswerResultEvent(false, 4), Context);
        Assert.True(claimed.MemoryIntent!.RejectedCandidate);
    }

    [Fact]
    public void IntentCarriesExactRoleVersionGenerationsEventAndQuestionIdentity()
    {
        var result = ArkReceiveReducer.Apply(Seed, QuestionEvent, Context);
        var intent = result.MemoryIntent!;
        Assert.Equal(Token, intent.Token);
        Assert.Equal((uint)17, intent.Role);
        Assert.Equal(new BigInteger(8), intent.DailyGeneration);
        Assert.Equal(new BigInteger(42), intent.ArkGeneration);
        Assert.Equal(Row, intent.Event);
        Assert.Equal((uint)101, intent.Question.Question);
        Assert.Equal("請問1+1=?", intent.Question.Text);
        Assert.Equal(new uint[] { 201, 202, 203, 204 }, intent.Question.Options);
        Assert.Equal(new[] { "1", "2", "3", "4" }, intent.Question.Labels);
        Assert.Equal(nameof(ArkQuestionMemoryIntent), intent.ToString());
        Assert.Equal(nameof(ArkReceiveSnapshot), result.State.ToString());
    }

    [Theory]
    [InlineData("role")]
    [InlineData("generation")]
    [InlineData("token")]
    [InlineData("catalog")]
    public void StaleCurrentQuestionCannotEmitStorageIntent(string change)
    {
        var context = change switch
        {
            "role" => Context with { PlayerRoleId = 18 },
            "generation" => Context with { DailyGeneration = 9 },
            "token" => Context with { CurrentRuntime = Runtime with { Token = new(true, new string('b', 64)) } },
            _ => Context with { CurrentRuntime = Runtime with { Available = false } }
        };
        var result = ArkReceiveReducer.Apply(Seed, QuestionEvent, context);
        Assert.Null(result.MemoryIntent);
        if (change == "role") { Assert.False(result.State.Uncertain); Assert.NotNull(result.State.Pending); } // Early ignore, not freeze.
        else { Assert.True(result.State.Uncertain); Assert.Null(result.State.Pending); }
    }

    [Fact]
    public void PendingRoleMismatchFreezesEvenWhenStateAndPlayerAgree()
    {
        var result = ArkReceiveReducer.Apply(Seed with { Pending = Pending with { Role = 18 } }, QuestionEvent, Context);
        Assert.True(result.State.Uncertain);
        Assert.Null(result.State.Pending);
        Assert.Null(result.MemoryIntent);
    }

    [Fact]
    public void SecondRuntimeReadCannotSubstituteDifferentVersionTexts()
    {
        var result = ArkReceiveReducer.Apply(Seed, QuestionEvent,
            Context with { QuestionRuntime = Runtime with { Token = new(true, new string('b', 64)) } });
        Assert.True(result.State.Uncertain);
        Assert.Null(result.MemoryIntent);
        Assert.Null(result.State.Question);
        Assert.StartsWith("問答缺少同版題目文字", result.State.Status);
    }

    [Fact]
    public void DetachedPendingCannotBeResurrectedByMatchingCompletionAfterListMismatch()
    {
        var result = ArkReceiveReducer.Apply(Seed, new ArkCompleteEvent(1, 123), Context);
        Assert.True(result.State.Uncertain);
        Assert.Null(result.State.Pending);
        Assert.False(Seed.Pending!.Complete);
    }

    [Fact]
    public void SnapshotsAndAllAcknowledgementsPreserveLatchedUncertaintyAndDoNotFinishActions()
    {
        var pending = new ArkPendingObservation("dispatch", 17, Token, 8)
        { Quote = new(1, 1, 60, 20), Balance = 100 };
        var state = Seed with { Pending = pending, Uncertain = true, Ready = true,
            Agents = ImmutableDictionary<byte, ArkAgent>.Empty.Add(1, new(1, 5, [1, 1], 0)),
            Starcoin = new(true, true, 100, 0), Reserved = 20 };
        var paid = ArkReceiveReducer.Apply(state, new ArkStarcoinEvent(80, 20, false, false), Context).State;
        var ack = ArkReceiveReducer.Apply(paid, new ArkDispatchEvent(1, 1, [1, 0], 60), Context).State;
        Assert.True(ack.Pending!.Paid);
        Assert.True(ack.Pending.ShipAck);
        Assert.True(ack.Uncertain);
        Assert.Equal(BigInteger.Zero, ack.Confirmed);
        Assert.Equal(new BigInteger(20), ack.Reserved);
        Assert.Equal((byte)0, state.Agents[1].Planet);
        Assert.Equal((byte)1, ack.Agents[1].Planet);
        var refreshed = ArkReceiveReducer.Apply(ack, new ArkSnapshotEvent(1, 0,
            state.Agents.ToFrozenDictionary(), new(0, 0, 0, 0, [0, 0])), Context).State;
        Assert.True(refreshed.Ready);
        Assert.True(refreshed.Uncertain);
        Assert.Null(refreshed.Pending);
    }

    [Fact]
    public void FightDefeatIncrementsAnUnboundedCounterWithoutClearingUncertainty()
    {
        var initial = Seed with { Pending = Pending with { Kind = "fight" }, Uncertain = true, SettingsRevision = BigInteger.One << 100 };
        var result = ArkReceiveReducer.Apply(initial, new ArkFightResultEvent(false), Context).State;
        Assert.Equal(initial.SettingsRevision + 1, result.SettingsRevision);
        Assert.False(result.Enabled);
        Assert.True(result.Uncertain);
        Assert.Null(result.Pending);
    }

    [Fact]
    public void CollectionRewardsDoNotInventInventoryDailyProgressOrCompletion()
    {
        var state = Seed;
        var result = ArkReceiveReducer.Apply(state, new ArkCollectRewardEvent(60, [new(123, 4)]), Context);
        Assert.Same(state, result.State);
        Assert.Null(result.MemoryIntent);
    }

    [Fact]
    public void SameRolePreservesStateWhileDifferentRoleResetsAllEvidence()
    {
        var state = Seed with { Uncertain = true, Question = Question, Enabled = false };
        var same = ArkReceiveReducer.Apply(state, ArkReceiveParityTests.World(17), Context).State;
        Assert.Same(state.Question, same.Question);
        Assert.Same(state.Pending, same.Pending);
        Assert.True(same.Uncertain);
        var other = ArkReceiveReducer.Apply(state, ArkReceiveParityTests.World(18), Context).State;
        Assert.Null(other.Question);
        Assert.Null(other.Pending);
        Assert.False(other.Uncertain);
        Assert.True(other.Enabled);
        Assert.Equal((uint)18, other.Role);
    }

    [Fact]
    public void UnconsumedEvidenceRemainsDeeplyImmutableAndUnchanged()
    {
        var source = new List<StateValue> { StateValue.Scalar("unchanged") };
        var evidence = StateValue.List(source);
        var state = Seed with { Rows = evidence, Attempted = evidence, Quote = StateValue.Map(("opaque", evidence)),
            Pending = Pending with { OtherFields = StateValue.Map(("bag", evidence)) } };
        source.Clear();
        var next = ArkReceiveReducer.Apply(state, new ArkExploreEvent(21, 10000), Context).State;
        Assert.Same(state.Rows, next.Rows);
        Assert.Same(state.Attempted, next.Attempted);
        Assert.Same(state.Quote, next.Quote);
        Assert.Same(state.Pending, next.Pending);
        Assert.Single(next.Rows.SequenceValue);
    }
}
