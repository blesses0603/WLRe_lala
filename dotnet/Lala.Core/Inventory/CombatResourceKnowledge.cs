using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

public sealed record CombatResourceAttribute(int Kind, long Value);
public sealed record CombatResourceItem(int? Kind = null, int FitType = 0, uint SkillLink = 0)
{
    public ImmutableArray<CombatResourceAttribute> Attributes { get; init; } = [];
    /// <summary>Explicit source item restrict mask, used only by offline candidates.</summary>
    public long Restrict { get; init; }
}
public sealed record CombatResourceNpc
{
    public string? Name { get; init; }
    public ImmutableArray<uint> Skills { get; init; } = [];
}
public sealed record CombatResourceCharacter(int Sex, int Head, uint Skill, ushort Body);
public sealed record CombatResourceSkill
{
    /// <summary>Explicit offline row fields with original SkillData spelling. Missing fields
    /// remain missing; helpers requiring them reject incomplete rows rather than invent data.</summary>
    public ImmutableDictionary<string, long> Fields { get; init; } = ImmutableDictionary<string, long>.Empty;
    public string? Name { get; init; }
    public long Required(string key)
    {
        ArgumentNullException.ThrowIfNull(Fields);
        return Fields.TryGetValue(key, out var value) ? value :
            throw new ArgumentException($"Missing skill catalog field: {key}.");
    }
}

/// <summary>Caller-supplied, unverified mappings for offline knowledge calculations. Nothing
/// here loads or activates a catalog, proves provenance, or grants permission to send actions.</summary>
public sealed record CombatResourceCatalog
{
    public static CombatResourceCatalog Empty { get; } = new();
    public ImmutableDictionary<ushort, uint> SkillKeys { get; init; } = ImmutableDictionary<ushort, uint>.Empty;
    public ImmutableDictionary<ushort, CombatResourceItem> Items { get; init; } = ImmutableDictionary<ushort, CombatResourceItem>.Empty;
    public ImmutableDictionary<uint, CombatResourceNpc> Npcs { get; init; } = ImmutableDictionary<uint, CombatResourceNpc>.Empty;
    public ImmutableDictionary<uint, CombatResourceSkill> Skills { get; init; } = ImmutableDictionary<uint, CombatResourceSkill>.Empty;
    public ImmutableArray<CombatResourceCharacter> Characters { get; init; } = [];
    /// <summary>Explicit finite source element weights. Missing rows/cells use source weight 1.</summary>
    public ImmutableDictionary<long, ImmutableDictionary<long, double>> ElementWeights { get; init; } = ImmutableDictionary<long, ImmutableDictionary<long, double>>.Empty;
    internal CombatKnowledgeCatalog EquipmentCatalog() => new()
    {
        SkillKeys = SkillKeys,
        ItemFitTypes = Items.ToImmutableDictionary(pair => pair.Key, pair => pair.Value.FitType)
    };
}

/// <summary>Sparse actor observation. Unknown HP/SP remain absent from Stats, not inferred
/// from maxima, attacks, readiness, or catalog data. Equipment is the current appearance.</summary>
public sealed record CombatResourceActor
{
    public uint? Pid { get; init; }
    public uint? MasterId { get; init; }
    public ushort? NpcIndex { get; init; }
    public int Col { get; init; }
    public int Row { get; init; }
    public uint ChangeBodyId { get; init; }
    public int? Sex { get; init; }
    public int? Head { get; init; }
    public string? Name { get; init; }
    public bool Exited { get; init; }
    public bool IsFly { get; init; }
    public ImmutableArray<KnowledgeEquipment> Equips { get; init; } = [];
    public ImmutableDictionary<string, long> Stats { get; init; } = ImmutableDictionary<string, long>.Empty;
    public ImmutableDictionary<string, bool> Statuses { get; init; } = ImmutableDictionary<string, bool>.Empty;
    public long? Element => Stats.TryGetValue("element", out var value) ? value : null;
    public long? Hp => Stats.TryGetValue("hp", out var value) ? value : null;
    public long? Sp => Stats.TryGetValue("sp", out var value) ? value : null;
    public override string ToString() => nameof(CombatResourceActor);
}

public sealed record LearnedSkillKnowledge(uint Id, long Level, uint? Exp, string? Source, ushort? Key = null);

