using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using Lala.Core.State;

namespace Lala.Core.Inventory;

/// <summary>Explicit offline display names only. Presence is not catalog verification,
/// permission to use an item, or evidence of its effects. Missing names use the source's
/// numeric fallback. No runtime, global catalog, resource loading or network is consulted.</summary>
public sealed record InventoryPlanningContext
{
    public static InventoryPlanningContext Empty { get; } = new();
    public ImmutableDictionary<BigInteger, string> ItemNames { get; init; } = ImmutableDictionary<BigInteger, string>.Empty;
}

public sealed record InventoryPlanningError(string Type, string Message);
public sealed record InventoryAllocation(ushort Index, BigInteger Count, BigInteger ItemId);

/// <summary>Read-only source allocation result, not an acquired hold or send authority.
/// Source quirks such as successful negative allocations are retained, not approved.</summary>
public sealed record InventoryAllocationCandidate(ImmutableArray<InventoryAllocation> Rows, InventoryPlanningError? Error)
{
    public bool Success => Error is null;
}

/// <summary>Hypothetical reservation accounting after validating an entire batch.
/// ObservedSnapshot is unchanged. ProposedSnapshot is absent on any validation failure.
/// Nothing installs this proposal in a session or authorizes sending or consumption.</summary>
public sealed record InventoryReservationCandidate(BagReceiveSnapshot ObservedSnapshot,
    BagReceiveSnapshot? ProposedSnapshot, InventoryPlanningError? Error)
{
    public bool Success => Error is null;
}

/// <summary>Pure inventory.allocate and reservations.acquire validation/proposal parity.
/// Integer allocation inputs are unbounded; malformed reservation values are represented
/// with immutable StateValue rows. Existing typed bag snapshots retain their wire domain.
/// No live acquisition/release, confirmation inference, retry, execution or dispatch.</summary>
public static class InventoryPlanning
{
    private const string NotReady = "包包資料尚未同步或已失效";
    private static readonly ImmutableHashSet<string> Owners =
        ImmutableHashSet.Create(StringComparer.Ordinal, "battle", "field_supply", "alchemy", "crafting", "expedition", "maintenance", "storage");

