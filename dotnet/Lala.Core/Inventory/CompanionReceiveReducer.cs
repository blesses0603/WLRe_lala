using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Only S15 snapshots/add/delete, S19 active companion and companion S8 receive
/// observations. Runtime owners can explicitly opt into resolving current NPC skill metadata
/// from retained S15 slots on every observation; the default preserves Python's stored profile.
/// S15 initial batches append, empty batches mark ready, and duplicates/late
/// packets apply in arrival order. No player knowledge, battle/equipment updates, catalogs
/// activation, commands, connection authority or session coordinator integration.</summary>
public static class CompanionReceiveReducer
{
    private const string NpcSkillSource = "S15技能槽＋NpcData";

    public static CompanionReceiveSnapshot Apply(CompanionReceiveSnapshot state, ServerEvent observation,
        uint? localRoleId = null, ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills = null,
        bool reconcileNpcSkills = false)
        => ObserveLocalAttribute(ApplyBeforeLocal(state, observation, localRoleId, npcSkills, reconcileNpcSkills), observation);

    /// <summary>The companion receive slice of apply_live, before dispatch_local writes S8.</summary>
    public static CompanionReceiveSnapshot ApplyBeforeLocal(CompanionReceiveSnapshot state, ServerEvent observation,
        uint? localRoleId = null, ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills = null,
        bool reconcileNpcSkills = false)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (observation is ServerLiveDataEvent live) return Apply(state, live.Event, localRoleId, npcSkills, reconcileNpcSkills);
        if (reconcileNpcSkills) state = ResolveNpcSkills(state, npcSkills);
        if (observation is not AttributeSetEvent { Index: { } index } attribute ||
            attribute.Entity != $"follow:{index}") return state;
        if (attribute.HumanKind == 4 && state.Companions.TryGetValue(index, out var profile))
            state = state with { Companions = state.Companions.SetItem(index, ApplyAttribute(profile,
                new(attribute.Kind, attribute.Parameter, attribute.Value), attribute.Sub)) };
        return state;
    }

    /// <summary>Mirrors only dispatch_local's companion buffer write, even human_kind != 4.
    /// Service composition calls this after local dispatch, not as another apply_live observer.</summary>
    public static CompanionReceiveSnapshot ObserveLocalAttribute(CompanionReceiveSnapshot state, ServerEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (observation is not AttributeSetEvent { Index: { } index } attribute ||
            attribute.Entity != $"follow:{index}") return state;
        var entries = state.Attributes.GetValueOrDefault(index, []);
        var position = -1;
        for (var i = 0; i < entries.Length; i++)
            if (entries[i].Kind == attribute.Kind && entries[i].Parameter == attribute.Parameter) { position = i; break; }
        var value = new CompanionAttribute(attribute.Kind, attribute.Parameter, attribute.Value);
        entries = position < 0 ? entries.Add(value) : entries.SetItem(position, value);
        return state with { Attributes = state.Attributes.SetItem(index, entries) };
    }

    /// <param name="npcSkills">Explicit offline NpcData skill-ID projection; raw slots are
    /// retained when a mapping is missing. Null means unknown. By default only a fresh S15
    /// consumes this mapping, matching Python's stored profile. No loading or provenance is implied.</param>
    /// <param name="reconcileNpcSkills">Explicit runtime-owned projection opt-in for this observation.
    /// Reconcile retained slots against the current mapping, revoking metadata-derived skills
    /// when it is absent or changed while preserving S8 evidence. Never grants action authority.</param>
    public static CompanionReceiveSnapshot Apply(CompanionReceiveSnapshot state, LiveDataEvent observation,
        uint? localRoleId = null, ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills = null,
        bool reconcileNpcSkills = false)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (reconcileNpcSkills) state = ResolveNpcSkills(state, npcSkills);
        switch (observation)
        {
            case CompanionSnapshotEvent snapshot:
                state = state with { Ready = true };
                foreach (var data in snapshot.Companions) state = SetCompanion(state, data, npcSkills);
                return state;
            case CompanionAddEvent add when add.OwnerId == localRoleId && state.Ready:
                for (var i = 1; i <= byte.MaxValue; i++)
                    if (!state.Companions.ContainsKey((ushort)i))
                        return SetCompanion(state, add.Companion with { Index = (byte)i }, npcSkills);
                return state;
            case CompanionDeleteEvent delete when delete.OwnerId == localRoleId:
                return state with
                {
                    Companions = state.Companions.Remove(delete.Index), CompanionOrder = state.CompanionOrder.Remove(delete.Index),
                    Attributes = state.Attributes.Remove(delete.Index)
                };
            case ActiveCompanionEvent active:
                return state with { ActiveNpcId = active.NpcId };
            default: return state;
        }
    }

    private static CompanionReceiveSnapshot SetCompanion(CompanionReceiveSnapshot state, CompanionSnapshot data,
        ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills)
    {
        // Wire S15-8 always carries an index; S15-1 receives a free index above.
        if (data.Index is not { } index) throw new ArgumentException("Companion snapshot requires a source slot index.", nameof(data));
        var exists = state.Companions.TryGetValue(index, out var previous);
        if (exists && previous!.Data.NpcId != data.NpcId) state = state with { Attributes = state.Attributes.Remove(index) };
        var profile = ResolveNpcSkills(new CompanionProfileSnapshot(data,
            ImmutableDictionary<uint, CompanionLearnedSkill>.Empty, ImmutableDictionary<string, long>.Empty), npcSkills);
        foreach (var attribute in state.Attributes.GetValueOrDefault(index, [])) profile = ApplyAttribute(profile, attribute, 0);
        return state with
        {
            Companions = state.Companions.SetItem(index, profile),
            CompanionOrder = exists ? state.CompanionOrder : state.CompanionOrder.Add(index)
        };
    }

    private static CompanionReceiveSnapshot ResolveNpcSkills(CompanionReceiveSnapshot state,
        ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills)
    {
        var companions = state.Companions;
        foreach (var (index, profile) in state.Companions)
        {
            var resolved = ResolveNpcSkills(profile, npcSkills);
            if (!ReferenceEquals(resolved, profile)) companions = companions.SetItem(index, resolved);
        }
        return ReferenceEquals(companions, state.Companions) ? state : state with { Companions = companions };
    }

    private static CompanionProfileSnapshot ResolveNpcSkills(CompanionProfileSnapshot profile,
        ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills)
    {
        var mapped = ImmutableDictionary.CreateBuilder<uint, CompanionLearnedSkill>();
        var mappedOrder = ImmutableArray.CreateBuilder<uint>();
        var mapping = npcSkills?.TryGetValue(profile.Data.NpcId, out var ids) == true && !ids.IsDefault ? ids : [];
        for (var i = 0; i < Math.Min(mapping.Length, profile.Data.SkillSlots.Length); i++)
            if (mapping[i] != 0 && profile.Data.SkillSlots[i].Level > 0)
            {
                // set_companion keeps the first insertion position and the last positive
                // duplicate value. This stored receive evidence is not learned()'s view.
                if (!mapped.ContainsKey(mapping[i])) mappedOrder.Add(mapping[i]);
                mapped[mapping[i]] = new(profile.Data.SkillSlots[i].Level, profile.Data.SkillSlots[i].Exp, NpcSkillSource);
            }

        var skills = profile.Skills;
        var order = profile.SkillOrder;
        var removed = profile.RemovedSkillIds ?? [];
        foreach (var (id, value) in profile.Skills)
        {
            if (value.Source != NpcSkillSource) continue;
            if (!mapped.TryGetValue(id, out var replacement) || removed.Contains(id))
            {
                skills = skills.Remove(id);
                order = order.Remove(id);
            }
            else if (value != replacement) skills = skills.SetItem(id, replacement);
        }
        foreach (var id in mappedOrder)
            if (!skills.ContainsKey(id) && !removed.Contains(id))
            {
                skills = skills.Add(id, mapped[id]);
                order = order.Add(id);
            }
        // Do not replay the raw S8 buffer here: a non-companion human_kind can have
        // changed it without changing this occupant's live evidence. Only S15 replays it.
        return ReferenceEquals(skills, profile.Skills) ? profile : profile with { Skills = skills, SkillOrder = order };
    }

    private static CompanionProfileSnapshot ApplyAttribute(CompanionProfileSnapshot profile, CompanionAttribute attribute, byte sub)
    {
        if (attribute.Kind == 110)
        {
            var removed = (profile.RemovedSkillIds ?? []).Remove(attribute.Parameter);
            return profile with
            {
                RemovedSkillIds = attribute.Value <= 0 ? removed.Add(attribute.Parameter) : removed,
                SkillOrder = attribute.Value <= 0 ? profile.SkillOrder.Remove(attribute.Parameter) :
                    profile.Skills.ContainsKey(attribute.Parameter) ? profile.SkillOrder : profile.SkillOrder.Add(attribute.Parameter),
                Skills = attribute.Value > 0 ? profile.Skills.SetItem(attribute.Parameter, new(attribute.Value, 0, $"S8-{sub}")) :
                    profile.Skills.Remove(attribute.Parameter)
            };
        }
        var name = attribute.Kind switch
        {
            25 => "hp", 26 => "sp", 27 => "int", 28 => "str", 29 => "con", 30 => "agi", 33 => "wis",
            35 => "level", 36 => "exp", 38 => "attribute_potential", 39 => "degree", 41 => "atk", 43 => "matk",
            46 or 205 => "max_hp", 47 or 206 => "max_sp", _ => null
        };
        return name is null ? profile : profile with { StatOverrides = profile.StatOverrides.SetItem(name, attribute.Value) };
    }
}
