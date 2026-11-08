using Lala.Core.Resources.Inventory;
using System.Collections.ObjectModel;
using System.Collections.Immutable;
using System.Text.Json;

namespace Lala.Core.Resources;

internal enum ResourceInventoryWriteOutcome { NotCommitted, Committed, Unknown }

internal sealed class InventoryRowChanges
{
    internal string Status { get; }
    internal int? Count { get; }
    internal bool PreviousAvailable { get; }
    internal string? PreviousStatus { get; }
    internal ImmutableArray<string> Added { get; }
    internal ImmutableArray<string> Changed { get; }
    internal ImmutableArray<string> Removed { get; }
    private InventoryRowChanges(string status, int? count, string? previousStatus,
        ImmutableArray<string> added, ImmutableArray<string> changed, ImmutableArray<string> removed)
    { Status = status; Count = count; PreviousStatus = previousStatus; PreviousAvailable = previousStatus == "parsed"; Added = added; Changed = changed; Removed = removed; }
    internal static InventoryRowChanges ParseFailed() => new("parse_failed", null, null, [], [], []);
    internal static InventoryRowChanges Parsed(IReadOnlyDictionary<string, string> current, IReadOnlyDictionary<string, string> prior, string previousStatus) =>
        new("parsed", current.Count, previousStatus, previousStatus == "parsed" ? Sorted(current.Keys.Except(prior.Keys, StringComparer.Ordinal)) : [],
            Sorted(current.Keys.Intersect(prior.Keys, StringComparer.Ordinal).Where(key => current[key] != prior[key])),
            Sorted(prior.Keys.Except(current.Keys, StringComparer.Ordinal)));
    internal object Projection() => Status == "parse_failed" ? new { status = Status } : (object)new
    { status = Status, count = Count!.Value, previous_available = PreviousAvailable, previous_status = PreviousStatus!, added = Added, changed = Changed, removed = Removed };
    internal static ImmutableArray<string> Sorted(IEnumerable<string> keys) => keys.Order(InventoryPythonStringComparer.Instance).ToImmutableArray();
}

internal sealed class ResourceInventoryReport
{
    internal IReadOnlyDictionary<string, InventoryRowChanges> OtherRows { get; }
    internal InventoryRowChanges? ItemRows { get; }
    internal InventoryRowChanges? SmithRows { get; }
    internal bool PreviousAvailable { get; }
    internal ImmutableArray<string> Added { get; }
    internal ImmutableArray<string> Changed { get; }
    internal ImmutableArray<string> MissingFromCurrent { get; }
    internal ResourceInventoryReport(Dictionary<string, InventoryRowChanges> other, InventoryRowChanges? items, InventoryRowChanges? smith,
        bool previousAvailable, IReadOnlyDictionary<string, string> digests, IReadOnlyDictionary<string, string> prior)
    {
        OtherRows = new ReadOnlyDictionary<string, InventoryRowChanges>(new Dictionary<string, InventoryRowChanges>(other, StringComparer.Ordinal)); ItemRows = items; SmithRows = smith; PreviousAvailable = previousAvailable;
        Added = previousAvailable ? InventoryRowChanges.Sorted(digests.Keys.Except(prior.Keys, StringComparer.Ordinal)) : [];
        Changed = InventoryRowChanges.Sorted(digests.Keys.Intersect(prior.Keys, StringComparer.Ordinal).Where(key => digests[key] != prior[key]));
        MissingFromCurrent = InventoryRowChanges.Sorted(prior.Keys.Except(digests.Keys, StringComparer.Ordinal));
    }
    internal string ToJson(CancellationToken token = default) => InventoryDerivedRows.CanonicalJson(JsonSerializer.SerializeToElement(new
    {
        other_rows = OtherRows.ToDictionary(pair => pair.Key, pair => pair.Value.Projection(), StringComparer.Ordinal),
        item_rows = ItemRows?.Projection(), smith_rows = SmithRows?.Projection(), smith_legacy_comparison = (object?)null,
        previous_available = PreviousAvailable, added = Added, changed = Changed, missing_from_current = MissingFromCurrent
    }), token);
}

/// <summary>Successful durable inventory selection, not runtime activation or official provenance.</summary>
internal sealed class ResourceInventoryReceipt(ResourceInventoryReport report, long versionId)
{
    internal ResourceInventoryReport Report { get; } = report;
    internal long VersionId { get; } = versionId;
    internal ResourceInventoryWriteOutcome Outcome => ResourceInventoryWriteOutcome.Committed;
    internal bool HasVerifiedProvenance => false;
    internal bool RuntimeAdmitted => false;
    internal bool AssetsReady => false;
    internal bool CanSendPackets => false;
}
