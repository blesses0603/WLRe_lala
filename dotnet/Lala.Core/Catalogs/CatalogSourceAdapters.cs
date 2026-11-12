using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Security.Cryptography;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

/// <summary>
/// Offline adapters for supplied, extracted source bytes. No extraction, storage, activation,
/// network, session or resource-gate integration. Supplied hashes are validation, never authority.
/// </summary>
public static partial class CatalogSourceAdapters
{
    public const int MaxSourceBytes = 16 * 1024 * 1024;
    public const int MaxRows = 20_000;
    public static ImmutableArray<string> Features { get; } = ["npc", "shops", "crafting", "scenes", "items"];
    private static readonly ParserDiagnosticDefinition FeatureDiagnostic =
        new("wlre.services.world.catalog_adapters.parse_feature", "catalog-contract-v1");
    private static readonly ParserDiagnosticDefinition SetDiagnostic =
        new("wlre.services.world.catalog_adapters.parse_selected", "catalog-set-v1");

    internal static bool IsDigest(string? value) => value is { Length: 64 } &&
        value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');
    internal static bool Supports(string? feature, string? schema) => (feature, schema) switch
    {
        ("npc", "eve-npc-json-v1") or ("shops", "eve-interact-json-v1") or ("items", "itemdata-v1") or
        ("crafting", "smith-new-33-v1" or "smith-new-35-v1" or "smith-reviewed-v1") or
        ("scenes", "stage-new-76-v1") => true,
        _ => false
    };

    public static ParsedSourceCatalog ParseFeature(string? catalogKey, IReadOnlyDictionary<string, string>? packageVersions,
        CatalogSourceContract? contract, ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // The digest and decoder observe identical owned bytes. Oversize validation does not copy.
        ReadOnlySpan<byte> snapshot = raw.Length <= MaxSourceBytes ? raw.ToArray() : raw;
        return ParserDiagnostics.RunWithRaw(FeatureDiagnostic, snapshot, bytes =>
        {
            if (!IsDigest(catalogKey))
                throw new CatalogAdapterException("A verified versioned Catalog key is required");
            if (contract is null || packageVersions is null ||
                !packageVersions.TryGetValue(contract.Package, out var version) || version != contract.PackageVersion)
                throw new CatalogAdapterException("Catalog/package source revision mismatch");
            if (bytes.Length is <= 0 or > MaxSourceBytes)
                throw new CatalogAdapterException("Missing or oversized source payload");
            string digest = Hash(bytes, cancellationToken);
            if (digest != contract.ExpectedSha256)
                throw new CatalogAdapterException("Unreviewed or corrupted source SHA-256");
            CatalogSourceRecords records;
            try { records = Decode(contract.SchemaId, bytes, cancellationToken); }
            catch (CatalogDecodeException)
            {
                // Match Python's wrapping while retaining no source exception/message/payload.
                throw new CatalogAdapterException("Source parser failed; adapter requires review");
            }
            cancellationToken.ThrowIfCancellationRequested();
            return new ParsedSourceCatalog(catalogKey!, contract, digest, records);
        }, _ => new(), null, cancellationToken);
    }

    public static IReadOnlyDictionary<string, ParsedSourceCatalog> ParseSelected(string? catalogKey,
        IReadOnlyDictionary<string, string>? packageVersions,
        IReadOnlyDictionary<string, CatalogSourceContract>? contracts,
        IReadOnlyDictionary<string, ReadOnlyMemory<byte>>? sourcePayloads, CancellationToken cancellationToken = default)
    {
        return ParserDiagnostics.Run(SetDiagnostic, [], () =>
        {
            // Keep the source's historic "four" message even though there are five features.
            if (contracts is null || contracts.Count != Features.Length ||
                !contracts.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(Features) || sourcePayloads is null)
                throw new CatalogAdapterException("All four independently reviewed feature contracts are required");
            var parsed = new Dictionary<string, ParsedSourceCatalog>(StringComparer.Ordinal);
            foreach (string feature in Features)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var contract = contracts[feature];
                if (contract is null || contract.Feature != feature)
                    throw new CatalogAdapterException("Feature/source contract mismatch");
                if (!sourcePayloads.TryGetValue(contract.SourceName, out var raw))
                    throw new CatalogAdapterException("Missing required feature source");
                parsed.Add(feature, ParseFeature(catalogKey, packageVersions, contract, raw.Span, cancellationToken));
            }
            cancellationToken.ThrowIfCancellationRequested();
            return (IReadOnlyDictionary<string, ParsedSourceCatalog>)new OrderedCatalog<string, ParsedSourceCatalog>(parsed, Features);
        }, rows => new(rows.Count), cancellationToken: cancellationToken);
    }

    private static CatalogSourceRecords Decode(string schema, ReadOnlySpan<byte> raw, CancellationToken token)
    {
        if (schema == "smith-reviewed-v1")
        {
            if (raw.Length < 4) throw new CatalogAdapterException("Truncated Smith header");
            int count = BinaryPrimitives.ReadInt32LittleEndian(raw);
            if (count is < 0 or > MaxRows) throw new CatalogAdapterException("Invalid Smith count");
            int size = raw.Length == 4 + count * 33 ? 33 : 35;
            BinaryTable(raw, size);
            // Do not call ParseRecords: the source adapter's 33-byte branch is an UNMARKED MAP.
            return Decode(size == 33 ? "smith-new-33-v1" : "smith-new-35-v1", raw, token);
        }
        switch (schema)
        {
            case "itemdata-v1": return new ItemSourceRecords(ItemDataParser.ParseForSourceAdapter(raw, token));
            case "eve-npc-json-v1": return JsonScenes(raw, npcs: true, token);
            case "eve-interact-json-v1": return JsonScenes(raw, npcs: false, token);
            case "smith-new-33-v1":
            {
                int count = BinaryTable(raw, 33);
                var rows = SmithDataParser.Parse33(raw, token);
                if (rows.Count != count) throw new CatalogAdapterException("Smith parser count mismatch");
                return new SmithMapSourceRecords(rows);
            }
            case "smith-new-35-v1":
            {
                int count = BinaryTable(raw, 35);
                var rows = SmithDataParser.MarkTimedRecipes(SmithDataParser.ParseCandidate(raw, token), token);
                if (rows.Length != count) throw new CatalogAdapterException("Smith parser count mismatch");
                return new SmithListSourceRecords(rows);
            }
            case "stage-new-76-v1":
            {
                int count = BinaryTable(raw, 76);
                var rows = StageDataParser.Parse(raw, token);
                if (rows.Count != count) throw new CatalogAdapterException("Stage parser count mismatch");
                return new StageSourceRecords(rows);
            }
            default: throw new CatalogAdapterException("Unreviewed schema adapter");
        }
    }

    private static int BinaryTable(ReadOnlySpan<byte> raw, int size)
    {
        if (raw.Length < 4) throw new CatalogAdapterException("Truncated binary table header");
        int count = BinaryPrimitives.ReadInt32LittleEndian(raw);
        if (count is < 0 or > MaxRows || raw.Length != 4 + count * size)
            throw new CatalogAdapterException("Unknown binary record layout or truncated table");
        return count;
    }

    private static string Hash(ReadOnlySpan<byte> bytes, CancellationToken token)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        while (!bytes.IsEmpty)
        {
            token.ThrowIfCancellationRequested();
            int size = Math.Min(64 * 1024, bytes.Length);
            hash.AppendData(bytes[..size]); bytes = bytes[size..];
        }
        token.ThrowIfCancellationRequested();
        return Convert.ToHexStringLower(hash.GetHashAndReset());
    }
}
