using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Inventory;

/// <summary>Original wire metadata plus current slot, quantity and damage observations.
/// OriginalRecord.Count/Damage are not current values. A stack keeps its first metadata.</summary>
public sealed record BagItemSnapshot(ItemSave OriginalRecord, byte Index, int Count, uint Damage)
{
    public ushort ItemId => OriginalRecord.ItemId;
    public override string ToString() => nameof(BagItemSnapshot);
}

/// <summary>Offline receive-only inventory projection. Holds are imported observations,
/// never acquired or released as commands. Slot and hold order retain Python insertion order.
/// ServerStackable is session-local evidence, not verified catalog or action authority.</summary>
public sealed record BagReceiveSnapshot
{
    public static BagReceiveSnapshot Empty { get; } = new();
    public bool Ready { get; init; }
    public bool Reliable { get; init; }
    public byte? Capacity { get; init; }
    public ImmutableDictionary<byte, BagItemSnapshot> Items { get; init; } = ImmutableDictionary<byte, BagItemSnapshot>.Empty;
    public ImmutableArray<byte> ItemOrder { get; init; } = [];
    public ImmutableDictionary<ushort, BigInteger> Reserved { get; init; } = ImmutableDictionary<ushort, BigInteger>.Empty;
    public ImmutableArray<StorageReservationGroup> Holds { get; init; } = [];
    public ImmutableArray<ushort>? AlchemySlots { get; init; }
    public ImmutableArray<ushort>? ExpeditionSlots { get; init; }
    public ImmutableArray<ushort>? MaintenanceSlots { get; init; }
    public ImmutableDictionary<ushort, bool>? ServerStackable { get; init; }
    public StateValue? FieldSupply { get; init; }
    public BigInteger Revision { get; init; }
    public bool UseFailed { get; init; }
    public byte? LastUseResult { get; init; }
    public string? SyncError { get; init; }
    public override string ToString() => nameof(BagReceiveSnapshot);
}
