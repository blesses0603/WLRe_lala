using System.Collections.Immutable;
using System.Text;
using System.Text.Json;

namespace Lala.Core.Catalogs;

public sealed class CatalogAdapterException(string message) : FormatException(message);

/// <summary>Caller-supplied validation inputs, not independently reviewed provenance or authority.</summary>
public sealed class CatalogSourceContract
{
    public CatalogSourceContract(string? feature, string? sourceName, string? schemaId,
        string? expectedSha256, string? package, string? packageVersion)
    {
        if (!CatalogSourceAdapters.Supports(feature, schemaId) || string.IsNullOrEmpty(sourceName) ||
            sourceName.EnumerateRunes().Count() > 120 || sourceName.Contains('/') || sourceName.Contains('\\') ||
            sourceName is "." or ".." || !CatalogSourceAdapters.IsDigest(expectedSha256) ||
            package is not ("DataPackage" or "MainPackage") || string.IsNullOrEmpty(packageVersion) ||
            packageVersion.EnumerateRunes().Count() > 100)
            throw new CatalogAdapterException("Unknown feature/schema or invalid reviewed source contract");
        Feature = feature!; SourceName = sourceName; SchemaId = schemaId!;
        ExpectedSha256 = expectedSha256!; Package = package; PackageVersion = packageVersion;
    }
    public string Feature { get; }
    public string SourceName { get; }
    public string SchemaId { get; }
    public string ExpectedSha256 { get; }
    public string Package { get; }
    public string PackageVersion { get; }
}

public abstract class CatalogSourceRecords
{
    private protected CatalogSourceRecords(int count) => RecordCount = count;
    public int RecordCount { get; }
}
public sealed class ItemSourceRecords : CatalogSourceRecords
{
    internal ItemSourceRecords(IReadOnlyDictionary<ushort, ItemDataRow> rows) : base(rows.Count) => Rows = rows;
    public IReadOnlyDictionary<ushort, ItemDataRow> Rows { get; }
}
public sealed class SmithMapSourceRecords : CatalogSourceRecords
{
    internal SmithMapSourceRecords(IReadOnlyDictionary<ushort, SmithRecipe> rows) : base(rows.Count) => Rows = rows;
    public IReadOnlyDictionary<ushort, SmithRecipe> Rows { get; }
}
public sealed class SmithListSourceRecords : CatalogSourceRecords
{
    internal SmithListSourceRecords(ImmutableArray<SmithRecipe> rows) : base(rows.Length) => Rows = rows;
    public ImmutableArray<SmithRecipe> Rows { get; }
}
public sealed class StageSourceRecords : CatalogSourceRecords
{
    internal StageSourceRecords(IReadOnlyDictionary<ushort, StageDataRow> rows) : base(rows.Count) => Rows = rows;
    public IReadOnlyDictionary<ushort, StageDataRow> Rows { get; }
}
/// <summary>Owned, immutable JSON rows retain extra fields without inventing event/shop semantics.</summary>
public sealed class EveIndexSourceRecords : CatalogSourceRecords
{
    internal EveIndexSourceRecords(IReadOnlyDictionary<string, ImmutableArray<JsonElement>> scenes, int count)
        : base(count) => Scenes = scenes;
    public IReadOnlyDictionary<string, ImmutableArray<JsonElement>> Scenes { get; }
}

/// <summary>Offline validated layout only. Caller claims never authorize runtime/resource use.</summary>
public sealed class ParsedSourceCatalog
{
    internal ParsedSourceCatalog(string catalogKey, CatalogSourceContract contract, string digest, CatalogSourceRecords records)
    {
        CatalogKey = catalogKey; Feature = contract.Feature; SourceName = contract.SourceName;
        SchemaId = contract.SchemaId; SourceSha256 = digest; Records = records;
    }
    public string CatalogKey { get; }
    public string Feature { get; }
    public string SourceName { get; }
    public string SchemaId { get; }
    public string SourceSha256 { get; }
    public int RecordCount => Records.RecordCount;
    public CatalogSourceRecords Records { get; }
    public bool CanSendPackets => false;
    public bool AssetsReady => false;
}
