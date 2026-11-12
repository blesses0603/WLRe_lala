using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Inventory;

public sealed class CombatKnowledgeContractTests
{
    private static readonly CombatKnowledgeCatalog Known = new()
    { ItemFitTypes = new Dictionary<ushort, int> { [42] = 3, [99] = 2 }.ToImmutableDictionary() };
    private static ItemSave Item(ushort id = 42) => new(null, id, 1, 4, 2, 999, null, null,
        3, -100, 10, 1, 2, 3, null, 4, 5, 6, [new(7, 8)], true, 9, 10, null);
    private static BattleUnit Unit(uint pid = 7, ushort npc = 0, uint master = 0, byte col = 1) =>
        new(9, 4, pid, npc, master, col, 1, 100, 20, 90, 15, 3, 1, 0, 0, 0, 0, 1, 2, 3, 4, "synthetic",
            [.. Enumerable.Range(0, 9).Select(_ => new EquipmentAppearance(42, 6))]);
    private static CompanionSnapshot Companion() => new(1, 42, 100, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2,
        3, "synthetic", [new(1, 10)], [.. Enumerable.Range(0, 9).Select(_ => Item())], 0, 1, 2, 3, 4, 5, 6);
    private static CombatKnowledgeReceiveResult Apply(PlayerKnowledgeSnapshot player, LiveDataEvent value,
        CombatKnowledgeCatalog? catalog = null, CompanionReceiveSnapshot? companions = null, BattleEventSnapshot? battle = null) =>
        CombatKnowledgeReceiveReducer.Apply(player, companions ?? CompanionReceiveSnapshot.Empty, battle ?? BattleEventSnapshot.Empty,
            new ServerLiveDataEvent(value), 7, catalog);

    [Fact]
    public void InitialUnknownValuesAndEquipmentNeverImplyCombatReadiness()
    {
        var empty = PlayerKnowledgeSnapshot.Empty;
        Assert.False(empty.Ready); Assert.Empty(empty.Stats); Assert.Null(empty.ServerSkillRecords);
        Assert.Null(empty.RemovedSkillIds); Assert.Null(empty.Equipment.Equips);
        Assert.Null(empty.Equipment.EquipmentNeedsSnapshot);
        var changed = Apply(empty, new PlayerEquipDataEvent([Item()]));
        Assert.False(changed.Player.Ready); Assert.Empty(changed.Player.Stats);
        Assert.Single(changed.Player.Equipment.UnresolvedEquips!.Value);
        Assert.False(changed.Player.Equipment.EquipmentNeedsSnapshot);
    }

