using System.Collections.Immutable;
using System.Numerics;

namespace Lala.Core.Inventory;

/// <summary>Immutable crafting.defaults projection. Pending and automation flags are
/// caller-supplied observations, not capabilities. Receipt application does not resolve
/// pending commands, confirm material spending or prove receipt of a crafted product.</summary>
public sealed record CraftingSnapshot
{
    public bool Ready { get; init; }
    public ImmutableDictionary<byte, CraftScheduleRow> Queue { get; init; } = ImmutableDictionary<byte, CraftScheduleRow>.Empty;
    /// <summary>Python dictionary insertion order. Callers importing a seeded snapshot
    /// must supply the matching order; compaction explicitly replaces it with sorted slots.</summary>
    public ImmutableArray<byte> QueueOrder { get; init; } = [];
    public byte Active { get; init; }
    public double? StartedAt { get; init; }
    public bool Running { get; init; }
    public bool AutoContinue { get; init; }
    public string? Pending { get; init; }
    public bool CompletionRequested { get; init; }
    public BigInteger Completed { get; init; }
    public string Status { get; init; } = "等待製作排程同步";
    public BigInteger Revision { get; init; }
    public byte HumanIndex { get; init; }
    public uint HumanId { get; init; }
    public bool Uncertain { get; init; }
    public string? SyncSource { get; init; }
    public override string ToString() => nameof(CraftingSnapshot);
}

/// <summary>Tool notices contain no geometry or contents. Null preserves that absence;
/// it must not be replaced with invented coordinates or an eleven-zero contents record.</summary>
public sealed record CraftFurnitureSnapshot(ushort Index, ushort ItemId, ushort Workbench,
    byte Floor, byte Status, ushort? X = null, ushort? Y = null, ushort? Z = null,
    byte? Direction = null, ImmutableArray<ushort>? Contents = null)
{
    internal static CraftFurnitureSnapshot From(FurnitureRecord row) => new(row.Index, row.ItemId,
        row.Workbench, row.Floor, row.Status, row.X, row.Y, row.Z, row.Direction, row.Contents);
    public override string ToString() => nameof(CraftFurnitureSnapshot);
}

public sealed record CraftingRoomSnapshot
{
    public uint? Owner { get; init; }
    public uint? CurrentOwner { get; init; }
    public bool Ready { get; init; }
    public ImmutableDictionary<ushort, CraftFurnitureSnapshot> Items { get; init; } =
        ImmutableDictionary<ushort, CraftFurnitureSnapshot>.Empty;
    /// <summary>Preserves insertion order, including replace versus remove-and-reinsert.
    /// This matters for future source tool lookup with duplicate item IDs. Enumerating
    /// Items itself has no ordering contract. Imported snapshots must supply matching order.</summary>
    public ImmutableArray<ushort> ItemOrder { get; init; } = [];
    public BigInteger Revision { get; init; }
    public bool? PersonalBatch { get; init; }
    public override string ToString() => nameof(CraftingRoomSnapshot);
}

/// <summary>Only the crafting and furniture domains. A new/Empty instance explicitly
/// resets them; schedule/furniture snapshots replace only their source-defined fields.
/// Runtime provenance, recipe layout selection, generation guards and account identity
/// belong to the caller, never to readiness flags or this non-authorizing projection.</summary>
public sealed record CraftingReceiveSnapshot
{
    public static CraftingReceiveSnapshot Empty { get; } = new();
    public CraftingSnapshot Crafting { get; init; } = new();
    public CraftingRoomSnapshot Furniture { get; init; } = new();
    public override string ToString() => nameof(CraftingReceiveSnapshot);
}
