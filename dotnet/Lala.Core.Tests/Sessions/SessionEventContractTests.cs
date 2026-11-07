using System.Collections.Immutable;
using System.Numerics;
using System.Text;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions;

public sealed class SessionEventContractTests
{
    [Fact]
    public void DefaultsMatchOnlyTheRelevantPythonStateFields()
    {
        var state = new SessionEventSnapshot();
        Assert.Equal("disconnected", state.Phase);
        Assert.Empty(state.Roles); Assert.Empty(state.Attributes);
        Assert.Equal(BigInteger.Zero, state.PacketCount); Assert.Equal(BigInteger.Zero, state.UnimplementedCount);
        Assert.False(state.InitialDataComplete);
        Assert.False(state.Gold.Ready); Assert.False(state.Gold.Reliable);
        Assert.Null(state.Gold.Amount); Assert.Null(state.Gold.Source); Assert.Equal(BigInteger.Zero, state.Gold.Revision);
        Assert.False(state.EventFlow.Blocked); Assert.False(state.EventFlow.AwaitingResponse);
        Assert.Null(state.EventFlow.LastSource); Assert.Equal(BigInteger.Zero, state.EventFlow.RequestsSent);
        Assert.False(state.NpcDialogue.Active); Assert.Equal("idle", state.NpcDialogue.Phase);
        Assert.Empty(state.NpcDialogue.History); Assert.False(state.NpcDialogue.ChoiceContinuationPending);
    }

    [Fact]
    public void PacketCountIsOwnedByTheCallerEvenForHandledOrUnknownEvents()
    {
        var initial = new SessionEventSnapshot { PacketCount = BigInteger.One << 100 };
        var first = SessionEventReducer.Apply(initial, new UnimplementedServerEvent(255, 255, 123));
        var dialogue = first with { NpcDialogue = new() { Active = true } };
        var second = SessionEventReducer.Apply(dialogue, new NpcEffectEvent(1, Effect(1), 18));
        Assert.Equal(initial.PacketCount, first.PacketCount);
        Assert.Equal(initial.PacketCount, second.PacketCount);
        Assert.Equal(initial.PacketCount, second.NpcDialogue.EffectPacket);
        Assert.Equal(BigInteger.One, second.UnimplementedCount);
    }

    public static IEnumerable<object[]> IgnoredEvents()
    {
        yield return [new UnsupportedServerDecoderEvent(65, 1, "tent", 100)];
        yield return [new AccountIdentityEvent(42)];
        yield return [new HeartbeatRequestEvent()];
        yield return [new AttributeAllocationSuccessEvent()];
        yield return [new RoundStartEvent(1)];
        yield return [new MovementRequestEvent(1, 2)];
        yield return [new WalkEvent(42, 1, 2)];
        yield return [new ServerLayoutEvent(new BattleUnitsEvent([]))];
        yield return [new ServerLayoutEvent(new BattleStartEvent(1, 1, []))];
        yield return [new TypeNameOnlyEvent()];
    }

    [Theory]
    [MemberData(nameof(IgnoredEvents))]
    public void UnrelatedOrUnsupportedEventsAreIdentityNoopsRatherThanCountedUnknowns(ServerEvent observation)
    {
        var state = new SessionEventSnapshot { Phase = "world_ready", UnimplementedCount = 6 };
        Assert.Same(state, SessionEventReducer.Apply(state, observation));
    }

    [Fact]
    public void InvalidArgumentsFailBeforeChangingAnything()
    {
        var state = new SessionEventSnapshot();
        Assert.Throws<ArgumentNullException>(() => SessionEventReducer.Apply(null!, new InitialDataCompleteEvent()));
        Assert.Throws<ArgumentNullException>(() => SessionEventReducer.Apply(state, null!));
        Assert.False(state.InitialDataComplete);
    }

