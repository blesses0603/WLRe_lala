using System.Buffers.Binary;
using System.Collections.Frozen;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Battle;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record NormalAttackNpcData(byte Kind, byte BodyType, byte NormalAttackKind, bool CanCatch);

/// <summary>Immutable offline inputs only. Capture facts and attack rules grant no command permission.</summary>
public sealed class NormalAttackCatalogData
{
    public IReadOnlyDictionary<ushort, NormalAttackNpcData> Npcs { get; }
    public IReadOnlyDictionary<ushort, byte> ItemKinds { get; }
    // Python subtracts 100 from signed Int32 attributes without overflowing.
    public IReadOnlyDictionary<ushort, long> CatchNets { get; }
    public NormalAttackCatalogSnapshot NormalAttacks { get; }

    internal NormalAttackCatalogData(IReadOnlyDictionary<ushort, NormalAttackNpcData> npcs,
        Dictionary<ushort, byte> items, Dictionary<ushort, long> catchNets)
    {
        Npcs = npcs.ToFrozenDictionary();
        ItemKinds = items.ToFrozenDictionary();
        CatchNets = catchNets.ToFrozenDictionary();
        NormalAttacks = new(ItemKinds.Select(pair => KeyValuePair.Create((int)pair.Key, (int)pair.Value)),
            Npcs.Select(pair => KeyValuePair.Create((uint)pair.Key,
                new NormalAttackNpc(pair.Value.Kind, pair.Value.BodyType, pair.Value.NormalAttackKind))));
    }
}

/// <summary>
/// Pure parse_npcs/build_catalog subset of normal_attack_catalog.py. Both production inputs keep
/// their fixed reviewed SHA-256 gates. No downloads, global CurrentNormalData or runtime activation.
/// </summary>
public static class NormalAttackCatalogParser
{
    public const string ReviewedNpcSha256 = "edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c";
    public const int MaxNpcs = 20_000;
    public const int NpcFieldBytes = 203;
    // Derived from the source's record/text limits, not an additional narrower layout assumption.
    public const int MaxNpcBytes = 4 + MaxNpcs * (4 + 2 * ItemDataParser.MaxTextBytes + NpcFieldBytes);
    private static readonly ParserDiagnosticDefinition NpcDiagnostic =
        new("wlre.services.world.normal_attack_catalog.parse_npcs", "normal-npc-reviewed-1296");

    public static IReadOnlyDictionary<ushort, NormalAttackNpcData> ParseNpcs(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default) => ParseNpcsDiagnosed(raw, true, cancellationToken);

    public static NormalAttackCatalogData BuildCatalog(ReadOnlySpan<byte> npcRaw, ReadOnlySpan<byte> itemRaw,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Source order is intentional: ItemData digest/parse precedes the NPC digest/parse.
        if (itemRaw.Length > ItemDataParser.MaxBytes)
            throw new CatalogDecodeException("物品普攻資料格式尚未驗證");
        byte[] itemSnapshot = itemRaw.ToArray();
        string itemDigest = Convert.ToHexStringLower(SHA256.HashData(itemSnapshot));
        cancellationToken.ThrowIfCancellationRequested();
        if (itemDigest != ItemDataParser.Reviewed1296Sha256)
            throw new CatalogDecodeException("物品普攻資料格式尚未驗證");
        var items = ItemDataParser.Parse(itemSnapshot, cancellationToken: cancellationToken);
        var npcs = ParseNpcs(npcRaw, cancellationToken);
        return BuildFromRows(npcs, items, cancellationToken);
    }

    // Synthetic test-only layout access. No caller-supplied digest or public pin bypass.
    internal static IReadOnlyDictionary<ushort, NormalAttackNpcData> ParseNpcsLayout(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default) => ParseNpcsDiagnosed(raw, false, cancellationToken);

    internal static NormalAttackCatalogData BuildCatalogLayout(ReadOnlySpan<byte> npcRaw, ReadOnlySpan<byte> itemRaw,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var items = ItemDataParser.ParseLayout(itemRaw, reviewed1296: true, cancellationToken: cancellationToken);
        var npcs = ParseNpcsLayout(npcRaw, cancellationToken);
        return BuildFromRows(npcs, items, cancellationToken);
    }