/// <summary>The caller must retain Player, which contains resolved equipment and replayed
/// deferred receive observations. Units is a field-only projection, not a battle mutation.</summary>
public sealed record FieldCombatContext(PlayerKnowledgeSnapshot Player, ImmutableArray<CombatResourceActor> Units)
{
    public CombatResourceActor Actor => Units[0];
    public override string ToString() => nameof(FieldCombatContext);
}

/// <summary>Pure combat_resources helpers. No commands, reservations, live activation,
/// sending, scheduler, or shared session state. Every catalog is explicitly supplied.</summary>
public static partial class CombatResourceKnowledge
{
    private static readonly ImmutableHashSet<ushort> BrokenWeapons = ImmutableHashSet.Create<ushort>(
        10062, 11098, 12069, 13064, 15051, 14063, 17066, 18062, 19055, 20039,
        21120, 22125, 23105, 24090, 25044);

    public static ImmutableArray<LearnedSkillKnowledge> Learned(PlayerKnowledgeSnapshot player,
        CompanionReceiveSnapshot companions, uint? localRoleId, CombatResourceActor actor, CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(player); ArgumentNullException.ThrowIfNull(companions);
        ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(catalog);
        Validate(actor); Validate(catalog);
        var records = new Dictionary<uint, LearnedSkillKnowledge>();
        var order = new List<uint>();
        void Put(LearnedSkillKnowledge value, bool onlyIfMissing = false)
        {
            if (records.ContainsKey(value.Id)) { if (!onlyIfMissing) records[value.Id] = value; }
            else { records.Add(value.Id, value); order.Add(value.Id); }
        }
        if (actor.Pid == localRoleId)
        {
            var ids = Ordered(player.Skills, player.SkillOrder, nameof(player.SkillOrder));
            foreach (var id in ids)
            {
                var value = player.Skills[id];
                if (value.Source is not ("S5-3" or "S15技能槽＋NpcData"))
                    Put(new(id, value.Level, value.Exp, value.Source, value.Key));
            }
            if (player.ServerSkillRecords is { } raw)
            {
                RequireArray(raw, nameof(player.ServerSkillRecords));
                foreach (var value in raw)
                    if (catalog.SkillKeys.TryGetValue(value.Key, out var id) && id != 0 && value.Level > 0)
                        Put(new(id, value.Level, value.Exp, "S5-3", value.Key), true);
            }
            else foreach (var id in ids)
            {
                var value = player.Skills[id];
                Put(new(id, value.Level, value.Exp, value.Source, value.Key), true);
            }
            var removed = player.RemovedSkillIds ?? []; RequireArray(removed, nameof(player.RemovedSkillIds));
            foreach (var id in removed) { records.Remove(id); order.Remove(id); }
        }
        else if (actor.MasterId == localRoleId && actor.NpcIndex is { } slot &&
            companions.Companions.TryGetValue(slot, out var profile) && profile.Data.NpcId == actor.Pid)
        {
            foreach (var id in Ordered(profile.Skills, profile.SkillOrder, nameof(profile.SkillOrder)))
            {
                var value = profile.Skills[id];
                if (value.Source is not ("S5-3" or "S15技能槽＋NpcData")) Put(new(id, value.Level, value.Exp, value.Source));
            }
            var mapping = catalog.Npcs.GetValueOrDefault(profile.Data.NpcId)?.Skills ?? [];
            RequireArray(mapping, "NPC skills"); RequireArray(profile.Data.SkillSlots, "Companion skill slots");
            for (var i = 0; i < Math.Min(mapping.Length, profile.Data.SkillSlots.Length); i++)
            {
                var value = profile.Data.SkillSlots[i]; var id = mapping[i];
                if (id != 0 && value.Level > 0) Put(new(id, value.Level, value.Exp, "S15技能槽＋NpcData"), true);
            }
            var removed = profile.RemovedSkillIds ?? []; RequireArray(removed, nameof(profile.RemovedSkillIds));
            foreach (var id in removed) { records.Remove(id); order.Remove(id); }
        }
        uint? equipmentSkill = null;
        foreach (var equipment in actor.Equips)
        {
            var id = catalog.Items.GetValueOrDefault(equipment.ItemId)?.SkillLink ?? 0;
            if (catalog.Skills.ContainsKey(id)) equipmentSkill = id;
        }
        // Python's truthiness excludes a last matched link of zero, even if a row zero exists.
        if (equipmentSkill is > 0) Put(new(equipmentSkill.Value,
            catalog.Skills[equipmentSkill.Value].Required("LvLimit"), null, "目前裝備附帶"));
        var result = new Dictionary<uint, LearnedSkillKnowledge>();
        var resultOrder = new List<uint>();
        foreach (var id in order)
        {
            var value = records[id]; var resolved = id;
            if (id == 15003 && catalog.Characters.FirstOrDefault(value => value.Sex == actor.Sex && value.Head == actor.Head) is { } character)
                resolved = character.Skill;
            if (value.Level <= 0) continue;
            if (!result.ContainsKey(resolved)) resultOrder.Add(resolved);
            result[resolved] = value with { Id = resolved };
        }
        return [.. resultOrder.Select(id => result[id])];
    }

