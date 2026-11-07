using System.Collections.Immutable;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>Only S15 snapshots/add/delete, S19 active companion and companion S8 receive
/// observations. S15 initial batches append, empty batches mark ready, and duplicates/late
/// packets apply in arrival order. No player knowledge, battle/equipment updates, catalogs
/// activation, commands, connection authority or session coordinator integration.</summary>
public static class CompanionReceiveReducer
{
    public static CompanionReceiveSnapshot Apply(CompanionReceiveSnapshot state, ServerEvent observation,
        uint? localRoleId = null, ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        if (observation is ServerLiveDataEvent live) return Apply(state, live.Event, localRoleId, npcSkills);
        if (observation is not AttributeSetEvent { Index: { } index } attribute ||
            attribute.Entity != $"follow:{index}") return state;
        if (attribute.HumanKind == 4 && state.Companions.TryGetValue(index, out var profile))
            state = state with { Companions = state.Companions.SetItem(index, ApplyAttribute(profile,
                new(attribute.Kind, attribute.Parameter, attribute.Value), attribute.Sub)) };
        // State's local-session observer stores S8 after apply_live, even human_kind != 4.
        var entries = state.Attributes.GetValueOrDefault(index, []);
        var position = -1;
        for (var i = 0; i < entries.Length; i++)
            if (entries[i].Kind == attribute.Kind && entries[i].Parameter == attribute.Parameter) { position = i; break; }
        var value = new CompanionAttribute(attribute.Kind, attribute.Parameter, attribute.Value);
        entries = position < 0 ? entries.Add(value) : entries.SetItem(position, value);
        return state with { Attributes = state.Attributes.SetItem(index, entries) };
    }

    /// <param name="npcSkills">Explicit offline NpcData skill-ID projection; raw slots are
    /// retained when a mapping is missing. No catalog loading or provenance is implied.</param>
    public static CompanionReceiveSnapshot Apply(CompanionReceiveSnapshot state, LiveDataEvent observation,
        uint? localRoleId = null, ImmutableDictionary<uint, ImmutableArray<uint>>? npcSkills = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
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
        var skills = ImmutableDictionary.CreateBuilder<uint, CompanionLearnedSkill>();
        var mapping = npcSkills?.TryGetValue(data.NpcId, out var ids) == true && !ids.IsDefault ? ids : [];
        for (var i = 0; i < Math.Min(mapping.Length, data.SkillSlots.Length); i++)
            if (mapping[i] != 0 && data.SkillSlots[i].Level > 0)
                skills[mapping[i]] = new(data.SkillSlots[i].Level, data.SkillSlots[i].Exp, "S15技能槽＋NpcData");
        var profile = new CompanionProfileSnapshot(data, skills.ToImmutable(), ImmutableDictionary<string, long>.Empty);
        foreach (var attribute in state.Attributes.GetValueOrDefault(index, [])) profile = ApplyAttribute(profile, attribute, 0);
        return state with
        {
            Companions = state.Companions.SetItem(index, profile),
            CompanionOrder = exists ? state.CompanionOrder : state.CompanionOrder.Add(index)
        };
    }

    private static CompanionProfileSnapshot ApplyAttribute(CompanionProfileSnapshot profile, CompanionAttribute attribute, byte sub)
    {
        if (attribute.Kind == 110)
        {
            var removed = (profile.RemovedSkillIds ?? []).Remove(attribute.Parameter);
            return profile with
            {
                RemovedSkillIds = attribute.Value <= 0 ? removed.Add(attribute.Parameter) : removed,
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
