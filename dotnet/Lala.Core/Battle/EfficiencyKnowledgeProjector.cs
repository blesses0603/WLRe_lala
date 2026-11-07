using Lala.Core.Inventory;
using Lala.Core.Protocol;

namespace Lala.Core.Battle;

/// <summary>
/// Explicit projection of complete knowledge after apply_live, with player identity/name
/// after dispatch_local. No default-empty knowledge, readiness filtering, inferred statistics,
/// role selection, resource loading, or owning-state mutation. Null local player means unknown
/// identity; it does not erase the supplied player or companion knowledge.
/// </summary>
public static class EfficiencyKnowledgeProjector
{
    public static EfficiencyKnowledgeSnapshot Project(PlayerKnowledgeSnapshot updatedPlayer,
        CompanionReceiveSnapshot updatedCompanions, WorldPlayer? postLocalPlayer,
        IReadOnlyDictionary<uint, string>? npcNames = null)
    {
        ArgumentNullException.ThrowIfNull(updatedPlayer);
        ArgumentNullException.ThrowIfNull(updatedCompanions);
        ArgumentNullException.ThrowIfNull(updatedPlayer.Stats);
        ArgumentNullException.ThrowIfNull(updatedCompanions.Companions);
        var playerStats = updatedPlayer.Stats;
        var companions = new Dictionary<int, EfficiencyCompanion>();
        foreach (var (slot, profile) in updatedCompanions.Companions)
        {
            ArgumentNullException.ThrowIfNull(profile);
            ArgumentNullException.ThrowIfNull(profile.Data);
            ArgumentNullException.ThrowIfNull(profile.StatOverrides);
            var original = profile.Data;
            var current = profile.StatOverrides;
            companions.Add(slot, new(original.NpcId, new(
                current.GetValueOrDefault("exp", original.Exp),
                current.GetValueOrDefault("level", original.Level),
                current.GetValueOrDefault("degree", original.Degree), original.Name),
                npcNames?.GetValueOrDefault(original.NpcId)));
        }
        return new(postLocalPlayer?.RoleId,
            new(Value("exp"), Value("level"), Value("degree")), companions,
            postLocalPlayer is null ? "玩家" : postLocalPlayer.Name);

        long? Value(string key) => playerStats.TryGetValue(key, out var value) ? value : null;
    }
}
