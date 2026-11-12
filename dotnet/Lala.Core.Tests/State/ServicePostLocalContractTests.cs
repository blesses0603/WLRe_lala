using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Social;
using Lala.Core.Social.Ark;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.State;

public sealed class ServicePostLocalContractTests
{
    private static readonly ArkCatalogToken Token = new(true, new string('a', 64));
    private static readonly ArkEventRow Event = new(1, 123, 3, 1, false);
    private static readonly ArkQuestionEvent Question = new(101, new(6, 8, 5), [201, 202, 203, 204]);
    private static readonly ArkRuntimeObservation Runtime = new(true, Token,
        new Dictionary<uint, string> { [101] = "請問1+1=?", [201] = "1", [202] = "2", [203] = "3", [204] = "4" }.ToImmutableDictionary());
    private static ServerEvent World(uint role = 17, string name = "New local name") => new ServerLayoutEvent(
        new WorldPlayerEvent(new(role, 0, 101, 1, 2, 0, 0, 0, 0, 0, 0, false, [], name, 0)));
    private static ServerEvent Ignored => new UnknownObservation();
    private sealed record UnknownObservation() : ServerEvent(255, 255) { public override string Type => "unimplemented"; }
    private static ServiceStateCoordinator Seed(bool pending = true, PlayerKnowledgeSnapshot? knowledge = null,
        CompanionReceiveSnapshot? companions = null, ArkReceiveSnapshot? ark = null, GuildActionsReceiveSnapshot? guildActions = null)
    {
        var boot = new ServiceStateCoordinator();
        var basis = boot.Apply(World(), new(boot.Snapshot(), new(100)));
        return new(new(local: basis.Local, dailyTasks: basis.DailyTasks, timeCube: basis.TimeCube, tent: basis.Tent,
            playerKnowledge: knowledge, companions: companions, efficiency: basis.Efficiency, guildActions: guildActions,
            ark: ark ?? new() { Role = 17, Generation = 42,
                Pending = pending ? new("question", 17, Token, basis.DailyTasks.Generation) { Due = 1, Event = Event } : null,
                Answers = ImmutableDictionary<string, uint>.Empty.Add("historical", 204) }));
    }
    private static ServiceStateSnapshot Apply(ServiceStateCoordinator state, ServerEvent value, ServiceObservationInputs? inputs = null) =>
        state.Apply(value, new(state.Snapshot(), inputs ?? new(123) { ArkRuntime = Runtime }));

    [Fact]
    public void AllSourceObserverSlotsAreComposedWithoutClaimingFullStateOrCreatingPendingActions()
    {
        Assert.Equal(18, ServiceStateCoordinator.ObserverOrder.Length);
        Assert.All(ServiceStateCoordinator.ObserverOrder, row => Assert.True(row.Composed));
        var state = new ServiceStateCoordinator();
        var result = Apply(state, World());
        Assert.False(result.IsCompleteState);
        Assert.Null(result.GuildActions.Pending);
        Assert.Null(result.Ark.Pending);
        Assert.Null(result.Observation!.ArkMemoryIntent);
        Assert.Null(result.Observation.ArkContext);
        Assert.Null(result.Observation.Inputs.ArkQuestionRuntime);
        Assert.True(result.Observation.Inputs.ResourceHeld);
    }

