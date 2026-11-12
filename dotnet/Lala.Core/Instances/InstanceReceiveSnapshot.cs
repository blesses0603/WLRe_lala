using System.Collections.Immutable;
using Lala.Core.State;

namespace Lala.Core.Instances;

/// <summary>Caller-declared inputs to the Python entry observer, not verified catalog
/// provenance, a capability token, permission to enter, or permission to send. The caller
/// must obtain the kind=1 catalog map IDs independently; this reducer does not validate,
/// load, activate or infer any catalog. An empty set cannot confirm scene entry.</summary>
public sealed record InstanceReceiveContext
{
    /// <summary>Own role before local dispatch of this observation. Retained state.py calls
    /// apply_instances before dispatch_local: do not substitute an incoming WorldPlayer or
    /// newly selected role into this value before reducing its receive evidence.</summary>
    public uint? OwnRoleId { get; init; }
    public ImmutableHashSet<ushort> DeclaredMainCatalogMapIds { get; init; } = ImmutableHashSet<ushort>.Empty;
}

/// <summary>Deeply immutable, source-shaped dungeon/cooperative receive state. StateValue
/// preserves absent/null/false and mixed numeric/text result fields, including caller-supplied
/// pending/attempt evidence. No method creates pending work or authorizes retries, spending,
/// rewards, room actions or transport. This is separate from the 英傑 challenge feature.
/// There is no source generation or sweep state; resetting requires an explicit fresh snapshot.</summary>
public sealed record InstanceReceiveSnapshot
{
    public static InstanceReceiveSnapshot Empty { get; } = new();
    public StateValue Main { get; init; } = Defaults(false);
    public StateValue Coop { get; init; } = Defaults(true);
    public override string ToString() => nameof(InstanceReceiveSnapshot);

    private static StateValue Defaults(bool coop)
    {
        var fields = new Dictionary<string, StateValue>(StringComparer.Ordinal);
        void Put(string key, object? value) => fields[key] = StateValue.Scalar(value);
        foreach (var key in new[] { "ready", "completed", "battle_active" }) Put(key, false);
        foreach (var key in new[] { "room", "list_updated_at", "completion_source" }) Put(key, null);
        fields["rooms"] = StateValue.List(); fields["members"] = StateValue.List();
        Put("phase", "idle"); Put("status", "尚未查詢房間");
        foreach (var operation in coop ? new[] { "create", "join", "leave", "standby" } : new[] { "create", "join", "leave", "start", "enter" })
        {
            Put(operation + "_pending", null); Put(operation + "_uncertain", false); Put(operation + "_result", null);
        }
        if (coop)
        {
            foreach (var key in new[] { "fight_count", "fight_consumed_battle", "last_fight_victory", "reward", "standby", "create_attempt", "standby_attempt", "match_kind", "claim_pending", "claim_result", "cancel_pending", "cancel_result", "reward_handled_fingerprint" }) Put(key, null);
            foreach (var key in new[] { "auto_claim_enabled", "reward_uncertain", "mail_notice" }) Put(key, false);
            Put("auto_claim_note", ""); fields["received_awards"] = StateValue.List();
        }
        else
        {
            Put("remaining_minutes", null); Put("entered_scene", null); fields["objectives"] = StateValue.Map();
        }
        return StateValue.Map(fields);
    }
}
