using System.Collections.Frozen;
using System.Security.Cryptography;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record ItemAttribute(ushort Kind, byte Effect, int Value);

/// <summary>These fields exist only for the independently pinned 1296 source.</summary>
public sealed class ReviewedItemDetails
{
    public byte Kind { get; internal init; }
    public ushort Order { get; internal init; }
    public ushort IconId { get; internal init; }
    public ushort ShopIconId { get; internal init; }
    public IReadOnlyList<ItemAttribute> Attributes { get; internal init; } = Array.Empty<ItemAttribute>();
    public byte Material { get; internal init; }
    public byte Level { get; internal init; }
    public byte FitType { get; internal init; }
    public byte Special { get; internal init; }
    public IReadOnlyList<ushort> Spares { get; internal init; } = Array.Empty<ushort>();
    public byte SizeL { get; internal init; }
    public byte SizeW { get; internal init; }
    public byte SizeH { get; internal init; }
    public byte ItemW { get; internal init; }
    public byte ItemH { get; internal init; }
    public ushort AvailableTime { get; internal init; }
    public ushort LimitedTime { get; internal init; }
    public ushort UseCount { get; internal init; }
    public byte Flags2 { get; internal init; }
    public bool IsPvpTimeOver => (Flags2 & 1) != 0;
    public string UnknownTail1296Hex { get; internal init; } = "";
    public ushort StyleBankSetSortId { get; internal init; }
    public bool Stackable { get; internal init; }
    public ushort? SkillLink { get; internal init; }
    internal ReviewedItemDetails() { }
}

/// <summary>Base prices only. No discounts, live totals, effects or purchase permissions.</summary>
public sealed record ItemDataRow(
    ushort ItemId, string Name, uint Price, uint SellPrice, ushort Restrict,
    byte OpenUsed, byte NeedLevel, ReviewedItemDetails? ReviewedDetails);

/// <summary>Offline port of itemdata_v1.py. Unknown versions and layouts fail closed.</summary>
public static class ItemDataParser
{
    public const int MaxItems = 20_000;
    public const int MaxTextBytes = 8_192;
    public const int MaxBytes = 16 * 1024 * 1024;
    public const string Reviewed1296Version = "1296_2026_11_04_13_34_19_13";
    public const string Reviewed1296Sha256 = "5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4";

    private static readonly FrozenSet<string> LegacyVersions = new[]
    {
        "1262_2026_10_14_15_00_34_84", "1275_2026_10_21_18_27_33_84", "1286_2026_10_29_13_42_37_94"
    }.ToFrozenSet(StringComparer.Ordinal);

    public static IReadOnlyDictionary<ushort, ItemDataRow> Parse(ReadOnlySpan<byte> raw,
        string? packageVersion = null, bool includeSkillLink = false, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ValidateSize(raw.Length);
        // Hash and decode the same owned bytes even when the caller retains a mutable array.
        byte[] snapshot = raw.ToArray();
        bool reviewed1296 = Convert.ToHexStringLower(SHA256.HashData(snapshot)) == Reviewed1296Sha256;
        cancellationToken.ThrowIfCancellationRequested();
        ValidateSource(packageVersion, reviewed1296, includeSkillLink);
        return ParseLayout(snapshot, reviewed1296, includeSkillLink, cancellationToken);
    }

    // Adapter-only entrypoint: the Python adapter does not pass its package version to
    // parse_itemdata. Preserve the parser's independent fixed source pin and diagnostics.
    internal static IReadOnlyDictionary<ushort, ItemDataRow> ParseForSourceAdapter(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken) => ParserDiagnostics.RunWithRaw(
            new("wlre.services.world.itemdata_v1.parse_itemdata", "itemdata-v1"), raw, bytes =>
            {
                ValidateSize(bytes.Length);
                bool reviewed = Convert.ToHexStringLower(SHA256.HashData(bytes)) == Reviewed1296Sha256;
                cancellationToken.ThrowIfCancellationRequested();
                ValidateSource(null, reviewed, false);
                return ReadLayout(bytes, reviewed, false, cancellationToken, sourceAdapter: true);
            }, rows => new(rows.Count), null, cancellationToken);

    internal static void ValidateSource(string? packageVersion, bool reviewed1296, bool includeSkillLink)
    {
        if (packageVersion is not null && packageVersion != Reviewed1296Version && !LegacyVersions.Contains(packageVersion))
            throw new CatalogDecodeException("Unreviewed ItemData package version");
        if (packageVersion == Reviewed1296Version && !reviewed1296)
            throw new CatalogDecodeException("ItemData 1296 source digest mismatch");
        if (packageVersion is not null && LegacyVersions.Contains(packageVersion) && reviewed1296)
            throw new CatalogDecodeException("ItemData source and package version differ");
        if (includeSkillLink && !reviewed1296)
            throw new CatalogDecodeException("Skill link needs reviewed ItemData source");
    }

    // Internal so synthetic tests can exercise the layout without shipping official bytes
    // or introducing a caller-supplied digest / public verification bypass.
    internal static IReadOnlyDictionary<ushort, ItemDataRow> ParseLayout(ReadOnlySpan<byte> raw,
        bool reviewed1296, bool includeSkillLink = false, CancellationToken cancellationToken = default)
        => ReadLayout(raw, reviewed1296, includeSkillLink, cancellationToken, sourceAdapter: false);