    [Fact]
    public void EfficiencyUsesAllUpdatedKnowledgeEvenWithoutReadyFlagsAndUsesNewLocalRoleAndName()
    {
        var player = new PlayerKnowledgeSnapshot { Stats = new Dictionary<string, long>
            { ["exp"] = 20000, ["level"] = 4294967295, ["degree"] = -4294967295 }.ToImmutableDictionary() };
        var profile = new CompanionProfileSnapshot(new(0, 8000, 10000, 12, 300, 50, 10, 11, 12, 13, 14, 0, 100, 1, 0, "",
            [], [], 0, 0, 0, 0, 0, 0, 0), ImmutableDictionary<uint, CompanionLearnedSkill>.Empty,
            ImmutableDictionary<string, long>.Empty.Add("exp", 900));
        var companions = new CompanionReceiveSnapshot
            { Companions = ImmutableDictionary<ushort, CompanionProfileSnapshot>.Empty.Add(0, profile) };
        var state = Seed(knowledge: player, companions: companions);
        var result = Apply(state, Ignored, new(123) { NpcNames = ImmutableDictionary<uint, string>.Empty.Add(8000, "Observed NPC label") });
        Assert.False(result.PlayerKnowledge.Ready);
        Assert.False(result.Companions.Ready);
        Assert.Equal(20000, result.Observation!.EfficiencyKnowledge.PlayerStats.Experience);
        Assert.Equal(4294967295, result.Observation.EfficiencyKnowledge.PlayerStats.Level);
        Assert.Equal(-4294967295, result.Observation.EfficiencyKnowledge.PlayerStats.Degree);
        Assert.Equal(900, result.Efficiency.Rows[EfficiencySubject.Companion(0)].Experience);
        Assert.Equal("Observed NPC label", result.Efficiency.Rows[EfficiencySubject.Companion(0)].Name);
        var historical = result;
        result = Apply(state, World(18, "Changed local role"));
        Assert.Equal(18u, result.Observation!.EfficiencyKnowledge.RoleId);
        Assert.Equal("Changed local role", result.Efficiency.Rows[EfficiencySubject.Player].Name);
        Assert.Equal(17u, historical.Efficiency.RoleId);
        Assert.Equal("New local name", historical.Efficiency.Rows[EfficiencySubject.Player].Name);
    }

    [Fact]
    public void ShopAndGuildActionsConsumeSamePacketUpdatedGoldAndOwnedBagWithoutSettlement()
    {
        var state = Seed(pending: false);
        var before = state.Snapshot();
        var result = Apply(state, new GoldSnapshotEvent(1000));
        var context = result.Observation!.ShopContext;
        var entry = Assert.Single(result.ShopEvidence.Events);
        Assert.Same(result.Bag, context.Inventory);
        Assert.Same(result.Local.Session.Gold, context.Gold);
        Assert.Same(context.Gold, result.Observation.GuildActionsContext.Gold);
        Assert.Equal(result.PacketCount, context.PacketCount);
        Assert.Equal(before.PacketCount + 1, entry.Packet);
        Assert.Equal(result.Local.Session.Gold.Revision, entry.GoldRevision);
        Assert.True(entry.GoldReliable);
        Assert.False(entry.InventoryReliable);
        Assert.Null(result.GuildActions.Pending);
        Assert.Contains("並非交易已完成", result.ShopEvidence.Status);
        Assert.Empty(before.ShopEvidence.Events);
    }

