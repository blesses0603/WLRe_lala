using System.Collections.Immutable;
using System.Numerics;

namespace Lala.Core.Battle;

/// <summary>Immutable attribute_points.defaults receive state. Pending/expected/timestamp
/// values are imported observations only, not authority to allocate or spend points.
/// A fresh snapshot resets this domain. No receive packet creates a pending request.</summary>
public sealed record AttributeAllocationSnapshot
{
    private ImmutableDictionary<string, BigInteger>? expected;

    public static AttributeAllocationSnapshot Empty { get; } = new();
    public bool Pending { get; init; }
    public bool Acknowledged { get; init; }
    public bool Uncertain { get; init; }
    /// <summary>Numeric expected stats from an explicitly supplied pending observation.
    /// Null and empty remain distinct snapshots, though Python treats both as an empty
    /// comparison when receiving an acknowledgment. Missing current keys never mean zero.</summary>
    public ImmutableDictionary<string, BigInteger>? Expected
    {
        get => expected;
        init => expected = value?.WithComparers(StringComparer.Ordinal);
    }
    public double? SentAt { get; init; }
    public string Status { get; init; } = "";
    public override string ToString() => nameof(AttributeAllocationSnapshot);
}

/// <summary>The current numeric knowledge.player.stats projection at apply_points_event.
/// State.apply runs apply_live first, so this includes the same packet's S8/S5 knowledge
/// updates, while State.attributes still contains its previous local-dispatch values.
/// The caller supplies this context; this reducer neither derives nor writes player stats.</summary>
public sealed record AttributeAllocationContext
{
    private ImmutableDictionary<string, BigInteger> playerStats =
        ImmutableDictionary<string, BigInteger>.Empty.WithComparers(StringComparer.Ordinal);

    public ImmutableDictionary<string, BigInteger> PlayerStats
    {
        get => playerStats;
        init => playerStats = (value ?? throw new ArgumentNullException(nameof(value))).WithComparers(StringComparer.Ordinal);
    }
    public override string ToString() => nameof(AttributeAllocationContext);
}
