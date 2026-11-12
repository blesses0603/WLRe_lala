using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Numerics;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record SmithMaterial(ushort ItemId, byte Count);
public sealed record SmithRecipe(ushort ItemId, ushort DesignId, byte Skill, ushort ToolId,
    byte Output, ImmutableArray<SmithMaterial> Materials, ushort Seconds, byte SkillLevel,
    byte Suggest, ushort TimeId, byte LimitKind, byte MarkId, byte LimitTimes, int Order,
    ushort? RecipeId = null, ushort? CandidateRowKey = null, bool? ReadOnly = null);

/// <summary>
/// Pure offline Smith table decoding. The reviewed selector recognizes row width only;
/// no result is source provenance, an active catalog, or permission to craft or send commands.
/// </summary>
public static class SmithDataParser
{
    public const int MaxRecords = 20_000;
    public const int LegacyRecordBytes = 33;
    public const int CandidateRecordBytes = 35;
    public const int MaxBytes = 4 + MaxRecords * CandidateRecordBytes;
    private static readonly ParserDiagnosticDefinition LegacyDiagnostic =
        new("wlre.services.world.preview_1275.parse_smith_1275", "smith-33-v1");
    private static readonly ParserDiagnosticDefinition CandidateDiagnostic =
        new("wlre.services.world.smith_candidate.parse_smith_candidate", "smith-35-v1");
    private static readonly ParserDiagnosticDefinition ReviewedDiagnostic =
        new("wlre.services.world.smith_candidate.parse_smith_records", "smith-reviewed-v1");

    public static IReadOnlyDictionary<ushort, SmithRecipe> Parse33(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = data.Length <= MaxBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(LegacyDiagnostic, snapshot,
            bytes => Read33(bytes, cancellationToken), rows => new(rows.Count), null,
            cancellationToken, inputName: "data");
    }

    public static ImmutableArray<SmithRecipe> ParseCandidate(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = data.Length <= MaxBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(CandidateDiagnostic, snapshot,
            bytes => ReadCandidate(bytes, cancellationToken), rows => new(rows.Length), null,
            cancellationToken, inputName: "data");
    }

    public static ImmutableArray<SmithRecipe> ParseRecords(ReadOnlySpan<byte> data,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = data.Length <= MaxBytes ? data.ToArray() : data;
        return ParserDiagnostics.RunWithRaw(ReviewedDiagnostic, snapshot, bytes =>
        {
            if (bytes.Length < 4) throw new CatalogDecodeException("Invalid Smith table header");
            int count = BinaryPrimitives.ReadInt32LittleEndian(bytes);
            if (count is < 0 or > MaxRecords) throw new CatalogDecodeException("Invalid Smith table count");
            try
            {
                // Zero records matches both widths; Python selects 33 first.
                if (bytes.Length == 4 + count * LegacyRecordBytes)
                {
                    ParserDiagnostics.Checkpoint(profile: "smith-33-v1");
                    return MarkTimedRecipes(Parse33(bytes, cancellationToken).Values.ToImmutableArray(), cancellationToken);
                }
                if (bytes.Length == 4 + count * CandidateRecordBytes)
                {
                    ParserDiagnostics.Checkpoint(profile: "smith-35-v1");
                    return MarkTimedRecipes(ParseCandidate(bytes, cancellationToken), cancellationToken);
                }
                throw new CatalogDecodeException("Unknown Smith table layout");
            }
            catch (CatalogDecodeException error)
            {
                // Python's outer decorator finds the child's local `pos` in its traceback.
                // Preserve only that numeric offset, not the child's record/field or payload.
                if (ParserDiagnostics.GetFailure(error)?.Location is { } location &&
                    location.TryGetValue("offset", out var value) && value is BigInteger offset)
                    ParserDiagnostics.Checkpoint(offset: offset);
                throw;
            }
        }, rows => new(rows.Length), null, cancellationToken, inputName: "data");
    }

