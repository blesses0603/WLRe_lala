using System.Collections.Immutable;
using Lala.Core.Battle;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Remaining receive-only apply_live branches. Run before dispatch_local against
/// the current role identity and pre-local battle units. Compose separately with bag and
/// companion receive reducers; this does not reapply their events or their S8 buffer writes.</summary>
public static class CombatKnowledgeReceiveReducer
{
    public static CombatKnowledgeReceiveResult Apply(PlayerKnowledgeSnapshot player,
        CompanionReceiveSnapshot companions, BattleEventSnapshot battle, ServerEvent observation,
        uint? localRoleId = null, CombatKnowledgeCatalog? catalog = null)
    {
        ArgumentNullException.ThrowIfNull(player);
        ArgumentNullException.ThrowIfNull(companions);
        ArgumentNullException.ThrowIfNull(battle);
        ArgumentNullException.ThrowIfNull(observation);
        catalog ??= CombatKnowledgeCatalog.Empty;
        // Source resolves only the player, before even an unrelated inventory branch returns.
        player = player with { Equipment = ResolveEquips(player.Equipment, catalog) };
        switch (observation)
        {
            case ServerLiveDataEvent { Event: PlayerCombatDataEvent value }:
                var skills = ImmutableDictionary.CreateBuilder<uint, PlayerSkillEvidence>();
                var order = ImmutableArray.CreateBuilder<uint>();
                foreach (var skill in value.Data.Skills)
                    if (catalog.SkillKeys.TryGetValue(skill.Key, out var id) && id != 0 && skill.Level > 0)
                    {
                        if (!skills.ContainsKey(id)) order.Add(id);
                        skills[id] = new(skill.Level, skill.Exp, "S5-3", skill.Key);
                    }
                player = player with { Ready = true, Skills = skills.ToImmutable(),
                    ServerSkillRecords = value.Data.Skills, RemovedSkillIds = [], SkillOrder = order.ToImmutable(),
                    Stats = player.Stats.SetItems(PlayerStats(value.Data)) };
                break;
            case ServerLiveDataEvent { Event: StarInfoEvent star }:
                player = player with { Stats = player.Stats.SetItem("level", star.Level).SetItem("degree", 2).SetItem("exp", star.Exp) };
                break;
            case AttributeSetEvent { Entity: "self" } attribute:
                player = ApplyAttribute(player, attribute);
                break;
            case ServerLiveDataEvent { Event: PlayerEquipDataEvent equipment }:
                var equips = Enumerable.Range(0, 9).Select(_ => new KnowledgeEquipment(0)).ToImmutableArray();
                foreach (var item in equipment.Equips)
                {
                    var fit = Fit(catalog, item.ItemId);
                    if (fit is >= 1 and <= 9) equips = equips.SetItem(fit.Value - 1, KnowledgeEquipment.FromItem(item));
                }
                player = player with { Equipment = new() { Equips = equips,
                    UnresolvedEquips = [.. equipment.Equips.Where(item => !catalog.ItemFitTypes.ContainsKey(item.ItemId))],
                    DeferredEquipUpdates = [], EquipmentNeedsSnapshot = false } };
                break;
            case ServerLiveDataEvent { Event: EquipDamageEvent or EquipBrokenEvent } live:
                var npc = live.Event is EquipDamageEvent damage ? damage.NpcIndex : ((EquipBrokenEvent)live.Event).NpcIndex;
                if (npc == 0) player = player with { Equipment = Damage(player.Equipment, live.Event, catalog) };
                else if (companions.Companions.TryGetValue(npc, out var companion))
                {
                    var current = Equipment(companion);
                    var changed = UpdateEquipment(current, live.Event, catalog);
                    companions = companions with { Companions = companions.Companions.SetItem(npc, companion with { EquipmentOverrides = changed }) };
                }
                break;
            case ServerLayoutEvent { Event: BattleStartEvent start }:
                foreach (var unit in start.Units) ApplyStats(unit, UnitStats(unit));
                break;
            case ServerLayoutEvent { Event: BattleUnitsEvent units }:
                foreach (var unit in units.Units) ApplyStats(unit, UnitStats(unit));
                break;
            case BattleAttributeSetEvent attributes:
                foreach (var value in attributes.Values)
                {
                    var name = value.Kind switch { 25 => "hp", 26 => "sp", 46 => "max_hp", 47 => "max_sp", _ => null };
                    if (name is not null && battle.UnitAt(new(value.Col, value.Row)) is { } unit)
                        ApplyStats(unit.Layout, [KeyValuePair.Create(name, (long)value.Value)]);
                }
                break;
            case ServerLiveDataEvent { Event: BattleEquipEvent equip } when equip.EquipIndex is >= 1 and <= 9:
                if (equip.OwnerId == localRoleId)
                {
                    if (equip.NpcIndex == 0)
                    {
                        var current = player.Equipment;
                        if (current.UnresolvedEquips is { IsEmpty: false }) current = Defer(current, equip);
                        // Source queues AND immediately applies a changed-ID appearance.
                        current = current with { Equips = ApplyAppearanceIfChanged(current.Equips, equip) };
                        player = player with { Equipment = current };
                    }
                    else if (companions.Companions.TryGetValue(equip.NpcIndex, out var profile))
                        companions = companions with { Companions = companions.Companions.SetItem(equip.NpcIndex,
                            profile with { EquipmentOverrides = ApplyAppearanceIfChanged(Equipment(profile), equip) }) };
                }
                var next = battle.Units;
                for (var i = 0; i < next.Length; i++)
                {
                    var unit = next[i];
                    var match = equip.NpcIndex == 0 ? unit.Layout.Pid == equip.OwnerId :
                        unit.Layout.MasterId == equip.OwnerId && unit.Layout.NpcIndex == equip.NpcIndex;
                    if (!match) continue;
                    if (unit.Equips.Length < equip.EquipIndex)
                        throw new ArgumentException("Battle unit must contain the received equipment slot.", nameof(battle));
                    next = next.SetItem(i, unit with { EquipmentOverrides = unit.Equips.SetItem(equip.EquipIndex - 1,
                        new(equip.ItemId, equip.DesignId)) });
                }
                battle = battle with { Units = next };
                break;
        }
        return new(player, companions, battle);

        void ApplyStats(BattleUnit actor, IEnumerable<KeyValuePair<string, long>> values)
        {
            // Player identity wins before master/slot checks, exactly like profile_for.
            if (actor.Pid == localRoleId) player = player with { Stats = player.Stats.SetItems(values) };
            else if (actor.MasterId == localRoleId && companions.Companions.TryGetValue(actor.NpcIndex, out var profile)
                && profile.Data.NpcId == actor.Pid)
                companions = companions with { Companions = companions.Companions.SetItem(actor.NpcIndex,
                    profile with { StatOverrides = profile.StatOverrides.SetItems(values) }) };
        }
    }

