using System.Buffers.Binary;
using System.Collections;
using System.Collections.Frozen;
using System.Collections.Immutable;
using System.Security.Cryptography;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record NpcBattleTalkRow(uint TextId, byte Kind, ushort Parameter, byte Duration);

/// <summary>
/// Offline known-source battle quotes. Public calls always require the fixed reviewed source
/// fingerprint; text-reference validation does not activate resources or grant command authority.
/// </summary>
public static class NpcBattleTalkCatalogParser
{
    public const string ReviewedSha256 = "9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8";
    public const int MaxRecords = 20_000;
    public const int RecordBytes = 10;
    public const int MaxRowsPerGroup = 255;
    public const int MaxBytes = 4 + MaxRecords * RecordBytes;
    private static readonly ParserDiagnosticDefinition Diagnostic =
        new("wlre.services.world.npc_battle_catalog.parse_known_battle_talk", "npc-battle-talk-known-v1");

    public static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> ParseKnownBattleTalk(
        ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default) =>
        ParseDiagnosed(raw, verifySource: true, cancellationToken);

    public static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> BuildCatalog(
        ReadOnlySpan<byte> raw, ReadOnlySpan<byte> textRaw, CancellationToken cancellationToken = default)
    {
        // Deliberately no builder diagnostic decorator: only the two source parsers are decorated.
        var groups = ParseKnownBattleTalk(raw, cancellationToken);
        var texts = TextDataParser.Parse(textRaw, cancellationToken);
        return ValidateReferences(groups, texts, cancellationToken);
    }

    // Synthetic fixtures only. No public hash override or caller-selected source profile.
    internal static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> ParseLayout(
        ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default) =>
        ParseDiagnosed(raw, verifySource: false, cancellationToken);

    internal static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> BuildCatalogLayout(
        ReadOnlySpan<byte> raw, ReadOnlySpan<byte> textRaw, CancellationToken cancellationToken = default)
    {
        var groups = ParseLayout(raw, cancellationToken);
        var texts = TextDataParser.Parse(textRaw, cancellationToken);
        return ValidateReferences(groups, texts, cancellationToken);
    }

    private static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> ValidateReferences(
        IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> groups,
        IReadOnlyDictionary<uint, string> texts, CancellationToken token)
    {
        foreach (var rows in groups.Values)
            foreach (var row in rows)
            {
                token.ThrowIfCancellationRequested();
                if (!texts.ContainsKey(row.TextId))
                    throw new CatalogDecodeException("戰鬥台詞缺少同版 TextData 文字");
            }
        token.ThrowIfCancellationRequested();
        return groups;
    }

    private static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> ParseDiagnosed(
        ReadOnlySpan<byte> raw, bool verifySource, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = raw.Length <= MaxBytes ? raw.ToArray() : raw;
        return ParserDiagnostics.RunWithRaw(Diagnostic, snapshot, bytes =>
        {
            ParserDiagnostics.Checkpoint(offset: 0, field: "source_fingerprint");
            if (verifySource)
            {
                // The production pin is checked before every structural check, as in Python.
                string digest = Convert.ToHexStringLower(SHA256.HashData(bytes));
                token.ThrowIfCancellationRequested();
                if (digest != ReviewedSha256)
                    throw new CatalogDecodeException("NpcTalkData 來源指紋未經審核；拒絕推測新格式");
            }
            token.ThrowIfCancellationRequested();
            return ReadGroups(bytes, token);
        }, groups => new(groups.Count), null, token);
    }

    private static IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> ReadGroups(
        ReadOnlySpan<byte> raw, CancellationToken token)
    {
        if (raw.Length < 4) throw new CatalogDecodeException("NpcTalkData 缺少筆數");
        uint count = BinaryPrimitives.ReadUInt32LittleEndian(raw);
        if (count is 0 or > MaxRecords || raw.Length != 4 + count * RecordBytes)
            throw new CatalogDecodeException("NpcTalkData 筆數或長度不符");
        var groups = new Dictionary<ushort, List<NpcBattleTalkRow>>();
        var order = new List<ushort>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            var row = raw.Slice(4 + index * RecordBytes, RecordBytes);
            ushort group = BinaryPrimitives.ReadUInt16LittleEndian(row);
            uint textId = BinaryPrimitives.ReadUInt32LittleEndian(row[2..]);
            if (!groups.TryGetValue(group, out var rows))
            {
                groups.Add(group, rows = []);
                order.Add(group);
            }
            if (group == 0 || textId == 0 || rows.Count >= MaxRowsPerGroup)
                throw new CatalogDecodeException("NpcTalkData 群組或文字 ID 無效");
            rows.Add(new(textId, row[6], BinaryPrimitives.ReadUInt16LittleEndian(row[7..]), row[9]));
        }
        var result = new OrderedGroups(groups, order);
        token.ThrowIfCancellationRequested();
        return result;
    }

    // Store ordering separately from lookup. FrozenDictionary enumeration is not source order.
    private sealed class OrderedGroups : IReadOnlyDictionary<ushort, ImmutableArray<NpcBattleTalkRow>>
    {
        private readonly ImmutableArray<ushort> order;
        private readonly FrozenDictionary<ushort, ImmutableArray<NpcBattleTalkRow>> groups;
        internal OrderedGroups(Dictionary<ushort, List<NpcBattleTalkRow>> rows, List<ushort> sourceOrder)
        {
            order = sourceOrder.ToImmutableArray();
            groups = rows.ToFrozenDictionary(pair => pair.Key, pair => pair.Value.ToImmutableArray());
        }
        public int Count => order.Length;
        public IEnumerable<ushort> Keys => order;
        public IEnumerable<ImmutableArray<NpcBattleTalkRow>> Values => order.Select(key => groups[key]);
        public ImmutableArray<NpcBattleTalkRow> this[ushort key] => groups[key];
        public bool ContainsKey(ushort key) => groups.ContainsKey(key);
        public bool TryGetValue(ushort key, out ImmutableArray<NpcBattleTalkRow> value) => groups.TryGetValue(key, out value);
        public IEnumerator<KeyValuePair<ushort, ImmutableArray<NpcBattleTalkRow>>> GetEnumerator() =>
            order.Select(key => KeyValuePair.Create(key, groups[key])).GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
