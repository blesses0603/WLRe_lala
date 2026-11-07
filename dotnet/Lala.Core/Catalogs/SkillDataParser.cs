using System.Collections.Frozen;
using System.Security.Cryptography;

namespace Lala.Core.Catalogs;

/// <summary>Unsigned fields retain the official spelling, including uninterpreted spare fields.</summary>
public sealed class SkillDataRow
{
    public ushort Id => (ushort)Fields["ID"];
    public uint NameTextId => Fields["Name"];
    public ushort Key => (ushort)Fields["Key"];
    public IReadOnlyDictionary<string, uint> Fields { get; }

    internal SkillDataRow(Dictionary<string, uint> fields) => Fields = fields.ToFrozenDictionary(StringComparer.Ordinal);
}

/// <summary>
/// Offline port of combat_catalog.parse_skills. No names, Lua execution, inferred effects,
/// runtime activation or command permissions. Unknown sources fail before field decoding.
/// </summary>
public static class SkillDataParser
{
    public const string ReviewedSha256 = "ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c";
    public const int MaxSkills = 10_000;
    public const int RecordBytes = 125;
    public const int MaxBytes = 4 + MaxSkills * RecordBytes;

    private static readonly (string Name, int Bytes)[] Layout =
    [
        ("Name", 4), ("Sort", 2), ("Kind", 1), ("ID", 2), ("ReduceSP", 2),
        ("ReduceHP", 1), ("Element", 1), ("AtkKind", 2), ("FightWay", 1), ("Grade", 1),
        ("FightArea", 1), ("VariableA", 2), ("VariableB", 2), ("VariableC", 1), ("VariableD", 2),
        ("Round", 1), ("HitStatus", 2), ("InitSkillPot", 1), ("PreSkillId", 2), ("NextSkillId", 2),
        ("Spare1", 2), ("Spare2", 2), ("Spare3", 2), ("Spare4", 2), ("Spare5", 2),
        ("Spare6", 2), ("Spare7", 2), ("Spare8", 2), ("Spare9", 2), ("Spare10", 2),
        ("Desc", 4), ("HitID", 2), ("Key", 2), ("TargetKind", 1), ("GId", 2),
        ("CornerTag", 1), ("StatusId", 2), ("Duration", 1), ("WeaponKind1", 1), ("WeaponKind2", 1),
        ("WeaponKind3", 1), ("WeaponKind4", 1), ("WeaponKind5", 1), ("LvLimit", 1), ("Discolor", 1),
        ("HitBackId", 2), ("RangeKind1", 1), ("RangeKind2", 1), ("RangeKind3", 1), ("RangeKind4", 1),
        ("SpareByte1", 1), ("SpareByte2", 1), ("SpareByte3", 1), ("SpareByte4", 1), ("SpareByte5", 1),
        ("SoundKey", 2), ("SpareWord2", 2), ("SpareWord3", 2), ("SpareWord4", 2), ("SpareWord5", 2),
        ("SpareInt1", 4), ("SpareInt2", 4), ("SpareInt3", 4), ("SpareInt4", 4), ("SpareInt5", 4),
        ("KindSort", 1), ("MotionKind", 1), ("SPSkillTextureId", 1), ("TargetNPCID", 2),
        ("CostItemID", 2), ("CostItemCount", 2)
    ];

    public static IReadOnlyDictionary<ushort, SkillDataRow> Parse(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ValidateSize(raw.Length);
        byte[] snapshot = raw.ToArray();
        string digest = Convert.ToHexStringLower(SHA256.HashData(snapshot));
        cancellationToken.ThrowIfCancellationRequested();
        if (digest != ReviewedSha256)
            throw new CatalogDecodeException("SkillData source fingerprint is not reviewed");
        return ParseLayout(snapshot, cancellationToken);
    }

    // Test-only access to synthetic layout bytes, never a public source-verification bypass.
    internal static IReadOnlyDictionary<ushort, SkillDataRow> ParseLayout(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ValidateSize(raw.Length);
        var reader = new CatalogReader(raw, cancellationToken);
        uint count = reader.UInt32();
        if (count is 0 or > MaxSkills || raw.Length != 4 + count * RecordBytes)
            throw new CatalogDecodeException("Invalid skill record size");
        var rows = new Dictionary<ushort, SkillDataRow>();
        for (int index = 0; index < count; index++)
        {
            var fields = new Dictionary<string, uint>(Layout.Length, StringComparer.Ordinal);
            foreach (var (name, bytes) in Layout)
                fields.Add(name, bytes switch
                {
                    1 => reader.UInt8(),
                    2 => reader.UInt16(),
                    4 => reader.UInt32(),
                    _ => throw new InvalidOperationException("Invalid compiled SkillData layout")
                });
            var row = new SkillDataRow(fields);
            if (row.Id == 0 || !rows.TryAdd(row.Id, row))
                throw new CatalogDecodeException("Invalid or duplicate skill ID");
        }
        var snapshot = rows.ToFrozenDictionary();
        cancellationToken.ThrowIfCancellationRequested();
        return snapshot;
    }

    private static void ValidateSize(int length)
    {
        if (length < 4 || length > MaxBytes)
            throw new CatalogDecodeException("Invalid skill record size");
    }
}
