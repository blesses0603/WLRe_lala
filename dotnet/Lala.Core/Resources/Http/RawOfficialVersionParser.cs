using System.Buffers.Binary;
using System.IO.Compression;
using System.Numerics;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lala.Core.Resources;

internal sealed record ResourcePathSelection(string DataVersion, string ExeVersion);

/// <summary>Bounded parsing only. An observation is never an authority or readiness token.</summary>
internal static class RawOfficialVersionParser
{
    internal const int MaximumBytes = 16 * 1024;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private static readonly Regex Version = new(@"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\z", RegexOptions.NonBacktracking);
    private static readonly Regex Semver = new(@"\A[0-9]+\.[0-9]+\.[0-9]+\z", RegexOptions.NonBacktracking);
    private static readonly Regex FinalComma = new(@",(?=\s*\]\s*\z)", RegexOptions.CultureInvariant);
    private static ResourceValidationException Invalid() => new("Invalid official version payload");

    internal static string ParsePackage(byte[] body, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        if (body.Length > MaximumBytes) throw Invalid();
        try
        {
            string value = Trim(Utf8Text(body));
            if (value.StartsWith('{'))
            {
                using var json = JsonDocument.Parse(value);
                var root = json.RootElement;
                JsonElement field = default;
                foreach (string name in new[] { "packageVersion", "PackageVersion", "version" })
                    if (root.TryGetProperty(name, out field)) break;
                value = field.ValueKind == JsonValueKind.String ? field.GetString()! : "";
            }
            if (!Version.IsMatch(value)) throw Invalid();
            token.ThrowIfCancellationRequested();
            return value;
        }
        catch (Exception ex) when (ex is JsonException or DecoderFallbackException or InvalidOperationException)
        { throw Invalid(); }
    }

    internal static ResourcePathSelection ParseMap(byte[] body, string supportedExe, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested();
        if (body.Length > MaximumBytes || !Semver.IsMatch(supportedExe)) throw Invalid();
        try
        {
            if (body.AsSpan().StartsWith(new byte[] { 0x1f, 0x8b })) body = InflateOne(body, token);
            string value;
            if (body.AsSpan().StartsWith(new byte[] { 0xff, 0xfe })) value = new UnicodeEncoding(false, false, true).GetString(body, 2, body.Length - 2);
            else if (body.AsSpan().StartsWith(new byte[] { 0xfe, 0xff })) value = new UnicodeEncoding(true, false, true).GetString(body, 2, body.Length - 2);
            else value = Utf8Text(body);
            value = Trim(value);
            if (!value.StartsWith('[')) throw Invalid();
            JsonDocument document;
            try { document = JsonDocument.Parse(value); }
            catch (JsonException) { document = JsonDocument.Parse(FinalComma.Replace(value, "", 1)); }
            using (document)
            {
                var rows = document.RootElement;
                if (rows.ValueKind != JsonValueKind.Array || rows.GetArrayLength() is < 1 or > 128) throw Invalid();
                string? matched = null, latestExe = null, latestData = null;
                int matches = 0;
                foreach (var row in rows.EnumerateArray())
                {
                    token.ThrowIfCancellationRequested();
                    string? exe = ResourceValidation.String(row, "ExeVer"), data = ResourceValidation.String(row, "DataVer");
                    if (exe is null || data is null || !Semver.IsMatch(exe) || !ResourceValidation.DataVersion.IsMatch(data)) throw Invalid();
                    if (exe == supportedExe) { matches++; matched = data; }
                    if (latestExe is null || Compare(exe, latestExe) > 0) { latestExe = exe; latestData = data; }
                }
                if (matches != 1) throw Invalid();
                return Compare(latestExe!, supportedExe) > 0 ? new(latestData!, latestExe!) : new(matched!, supportedExe);
            }
        }
        catch (Exception ex) when (ex is JsonException or DecoderFallbackException or InvalidDataException or IOException or OverflowException)
        { throw Invalid(); }
    }

    private static string Utf8Text(byte[] body) => Utf8.GetString(body.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) ? body.AsSpan(3) : body);
    private static string Trim(string text)
    {
        static bool White(char c) => char.IsWhiteSpace(c) || c is >= '\u001c' and <= '\u001f';
        int start = 0, end = text.Length;
        while (start < end && White(text[start])) start++;
        while (end > start && White(text[end - 1])) end--;
        return text[start..end];
    }

    private static int Compare(string a, string b)
    {
        string[] aa = a.Split('.'), bb = b.Split('.');
        for (int i = 0; i < 3; i++)
        {
            int comparison = BigInteger.Parse(aa[i]).CompareTo(BigInteger.Parse(bb[i]));
            if (comparison != 0) return comparison;
        }
        return 0;
    }

    // Parse framing ourselves; GZipStream accepts concatenated members and trailing bytes.
    // One-byte compressed reads prevent DeflateStream buffering past the first member.
    private static byte[] InflateOne(byte[] bytes, CancellationToken token)
    {
        if (bytes.Length < 18 || bytes[2] != 8 || (bytes[3] & 0xe0) != 0) throw Invalid();
        int offset = 10, flags = bytes[3];
        if ((flags & 4) != 0)
        {
            if (offset + 2 > bytes.Length) throw Invalid();
            int length = BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(offset)); offset += 2 + length;
        }
        foreach (int flag in new[] { 8, 16 })
            if ((flags & flag) != 0)
            {
                while (offset < bytes.Length && bytes[offset] != 0) offset++;
                offset++;
            }
        if (offset > bytes.Length - 8) throw Invalid();
        if ((flags & 2) != 0)
        {
            if (offset + 2 > bytes.Length - 8 || (Crc(bytes.AsSpan(0, offset)) & 0xffff) != BinaryPrimitives.ReadUInt16LittleEndian(bytes.AsSpan(offset))) throw Invalid();
            offset += 2;
        }
        using var input = new SingleByteInput(bytes, offset);
        using var inflater = new DeflateStream(input, CompressionMode.Decompress, leaveOpen: true);
        using var output = new MemoryStream();
        byte[] buffer = new byte[1024];
        while (true)
        {
            token.ThrowIfCancellationRequested();
            int n = inflater.Read(buffer, 0, Math.Min(buffer.Length, MaximumBytes + 1 - (int)output.Length));
            if (n == 0) break;
            output.Write(buffer, 0, n);
            if (output.Length > MaximumBytes) throw Invalid();
        }
        byte[] result = output.ToArray();
        int end = (int)input.Position;
        if (end != bytes.Length - 8 || BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(end)) != Crc(result) ||
            BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(end + 4)) != result.Length) throw Invalid();
        return result;
    }
    private static uint Crc(ReadOnlySpan<byte> bytes)
    {
        uint crc = 0xffffffff;
        foreach (byte b in bytes) { crc ^= b; for (int j = 0; j < 8; j++) crc = (crc >> 1) ^ ((crc & 1) == 0 ? 0u : 0xedb88320u); }
        return ~crc;
    }
    private sealed class SingleByteInput(byte[] bytes, int offset) : MemoryStream(bytes, 0, bytes.Length, false)
    {
        private bool _started;
        public override int Read(byte[] buffer, int offsetInBuffer, int count)
        {
            if (!_started) { Position = offset; _started = true; }
            return base.Read(buffer, offsetInBuffer, Math.Min(count, 1));
        }
        public override int Read(Span<byte> buffer)
        {
            if (!_started) { Position = offset; _started = true; }
            return base.Read(buffer[..Math.Min(buffer.Length, 1)]);
        }
    }
}