    [Fact]
    public void MissingRuntimeIsRejectedAtomicallyRatherThanInventingUnavailableEvidence()
    {
        var state = Seed(); var before = state.Snapshot();
        var error = Assert.Throws<InvalidOperationException>(() => Apply(state, Question, new(123)));
        Assert.Contains("runtime observation", error.Message);
        Assert.Same(before, state.Snapshot());
        Assert.False(before.Ark.Uncertain);
        Assert.NotNull(before.Ark.Pending);
        Assert.Null(before.Ark.Question);
        Assert.Null(before.Observation);
        var unavailable = Apply(state, Question, new(123) { ArkRuntime = ArkRuntimeObservation.Absent });
        Assert.True(unavailable.Ark.Uncertain);
        Assert.Null(unavailable.Ark.Pending);
        Assert.Null(unavailable.Observation!.ArkMemoryIntent);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void DeferredAndActualUnavailableMemoryRemainDistinctAndOnlyExposeIdentityBoundIntent(bool unavailable)
    {
        var state = Seed(); var before = state.Snapshot();
        var result = Apply(state, Question, new(123) { ArkRuntime = Runtime,
            ArkMemoryAvailability = unavailable ? ArkQuestionMemoryAvailability.Unavailable : ArkQuestionMemoryAvailability.Deferred });
        var intent = result.Observation!.ArkMemoryIntent!;
        Assert.NotNull(intent);
        Assert.Equal(ArkQuestionMemoryOperation.Observe, intent.Operation);
        Assert.Equal(Token, intent.Token);
        Assert.Equal(17u, intent.Role);
        Assert.Equal(new BigInteger(result.DailyTasks.Generation), intent.DailyGeneration);
        Assert.Equal(42, intent.ArkGeneration);
        Assert.Same(before.Ark.Pending!.Event, intent.Event);
        Assert.Equal(Runtime.Texts[101], intent.Question.Text);
        Assert.Null(intent.SelectedAnswer);
        Assert.Null(result.Ark.Question!.KnownAnswer);
        Assert.Same(before.Ark.Answers, result.Ark.Answers);
        Assert.Equal(unavailable ? ArkReceiveReducer.UnavailableMemoryStatus : ArkReceiveReducer.DeferredMemoryStatus,
            result.Ark.QuestionStoreStatus);
        Assert.NotNull(result.Ark.Pending);
        Assert.Null(result.Ark.Pending.Due);
        var later = Apply(state, Ignored, new(1e12));
        Assert.Same(result.Ark, later.Ark);
        Assert.Null(later.Observation!.ArkMemoryIntent);
        Assert.Null(later.Observation.ArkContext);
        Assert.Same(intent, result.Observation.ArkMemoryIntent);
        Assert.Null(before.Ark.Question);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void FirstAndSecondRuntimeIdentityChangesFailClosedWithoutMemoryIntent(bool second)
    {
        var state = Seed(); var changed = Runtime with { Token = new(true, new string('b', 64)) };
        var result = Apply(state, Question, new(123)
            { ArkRuntime = second ? Runtime : changed, ArkQuestionRuntime = second ? changed : null });
        Assert.True(result.Ark.Uncertain);
        Assert.Null(result.Ark.Pending);
        Assert.Null(result.Ark.Question);
        Assert.Null(result.Observation!.ArkMemoryIntent);
        Assert.Contains(second ? "同版題目文字" : "角色／版本／每日任務週期", result.Ark.Status);
    }

    [Fact]
    public void UnboundQuestionDoesNotRequireRuntimeAndCannotCreatePendingOrAnswer()
    {
        var state = Seed(pending: false);
        var result = Apply(state, Question, new(123));
        Assert.True(result.Ark.Uncertain);
        Assert.Null(result.Ark.Pending);
        Assert.Null(result.Ark.Question);
        Assert.Null(result.Observation!.ArkContext);
        Assert.Null(result.Observation.ArkMemoryIntent);
    }

    [Fact]
    public void LastObserverTypedFailureRollsBackCountEfficiencyAndAllStagedDomains()
    {
        var state = Seed(); var before = state.Snapshot();
        var bad = new ArkQuestionEvent(101, null!, [201, 202, 203, 204]);
        Assert.Throws<NullReferenceException>(() => Apply(state, bad));
        Assert.Same(before, state.Snapshot());
        Assert.Same(before.Efficiency, state.Snapshot().Efficiency);
        Assert.Null(before.Ark.Question);
        var success = Apply(state, Question);
        Assert.Equal(before.PacketCount + 1, success.PacketCount);
        Assert.NotSame(before.Efficiency, success.Efficiency);
        Assert.Equal(before.PacketCount, before.Local.PacketCount);
    }

    [Fact]
    public void ImportedGuildPendingAcknowledgementsNeverRunTickCompletionOrTimeout()
    {
        var pending = new GuildDonationPending(17, 72, new(true, "unverified"), 3, -1,
            new(150, 4, 8, 7, 2), 5, 1000, true, true, true);
        var imported = new GuildActionsReceiveSnapshot { Role = 17, Guild = 72, Epoch = 3,
            Pending = pending, Reserved = 150, Confirmed = 300, CatalogReady = false };
        var state = Seed(pending: false, guildActions: imported);
        var result = Apply(state, Ignored, new(1e12) { ResourceHeld = false });
        Assert.Same(imported, result.GuildActions);
        Assert.Same(pending, result.GuildActions.Pending);
        Assert.Equal(150, result.GuildActions.Reserved);
        Assert.Equal(300, result.GuildActions.Confirmed);
        Assert.False(result.GuildActions.CatalogReady);
        Assert.False(result.GuildActions.Uncertain);
    }

    [Fact]
    public void StaleContextCannotReplayIdentityBoundMemoryIntentOrAdvancePublication()
    {
        var state = Seed(); var before = state.Snapshot();
        var context = new ServiceObservationContext(before, new(123) { ArkRuntime = Runtime });
        var result = state.Apply(Question, context);
        Assert.Throws<InvalidOperationException>(() => state.Apply(Question, context));
        Assert.Same(result, state.Snapshot());
        Assert.Equal(before.PacketCount + 1, result.PacketCount);
        Assert.NotNull(result.Observation!.ArkMemoryIntent);
    }
}