    // Typed rows make Python's exact-dict/exact-int validation unnecessary. A default array
    // or null row is still invalid; this helper is intentionally not a diagnosed parser.
    public static ImmutableArray<SmithRecipe> MarkTimedRecipes(ImmutableArray<SmithRecipe> rows,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (rows.IsDefault) throw new CatalogDecodeException("Recipe time condition is missing or invalid");
        foreach (var row in rows)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (row is null) throw new CatalogDecodeException("Recipe time condition is missing or invalid");
        }
        var result = ImmutableArray.CreateBuilder<SmithRecipe>(rows.Length);
        foreach (var row in rows)
        {
            cancellationToken.ThrowIfCancellationRequested();
            result.Add(row with { ReadOnly = row.TimeId != 0 });
        }
        return result.MoveToImmutable();
    }

    private static IReadOnlyDictionary<ushort, SmithRecipe> Read33(ReadOnlySpan<byte> data, CancellationToken token)
    {
        if (data.Length < 4) throw new CatalogDecodeException("1275 製作配方資料無效");
        int count = BinaryPrimitives.ReadInt32LittleEndian(data);
        if (count is < 0 or > MaxRecords || data.Length != 4 + count * LegacyRecordBytes)
            throw new CatalogDecodeException("1275 配方筆數或長度不符");
        var result = new Dictionary<ushort, SmithRecipe>();
        var order = new List<ushort>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            int pos = 4 + index * LegacyRecordBytes;
            ParserDiagnostics.Checkpoint(offset: pos, field: "recipe", record: index + 1);
            var row = data.Slice(pos, LegacyRecordBytes);
            ushort item = U16(row), design = U16(row[2..]), tool = U16(row[5..]);
            var materials = ImmutableArray.CreateBuilder<SmithMaterial>(5);
            for (int slot = 0; slot < 5; slot++)
            {
                ushort material = U16(row[(8 + 3 * slot)..]);
                if (material != 0) materials.Add(new(material, row[10 + 3 * slot]));
            }
            // material_count is a validation byte, not a truncation count or returned field.
            if (item == 0 || result.ContainsKey(item) || row[23] > 5)
                throw new CatalogDecodeException("1275 配方 ID 重複或材料數異常");
            result.Add(item, new(item, design, row[4], tool, row[7], materials.ToImmutable(),
                U16(row[24..]), row[26], row[27], U16(row[28..]), row[30], row[31], row[32], index + 1));
            order.Add(item);
        }
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, SmithRecipe>(result, order);
    }

    private static ImmutableArray<SmithRecipe> ReadCandidate(ReadOnlySpan<byte> data, CancellationToken token)
    {
        if (data.Length < 4) throw new CatalogDecodeException("Invalid Smith candidate header");
        int count = BinaryPrimitives.ReadInt32LittleEndian(data);
        if (count is < 0 or > MaxRecords || data.Length != 4 + count * CandidateRecordBytes)
            throw new CatalogDecodeException("Invalid Smith candidate length or record count");
        var result = ImmutableArray.CreateBuilder<SmithRecipe>(count);
        var keys = new HashSet<ushort>();
        byte[] nested = new byte[4 + LegacyRecordBytes];
        BinaryPrimitives.WriteInt32LittleEndian(nested, 1);
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            int pos = 4 + index * CandidateRecordBytes;
            ParserDiagnostics.Checkpoint(offset: pos, field: "recipe", record: index + 1);
            ushort key = U16(data[pos..]);
            if (key == 0 || !keys.Add(key))
                throw new CatalogDecodeException("Invalid or duplicate Smith candidate row key");
            data.Slice(pos + 2, LegacyRecordBytes).CopyTo(nested.AsSpan(4));
            var row = Parse33(nested, token).Values.Single();
            result.Add(row with { Order = index + 1, RecipeId = key, CandidateRowKey = key });
        }
        token.ThrowIfCancellationRequested();
        return result.MoveToImmutable();
    }
    private static ushort U16(ReadOnlySpan<byte> bytes) => BinaryPrimitives.ReadUInt16LittleEndian(bytes);
}
