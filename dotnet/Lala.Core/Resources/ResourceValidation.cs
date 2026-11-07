using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Lala.Core.Resources;

public sealed class ResourceValidationException(string message) : FormatException(message);

/// <summary>Pure approved-origin selection. Does not read the environment or perform requests.</summary>
public static class OfficialResourceOrigin
{
    public const string DefaultHost = "wlreftpsrc.chinesegamer.net";
    public static string SelectHost() => DefaultHost;
    public static string SelectHost(string configuredHost) => configuredHost switch
    {
        "wlreftp.chinesegamer.net" or DefaultHost => configuredHost,
        _ => throw new ResourceValidationException("Unsupported official resource host")
    };
}

internal static class ResourceValidation
{
    internal static readonly string[] Packages = ["DataPackage", "MainPackage"];
    internal static readonly string[] Features = ["npc", "shops", "crafting", "scenes", "items"];
    internal static readonly Regex GameVersion = Pattern(@"[0-9]{1,4}(?:\.[0-9]{1,4}){2}");
    internal static readonly Regex DataVersion = Pattern(@"[0-9]{1,4}(?:\.[0-9]{1,4}){2,3}");
    internal static readonly Regex Revision = Pattern(@"[1-9][0-9]{0,5}");
    internal static readonly Regex Manifest = Pattern(@"([1-9][0-9]{0,5})_20[0-9]{2}(?:_[0-9]{2}){6}");
    internal static readonly Regex Sha256 = Pattern("[0-9a-f]{64}");
    private static readonly Regex NumericRevision = Pattern(@"([0-9]+)(?:_20[0-9]{2}(?:_[0-9]{2}){6})?");
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);
    private static Regex Pattern(string pattern) => new(@"\A(?:" + pattern + @")\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    internal const int MaximumMetadataBytes = 64 * 1024;
    internal static JsonDocument Parse(ReadOnlySpan<byte> raw, int maximum = MaximumMetadataBytes, bool allowBom = false, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (raw.Length > maximum)
            throw new ResourceValidationException("Resource metadata exceeds size limit");
        if (allowBom && raw.StartsWith(new byte[] { 0xef, 0xbb, 0xbf })) raw = raw[3..];
        try
        {
            StrictUtf8.GetCharCount(raw); // Validate even bytes in ignored fields, as Python UTF-8 decoding does.
            var document = JsonDocument.Parse(raw.ToArray());
            if (cancellationToken.IsCancellationRequested)
            {
                document.Dispose();
                cancellationToken.ThrowIfCancellationRequested();
            }
            return document;
        }
        catch (JsonException) { throw new ResourceValidationException("Invalid resource JSON"); }
        catch (DecoderFallbackException) { throw new ResourceValidationException("Invalid resource UTF-8"); }
    }

    internal static bool HasKeys(JsonElement value, params string[] names) =>
        value.ValueKind == JsonValueKind.Object && value.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal).SetEquals(names);
    internal static bool IsObject(JsonElement value) => value.ValueKind == JsonValueKind.Object;
    internal static JsonElement Property(JsonElement value, string key) =>
        IsObject(value) && value.TryGetProperty(key, out JsonElement result) ? result : default;
    internal static string? String(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String) return null;
        try { return value.GetString(); }
        catch (InvalidOperationException) { throw new ResourceValidationException("Invalid Unicode resource identifier"); }
    }
    internal static string? String(JsonElement value, string key) => String(Property(value, key));
    internal static bool Integer(JsonElement value, out int result)
    {
        result = 0;
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out result);
    }
    internal static bool One(JsonElement value) => Integer(value, out int result) && result == 1;
    internal static int TextLength(string value) => value.EnumerateRunes().Count();
    internal static string Digest(ReadOnlySpan<byte> raw, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        string digest = Convert.ToHexStringLower(SHA256.HashData(raw));
        cancellationToken.ThrowIfCancellationRequested();
        return digest;
    }

    // Python json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(',', ':')).
    // System.Text.Json's default encoder also escapes ASCII <, >, +, etc.; that changes identity.
    internal static string Quote(string value)
    {
        var result = new StringBuilder("\"");
        foreach (char character in value)
        {
            result.Append(character switch
            {
                '"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
                < ' ' or >= '\x7f' => "\\u" + ((int)character).ToString("x4"),
                _ => character.ToString()
            });
        }
        return result.Append('"').ToString();
    }
    internal static string CompareRevision(string local, string remote)
    {
        if (local == remote) return "same";
        Match a = NumericRevision.Match(local), b = NumericRevision.Match(remote);
        if (!a.Success || !b.Success) return "different";
        int comparison = BigInteger.Parse(b.Groups[1].Value).CompareTo(BigInteger.Parse(a.Groups[1].Value));
        return comparison == 0 ? "same" : comparison > 0 ? "newer" : "older";
    }
}
