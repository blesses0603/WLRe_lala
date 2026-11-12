using System.Collections.Immutable;
using System.Text;

namespace Lala.Core.Resources;

internal sealed record ResourceInventoryMember(string Name, ReadOnlyMemory<byte>? Data);

internal sealed class InventoryRawTable
{
    private readonly byte[] bytes;
    internal string Name { get; }
    internal string Sha256 { get; }
    internal int Length => bytes.Length;
    internal ReadOnlySpan<byte> Bytes => bytes;
    internal byte[] CopyBytes() => bytes.ToArray();
    internal InventoryRawTable(string name, ReadOnlyMemory<byte> data, CancellationToken token)
    {
        Name = name; bytes = data.ToArray(); Sha256 = ResourceValidation.Digest(bytes, token);
    }
}

/// <summary>Owned, bounded inventory input, never verified official provenance. Member paths are
/// logical POSIX archive names only; this class does not access a filesystem.</summary>
internal sealed class ResourceInventoryInput
{
    internal const int MaximumMembers = 512;
    internal const int MaximumTables = 256;
    internal const int MaximumTableBytes = 16 * 1024 * 1024;
    internal const long MaximumRawBytes = 128L * 1024 * 1024;
    internal const int MaximumNameCharacters = 120;
    internal const int MaximumCatalogKeyCharacters = 128;
    internal const int MaximumIdentityCharacters = 4096;
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    internal string CatalogKey { get; }
    internal string? IdentityJson { get; }
    internal ImmutableArray<InventoryRawTable> Tables { get; }
    internal long RawBytes { get; }
    private ResourceInventoryInput(string key, string? identity, ImmutableArray<InventoryRawTable> tables, long bytes)
    { CatalogKey = key; IdentityJson = identity; Tables = tables; RawBytes = bytes; }

    internal static ResourceInventoryInput Capture(string catalogKey, IReadOnlyList<ResourceInventoryMember> members,
        ManifestIdentity? identity = null, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested(); ArgumentNullException.ThrowIfNull(members);
        int memberCount = members.Count;
        if (memberCount < 0 || memberCount > MaximumMembers) throw new InvalidDataException("Inventory member quota exceeded");
        var names = new HashSet<string>(StringComparer.Ordinal);
        var tables = ImmutableArray.CreateBuilder<InventoryRawTable>(); long total = 0;
        for (int index = 0; index < memberCount; index++)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var member = members[index] ?? throw new ArgumentException("Inventory member is null", nameof(members));
            ArgumentNullException.ThrowIfNull(member.Name);
            if (!member.Name.StartsWith("tables/", StringComparison.Ordinal) || !member.Name.EndsWith(".bytes", StringComparison.Ordinal)) continue;
            if (member.Name.Length > 2048) throw new InvalidDataException("Inventory member name quota exceeded");
            string name = member.Name[(member.Name.LastIndexOf('/') + 1)..];
            if (!names.Add(name) || member.Data is null) throw new ArgumentException("Ambiguous or invalid resource table", nameof(members));
            ValidateText(name, MaximumNameCharacters);
            if (tables.Count == MaximumTables || member.Data.Value.Length > MaximumTableBytes ||
                (total += member.Data.Value.Length) > MaximumRawBytes) throw new InvalidDataException("Inventory raw byte/table quota exceeded");
            // Empty bytes are intentionally retained: the source inventory accepts them, even
            // though a parser may report parse_failed and the runtime matcher rejects them.
            tables.Add(new(name, member.Data.Value, cancellationToken));
        }
        if (tables.Count == 0) throw new ArgumentException("No resource tables to record", nameof(members));
        ValidateText(catalogKey, MaximumCatalogKeyCharacters);
        if (identity is not null && identity.Key != catalogKey) throw new ArgumentException("Catalog identity does not match inventory", nameof(identity));
        if (identity?.CanonicalJson.Length > MaximumIdentityCharacters) throw new InvalidDataException("Inventory identity quota exceeded");
        cancellationToken.ThrowIfCancellationRequested();
        return new(catalogKey, identity?.CanonicalJson, tables.ToImmutable(), total);
    }
    internal static void ValidateText(string value, int maximumCharacters)
    {
        ArgumentNullException.ThrowIfNull(value);
        if (value.Length > maximumCharacters * 2) throw new InvalidDataException("Inventory text quota exceeded");
        try { _ = StrictUtf8.GetByteCount(value); }
        catch (EncoderFallbackException error) { throw new ArgumentException("Invalid inventory Unicode", nameof(value), error); }
        if (ResourceValidation.TextLength(value) > maximumCharacters) throw new InvalidDataException("Inventory text quota exceeded");
    }
}

internal sealed class InventoryPythonStringComparer : IComparer<string>
{
    internal static readonly InventoryPythonStringComparer Instance = new();
    public int Compare(string? left, string? right)
    {
        if (ReferenceEquals(left, right)) return 0;
        if (left is null) return -1; if (right is null) return 1;
        var a = left.EnumerateRunes().GetEnumerator(); var b = right.EnumerateRunes().GetEnumerator();
        while (true)
        {
            bool x = a.MoveNext(), y = b.MoveNext();
            if (!x || !y) return x.CompareTo(y);
            int result = a.Current.Value.CompareTo(b.Current.Value); if (result != 0) return result;
        }
    }
}
