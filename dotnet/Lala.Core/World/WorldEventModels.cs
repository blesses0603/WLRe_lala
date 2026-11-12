using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.World;

public sealed record WorldCoordinates(ushort X, ushort Y);
public sealed record WorldCachedPosition(long RoleId, ushort X, ushort Y);

/// <summary>Immutable, oldest-first observation cache. Role IDs are widened without reinterpreting
/// signed S6 IDs as unsigned. The local slot is protected only when a local identity is known.</summary>
public sealed class WorldPositionCache
{
    public const int Limit = 2048;
    public static WorldPositionCache Empty { get; } = new(
        ImmutableDictionary<long, Entry>.Empty, ImmutableSortedDictionary<BigInteger, long>.Empty, 0);
    private sealed record Entry(WorldCoordinates Position, BigInteger Order);
    private readonly ImmutableDictionary<long, Entry> values;
    private readonly ImmutableSortedDictionary<BigInteger, long> order;
    private readonly BigInteger nextOrder;

    private WorldPositionCache(ImmutableDictionary<long, Entry> values,
        ImmutableSortedDictionary<BigInteger, long> order, BigInteger nextOrder)
    {
        this.values = values; this.order = order; this.nextOrder = nextOrder;
    }

    public int Count => values.Count;
    public IEnumerable<WorldCachedPosition> Entries => order.Values.Select(id =>
        new WorldCachedPosition(id, values[id].Position.X, values[id].Position.Y));
    public WorldCoordinates? Get(long roleId) => values.GetValueOrDefault(roleId)?.Position;

    public WorldPositionCache Remove(long roleId) => values.TryGetValue(roleId, out var entry)
        ? new(values.Remove(roleId), order.Remove(entry.Order), nextOrder) : this;

    public WorldPositionCache Remember(long roleId, ushort x, ushort y, uint? ownRoleId)
    {
        var cache = Remove(roleId);
        var entries = cache.values.Add(roleId, new(new(x, y), cache.nextOrder));
        var sequence = cache.order.Add(cache.nextOrder, roleId);
        var next = cache.nextOrder + 1;
        while (entries.Count > Limit)
        {
            var oldest = sequence.First();
            if (ownRoleId is { } own && oldest.Value == own)
            {
                // Python moves a protected oldest local entry to the newest position before eviction.
                sequence = sequence.Remove(oldest.Key).Add(next, own);
                entries = entries.SetItem(own, entries[own] with { Order = next });
                next += 1;
                oldest = sequence.First();
            }
            sequence = sequence.Remove(oldest.Key);
            entries = entries.Remove(oldest.Value);
        }
        return new(entries, sequence, next);
    }
}

/// <summary>A target or server observation, not a claim that movement was executed.</summary>
public sealed record WorldPosition(ushort? Scene, ushort X, ushort Y,
    string? Source = null, BigInteger? PacketNumber = null);
public sealed record WorldLocationSnapshot
{
    public WorldPosition? Confirmed { get; init; }
    public bool ConfirmedIsCurrent { get; init; }
    public WorldPosition? RequestedDestination { get; init; }
    public WorldPosition? ServerDestination { get; init; }
}
public sealed record WorldMovementCheck(string Status, WorldPosition Target,
    uint? RoleId, WorldPosition? Confirmation = null);
/// <summary>Only the status/target inputs consumed by wait_for_position. A finished route is
/// still only a target; this projection does not port or authorize the route executor.</summary>
public sealed record WorldLocalMovement(string Status, WorldPosition Target);
public sealed record WorldHouseContext(ushort Scene, bool Verified, byte? Floor = null)
{
    public ImmutableDictionary<byte, byte> Sizes { get; init; } = ImmutableDictionary<byte, byte>.Empty;
}
public sealed record WorldNavigationSnapshot
{
    public ushort? Scene { get; init; }
    public BigInteger Revision { get; init; }
    public bool Stale { get; init; }
    public bool RuntimeGeometryVerified { get; init; }
    [System.Text.Json.Serialization.JsonIgnore] public string? InvalidationScope { get; init; }
    [System.Text.Json.Serialization.JsonIgnore] public string? GeometryResourceKey { get; init; }
    [System.Text.Json.Serialization.JsonIgnore] public ushort? GeometryModel { get; init; }
    public ImmutableArray<string> Reasons { get; init; } = [];
    public WorldHouseContext? HouseContext { get; init; }
}

/// <summary>Only fields consumed by the world reducer and its position helpers. PacketCount is
/// supplied by the caller, not incremented here. Player is the full immutable decoded S3 layout.
/// No session ownership, socket, geometry rebuild, command permission or arrival inference.</summary>
public sealed record WorldEventSnapshot
{
    public string Phase { get; init; } = "disconnected";
    public BigInteger PacketCount { get; init; }
    public WorldPlayer? Player { get; init; }
    public WorldPositionCache Positions { get; init; } = WorldPositionCache.Empty;
    public WorldNavigationSnapshot Navigation { get; init; } = new();
    [System.Text.Json.Serialization.JsonIgnore] public WorldNpcRuntime NpcRuntime { get; init; } = new();
    public WorldLocationSnapshot Location { get; init; } = new();
    public WorldLocalMovement? LocalMovement { get; init; }
    public WorldMovementCheck? MovementCheck { get; init; }
}

/// <summary>Explicit immutable evidence supplied by a caller, never loaded/activated here.
/// Null means no current catalog. Null aliases mean alias validation is unavailable or failed.
/// The caller must establish current version and reviewed binary-order alias validation;
/// these sets alone neither establish provenance nor authorize navigation.</summary>
public sealed record WorldSceneCatalog(ImmutableHashSet<ushort> StageIds,
    ImmutableHashSet<ushort>? VerifiedInstanceAliasIds = null);