    /// <summary>Matches the retained integer-input allocate path, including the ordering of
    /// readiness, numeric slot sorting, alchemy exclusion, identity and availability checks.
    /// A zero request succeeds only after a matching non-alchemy item is visited; a negative
    /// request can produce a negative row even at a locked slot. Validate a reservation
    /// proposal separately before treating these source-compatible rows as usable.</summary>
    public static InventoryAllocationCandidate Allocate(BagReceiveSnapshot state, BigInteger itemId,
        BigInteger count, InventoryPlanningContext context)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(context);
        if (!state.Ready || !state.Reliable) return AllocationError(NotReady);
        var rows = ImmutableArray.CreateBuilder<InventoryAllocation>();
        foreach (var (index, item) in state.Items.OrderBy(pair => pair.Key))
        {
            if (state.AlchemySlots?.Contains(index) == true || item.ItemId != itemId) continue;
            var amount = BigInteger.Min(count, BagReceiveReducer.Available(state, index));
            if (amount != 0)
            {
                rows.Add(new(index, amount, itemId));
                count -= amount;
            }
            if (count == 0) return new(rows.ToImmutable(), null);
        }
        var name = context.ItemNames.GetValueOrDefault(itemId) ?? "物品" + itemId.ToString(CultureInfo.InvariantCulture);
        return AllocationError(name + "數量不足或仍待伺服器扣除");
    }

    private static InventoryAllocationCandidate AllocationError(string message) => new([], new("ProtocolError", message));

    /// <summary>Each immutable row has source keys index, count and optional item_id. Integer
    /// or canonical decimal string indices address the typed bag; Python bool/float indices
    /// do not alias integer slots. Count must be an exact integer (not bool or float).
    /// A missing item_id means the current item; explicit null is a mismatching identity.
    /// Missing keys and malformed rows retain source error precedence. Empty valid batches
    /// still propose the source's empty owner group and owner-specific slot projection.</summary>
    public static InventoryReservationCandidate PlanReservation(BagReceiveSnapshot state,
        ImmutableArray<StateValue> allocations, string owner = "battle", bool exclusive = false)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(owner);
        if (allocations.IsDefault) throw new ArgumentException("An initialized immutable batch is required.", nameof(allocations));
        InventoryReservationCandidate Fail(string message, string type = "ProtocolError") => new(state, null, new(type, message));
        if (!Owners.Contains(owner)) return Fail("未知的背包保留用途", "ValueError");
        if (!state.Ready || !state.Reliable) return Fail(NotReady);
        var combined = new Dictionary<ushort, BigInteger>();
        var order = new List<ushort>();
        var ownerPosition = -1;
        for (var i = 0; i < state.Holds.Length; i++)
            if (state.Holds[i].Owner == owner) { ownerPosition = i; break; }
        var priorRows = ownerPosition >= 0 ? state.Holds[ownerPosition].Rows : [];
        foreach (var value in allocations)
        {
            ArgumentNullException.ThrowIfNull(value);
            var indexError = ReadKey(value, "index", out var rawIndex);
            if (indexError is not null) return Fail(indexError.Message, indexError.Type);
            var countError = ReadKey(value, "count", out var rawCount);
            if (countError is not null) return Fail(countError.Message, countError.Type);
            var hasIndex = InventoryReservationPlanning.TryIndex(rawIndex!, out var index);
            var item = hasIndex && index <= byte.MaxValue ? state.Items.GetValueOrDefault((byte)index) : null;
            if (!Integer(rawCount!, out var count) || count <= 0) return Fail("背包保留數量必須為正整數");
            if (hasIndex && state.AlchemySlots?.Contains(index) == true) return Fail("此格仍等待煉金材料扣除回覆");
            if (item is null || value.MapValue.TryGetValue("item_id", out var requestedItem) && !ItemEquals(requestedItem, item.ItemId))
                return Fail("包包物品已變更");
            var previous = priorRows.FirstOrDefault(row => row.Index == index);
            if (previous is not null && previous.Identity != InventoryReservationPlanning.Identity(item)) return Fail("包包格位序號已變更");
            if (state.Holds.Any(group => group.Owner != owner && group.Rows.Any(row => row.Index == index)))
                return Fail("此格仍等待其他功能確認");
            if (BagReceiveReducer.Available(state, index) < combined.GetValueOrDefault(index) + count)
                return Fail("包包數量已變更或仍等待操作確認");
            if (!combined.ContainsKey(index)) order.Add(index);
            combined[index] = combined.GetValueOrDefault(index) + count;
        }
        var rows = priorRows.ToBuilder();
        var reserved = state.Reserved;
        foreach (var index in order)
        {
            var item = state.Items[(byte)index];
            var count = combined[index];
            var rowPosition = -1;
            for (var i = 0; i < rows.Count; i++) if (rows[i].Index == index) { rowPosition = i; break; }
            if (rowPosition >= 0)
            {
                var row = rows[rowPosition];
                // The source preserves all existing row flags, identity and before count,
                // even when this call's exclusive argument differs.
                rows[rowPosition] = row with { Count = row.Count + count, Remaining = row.Remaining + count };
            }
            else rows.Add(new(index, InventoryReservationPlanning.Identity(item), count, count, item.Count, exclusive, false));
            reserved = reserved.SetItem(index, reserved.GetValueOrDefault(index) + count);
        }
        var group = new StorageReservationGroup(owner, rows.ToImmutable());
        var holds = ownerPosition < 0 ? state.Holds.Add(group) : state.Holds.SetItem(ownerPosition, group);
        var proposed = state with { Holds = holds, Reserved = reserved };
        proposed = InventoryReservationPlanning.ProjectSlots(proposed, owner);
        return new(state, proposed, null);
    }

    public static InventoryReservationCandidate PlanReservation(BagReceiveSnapshot state,
        InventoryAllocationCandidate allocation, string owner = "battle", bool exclusive = false)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(allocation);
        // A failed allocation does not become a successful empty reservation proposal.
        if (allocation.Error is not null) return new(state, null, allocation.Error);
        return PlanReservation(state, [.. allocation.Rows.Select(row => StateValue.Map(
            ("index", StateValue.Scalar(row.Index)), ("count", StateValue.Scalar(row.Count)),
            ("item_id", StateValue.Scalar(row.ItemId))))], owner, exclusive);
    }

    private static InventoryPlanningError? ReadKey(StateValue row, string key, out StateValue? value)
    {
        value = null;
        if (row.Kind == StateValueKind.Map)
            return row.MapValue.TryGetValue(key, out value) ? null : new("KeyError", "'" + key + "'");
        var message = row.Kind switch
        {
            StateValueKind.List => "list indices must be integers or slices, not str",
            StateValueKind.Tuple => "tuple indices must be integers or slices, not str",
            _ when row.ScalarValue is string or char => "string indices must be integers, not 'str'",
            _ => $"'{ScalarType(row.ScalarValue)}' object is not subscriptable"
        };
        return new("TypeError", message);
    }

    private static string ScalarType(object? value) => value switch
    {
        null => "NoneType", bool => "bool", float or double => "float", decimal => "decimal.Decimal", char => "str", _ => "int"
    };

    private static bool ItemEquals(StateValue value, ushort item) => Integer(value, out var number) ? number == item :
        value.Kind == StateValueKind.Scalar && value.ScalarValue switch
        {
            bool boolean => (boolean ? 1 : 0) == item,
            double real => real == item, float real => real == item, decimal real => real == item,
            _ => false
        };

    internal static bool Integer(StateValue value, out BigInteger number)
    {
        number = default;
        if (value.Kind != StateValueKind.Scalar) return false;
        switch (value.ScalarValue)
        {
            case BigInteger big: number = big; break;
            case sbyte integer: number = integer; break;
            case byte integer: number = integer; break;
            case short integer: number = integer; break;
            case ushort integer: number = integer; break;
            case int integer: number = integer; break;
            case uint integer: number = integer; break;
            case long integer: number = integer; break;
            case ulong integer: number = integer; break;
            default: return false;
        }
        return true;
    }
}