    public static int? WeaponGroup(CombatResourceActor actor, CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(catalog);
        Validate(actor); Validate(catalog);
        if (actor.Equips.Length < 3) return null;
        var id = actor.Equips[2].ItemId;
        var kind = id == 0 || BrokenWeapons.Contains(id) ? 0 : catalog.Items.GetValueOrDefault(id)?.Kind;
        return kind switch { 1 or 2 or 3 or 6 or 8 => 1, 0 or 7 or 9 => 2, 5 or 10 => 3, 4 => 4, 11 => 5, _ => null };
    }

    public static bool TargetValid(CombatResourceActor actor, CombatResourceActor target, CombatResourceSkill skill)
    {
        ArgumentNullException.ThrowIfNull(actor); ArgumentNullException.ThrowIfNull(target); ArgumentNullException.ThrowIfNull(skill);
        if (target.Exited || target.IsFly) return false;
        ArgumentNullException.ThrowIfNull(target.Stats);
        var dead = (target.Hp ?? 0) <= 0;
        var id = skill.Required("ID");
        if (id is 11053 or 15138) { if (!dead) return false; }
        else if (id != 15253 && skill.Required("HitStatus") != 254 && dead) return false;
        var same = (actor.Col > 2) == (target.Col > 2);
        return skill.Required("TargetKind") switch
        {
            0 => !same, 1 => same, 2 => true,
            3 => actor.Col == target.Col && actor.Row == target.Row,
            5 => same && (actor.Col != target.Col || actor.Row != target.Row), _ => false
        };
    }

    public static ImmutableDictionary<string, long> HealEffects(ushort itemId, CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(catalog); Validate(catalog);
        if (!catalog.Items.TryGetValue(itemId, out var item) || item.Kind is not (23 or 32))
            return ImmutableDictionary<string, long>.Empty;
        RequireArray(item.Attributes, nameof(item.Attributes));
        if (item.Attributes.Any(value => value is null)) throw new ArgumentException("Null item attribute.", nameof(catalog));
        var result = ImmutableDictionary.CreateBuilder<string, long>();
        foreach (var value in item.Attributes)
            if (value.Kind is 25 or 26 && value.Value > 100) result[value.Kind == 25 ? "hp" : "sp"] = value.Value - 100;
        return result.ToImmutable();
    }

