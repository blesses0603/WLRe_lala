using System.Buffers.Binary;
using System.Text;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

public sealed record TalkDataRow(string Text, ushort VoiceId);

/// <summary>Strict offline TalkData_C decoding, not verified provenance or an active dialogue catalog.</summary>
public static class TalkDataParser
{
    public const int MaxBytes = 16 * 1024 * 1024;
    public const int MaxRecords = 65_536;
    public const int MaxTextBytes = 32_768;
    private static readonly UnicodeEncoding StrictUnicode = new(false, false, true);
    private static readonly ParserDiagnosticDefinition Diagnostic =
        new("wlre.services.world.npc_talk.parse_talk_data", "talk-v1");

    public static IReadOnlyDictionary<ushort, TalkDataRow> Parse(ReadOnlySpan<byte> raw,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ReadOnlySpan<byte> snapshot = raw.Length <= MaxBytes ? raw.ToArray() : raw;
        return ParserDiagnostics.RunWithRaw(Diagnostic, snapshot, bytes => Read(bytes, cancellationToken),
            rows => new(rows.Count), null, cancellationToken);
    }

    private static IReadOnlyDictionary<ushort, TalkDataRow> Read(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        if (raw.Length < 4 || raw.Length > MaxBytes)
            throw new CatalogDecodeException("TalkData_C 大小不合法");
        int count = BinaryPrimitives.ReadInt32LittleEndian(raw);
        if (count is < 1 or > MaxRecords || count > (raw.Length - 4) / 39)
            throw new CatalogDecodeException("TalkData_C 筆數超出資料邊界");
        int pos = 4;
        var rows = new Dictionary<ushort, TalkDataRow>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: pos, field: "talk_record", record: index + 1);
            if (raw.Length - pos < 39) throw new CatalogDecodeException("TalkData_C 資料遭到截斷");
            ushort id = BinaryPrimitives.ReadUInt16LittleEndian(raw[pos..]);
            ushort size = BinaryPrimitives.ReadUInt16LittleEndian(raw[(pos + 2)..]);
            pos += 4;
            ParserDiagnostics.Checkpoint(offset: pos - 2, field: "text_length", expected: size, actual: raw.Length - pos);
            if ((size & 1) != 0 || size > MaxTextBytes || raw.Length - pos < size + 35)
                throw new CatalogDecodeException("TalkData_C 字串長度不合法");
            string value;
            try { value = StrictUnicode.GetString(raw.Slice(pos, size)).TrimEnd('\0'); }
            catch (DecoderFallbackException) { throw new CatalogDecodeException("TalkData_C 文字不是合法 UTF-16LE"); }
            pos += size + 5;
            ushort voice = BinaryPrimitives.ReadUInt16LittleEndian(raw[pos..]);
            pos += 2 + 4 * 2 + 5 * 4;
            if (rows.ContainsKey(id)) throw new CatalogDecodeException("TalkData_C 對話 ID 重複");
            if (value.Any(character => character < 32 && character is not ('\r' or '\n' or '\t')))
                throw new CatalogDecodeException("TalkData_C 含無效控制字元");
            rows.Add(id, new(value, voice));
        }
        if (pos != raw.Length) throw new CatalogDecodeException("TalkData_C 存在未知尾端資料");
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, TalkDataRow>(rows, rows.Keys);
    }
}