    [Fact]
    public void BattleAppearancePreservesOriginalLayoutAttributesHealthAndExit()
    {
        var original = Unit();
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent([original]));
        battle = BattleEventReducer.Apply(battle, new BattleAttributeSetEvent([new(1, 1, 25, 0xffffffff), new(1, 1, 26, 0xffffffff)]));
        battle = BattleEventReducer.Apply(battle, new BattleUnitExitEvent(1, 1, null), 7);
        var next = Apply(PlayerKnowledgeSnapshot.Empty, new BattleEquipEvent(7, 0, 3, 99, 123), battle: battle).Battle;
        var unit = Assert.Single(next.Units);
        Assert.Same(original, unit.Layout);
        Assert.Equal(new EquipmentAppearance(42, 6), unit.Layout.Equips[2]);
        Assert.Equal(new EquipmentAppearance(99, 123), unit.Equips[2]);
        Assert.Equal(uint.MaxValue, unit.Hp); Assert.Equal(uint.MaxValue, unit.Sp); Assert.True(unit.Exited);
        Assert.Same(battle.Units[0].Attributes, unit.Attributes);
        Assert.Null(battle.Units[0].EquipmentOverrides);
        var replacement = BattleEventReducer.Apply(next, new BattleUnitsEvent([original]));
        Assert.Null(replacement.Units[0].EquipmentOverrides);
        Assert.Equal(original.Equips, replacement.Units[0].Equips);
    }

    [Fact]
    public void CompanionSparseReplacementRetainsOriginalFullSnapshotAndClearsOnS15()
    {
        var original = Companion();
        var companions = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty, new CompanionSnapshotEvent([original]));
        var changed = Apply(PlayerKnowledgeSnapshot.Empty, new BattleEquipEvent(7, 1, 3, 99, 123), companions: companions).Companions;
        Assert.Same(original, changed.Companions[1].Data);
        var equip = changed.Companions[1].EquipmentOverrides!.Value[2];
        Assert.Null(equip.OriginalRecord); Assert.Null(equip.Damage); Assert.Equal((uint)123, equip.DesignId);
        Assert.Equal((ushort)42, changed.Companions[1].Data.Equips[2].ItemId);
        Assert.Null(companions.Companions[1].EquipmentOverrides);
        var fresh = CompanionReceiveReducer.Apply(changed, new CompanionSnapshotEvent([original]));
        Assert.Null(fresh.Companions[1].EquipmentOverrides);
    }

    [Fact]
    public void SameItemIgnoresProfileDesignButStillChangesBattleAppearance()
    {
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item()]), Known).Player;
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent([Unit()]));
        var next = Apply(player, new BattleEquipEvent(7, 0, 3, 42, 999), Known, battle: battle);
        Assert.Equal((uint)6, next.Player.Equipment.Equips!.Value[2].DesignId);
        Assert.Equal((uint)999, next.Battle.Units[0].Equips[2].DesignId);
        Assert.Equal((uint)6, next.Battle.Units[0].Layout.Equips[2].DesignId);
    }

    [Fact]
    public void QueuedSameItemAppearanceReplaysUnconditionallyAfterLateResolution()
    {
        var partial = Known with { ItemFitTypes = Known.ItemFitTypes.Remove(99) };
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item(), Item(99)]), partial).Player;
        player = Apply(player, new BattleEquipEvent(7, 0, 3, 42, 999), partial).Player;
        Assert.Equal((uint)6, player.Equipment.Equips!.Value[2].DesignId);
        var resolved = CombatKnowledgeReceiveReducer.ResolveEquips(player.Equipment, Known);
        Assert.Equal((uint)999, resolved.Equips!.Value[2].DesignId);
        Assert.Null(resolved.Equips.Value[2].OriginalRecord); Assert.Null(resolved.Equips.Value[2].Damage);
        Assert.Null(resolved.DeferredEquipUpdates); Assert.Single(player.Equipment.DeferredEquipUpdates!.Value);
    }

    [Fact]
    public void DamageCanExceedOriginalByteWithoutMutatingFullRecord()
    {
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item()]), Known).Player;
        var changed = Apply(player, new EquipDamageEvent(140, 0, 3, uint.MaxValue, 2), Known).Player;
        Assert.Equal(uint.MaxValue, changed.Equipment.Equips!.Value[2].Damage);
        Assert.Equal((byte)4, changed.Equipment.Equips.Value[2].OriginalRecord!.Damage);
        Assert.Equal((uint)4, player.Equipment.Equips!.Value[2].Damage);
        Assert.Equal(999U, changed.Equipment.Equips.Value[2].OriginalRecord!.Serial);
    }

    [Fact]
    public void KnownZeroFitIsResolvedAndDoesNotDelayOtherSlots()
    {
        var catalog = Known with { ItemFitTypes = Known.ItemFitTypes.SetItem(99, 0) };
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item(99), Item()])).Player;
        player = Apply(player, new EquipDamageEvent(27, 0, 3, 17)).Player;
        var resolved = CombatKnowledgeReceiveReducer.ResolveEquips(player.Equipment, catalog);
        Assert.Empty(resolved.UnresolvedEquips!.Value); Assert.Null(resolved.DeferredEquipUpdates);
        Assert.Equal((ushort)42, resolved.Equips!.Value[2].ItemId); Assert.Equal((uint)17, resolved.Equips.Value[2].Damage);
        Assert.DoesNotContain(resolved.Equips.Value, item => item.ItemId == 99);
    }

    [Fact]
    public void UnrelatedReceiveResolvesPendingEquipmentButCatalogSelectionAloneDoesNot()
    {
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item()])).Player;
        var changed = CombatKnowledgeReceiveReducer.Apply(player, CompanionReceiveSnapshot.Empty, BattleEventSnapshot.Empty,
            new UnimplementedServerEvent(255, 255, 0), 7, Known);
        Assert.Single(player.Equipment.UnresolvedEquips!.Value);
        Assert.Empty(changed.Player.Equipment.UnresolvedEquips!.Value);
        Assert.Empty(changed.Player.Stats);
    }

    [Fact]
    public void NestedCollectionsAndResetHistoryAreImmutable()
    {
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item()]), Known).Player;
        Assert.Throws<NotSupportedException>(() => ((IList<KnowledgeEquipment>)player.Equipment.Equips!.Value).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemPlugin>)player.Equipment.Equips!.Value[2].OriginalRecord!.Plugins).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, long>)player.Stats).Add("hp", 1));
        var fresh = PlayerKnowledgeSnapshot.Empty;
        Assert.Null(fresh.Equipment.Equips); Assert.Equal(9, player.Equipment.Equips!.Value.Length);
    }

    [Fact]
    public void KnownRoleZeroMatchesProfilesWhileUnknownRoleOnlyChangesMatchingBattleAppearance()
    {
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item()]), Known).Player;
        var companions = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty,
            new CompanionSnapshotEvent([Companion()]));
        var units = new BattleUnitsEvent([Unit(pid: 0, npc: 9, master: 8), Unit(pid: 42, npc: 1, master: 0, col: 2)]);
        var message = new ServerLayoutEvent(units);
        var known = CombatKnowledgeReceiveReducer.Apply(player, companions, BattleEventSnapshot.Empty, message, 0, Known);
        var unknown = CombatKnowledgeReceiveReducer.Apply(player, companions, BattleEventSnapshot.Empty, message, null, Known);
        Assert.Equal(90L, known.Player.Stats["hp"]);
        Assert.Equal(90L, known.Companions.Companions[1].StatOverrides["hp"]);
        Assert.Empty(unknown.Player.Stats);
        Assert.Empty(unknown.Companions.Companions[1].StatOverrides);

        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, units);
        foreach (byte npc in new byte[] { 0, 1 })
        {
            var equipment = new ServerLiveDataEvent(new BattleEquipEvent(0, npc, 3, 99, 123));
            var matched = CombatKnowledgeReceiveReducer.Apply(player, companions, battle, equipment, 0, Known);
            var unmatched = CombatKnowledgeReceiveReducer.Apply(player, companions, battle, equipment, null, Known);
            if (npc == 0)
            {
                Assert.Equal((ushort)99, matched.Player.Equipment.Equips!.Value[2].ItemId);
                Assert.Equal((ushort)42, unmatched.Player.Equipment.Equips!.Value[2].ItemId);
            }
            else
            {
                Assert.Equal((ushort)99, matched.Companions.Companions[1].EquipmentOverrides!.Value[2].ItemId);
                Assert.Null(unmatched.Companions.Companions[1].EquipmentOverrides);
            }
            // Appearance matches the packet owner independently of local profile ownership.
            Assert.Equal(new EquipmentAppearance(99, 123), matched.Battle.Units[npc].Equips[2]);
            Assert.Equal(new EquipmentAppearance(99, 123), unmatched.Battle.Units[npc].Equips[2]);
            Assert.Equal(new EquipmentAppearance(42, 6), battle.Units[npc].Equips[2]);
        }
        Assert.Empty(player.Stats);
        Assert.Null(companions.Companions[1].EquipmentOverrides);
    }

    [Fact]
    public void ShortSyntheticBattleEquipmentFailsAtomicallyAfterEarlierCandidateUpdates()
    {
        var partial = Known with { ItemFitTypes = Known.ItemFitTypes.Remove(99) };
        var player = Apply(PlayerKnowledgeSnapshot.Empty, new PlayerEquipDataEvent([Item(), Item(99)]), partial).Player;
        player = Apply(player, new EquipDamageEvent(27, 0, 3, 17), partial).Player;
        var companions = CompanionReceiveReducer.Apply(CompanionReceiveSnapshot.Empty,
            new CompanionSnapshotEvent([Companion()]));
        var valid = Unit();
        var shortUnit = Unit(col: 2) with { Equips = [] };
        var battle = BattleEventReducer.Apply(BattleEventSnapshot.Empty, new BattleUnitsEvent([valid, shortUnit]));
        var publication = new CombatKnowledgeReceiveResult(player, companions, battle);
        var original = publication;

        // Resolution, own-profile replacement, and the first matching unit update would all
        // precede the second unit's invalid slot. No partial result may be published.
        var error = Assert.Throws<ArgumentException>(() => publication = CombatKnowledgeReceiveReducer.Apply(
            publication.Player, publication.Companions, publication.Battle,
            new ServerLiveDataEvent(new BattleEquipEvent(7, 0, 3, 45, 123)), 7, Known));
        Assert.Equal("battle", error.ParamName);
        Assert.Same(original, publication);
        Assert.Same(player, publication.Player);
        Assert.Same(companions, publication.Companions);
        Assert.Same(battle, publication.Battle);
        Assert.Single(player.Equipment.UnresolvedEquips!.Value);
        Assert.Single(player.Equipment.DeferredEquipUpdates!.Value);
        Assert.Equal((ushort)42, player.Equipment.Equips!.Value[2].ItemId);
        Assert.Equal((uint)4, player.Equipment.Equips.Value[2].Damage);
        Assert.Null(companions.Companions[1].EquipmentOverrides);
        Assert.Same(valid, battle.Units[0].Layout);
        Assert.Null(battle.Units[0].EquipmentOverrides);
        Assert.Equal(new EquipmentAppearance(42, 6), battle.Units[0].Equips[2]);
        Assert.Same(shortUnit, battle.Units[1].Layout);
        Assert.Empty(battle.Units[1].Equips);
    }

    [Fact]
    public void NullArgumentsAreRejectedWithoutChangingAnyPublication()
    {
        Assert.Throws<ArgumentNullException>(() => CombatKnowledgeReceiveReducer.Apply(null!, CompanionReceiveSnapshot.Empty,
            BattleEventSnapshot.Empty, new UnimplementedServerEvent(1, 2, 0)));
        Assert.Throws<ArgumentNullException>(() => CombatKnowledgeReceiveReducer.ResolveEquips(new(), null!));
    }
}
