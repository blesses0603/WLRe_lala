using System.Collections.Immutable;

namespace Lala.Core.State;

/// <summary>Exact service field grants from wlre/core/state_ownership.py.</summary>
public static class StateOwnership
{
    public static ImmutableDictionary<string, ImmutableHashSet<string>> Fields { get; } =
        new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["expedition"] = ["expedition", "inventory"],
            ["alchemy"] = ["alchemy", "inventory"],
            ["crafting"] = ["crafting", "inventory", "room_storage"],
            ["room_storage"] = ["room_storage", "inventory"],
            ["tent"] = ["tent"],
            ["field_supply"] = ["inventory", "potion_storage"],
            ["maintenance"] = ["maintenance", "inventory"],
            ["auto_battle"] = ["auto_battle", "inventory"],
            ["roaming"] = ["roaming", "local_movement"],
            ["movement"] = ["local_movement", "movement_check", "location"],
            ["portal_travel"] = ["portal_travel", "event_flow"]
        }.ToImmutableDictionary(pair => pair.Key,
            pair => pair.Value.ToImmutableHashSet(StringComparer.Ordinal), StringComparer.Ordinal);
}

/// <summary>A detached immutable publication; safe to read on another thread indefinitely.</summary>
public sealed class StateSnapshot
{
    internal StateSnapshot(ImmutableDictionary<string, StateValue> fields) => Fields = fields;
    public ImmutableDictionary<string, StateValue> Fields { get; }
    public StateValue this[string field] => Fields[field];
}
