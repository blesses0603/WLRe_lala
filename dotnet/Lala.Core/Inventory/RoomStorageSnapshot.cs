using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

/// <summary>The first row's full garage metadata is retained, just as Python _add retains
/// the original dictionary. Count is the current accumulated quantity; the original wire
/// record's byte-sized Count is not a current balance. Materials have no garage record.</summary>
public sealed record StorageItemSnapshot(ushort Index, ushort ItemId, BigInteger Count,
    ItemSave? OriginalGarageRecord = null)
{
    public override string ToString() => nameof(StorageItemSnapshot);
}

public sealed record StorageReservationIdentity(ushort ItemId, uint? Serial, byte? SerialVersion)
{
    public override string ToString() => nameof(StorageReservationIdentity);
}

/// <summary>Caller-supplied reservation observations, not acquired by this receive reducer.</summary>
public sealed record StorageReservationSnapshot(ushort Index, StorageReservationIdentity Identity,
    BigInteger Count, BigInteger Remaining, BigInteger Before, bool Exclusive, bool Uncertain)
{
    public override string ToString() => nameof(StorageReservationSnapshot);
}

/// <summary>Owner and row order are significant: an authoritative deduction is distributed
/// in Python dictionary/list insertion order, not sorted owner order.</summary>
public sealed record StorageReservationGroup(string Owner, ImmutableArray<StorageReservationSnapshot> Rows)
{
    public override string ToString() => nameof(StorageReservationGroup);
}

public sealed record StorageBucketSnapshot
{
    public bool Ready { get; init; }
    public bool Reliable { get; init; } = true;
    public ImmutableDictionary<ushort, StorageItemSnapshot> Items { get; init; } =
        ImmutableDictionary<ushort, StorageItemSnapshot>.Empty;
    /// <summary>Python dictionary insertion order, including remove-and-reinsert behavior.
    /// Callers importing a seeded snapshot must supply its matching item order.</summary>
    public ImmutableArray<ushort> ItemOrder { get; init; } = [];
    public ushort? Capacity { get; init; }
    public ImmutableDictionary<ushort, BigInteger> Reserved { get; init; } =
        ImmutableDictionary<ushort, BigInteger>.Empty;
    public ImmutableArray<StorageReservationGroup> Holds { get; init; } = [];
    // Null means the optional Python projection is absent. Receive updates preserve it.
    public ImmutableArray<ushort>? AlchemySlots { get; init; }
    public ImmutableArray<ushort>? ExpeditionSlots { get; init; }
    public ImmutableArray<ushort>? MaintenanceSlots { get; init; }
    public override string ToString() => nameof(StorageBucketSnapshot);
}

/// <summary>Immutable, receive-only room_storage.defaults projection. Receipts never resolve
/// Pending/Uncertain, change Status, release nonbattle holds, or infer moved quantities.
/// A new snapshot explicitly resets this domain; an initial packet does not reset it.</summary>
public sealed record RoomStorageSnapshot
{
    public StorageBucketSnapshot Garage { get; init; } = new();
    public StorageBucketSnapshot Materials { get; init; } = new();
    public ushort? MaterialStackLimit { get; init; }
    public bool ParametersReady { get; init; }
    public BigInteger Revision { get; init; }
    public byte? LastResult { get; init; }
    public byte? LastError { get; init; }
    public string? Pending { get; init; }
    public bool Uncertain { get; init; }
    public string Status { get; init; } = "等待儲藏空間同步";
    public override string ToString() => nameof(RoomStorageSnapshot);
}

/// <summary>Only the room-storage domain and inventory.server_stackable side effect. The
/// stackability map is session-local observation, never catalog verification or persistent
/// authority. Null distinguishes an absent map from an observed empty material batch.
/// No bag items, account identity, session lifecycle, transport or command state is owned.</summary>
public sealed record StorageReceiveSnapshot
{
    public static StorageReceiveSnapshot Empty { get; } = new();
    public RoomStorageSnapshot Storage { get; init; } = new();
    public ImmutableDictionary<ushort, bool>? ServerStackable { get; init; }
    public override string ToString() => nameof(StorageReceiveSnapshot);
}