    private static IReadOnlyDictionary<ushort, ItemDataRow> ReadLayout(ReadOnlySpan<byte> raw,
        bool reviewed1296, bool includeSkillLink, CancellationToken cancellationToken, bool sourceAdapter)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ValidateSize(raw.Length);
        if (includeSkillLink && !reviewed1296)
            throw new CatalogDecodeException("Skill link needs reviewed ItemData source");
        var reader = new CatalogReader(raw, cancellationToken, sourceAdapter);
        uint count = reader.UInt32();
        if (count is 0 or > MaxItems)
            throw new CatalogDecodeException("ItemData record count outside reviewed range");
        var rows = new Dictionary<ushort, ItemDataRow>();
        var sourceOrder = sourceAdapter ? new List<ushort>() : null;
        for (int index = 0; index < count; index++)
        {
            if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "name_length", record: index + 1);
            string name = reader.Utf16();
            byte kind = reader.UInt8();
            if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "kind_name_length");
            reader.Utf16(allowEmpty: true);
            if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "item_id");
            ushort itemId = reader.UInt16();
            if (itemId == 0 || rows.ContainsKey(itemId))
                throw new CatalogDecodeException("Invalid or duplicate ItemData item ID");
            ushort order = reader.UInt16(), iconId = reader.UInt16(), shopIconId = reader.UInt16();
            reader.Skip(8);
            ItemAttribute[] attributes =
            [
                new(reader.UInt16(), reader.UInt8(), reader.Int32()),
                new(reader.UInt16(), reader.UInt8(), reader.Int32())
            ];
            byte material = reader.UInt8(), level = reader.UInt8(), fitType = reader.UInt8(), special = reader.UInt8();
            reader.Skip(64);
            byte openUsed = reader.UInt8(), needLevel = reader.UInt8();
            uint price = reader.UInt32(), sellPrice = reader.UInt32();
            reader.Skip(1);
            ushort restrict = reader.UInt16();
            reader.Skip(9);
            ushort skillLink = reader.UInt16();
            ushort[] spares = [reader.UInt16(), reader.UInt16(), reader.UInt16(), reader.UInt16(), reader.UInt16()];
            if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "description_length");
            ushort descriptionSize = reader.UInt16();
            if (descriptionSize > MaxTextBytes || (descriptionSize & 1) != 0)
                throw new CatalogDecodeException("Invalid ItemData description length");
            // Python intentionally skips, rather than decodes, this unreviewed description.
            reader.Skip(descriptionSize);
            byte sizeL = reader.UInt8(), sizeW = reader.UInt8(), sizeH = reader.UInt8();
            reader.Skip(2);
            byte itemW = reader.UInt8(), itemH = reader.UInt8();
            reader.Skip(12);
            reader.Skip(3);
            ushort availableTime = reader.UInt16(), limitedTime = reader.UInt16(), useCount = reader.UInt16();
            reader.Skip(4);
            reader.Skip(24);
            reader.Skip(5);
            byte flags2 = reader.UInt8();
            reader.Skip(7);
            reader.Skip(10);
            reader.Skip(7);
            ReviewedItemDetails? details = null;
            if (reviewed1296)
            {
                if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "unknown_tail_1296");
                ReadOnlySpan<byte> tail = reader.Take(2);
                details = new ReviewedItemDetails
                {
                    Kind = kind, Order = order, IconId = iconId, ShopIconId = shopIconId,
                    Attributes = Array.AsReadOnly(attributes), Material = material, Level = level,
                    FitType = fitType, Special = special, Spares = Array.AsReadOnly(spares),
                    SizeL = sizeL, SizeW = sizeW, SizeH = sizeH, ItemW = itemW, ItemH = itemH,
                    AvailableTime = availableTime, LimitedTime = limitedTime, UseCount = useCount,
                    Flags2 = flags2, UnknownTail1296Hex = Convert.ToHexStringLower(tail),
                    StyleBankSetSortId = System.Buffers.Binary.BinaryPrimitives.ReadUInt16LittleEndian(tail),
                    SkillLink = includeSkillLink ? skillLink : null,
                    Stackable = ItemStackRules.CanOverlap(itemId, new(fitType, kind, special,
                        availableTime, limitedTime, useCount, flags2, attributes[0].Kind, attributes[1].Kind))
                };
            }
            rows.Add(itemId, new(itemId, name, price, sellPrice, restrict, openUsed, needLevel, details));
            sourceOrder?.Add(itemId);
        }
        if (sourceAdapter) ParserDiagnostics.Checkpoint(offset: reader.Position, field: "end_of_file", expected: raw.Length, actual: reader.Position);
        if (reader.Remaining != 0)
            throw new CatalogDecodeException("ItemData record layout changed or trailing bytes");
        IReadOnlyDictionary<ushort, ItemDataRow> snapshot = sourceAdapter
            ? new OrderedCatalog<ushort, ItemDataRow>(rows, sourceOrder!) : rows.ToFrozenDictionary();
        cancellationToken.ThrowIfCancellationRequested();
        return snapshot;
    }

    private static void ValidateSize(int length)
    {
        if (length <= 4 || length > MaxBytes)
            throw new CatalogDecodeException("ItemData is missing or oversized");
    }
}
