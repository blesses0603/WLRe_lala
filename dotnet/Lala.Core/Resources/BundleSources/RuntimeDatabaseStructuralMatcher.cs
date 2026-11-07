using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Text;
using System.Text.Json;

namespace Lala.Core.Resources;

internal sealed record RuntimeDatabaseActiveInput(long VersionId, string? CatalogKey, string? IdentityJson);
internal sealed record RuntimeDatabaseTableInput(long VersionId, string? Name, string? RecordedSha256, ReadOnlyMemory<byte>? Data);

/// <summary>One detached set of supplied database observations, NOT evidence of a real database
/// transaction. A future reader must establish transactional coherence separately. No SQLite I/O.</summary>
internal sealed class OwnedRuntimeDatabaseSnapshot
{
    internal const int MaximumIdentityCharacters = 4096;
    internal const int MaximumTableBytes = 16 * 1024 * 1024;
    internal const long MaximumOwnedTableBytes = 10L * MaximumTableBytes;
    internal RuntimeDatabaseActiveInput? Active { get; }
    private readonly FrozenDictionary<string, OwnedTable> _tables;

    internal sealed class OwnedTable
    {
        private readonly byte[] _bytes;
        internal long VersionId { get; }
        internal string? RecordedSha256 { get; }
        internal bool HasBlob { get; }
        internal int ByteLength { get; }
        internal ReadOnlySpan<byte> Bytes => _bytes;
        internal OwnedTable(RuntimeDatabaseTableInput input)
        {
            VersionId = input.VersionId;
            RecordedSha256 = Bounded(input.RecordedSha256, 64);
            HasBlob = input.Data.HasValue; ByteLength = input.Data?.Length ?? 0;
            // Preserve invalid/empty metadata for matching, but do not copy oversized blobs.
            _bytes = HasBlob && ByteLength is > 0 and <= MaximumTableBytes ? input.Data!.Value.ToArray() : [];
        }
    }

    private OwnedRuntimeDatabaseSnapshot(RuntimeDatabaseActiveInput? active, Dictionary<string, OwnedTable> tables)
    { Active = active; _tables = tables.ToFrozenDictionary(StringComparer.Ordinal); }

    internal static OwnedRuntimeDatabaseSnapshot Capture(RuntimeDatabaseActiveInput? active,
        IReadOnlyDictionary<string, RuntimeDatabaseTableInput?>? rows, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Strings are immutable. Invalid oversized fields cannot match, so retain only null
        // sentinels rather than attacker-sized backing strings. No valid field is normalized.
        var ownedActive = active is null ? null : new RuntimeDatabaseActiveInput(active.VersionId,
            Bounded(active.CatalogKey, 64), Bounded(active.IdentityJson, MaximumIdentityCharacters));
        var owned = new Dictionary<string, OwnedTable>(StringComparer.Ordinal);
        // Exactly ten table slots bounds retained data to 160 MiB. Optional/other-version
        // rows are not enumerated, matching the source's requested SQL projection.
        foreach (string name in BundleSourcePlan.RequiredTables)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (rows is not null && rows.TryGetValue(name + ".bytes", out var row) && row is not null &&
                row.Name == name + ".bytes" && row.VersionId == ownedActive?.VersionId)
            {
                cancellationToken.ThrowIfCancellationRequested();
                owned.Add(name + ".bytes", new(row));
            }
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(ownedActive, owned);
    }

    internal OwnedTable? Table(long activeVersion, string exactName) =>
        _tables.TryGetValue(exactName, out var row) && row.VersionId == activeVersion ? row : null;
    internal static string? Bounded(string? value, int maximum) => value is not null && value.Length <= maximum ? value : null;
}

/// <summary>Only structural equality against supplied expected values. This is never an admission
/// capability, official-source proof, transaction certificate or installed-resource status.</summary>
internal sealed class RuntimeDatabaseStructuralMatch
{
    internal bool MatchesSuppliedRuntime { get; }
    internal ImmutableArray<string> ExaminedSources { get; }
    internal bool HasVerifiedProvenance => false;
    internal bool ProvesDatabaseTransaction => false;
    internal bool RuntimeAdmitted => false;
    internal bool AssetsReady => false;
    internal bool CanSendPackets => false;
    internal RuntimeDatabaseStructuralMatch(bool matches, ImmutableArray<string> examinedSources = default)
    { MatchesSuppliedRuntime = matches; ExaminedSources = examinedSources.IsDefault ? [] : examinedSources; }
}

internal static class RuntimeDatabaseStructuralMatcher
{
    private static readonly int MaximumSourceNameLength = BundleSourcePlan.RequiredTables.Max(name => name.Length);
    internal static RuntimeDatabaseStructuralMatch Match(OwnedRuntimeDatabaseSnapshot? snapshot,
        ManifestIdentity? expectedIdentity, IReadOnlyDictionary<string, string?>? expectedDigests,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // The expected map is only a claim. Copy key/value pairs once, preserve iteration order,
        // and require precisely the ten source names before examining the active identity.
        if (expectedDigests is null || expectedDigests.Count != BundleSourcePlan.RequiredTables.Count) return new(false);
        var digests = new List<KeyValuePair<string, string?>>(BundleSourcePlan.RequiredTables.Count);
        foreach (var pair in expectedDigests)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (digests.Count == BundleSourcePlan.RequiredTables.Count) return new(false);
            digests.Add(pair);
        }
        cancellationToken.ThrowIfCancellationRequested();
        if (digests.Count != BundleSourcePlan.RequiredTables.Count ||
            digests.Any(pair => pair.Key is null || pair.Key.Length > MaximumSourceNameLength) ||
            !digests.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal).SetEquals(BundleSourcePlan.RequiredTables)) return new(false);
        var active = snapshot?.Active;
        if (expectedIdentity is null || active is null || active.CatalogKey != expectedIdentity.Key || active.IdentityJson is null) return new(false);
        string json = active.IdentityJson;
        if (json.Length > OwnedRuntimeDatabaseSnapshot.MaximumIdentityCharacters || json.Any(character => character > 127)) return new(false);
        // Hash the original ASCII representation, never canonicalize/reformat it first.
        if (ResourceValidation.Digest(Encoding.ASCII.GetBytes(json), cancellationToken) != expectedIdentity.Key) return new(false);
        try
        {
            using var actual = JsonDocument.Parse(json);
            using var expected = JsonDocument.Parse(expectedIdentity.CanonicalJson);
            if (!JsonElement.DeepEquals(actual.RootElement, expected.RootElement)) return new(false);
        }
        catch (JsonException) { return new(false); }
        var examined = ImmutableArray.CreateBuilder<string>(digests.Count);
        foreach (var (name, digest) in digests)
        {
            cancellationToken.ThrowIfCancellationRequested();
            examined.Add(name);
            var row = snapshot!.Table(active.VersionId, name + ".bytes");
            if (row is null || row.RecordedSha256 != digest || !row.HasBlob ||
                row.ByteLength is <= 0 or > OwnedRuntimeDatabaseSnapshot.MaximumTableBytes ||
                ResourceValidation.Digest(row.Bytes, cancellationToken) != digest) return new(false, examined.ToImmutable());
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(true, examined.MoveToImmutable());
    }
}