    private static NormalAttackCatalogData BuildFromRows(IReadOnlyDictionary<ushort, NormalAttackNpcData> npcs,
        IReadOnlyDictionary<ushort, ItemDataRow> items, CancellationToken token)
    {
        var kinds = new Dictionary<ushort, byte>();
        var nets = new Dictionary<ushort, long>();
        foreach (var (id, item) in items)
        {
            token.ThrowIfCancellationRequested();
            var details = item.ReviewedDetails ?? throw new CatalogDecodeException("物品普攻資料格式尚未驗證");
            kinds.Add(id, details.Kind);
            if (details.Special == 140) nets.Add(id, (long)details.Attributes[0].Value - 100);
        }
        var result = new NormalAttackCatalogData(npcs, kinds, nets);
        token.ThrowIfCancellationRequested();
        return result;
    }

    private static IReadOnlyDictionary<ushort, NormalAttackNpcData> ParseNpcsDiagnosed(ReadOnlySpan<byte> raw,
        bool verifySource, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        // Hash, decode and diagnose one owned snapshot; oversized failures need no large copy.
        ReadOnlySpan<byte> snapshot = raw.Length <= MaxNpcBytes ? raw.ToArray() : raw;
        return ParserDiagnostics.RunWithRaw(NpcDiagnostic, snapshot, bytes =>
        {
            if (bytes.Length > MaxNpcBytes)
                throw new CatalogDecodeException("NPC 普攻資料格式尚未驗證");
            if (verifySource)
            {
                string digest = Convert.ToHexStringLower(SHA256.HashData(bytes));
                token.ThrowIfCancellationRequested();
                if (digest != ReviewedNpcSha256)
                    throw new CatalogDecodeException("NPC 普攻資料格式尚未驗證");
            }
            token.ThrowIfCancellationRequested();
            return ReadNpcs(bytes, token);
        }, rows => new(rows.Count), null, token);
    }

    private static IReadOnlyDictionary<ushort, NormalAttackNpcData> ReadNpcs(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        var reader = new NpcReader(raw, token);
        uint count = BinaryPrimitives.ReadUInt32LittleEndian(reader.Take(4));
        if (count is 0 or > MaxNpcs) throw new CatalogDecodeException("Invalid NPC count");
        var rows = new Dictionary<ushort, NormalAttackNpcData>();
        for (int index = 0; index < count; index++)
        {
            reader.Utf16();
            reader.Utf16();
            var fields = reader.Take(NpcFieldBytes);
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(fields[1..]);
            if (id == 0 || !rows.TryAdd(id, new(fields[106], fields[27], fields[114], fields[26] == 0)))
                throw new CatalogDecodeException("Invalid or duplicate NPC ID");
        }
        if (reader.Remaining != 0) throw new CatalogDecodeException("Unexpected NPC trailing bytes");
        var result = rows.ToFrozenDictionary();
        token.ThrowIfCancellationRequested();
        return result;
    }

    // Reader's source diagnostics apply here only; existing catalog parsers remain unchanged.
    // The two ignored strings must still be strictly decoded and permit empty/NUL-only values.
    private ref struct NpcReader(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        private static readonly UnicodeEncoding StrictUnicode = new(false, false, true);
        private CatalogReader reader = new(raw, token);
        private readonly CancellationToken cancellationToken = token;
        public int Remaining => reader.Remaining;
        public ReadOnlySpan<byte> Take(int count)
        {
            ParserDiagnostics.ReadCheckpoint(reader.Position, count, reader.Remaining);
            cancellationToken.ThrowIfCancellationRequested();
            // Keep this source reader's wording without altering shared catalog contracts.
            if (count < 0 || count > reader.Remaining)
                throw new CatalogDecodeException("ItemData record truncated");
            return reader.Take(count);
        }

        public void Utf16()
        {
            ushort length = BinaryPrimitives.ReadUInt16LittleEndian(Take(2));
            if (length > ItemDataParser.MaxTextBytes || (length & 1) != 0)
            {
                ParserDiagnostics.Checkpoint(actual: length, expectedMax: ItemDataParser.MaxTextBytes,
                    constraint: "even_utf16_length");
                throw new CatalogDecodeException("Invalid ItemData Unicode byte length");
            }
            try { StrictUnicode.GetString(Take(length)); }
            catch (DecoderFallbackException) { throw new CatalogDecodeException("Invalid ItemData Unicode data"); }
        }
    }
}
