using System.Buffers.Binary;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Text;
using Lala.Core.Diagnostics.Parsing;

namespace Lala.Core.Catalogs;

/// <summary>
/// Pure TextData_C v1 decoding. An immutable text index is not reviewed-resource identity,
/// an active runtime, or permission to send commands. No filesystem or fallback text source.
/// </summary>
public static class TextDataParser
{
    public const int MaxBytes = 16 * 1024 * 1024;
    public const int MaxRecords = 1_000_000;
    private static readonly UnicodeEncoding StrictUnicode = new(false, false, true);
    private static readonly ParserDiagnosticDefinition Diagnostic =
        new("wlre.services.expedition.data.parse_text_data", "text-v1");

    public static IReadOnlyDictionary<uint, string> Parse(ReadOnlySpan<byte> textData,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        // Parse and diagnose one owned snapshot. Reject oversized spans without copying them.
        ReadOnlySpan<byte> snapshot = textData.Length <= MaxBytes ? textData.ToArray() : textData;
        return ParserDiagnostics.RunWithRaw(Diagnostic, snapshot,
            bytes => ReadTexts(bytes, cancellationToken), rows => new(rows.Count), null,
            cancellationToken, inputName: "text_data");
    }

    private static IReadOnlyDictionary<uint, string> ReadTexts(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        if (raw.Length <= 4 || raw.Length > MaxBytes)
            throw new CatalogDecodeException("文字資料來源缺失或大小不合法");
        var reader = new TextReader(raw, token);
        int count = BinaryPrimitives.ReadInt32LittleEndian(reader.Take(4));
        if (count is < 1 or > MaxRecords) throw new CatalogDecodeException("文字資料筆數錯誤");
        var texts = new Dictionary<uint, string>();
        for (int index = 0; index < count; index++)
        {
            token.ThrowIfCancellationRequested();
            ParserDiagnostics.Checkpoint(offset: reader.Position, field: "record", record: index + 1);
            uint key = BinaryPrimitives.ReadUInt32LittleEndian(reader.Take(4));
            ushort size = BinaryPrimitives.ReadUInt16LittleEndian(reader.Take(2));
            if ((size & 1) != 0 || texts.ContainsKey(key))
                throw new CatalogDecodeException("文字資料長度或識別碼錯誤");
            string text;
            try { text = StrictUnicode.GetString(reader.Take(size)); }
            catch (DecoderFallbackException) { throw new CatalogDecodeException("文字資料編碼錯誤"); }
            // Empty strings, key zero, BOMs, and every NUL are valid and remain unchanged.
            texts.Add(key, text);
        }
        reader.End();
        token.ThrowIfCancellationRequested();
        return new ReadOnlyDictionary<uint, string>(texts);
    }

    // The shared catalog reader trims NULs and applies an unrelated 8192-byte string cap.
    // This local reader exactly follows wire.Reader positions and diagnostics instead.
    private ref struct TextReader(ReadOnlySpan<byte> raw, CancellationToken token)
    {
        private readonly ReadOnlySpan<byte> raw = raw;
        private readonly CancellationToken token = token;
        public int Position { get; private set; }
        private int Remaining => raw.Length - Position;
        public ReadOnlySpan<byte> Take(int size)
        {
            ParserDiagnostics.ReadCheckpoint(Position, size, Remaining);
            token.ThrowIfCancellationRequested();
            if (size > Remaining)
                throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                    $"offset {Position}: need {size}, have {Remaining}"));
            var result = raw.Slice(Position, size);
            Position += size;
            return result;
        }
        public void End()
        {
            ParserDiagnostics.ReadCheckpoint(Position, 0, Remaining);
            if (Remaining != 0)
                throw new CatalogDecodeException(string.Create(CultureInfo.InvariantCulture,
                    $"unexpected trailing bytes: {Remaining}"));
        }
    }
}