    public static FieldCombatContext FieldContext(PlayerKnowledgeSnapshot player, CompanionReceiveSnapshot companions,
        WorldPlayer? localPlayer, CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(player); ArgumentNullException.ThrowIfNull(companions); ArgumentNullException.ThrowIfNull(catalog);
        Validate(catalog); ArgumentNullException.ThrowIfNull(player.Stats); ArgumentNullException.ThrowIfNull(player.Equipment);
        if (player.Equipment.Equips is { } oldEquips) RequireArray(oldEquips, "Player equips");
        if (player.Equipment.UnresolvedEquips is { } pending) RequireArray(pending, "Unresolved equips");
        if (player.Equipment.DeferredEquipUpdates is { } deferred) RequireArray(deferred, "Deferred equipment updates");
        var equipment = CombatKnowledgeReceiveReducer.ResolveEquips(player.Equipment, catalog.EquipmentCatalog());
        player = player with { Equipment = equipment };
        var actor = new CombatResourceActor { Pid = localPlayer?.RoleId, MasterId = 0, NpcIndex = 0, Col = 1, Row = 1,
            Sex = localPlayer?.Sex, Head = localPlayer?.Head, Name = localPlayer?.Name ?? "角色",
            Equips = equipment.Equips ?? [], Stats = player.Stats };
        Validate(actor);
        var units = ImmutableArray.CreateBuilder<CombatResourceActor>(); units.Add(actor);
        foreach (var slot in Ordered(companions.Companions, companions.CompanionOrder, nameof(companions.CompanionOrder)))
        {
            var profile = companions.Companions[slot]; var data = profile.Data;
            if (data.NpcId != companions.ActiveNpcId) continue;
            if (data.Index is null) throw new ArgumentException("Field companion requires a source slot index.", nameof(companions));
            var stats = CompanionStats(data).SetItems(profile.StatOverrides);
            if (profile.EquipmentOverrides is null) RequireArray(data.Equips, "Companion equips");
            var companionActor = new CombatResourceActor { Pid = data.NpcId, MasterId = localPlayer?.RoleId, NpcIndex = data.Index,
                Col = 2, Row = 1, Name = data.Name ?? catalog.Npcs.GetValueOrDefault(data.NpcId)?.Name ?? "出戰夥伴",
                Equips = profile.EquipmentOverrides ?? [.. data.Equips.Select(KnowledgeEquipment.FromItem)], Stats = stats };
            Validate(companionActor);
            units.Add(companionActor);
            break;
        }
        return new(player, units.ToImmutable());
    }

    private static ImmutableDictionary<string, long> CompanionStats(CompanionSnapshot data)
    {
        var result = new Dictionary<string, long> { ["npc_id"] = data.NpcId, ["exp"] = data.Exp, ["level"] = data.Level,
            ["str"] = data.Str, ["con"] = data.Con, ["int"] = data.Int, ["wis"] = data.Wis, ["agi"] = data.Agi,
            ["faith"] = data.Faith, ["can_grow"] = data.CanGrow, ["sport_exp"] = data.SportExp, ["degree"] = data.Degree,
            ["potential"] = data.Potential, ["modeling"] = data.Modeling, ["use_up_stats"] = data.UseUpStats };
        Add("index", data.Index); Add("hp", data.Hp); Add("sp", data.Sp); Add("die", data.Die);
        Add("skill_potential", data.SkillPotential); Add("sublime_count", data.SublimeCount); Add("party_index", data.PartyIndex);
        return result.ToImmutableDictionary();
        void Add(string key, long? value) { if (value is { } known) result[key] = known; }
    }

    private static ImmutableArray<TKey> Ordered<TKey, TValue>(ImmutableDictionary<TKey, TValue> rows,
        ImmutableArray<TKey> order, string name) where TKey : notnull
    {
        ArgumentNullException.ThrowIfNull(rows); RequireArray(order, name);
        // An immutable dictionary has no source insertion order. Refuse to guess it.
        if (order.Length != rows.Count || order.Distinct().Count() != order.Length || order.Any(id => !rows.ContainsKey(id)))
            throw new ArgumentException("Source insertion order must name each current entry exactly once.", name);
        return order;
    }
    private static void Validate(CombatResourceActor actor)
    {
        RequireArray(actor.Equips, nameof(actor.Equips)); ArgumentNullException.ThrowIfNull(actor.Stats);
        if (actor.Equips.Any(value => value is null)) throw new ArgumentException("Null equipment record.", nameof(actor));
    }
    private static void Validate(CombatResourceCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(catalog.SkillKeys); ArgumentNullException.ThrowIfNull(catalog.Items);
        ArgumentNullException.ThrowIfNull(catalog.Npcs); ArgumentNullException.ThrowIfNull(catalog.Skills);
        RequireArray(catalog.Characters, nameof(catalog.Characters));
        if (catalog.Items.Values.Any(value => value is null) || catalog.Npcs.Values.Any(value => value is null) ||
            catalog.Skills.Values.Any(value => value is null) || catalog.Characters.Any(value => value is null))
            throw new ArgumentException("Null catalog rows are not valid observations.", nameof(catalog));
    }
    private static void RequireArray<T>(ImmutableArray<T> values, string name)
    {
        if (values.IsDefault) throw new ArgumentException("An initialized immutable array is required.", name);
    }
}
