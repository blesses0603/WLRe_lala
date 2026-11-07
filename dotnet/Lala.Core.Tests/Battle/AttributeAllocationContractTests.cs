using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class AttributeAllocationContractTests
{
    private static ImmutableDictionary<string, BigInteger> Stats(params (string Key, BigInteger Value)[] entries) =>
        entries.ToImmutableDictionary(entry => entry.Key, entry => entry.Value, StringComparer.Ordinal);
    private static AttributeAllocationContext Context(params (string Key, BigInteger Value)[] entries) => new() { PlayerStats = Stats(entries) };
    private static AttributeAllocationSnapshot Pending() => new() { Pending = true, Expected = Stats(("str", 22)), SentAt = 1.25, Status = "imported" };
    private static AttributeSetEvent Attribute(long value = 22, string entity = "self", byte kind = 28) =>
        new(1, entity, null, null, kind, "unused source label", 1, value, uint.MaxValue);

    [Fact]
    public void DefaultsAreExactAndNeverCreatePendingOrInferAcknowledgement()
    {
        var state = AttributeAllocationSnapshot.Empty;
        Assert.False(state.Pending); Assert.False(state.Acknowledged); Assert.False(state.Uncertain);
        Assert.Null(state.Expected); Assert.Null(state.SentAt); Assert.Equal("", state.Status);
        Assert.Same(state, AttributeAllocationReducer.Apply(state, new AttributeAllocationSuccessEvent(), Context(("str", 22))));
        Assert.Same(state, AttributeAllocationReducer.Apply(state, Attribute(), Context(("str", 22))));
        var pending = Pending();
        Assert.Same(pending, AttributeAllocationReducer.Apply(pending, Attribute(), Context(("str", 22))));
    }

    [Fact]
    public void AckNeedsAllExpectedCurrentKnowledgeAndDoesNotUseEventValue()
    {
        var seed = Pending() with { Expected = Stats(("str", 22), ("attribute_potential", 18)) };
        var ack = AttributeAllocationReducer.Apply(seed, new AttributeAllocationSuccessEvent(), Context(("str", 22)));
        Assert.True(ack.Pending); Assert.True(ack.Acknowledged); Assert.Equal(1.25, ack.SentAt);
        Assert.Equal("伺服器已回覆成功，等待能力值同步", ack.Status);
        Assert.Same(ack, AttributeAllocationReducer.Apply(ack, Attribute(18, kind: 38), Context(("str", 22))));
        var done = AttributeAllocationReducer.Apply(ack, Attribute(999, "player:42"), Context(("str", 22), ("attribute_potential", 18)));
        Assert.False(done.Pending); Assert.False(done.Acknowledged); Assert.Null(done.Expected); Assert.Null(done.SentAt);
        Assert.Equal("配點成功，能力值已同步", done.Status);
        Assert.Same(done, AttributeAllocationReducer.Apply(done, new AttributeAllocationSuccessEvent(), Context()));
        Assert.True(seed.Pending); Assert.False(seed.Acknowledged); Assert.Equal(2, seed.Expected!.Count);
    }

    [Fact]
    public void CompletionPreservesImportedUncertaintyAndLateAckCannotResolveExpiredSeed()
    {
        var expired = Pending() with { Pending = false, Uncertain = true, Acknowledged = true };
        Assert.Same(expired, AttributeAllocationReducer.Apply(expired, new AttributeAllocationSuccessEvent(), Context(("str", 22))));
        var done = AttributeAllocationReducer.Apply(Pending() with { Uncertain = true }, new AttributeAllocationSuccessEvent(), Context(("str", 22)));
        Assert.True(done.Uncertain); Assert.False(done.Pending);
    }

    [Fact]
    public void NullAndEmptyExpectedFollowVacuousSourceComparisonWithoutValidation()
    {
        foreach (var expected in new[] { null, Stats() })
        {
            var seed = Pending() with { Expected = expected, SentAt = null };
            Assert.Same(seed, AttributeAllocationReducer.Apply(seed, Attribute(), Context()));
            var done = AttributeAllocationReducer.Apply(seed, new AttributeAllocationSuccessEvent(), Context());
            Assert.False(done.Pending); Assert.Null(done.Expected);
        }
    }

    [Fact]
    public void IrrelevantEventsDoNotResolveEvenAcknowledgedMatchingOrEmptyPending()
    {
        foreach (var expected in new[] { null, Stats(), Stats(("str", 22)) })
        {
            var seed = Pending() with { Acknowledged = true, Expected = expected };
            Assert.Same(seed, AttributeAllocationReducer.Apply(seed, new RoundStartEvent(ushort.MaxValue), Context(("str", 22))));
            Assert.Same(seed, AttributeAllocationReducer.Apply(seed, new StarInfoEvent(255, 255, long.MaxValue), Context(("str", 22))));
        }
    }

    [Fact]
    public void OrdinalKeysMissingZeroAndArbitraryWidthImportsRemainDistinct()
    {
        var caseInsensitive = ImmutableDictionary.Create<string, BigInteger>(StringComparer.OrdinalIgnoreCase).Add("STR", 22);
        var seed = Pending() with { Acknowledged = true, Expected = caseInsensitive };
        Assert.Same(seed, AttributeAllocationReducer.Apply(seed, Attribute(), Context(("str", 22))));
        var wrongCase = new AttributeAllocationContext { PlayerStats = caseInsensitive };
        Assert.Same(Pending().Expected!.KeyComparer, wrongCase.PlayerStats.KeyComparer);
        var zero = Pending() with { Acknowledged = true, Expected = Stats(("missing", 0)) };
        Assert.Same(zero, AttributeAllocationReducer.Apply(zero, Attribute(), Context()));
        var huge = BigInteger.One << 200;
        var large = Pending() with { Expected = Stats(("custom", huge)) };
        Assert.False(AttributeAllocationReducer.Apply(large, new AttributeAllocationSuccessEvent(), Context(("custom", huge))).Pending);
    }

    [Fact]
    public async Task ImmutableCopiesAndParallelReductionsNeverAliasStateOrContext()
    {
        var mutable = new Dictionary<string, BigInteger> { ["str"] = 22 };
        var seed = Pending() with { Expected = mutable.ToImmutableDictionary() };
        var context = new AttributeAllocationContext { PlayerStats = mutable.ToImmutableDictionary() };
        mutable["str"] = 99;
        var changedContext = context with { PlayerStats = context.PlayerStats.SetItem("str", 30) };
        var results = await Task.WhenAll(Enumerable.Range(0, 50).Select(index => Task.Run(() =>
            AttributeAllocationReducer.Apply(seed, new AttributeAllocationSuccessEvent(), index % 2 == 0 ? context : changedContext))));
        for (var index = 0; index < results.Length; index++) Assert.Equal(index % 2 != 0, results[index].Pending);
        Assert.True(seed.Pending); Assert.False(seed.Acknowledged); Assert.Equal(new BigInteger(22), seed.Expected!["str"]);
        Assert.Equal(new BigInteger(22), context.PlayerStats["str"]);
    }

    [Fact]
    public void NullApiArgumentsFailWithoutPartialMutation()
    {
        var seed = Pending(); var ack = new AttributeAllocationSuccessEvent();
        Assert.Throws<ArgumentNullException>(() => AttributeAllocationReducer.Apply(null!, ack, Context()));
        Assert.Throws<ArgumentNullException>(() => AttributeAllocationReducer.Apply(seed, (ServerEvent)null!, Context()));
        Assert.Throws<ArgumentNullException>(() => AttributeAllocationReducer.Apply(seed, ack, null!));
        Assert.Throws<ArgumentNullException>(() => AttributeAllocationReducer.Apply(seed, (LiveDataEvent)null!, Context()));
        Assert.Throws<ArgumentNullException>(() => new AttributeAllocationContext { PlayerStats = null! });
        Assert.True(seed.Pending); Assert.False(seed.Acknowledged);
    }
}
