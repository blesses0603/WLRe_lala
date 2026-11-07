using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

public sealed record PotionResourceSnapshot(BigInteger? Value, BigInteger Revision)
{
    public override string ToString() => nameof(PotionResourceSnapshot);
}

/// <summary>Only recovery.apply_recovery's receive balances. Missing Value is unknown, not
/// zero. A new snapshot resets this domain; there is no timer, spending plan or persistence.</summary>
public sealed record PotionStorageSnapshot
{
    public static PotionStorageSnapshot Empty { get; } = new();
    public ImmutableDictionary<string, PotionResourceSnapshot> Resources { get; init; } =
        ImmutableDictionary<string, PotionResourceSnapshot>.Empty.WithComparers(StringComparer.Ordinal);
    public override string ToString() => nameof(PotionStorageSnapshot);
}

/// <summary>Decode before reducing. Absolute balances replace, known deltas clamp at zero,
/// duplicates and late deltas still count, and no delta creates an unknown baseline. Used
/// and item-update receipts are ignored here, never inferred as credits/debits or healing.
/// This is deliberately not wired to AccountSession, field_supply or any command sender.</summary>
public static class RecoveryReducer
{
    public static PotionStorageSnapshot Apply(PotionStorageSnapshot state, ServerEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        return observation is ServerInventoryEvent inventory ? Apply(state, inventory.Event) : state;
    }

    public static PotionStorageSnapshot Apply(PotionStorageSnapshot state, InventoryEvent observation)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(observation);
        string resource;
        BigInteger value;
        switch (observation)
        {
            case PotionBalanceEvent balance:
                resource = balance.Resource; value = balance.Value;
                break;
            case PotionBalanceAddEvent delta:
                resource = delta.Resource;
                if (state.Resources.GetValueOrDefault(resource)?.Value is not { } oldValue) return state;
                value = BigInteger.Max(0, oldValue + delta.Value);
                break;
            default: return state;
        }
        var revision = state.Resources.GetValueOrDefault(resource)?.Revision ?? 0;
        return state with { Resources = state.Resources.SetItem(resource, new(value, revision + 1)) };
    }
}