    [Fact]
    public void DefaultImmutableRoleArrayMeansAnEmptyRoleListAndResetsOnlyGoldAndPhase()
    {
        var state = new SessionEventSnapshot
        {
            Gold = new() { Ready = true, Reliable = true, Amount = 100, Revision = 900 },
            InitialDataComplete = true, NpcDialogue = new() { Active = true, Phase = "talk" },
            EventFlow = new() { Blocked = true, RequestsSent = 5 }
        };
        var result = SessionEventReducer.Apply(state, new ServerLayoutEvent(new RoleListAvailableEvent(default)));
        Assert.Empty(result.Roles); Assert.Equal("role_selection", result.Phase);
        Assert.Equal(new SessionGoldSnapshot(), result.Gold);
        Assert.True(result.InitialDataComplete);
        Assert.Same(state.NpcDialogue, result.NpcDialogue); Assert.Same(state.EventFlow, result.EventFlow);
        Assert.Equal((uint)100, state.Gold.Amount);
    }

    [Fact]
    public void BuildersCannotChangePublishedRolesHistoryOrNestedAttributes()
    {
        var roles = ImmutableArray.CreateBuilder<RoleSnapshot>(); roles.Add(Role());
        var history = ImmutableArray.CreateBuilder<ushort>(); history.Add(123);
        var attributes = ImmutableDictionary.CreateBuilder<string, long>(); attributes.Add("36:0", 90);
        var outer = ImmutableDictionary.CreateBuilder<string, ImmutableDictionary<string, long>>();
        outer.Add("self", attributes.ToImmutable());
        var input = new SessionEventSnapshot
        {
            Roles = roles.ToImmutable(), NpcDialogue = new() { Active = true, History = history.ToImmutable() },
            Attributes = outer.ToImmutable()
        };
        var output = SessionEventReducer.Apply(input, new NpcEffectEvent(1, Effect(1), 18));
        roles.Clear(); history[0] = 0; attributes["36:0"] = -1; outer.Clear();
        Assert.Single(input.Roles); Assert.Single(output.Roles);
        Assert.Equal(new ushort[] { 123 }, input.NpcDialogue.History);
        Assert.Equal(new ushort[] { 123, 42 }, output.NpcDialogue.History);
        Assert.Equal(90, input.Attributes["self"]["36:0"]);
        Assert.Equal(90, output.Attributes["self"]["36:0"]);
        var replacement = SessionEventReducer.Apply(output, new AttributeSetEvent(1, "self", null, null, 36, "exp", 2, -10, 0));
        Assert.Equal(-10, replacement.Attributes["self"]["36:0"]);
        Assert.Equal(90, output.Attributes["self"]["36:0"]);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, long>)replacement.Attributes["self"])["36:0"] = 22);
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)output.NpcDialogue.History)[0] = 22);
    }

    [Fact]
    public void ChoicePermissionNeverConsumesPendingChoiceAndNewEffectsDo()
    {
        var initial = new SessionEventSnapshot
        {
            NpcDialogue = new() { Active = true, Phase = "awaiting_choice", ChoiceContinuationPending = true },
            EventFlow = new() { AwaitingResponse = true, RequestsSent = 7 }
        };
        var continued = SessionEventReducer.Apply(initial, new EventContinuePermissionEvent(7, 0));
        Assert.Equal("continue", continued.NpcDialogue.Phase);
        Assert.True(continued.NpcDialogue.ChoiceContinuationPending);
        Assert.True(continued.EventFlow.Blocked); Assert.False(continued.EventFlow.AwaitingResponse);
        Assert.Equal(new BigInteger(7), continued.EventFlow.RequestsSent);
        var active = SessionEventReducer.Apply(continued, new NpcEffectEvent(1, null, 17));
        Assert.False(active.NpcDialogue.ChoiceContinuationPending);
        Assert.Equal("effect_unavailable", active.NpcDialogue.Phase);
        Assert.True(active.EventFlow.Blocked);
    }

    [Fact]
    public void NullEffectDoesNotClearPriorEvidenceOrPretendAnEventEnded()
    {
        var initial = new SessionEventSnapshot
        {
            NpcDialogue = new() { Active = true, Phase = "talk", EffectType = 1, TextId = 7,
                EffectPacket = 11, History = [7], ChoiceContinuationPending = true }
        };
        var result = SessionEventReducer.Apply(initial, new NpcEffectEvent(1, null, 0));
        Assert.Equal("effect_unavailable", result.NpcDialogue.Phase);
        Assert.Equal((byte)1, result.NpcDialogue.EffectType); Assert.Equal((ushort)7, result.NpcDialogue.TextId);
        Assert.Equal(new BigInteger(11), result.NpcDialogue.EffectPacket);
        Assert.Equal(new ushort[] { 7 }, result.NpcDialogue.History);
        Assert.True(result.NpcDialogue.Active); Assert.True(result.EventFlow.Blocked);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void InactiveRejectionDoesNotReleaseAnotherEventBlock(bool awaiting)
    {
        var initial = new SessionEventSnapshot
        {
            NpcDialogue = new() { Active = false, Phase = "ended", ChoiceContinuationPending = true },
            EventFlow = new() { Blocked = true, AwaitingResponse = awaiting }
        };
        Assert.Same(initial, SessionEventReducer.Apply(initial, new EventRejectedEvent(1, "fixture")));
        var ended = SessionEventReducer.Apply(initial, new EventEndEvent());
        Assert.False(ended.EventFlow.Blocked); Assert.False(ended.EventFlow.AwaitingResponse);
        Assert.Same(initial.NpcDialogue, ended.NpcDialogue);
    }

    [Fact]
    public void GoldLimitPreservesKnownAmountButInvalidatesReliabilityUntilAuthoritativeSnapshot()
    {
        var initial = new SessionEventSnapshot { Gold = new() { Ready = true, Reliable = true, Amount = 8, Revision = 3 } };
        var limited = SessionEventReducer.Apply(initial, new GoldLimitEvent());
        Assert.True(limited.Gold.Ready); Assert.False(limited.Gold.Reliable);
        Assert.Equal((uint)8, limited.Gold.Amount); Assert.Equal(new BigInteger(3), limited.Gold.Revision);
        var delta = SessionEventReducer.Apply(limited, new GoldDeltaEvent(1, 0, false));
        Assert.False(delta.Gold.Ready); Assert.False(delta.Gold.Reliable); Assert.Null(delta.Gold.Amount);
        Assert.Equal(new BigInteger(3), delta.Gold.Revision);
        var recovered = SessionEventReducer.Apply(delta, new GoldSnapshotEvent(0));
        Assert.True(recovered.Gold.Ready); Assert.True(recovered.Gold.Reliable);
        Assert.Equal((uint)0, recovered.Gold.Amount); Assert.Equal(new BigInteger(4), recovered.Gold.Revision);
    }

    [Fact]
    public void DecoderDiscardedPrivateBytesNeverEnterTheSessionProjection()
    {
        const string secret = "SYNTHETIC-CREDENTIAL-NEVER-RETAIN";
        byte[] echo = Encoding.ASCII.GetBytes(secret);
        byte[] account = [42, 0, 0, 0, (byte)echo.Length, .. echo, (byte)echo.Length, .. echo, (byte)echo.Length, .. echo];
        var initial = new SessionEventSnapshot();
        Assert.Same(initial, SessionEventReducer.Apply(initial, ServerProtocol.Decode(new(1, 4, account))));
        var unknown = SessionEventReducer.Apply(initial, ServerProtocol.Decode(new(255, 255, echo)));
        Assert.Equal(BigInteger.One, unknown.UnimplementedCount);
        Assert.DoesNotContain(secret, unknown.ToString());
        var effect = SessionEventReducer.Apply(initial, ServerProtocol.Decode(new(20, 1, new byte[18].Concat(echo).ToArray())));
        Assert.NotNull(effect.NpcDialogue.LastEffect);
        Assert.DoesNotContain(secret, effect.NpcDialogue.LastEffect.ToString());
        Assert.Equal(echo.Length, effect.NpcDialogue.LastEffect.ExtensionBytes);
    }

    private static NpcEffect Effect(byte kind) => new(0, 0, 0, kind, 0, 0, 0, 0, 42, 0, 0, 0);
    private static RoleSnapshot Role() => new(1, "Fixture", 1, 1, 100, 100, 100, 100, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, false,
        new(0, 0, 0, 0, 0, 0, 0, 0, 0));
    private sealed record TypeNameOnlyEvent() : ServerEvent(63, 7)
    {
        public override string Type => "login_result";
    }
}