    public static PlayerEquipmentKnowledge ResolveEquips(PlayerEquipmentKnowledge profile, CombatKnowledgeCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(profile); ArgumentNullException.ThrowIfNull(catalog);
        if (profile.UnresolvedEquips is not { IsEmpty: false } pending) return profile;
        var equips = profile.Equips ?? Enumerable.Range(0, 9).Select(_ => new KnowledgeEquipment(0)).ToImmutableArray();
        var unresolved = ImmutableArray.CreateBuilder<ItemSave>();
        foreach (var value in pending)
        {
            if (!catalog.ItemFitTypes.ContainsKey(value.ItemId)) { unresolved.Add(value); continue; }
            var fit = Fit(catalog, value.ItemId);
            if (fit >= 1 && fit <= equips.Length) equips = equips.SetItem(fit.Value - 1, KnowledgeEquipment.FromItem(value));
        }
        var remaining = unresolved.ToImmutable();
        if (remaining.IsEmpty)
            foreach (var update in profile.DeferredEquipUpdates ?? []) equips = UpdateEquipment(equips, update, catalog);
        return profile with { Equips = equips, UnresolvedEquips = remaining,
            DeferredEquipUpdates = remaining.IsEmpty ? null : profile.DeferredEquipUpdates };
    }

    private static ImmutableArray<KnowledgeEquipment> Equipment(CompanionProfileSnapshot profile) =>
        profile.EquipmentOverrides ?? [.. profile.Data.Equips.Select(KnowledgeEquipment.FromItem)];

    private static ImmutableArray<KnowledgeEquipment>? ApplyAppearanceIfChanged(ImmutableArray<KnowledgeEquipment>? equips, BattleEquipEvent value)
        => equips is { } values && value.EquipIndex <= values.Length && values[value.EquipIndex - 1].ItemId != value.ItemId ?
            values.SetItem(value.EquipIndex - 1, new(value.ItemId, value.DesignId)) : equips;

    private static PlayerEquipmentKnowledge Damage(PlayerEquipmentKnowledge profile, LiveDataEvent update, CombatKnowledgeCatalog catalog)
    {
        if (profile.UnresolvedEquips is { IsEmpty: false }) return Defer(profile, update);
        return profile.Equips is { } equips ? profile with { Equips = UpdateEquipment(equips, update, catalog) } : profile;
    }

