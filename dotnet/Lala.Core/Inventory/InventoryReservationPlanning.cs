using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.State;

namespace Lala.Core.Inventory;

/// <summary>Exactly reservations.checkpoint's five fields, not a complete bag snapshot.
/// Only Checkpoint creates this value. Missing optional slot lists become empty lists,
/// matching Python's defaults. All nested values are immutable; sharing them cannot
/// change either a saved checkpoint or any historical proposal.</summary>
public sealed record InventoryReservationCheckpoint
{
    internal InventoryReservationCheckpoint(ImmutableArray<StorageReservationGroup> holds,
        ImmutableDictionary<ushort, BigInteger> reserved, ImmutableArray<ushort> alchemySlots,
        ImmutableArray<ushort> expeditionSlots, ImmutableArray<ushort> maintenanceSlots) =>
        (Holds, Reserved, AlchemySlots, ExpeditionSlots, MaintenanceSlots) =
        (holds, reserved, alchemySlots, expeditionSlots, maintenanceSlots);

    public ImmutableArray<StorageReservationGroup> Holds { get; }
    public ImmutableDictionary<ushort, BigInteger> Reserved { get; }
    public ImmutableArray<ushort> AlchemySlots { get; }
    public ImmutableArray<ushort> ExpeditionSlots { get; }
    public ImmutableArray<ushort> MaintenanceSlots { get; }
    public override string ToString() => nameof(InventoryReservationCheckpoint);
}

/// <summary>Read-only reservation queries and hypothetical immutable accounting proposals.
/// No method installs a proposal, confirms an operation, acquires/releases a live hold,
/// sends anything or infers that a timeout/stop makes an uncertain operation safe.</summary>
public static class InventoryReservationPlanning
{
    public static StorageReservationIdentity Identity(BagItemSnapshot item)
    {
        ArgumentNullException.ThrowIfNull(item);
        return new(item.ItemId, item.OriginalRecord.Serial, item.OriginalRecord.SerialVersion);
    }

    /// <summary>Locks are independent of readiness, item presence/count and remaining hold
    /// quantity. A stale slot projection or an uncertain/exclusive zero hold still locks.</summary>
    public static bool Locked(BagReceiveSnapshot state, ushort index)
    {
        ArgumentNullException.ThrowIfNull(state);
        return state.AlchemySlots?.Contains(index) == true || state.ExpeditionSlots?.Contains(index) == true ||
            state.MaintenanceSlots?.Contains(index) == true || state.Holds.Any(group => group.Rows.Any(row =>
                row.Index == index && (row.Exclusive || row.Uncertain)));
    }

    /// <summary>Source str(index) semantics against the typed snapshot's canonical numeric
    /// slot keys: booleans, floats, padded strings and nonnumeric values never alias a slot.</summary>
    public static bool Locked(BagReceiveSnapshot state, StateValue index)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(index);
        return TryIndex(index, out var slot) && Locked(state, slot);
    }

    /// <summary>Proposes the source release result only. This call does not establish the
    /// definitive confirmation required for a live release. Source release accepts unknown
    /// owners and ignores readiness/reliability. Duplicate rows subtract in order with a
    /// separate zero clamp after each row, including imported negative/huge remaining values.</summary>
    public static InventoryReservationCandidate PlanRelease(BagReceiveSnapshot state, string owner)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(owner);
        var position = OwnerPosition(state, owner);
        var reserved = state.Reserved;
        if (position >= 0)
            foreach (var row in state.Holds[position].Rows)
                reserved = reserved.SetItem(row.Index, BigInteger.Max(0, reserved.GetValueOrDefault(row.Index) - row.Remaining));
        var proposed = state with
        {
            Holds = position >= 0 ? state.Holds.RemoveAt(position) : state.Holds,
            Reserved = reserved
        };
        return new(state, ProjectSlots(proposed, owner), null);
    }

    /// <summary>Marks only this owner's rows uncertain in a proposal. It does not release
    /// anything, alter remaining/count/reserved, rebuild slots, or mark the bag unreliable.
    /// The existing receive refresh reducer separately handles later uncertainty evidence.</summary>
    public static InventoryReservationCandidate PlanUncertain(BagReceiveSnapshot state, string owner)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(owner);
        var position = OwnerPosition(state, owner);
        if (position < 0) return new(state, state, null);
        var group = state.Holds[position];
        var proposed = state with
        {
            Holds = state.Holds.SetItem(position, group with { Rows = [.. group.Rows.Select(row => row with { Uncertain = true })] })
        };
        return new(state, proposed, null);
    }

    public static InventoryReservationCheckpoint Checkpoint(BagReceiveSnapshot state)
    {
        ArgumentNullException.ThrowIfNull(state);
        return new(state.Holds, state.Reserved, state.AlchemySlots ?? [], state.ExpeditionSlots ?? [], state.MaintenanceSlots ?? []);
    }

    /// <summary>Restores exactly a complete typed checkpoint's five fields in a proposal.
    /// Does not restore bag items/revision/readiness/reliability, revalidate identity, repair
    /// counters, project slots, or clear errors. Arbitrary Python dictionary patches are not
    /// accepted: only a reservation checkpoint is a supported restore input.</summary>
    public static InventoryReservationCandidate PlanRestore(BagReceiveSnapshot state, InventoryReservationCheckpoint saved)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(saved);
        return new(state, state with
        {
            Holds = saved.Holds, Reserved = saved.Reserved, AlchemySlots = saved.AlchemySlots,
            ExpeditionSlots = saved.ExpeditionSlots, MaintenanceSlots = saved.MaintenanceSlots
        }, null);
    }

    /// <summary>Pure source _slots projection, shared by acquire/release proposals. No owner
    /// validation and no sorting: first occurrence wins, including zero/uncertain rows.</summary>
    internal static BagReceiveSnapshot ProjectSlots(BagReceiveSnapshot state, string owner)
    {
        if (owner is not ("alchemy" or "expedition" or "maintenance")) return state;
        var position = OwnerPosition(state, owner);
        var slots = position < 0 ? [] : state.Holds[position].Rows.Select(row => row.Index).Distinct().ToImmutableArray();
        return owner switch
        {
            "alchemy" => state with { AlchemySlots = slots },
            "expedition" => state with { ExpeditionSlots = slots },
            _ => state with { MaintenanceSlots = slots }
        };
    }

    private static int OwnerPosition(BagReceiveSnapshot state, string owner)
    {
        for (var i = 0; i < state.Holds.Length; i++) if (state.Holds[i].Owner == owner) return i;
        return -1;
    }

    internal static bool TryIndex(StateValue value, out ushort index)
    {
        index = 0;
        if (InventoryPlanning.Integer(value, out var number) && number >= 0 && number <= ushort.MaxValue)
        {
            index = (ushort)number; return true;
        }
        if (value.Kind == StateValueKind.Scalar && value.ScalarValue is string text &&
            ushort.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out index))
            return text == index.ToString(CultureInfo.InvariantCulture);
        return false;
    }
}
