using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public sealed class ReceivedBattleActorTests
{
    private static BattleUnit Unit(byte col = 3, uint pid = 0) => new(16, 0, pid, 2, 0, col, 1,
        100, 40, 90, 20, 19, 2, 1, 3, 0, 7, 1, 2, 0, 0, "Fixture", [new(123, 456)]);

    [Fact]
    public void ActorCarriesOnlyReceivedFieldsAndSparseAppearance()
    {
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(12, 3, [Unit()]));
        var actor = battle.Actors.Single().Actor;
        Assert.Equal("3:1", battle.Actors.Single().Slot);
        Assert.Equal(0u, actor.Pid); Assert.Equal(0u, actor.MasterId); Assert.Equal((ushort)2, actor.NpcIndex);
        Assert.Equal(7u, actor.ChangeBodyId); Assert.Equal(1, actor.Sex); Assert.Equal(2, actor.Head);
        Assert.Equal("Fixture", actor.Name); Assert.Equal(3, actor.Col); Assert.Equal(1, actor.Row);
        Assert.Equal(8, actor.Stats.Count);
        Assert.Equal(90L, actor.Hp); Assert.Equal(20L, actor.Sp); Assert.Equal(2L, actor.Element);
        Assert.Equal(100L, actor.Stats["max_hp"]); Assert.Equal(40L, actor.Stats["max_sp"]);
        Assert.Equal(19L, actor.Stats["level"]); Assert.Equal(1L, actor.Stats["degree"]); Assert.Equal(3L, actor.Stats["job"]);
        Assert.False(actor.IsFly); Assert.Empty(actor.Statuses); Assert.False(actor.Exited);
        Assert.Equal(new KnowledgeEquipment(123, 456), actor.Equips.Single());
        Assert.False(actor.Stats.ContainsKey("atk")); Assert.False(actor.Stats.ContainsKey("speed"));
        Assert.Empty(BattleEventSnapshot.Empty.Actors);
    }

    [Fact]
    public void CurrentVitalsButOriginalMaximaAndDesignOnlyAppearanceMatchPython()
    {
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(12, 3, [Unit()]));
        var original = battle.Actors.Single().Actor;
        var attrs = new BattleAttributeSetEvent([new(3, 1, 25, uint.MaxValue), new(3, 1, 26, 70000),
            new(3, 1, 46, 999), new(3, 1, 47, 888), new(3, 1, 41, 777)]);
        var knowledge = CombatKnowledgeReceiveReducer.Apply(PlayerKnowledgeSnapshot.Empty, CompanionReceiveSnapshot.Empty,
            battle, attrs, 0);
        battle = BattleEventReducer.Apply(knowledge.Battle, attrs, 0);
        Assert.Equal(999L, knowledge.Player.Stats["max_hp"]); Assert.Equal(888L, knowledge.Player.Stats["max_sp"]);
        battle = CombatKnowledgeReceiveReducer.Apply(knowledge.Player, knowledge.Companions, battle,
            new ServerLiveDataEvent(new BattleEquipEvent(0, 0, 1, 123, 999)), 0).Battle;
        var current = battle.Actors.Single().Actor;
        Assert.Equal((long)uint.MaxValue, current.Hp); Assert.Equal(70000L, current.Sp);
        Assert.Equal(100L, current.Stats["max_hp"]); Assert.Equal(40L, current.Stats["max_sp"]);
        Assert.False(current.Stats.ContainsKey("atk")); Assert.Equal(new KnowledgeEquipment(123, 999), current.Equips.Single());
        Assert.Equal(90L, original.Hp); Assert.Equal(456u, original.Equips.Single().DesignId);
    }

    [Fact]
    public void ReplacementKeepsInsertionOrderClearsOverlaysAndStartClearsEntries()
    {
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleStartEvent(12, 3, [Unit(), Unit(1, 9)]));
        battle = BattleEventReducer.Apply(battle, new BattleAttributeSetEvent([new(3, 1, 25, 1)]));
        battle = BattleEventReducer.Apply(battle, new BattleUnitExitEvent(3, 1, null));
        battle = CombatKnowledgeReceiveReducer.Apply(PlayerKnowledgeSnapshot.Empty, CompanionReceiveSnapshot.Empty, battle,
            new ServerLiveDataEvent(new BattleEquipEvent(0, 0, 1, 999, 888)), 0).Battle;
        var exited = battle.Actors;
        battle = BattleEventReducer.Apply(battle, new BattleUnitsEvent([Unit(3, 8)]));
        Assert.Equal(new[] { "3:1", "1:1" }, battle.Actors.Select(entry => entry.Slot));
        Assert.Equal(8u, battle.Actors[0].Actor.Pid); Assert.Equal(90L, battle.Actors[0].Actor.Hp);
        Assert.Equal(new KnowledgeEquipment(123, 456), battle.Actors[0].Actor.Equips.Single());
        Assert.Equal(new KnowledgeEquipment(999, 888), exited[0].Actor.Equips.Single());
        Assert.False(battle.Actors[0].Actor.Exited); Assert.True(exited[0].Actor.Exited); Assert.Equal(1L, exited[0].Actor.Hp);
        Assert.Empty(BattleEventReducer.Apply(battle, new BattleStartEvent(12, 3, [])).Actors);
    }
}