    private static PlayerEquipmentKnowledge Defer(PlayerEquipmentKnowledge profile, LiveDataEvent update)
    {
        var queue = profile.DeferredEquipUpdates ?? [];
        return queue.Length >= 256 ? profile with { Equips = [], UnresolvedEquips = [], DeferredEquipUpdates = [], EquipmentNeedsSnapshot = true } :
            profile with { DeferredEquipUpdates = queue.Add(update) };
    }

    private static ImmutableArray<KnowledgeEquipment> UpdateEquipment(ImmutableArray<KnowledgeEquipment> equips, LiveDataEvent update, CombatKnowledgeCatalog catalog)
    {
        int? index = update switch { EquipDamageEvent value => value.Index,
            EquipBrokenEvent value => value.Index is { } explicitIndex ? explicitIndex : Fit(catalog, value.ItemId),
            BattleEquipEvent value => value.EquipIndex, _ => null };
        if (index is null || index < 1 || index > equips.Length) return equips;
        var i = index.Value - 1;
        var previous = equips[i];
        return equips.SetItem(i, update switch
        {
            EquipDamageEvent value => previous with { Damage = value.Damage },
            EquipBrokenEvent value => previous with { ItemId = value.ItemId, Damage = 250 },
            BattleEquipEvent value => new(value.ItemId, value.DesignId),
            _ => previous
        });
    }

    private static int? Fit(CombatKnowledgeCatalog catalog, ushort id) =>
        catalog.ItemFitTypes.TryGetValue(id, out var fit) ? fit == 11 ? 7 : fit : null;

    private static PlayerKnowledgeSnapshot ApplyAttribute(PlayerKnowledgeSnapshot player, AttributeSetEvent value)
    {
        if (value.Kind == 110)
        {
            var removed = (player.RemovedSkillIds ?? []).Remove(value.Parameter);
            return player with { RemovedSkillIds = value.Value <= 0 ? removed.Add(value.Parameter) : removed,
                SkillOrder = value.Value <= 0 ? player.SkillOrder.Remove(value.Parameter) :
                    player.Skills.ContainsKey(value.Parameter) ? player.SkillOrder : player.SkillOrder.Add(value.Parameter),
                Skills = value.Value > 0 ? player.Skills.SetItem(value.Parameter, new(value.Value, 0, $"S8-{value.Sub}")) : player.Skills.Remove(value.Parameter) };
        }
        var name = value.Kind switch { 25 => "hp", 26 => "sp", 27 => "int", 28 => "str", 29 => "con", 30 => "agi", 33 => "wis",
            35 => "level", 36 => "exp", 38 => "attribute_potential", 39 => "degree", 41 => "atk", 43 => "matk",
            46 or 205 => "max_hp", 47 or 206 => "max_sp", _ => null };
        return name is null ? player : player with { Stats = player.Stats.SetItem(name, value.Value) };
    }

    private static IEnumerable<KeyValuePair<string, long>> UnitStats(BattleUnit unit) => new Dictionary<string, long>
    { ["hp"] = unit.Hp, ["sp"] = unit.Sp, ["max_hp"] = unit.MaxHp, ["max_sp"] = unit.MaxSp, ["level"] = unit.Level, ["degree"] = unit.Degree };

    private static IEnumerable<KeyValuePair<string, long>> PlayerStats(PlayerCombatData data) => new Dictionary<string, long>
    {
        ["element"] = data.Element, ["hp"] = data.Hp, ["sp"] = data.Sp, ["str"] = data.Str, ["con"] = data.Con,
        ["int"] = data.Int, ["wis"] = data.Wis, ["agi"] = data.Agi, ["level"] = data.Level, ["exp"] = data.Exp,
        ["skill_potential"] = data.SkillPotential, ["attribute_potential"] = data.AttributePotential,
        ["max_hp"] = data.MaxHp, ["max_sp"] = data.MaxSp, ["equip_atk"] = data.EquipAtk, ["equip_def"] = data.EquipDef,
        ["equip_matk"] = data.EquipMatk, ["equip_speed_atk"] = data.EquipSpeedAtk, ["equip_max_hp"] = data.EquipMaxHp,
        ["equip_max_sp"] = data.EquipMaxSp, ["spring_hp"] = data.SpringHp, ["spring_sp"] = data.SpringSp,
        ["degree"] = data.Degree, ["job"] = data.Job, ["potential"] = data.Potential
    };
}
