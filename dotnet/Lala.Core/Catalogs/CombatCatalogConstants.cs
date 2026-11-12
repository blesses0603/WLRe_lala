using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;

namespace Lala.Core.Catalogs;

public sealed record CombatCatalogCharacter(BigInteger Sex, BigInteger Head, BigInteger Skill, BigInteger Body);

/// <summary>Data-only constants. A parsed table is not runtime activation or action permission.</summary>
public sealed class CombatCatalogConstants
{
    public ImmutableArray<CombatCatalogCharacter> Characters { get; }
    public ImmutableDictionary<int, ImmutableDictionary<int, double>> ElementWeights { get; }
    internal CombatCatalogConstants(ImmutableArray<CombatCatalogCharacter> characters,
        ImmutableDictionary<int, ImmutableDictionary<int, double>> weights)
        => (Characters, ElementWeights) = (characters, weights);
}

/// <summary>
/// Literal, data-only port of combat_catalog._block/_enum/parse_constants. This is deliberately
/// not a Lua parser: comment/string braces, first matches and repeated matrix entries keep the
/// retained Python scanner's semantics. Nothing is executed, normalized, downloaded or activated.
/// </summary>
public static partial class CombatCatalogParser
{
    public const string ReviewedDefineSha256 = "452e32903a686f22b8e98c1707efca80a45dcf73fd4f1bd5e7e08b38ae3db92c";
    public const string ReviewedFightUnitSha256 = "4c0366884264b14765192c2b7d1644439898edfc06bf29dea988f6de6bf75d88";
    public const int MaxLuaBytes = 2 * 1024 * 1024;
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    public static CombatCatalogConstants ParseConstants(string define, string fight,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        VerifyLua(define, ReviewedDefineSha256, cancellationToken);
        VerifyLua(fight, ReviewedFightUnitSha256, cancellationToken);
        return ParseConstantsLayout(define, fight, cancellationToken);
    }

    private static void VerifyLua(string text, string pin, CancellationToken token)
    {
        ValidateLua(text, token);
        string digest = Convert.ToHexStringLower(SHA256.HashData(StrictUtf8.GetBytes(text)));
        token.ThrowIfCancellationRequested();
        if (digest != pin) throw new CatalogDecodeException("Unreviewed combat Lua text");
    }

    private static void ValidateLua(string text, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(text);
        if (text.Length > MaxLuaBytes) throw new CatalogDecodeException("Combat Lua text exceeds byte limit");
        try
        {
            if (StrictUtf8.GetByteCount(text) > MaxLuaBytes)
                throw new CatalogDecodeException("Combat Lua text exceeds byte limit");
        }
        catch (EncoderFallbackException) { throw new CatalogDecodeException("Invalid combat Lua Unicode text"); }
    }

    // Internal synthetic layout access only. No public arbitrary digest or layout option.
    internal static CombatCatalogConstants ParseConstantsLayout(string define, string fight, CancellationToken token = default)
    {
        ValidateLua(define, token); ValidateLua(fight, token);
        var elements = Enum(define, "EElementType", token);
        var sex = Enum(define, "ERoleType", token);
        var weights = new Dictionary<BigInteger, Dictionary<BigInteger, double>>();
        foreach (var (label, body) in Rows(Block(fight, "elementAttackTimes", token), "[EElementType.", false, token))
        {
            var row = new Dictionary<BigInteger, double>();
            foreach (var (key, value) in Entries(body, "[EElementType.", token))
            {
                // Python evaluates the key lookup before float conversion in the comprehension.
                var id = Lookup(elements, key);
                string numeric = DecimalAscii(value, token, allowDot: true);
                if (!double.TryParse(numeric, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out double parsed))
                    throw new CatalogDecodeException("Invalid element weight");
                row[id] = parsed; // Source last-write-wins, including numeric enum aliases.
            }
            weights[Lookup(elements, label)] = row;
        }
        if (weights.Count != 5 || Enumerable.Range(0, 5).Any(key => !weights.ContainsKey(key)) ||
            weights.Values.Any(row => row.Count != 5 || Enumerable.Range(0, 5).Any(key => !row.ContainsKey(key))))
            throw new CatalogDecodeException("Incomplete element matrix");
        var characters = ImmutableArray.CreateBuilder<CombatCatalogCharacter>();
        foreach (var (ident, body) in Rows(Block(define, "CHARACTER_DATAS", token), "[", true, token))
        {
            if (Integer(ident, token) != characters.Count + 1) throw new CatalogDecodeException("Unexpected character order");
            string? gender = FindValue(body, "sex", "ERoleType.", boundary: false, digits: false, token);
            if (gender is null) throw new CatalogDecodeException("Missing character type");
            BigInteger Number(string key) => Integer(FindValue(body, key, "", true, true, token)
                ?? throw new CatalogDecodeException("Missing character field"), token);
            characters.Add(new(Lookup(sex, gender), Number("headStyle"), Number("firstSkill"), Number("InitialEquip")));
        }
        if (characters.Count != 15) throw new CatalogDecodeException("Incomplete reviewed character table");
        var result = new CombatCatalogConstants(characters.ToImmutable(), weights.ToImmutableDictionary(
            pair => (int)pair.Key, pair => pair.Value.ToImmutableDictionary(cell => (int)cell.Key, cell => cell.Value)));
        token.ThrowIfCancellationRequested();
        return result;
    }

    internal static string Block(string text, string name, CancellationToken token = default)
    {
        ValidateLua(text, token);
        int from = 0;
        while (from < text.Length)
        {
            token.ThrowIfCancellationRequested();
            int start = text.IndexOf(name, from, StringComparison.Ordinal);
            if (start < 0) break;
            from = start + 1;
            if (PreviousWord(text, start) == (name.Length != 0 && Word(Rune.GetRuneAt(name, 0)))) continue;
            int at = start + name.Length;
            if (!Assignment(text, ref at) || !Literal(text, ref at, "{")) continue;
            start = at; int depth = 1;
            for (; at < text.Length; at++)
            {
                token.ThrowIfCancellationRequested();
                if (text[at] == '{') depth++;
                else if (text[at] == '}' && --depth == 0) return text[start..at];
            }
            throw new CatalogDecodeException("Unterminated official table");
        }
        throw new CatalogDecodeException("Missing official constant: " + name);
    }

    internal static ImmutableDictionary<string, BigInteger> Enum(string text, string name, CancellationToken token = default)
    {
        string body = Block(text, name, token);
        var matches = new List<(string Key, string Value)>();
        for (int at = 0; at < body.Length;)
        {
            token.ThrowIfCancellationRequested();
            int start = at;
            string key = Take(body, ref at, Word);
            int end = at;
            if (key.Length != 0 && Assignment(body, ref at))
            {
                string value = Take(body, ref at, Digit);
                if (value.Length != 0)
                {
                    matches.Add((key, value));
                    continue;
                }
            }
            // Failed greedy word matches cannot acquire '=' by dropping a prefix.
            at = Math.Max(end, start + RuneLength(body, start));
        }
        // Python checks duplicate raw keys before attempting any integer conversion.
        if (matches.Select(row => row.Key).Distinct(StringComparer.Ordinal).Count() != matches.Count)
            throw new CatalogDecodeException("Duplicate enum key");
        return matches.ToImmutableDictionary(row => row.Key, row => Integer(row.Value, token), StringComparer.Ordinal);
    }

    private static IEnumerable<(string Key, string Body)> Rows(string text, string prefix, bool digits, CancellationToken token)
    {
        int from = 0;
        while (from < text.Length)
        {
            token.ThrowIfCancellationRequested();
            int start = text.IndexOf(prefix, from, StringComparison.Ordinal);
            if (start < 0) yield break;
            from = start + 1; int at = start + prefix.Length;
            string key = Take(text, ref at, digits ? Digit : Word);
            if (key.Length == 0 || !Literal(text, ref at, "]") || !Assignment(text, ref at) || !Literal(text, ref at, "{")) continue;
            int end = text.IndexOf('}', at);
            if (end <= at) continue;
            yield return (key, text[at..end]);
            from = end + 1;
        }
    }

    private static IEnumerable<(string Key, string Value)> Entries(string text, string prefix, CancellationToken token)
    {
        int from = 0;
        while (from < text.Length)
        {
            token.ThrowIfCancellationRequested();
            int start = text.IndexOf(prefix, from, StringComparison.Ordinal);
            if (start < 0) yield break;
            from = start + 1; int at = start + prefix.Length;
            string key = Take(text, ref at, Word);
            if (key.Length == 0 || !Literal(text, ref at, "]") || !Assignment(text, ref at)) continue;
            string value = Take(text, ref at, rune => Digit(rune) || rune.Value == '.');
            if (value.Length == 0) continue;
            yield return (key, value); from = at;
        }
    }

    private static string? FindValue(string text, string key, string prefix, bool boundary, bool digits, CancellationToken token)
    {
        int from = 0;
        while (from < text.Length)
        {
            token.ThrowIfCancellationRequested();
            int start = text.IndexOf(key, from, StringComparison.Ordinal);
            if (start < 0) return null;
            from = start + 1;
            if (boundary && PreviousWord(text, start)) continue;
            int at = start + key.Length;
            if (!Assignment(text, ref at) || !Literal(text, ref at, prefix)) continue;
            string value = Take(text, ref at, digits ? Digit : Word);
            if (value.Length != 0) return value;
        }
        return null;
    }

    private static bool Assignment(string text, ref int at)
    {
        Space(text, ref at);
        if (!Literal(text, ref at, "=")) return false;
        Space(text, ref at); return true;
    }
    private static bool Literal(string text, ref int at, string literal)
    {
        if (!text.AsSpan(at).StartsWith(literal, StringComparison.Ordinal)) return false;
        at += literal.Length; return true;
    }
    private static void Space(string text, ref int at)
    {
        while (at < text.Length && (char.IsWhiteSpace(text[at]) || text[at] is >= '\u001c' and <= '\u001f')) at++;
    }
    private static string Take(string text, ref int at, Func<Rune, bool> predicate)
    {
        int start = at;
        while (at < text.Length)
        {
            var rune = Rune.GetRuneAt(text, at);
            if (!predicate(rune)) break;
            at += rune.Utf16SequenceLength;
        }
        return text[start..at];
    }
    private static bool Word(Rune rune) => Rune.IsLetterOrDigit(rune) || rune.Value == '_' ||
        Rune.GetUnicodeCategory(rune) is UnicodeCategory.LetterNumber or UnicodeCategory.OtherNumber;
    private static bool Digit(Rune rune) => Rune.GetUnicodeCategory(rune) == UnicodeCategory.DecimalDigitNumber;
    private static int RuneLength(string text, int at) => Rune.GetRuneAt(text, at).Utf16SequenceLength;
    private static bool PreviousWord(string text, int at)
    {
        if (at == 0) return false;
        int previous = at - 1;
        if (char.IsLowSurrogate(text[previous]) && previous > 0 && char.IsHighSurrogate(text[previous - 1])) previous--;
        return Word(Rune.GetRuneAt(text, previous));
    }
    private static BigInteger Lookup(IReadOnlyDictionary<string, BigInteger> values, string key) =>
        values.TryGetValue(key, out var value) ? value : throw new CatalogDecodeException("Unknown official enum key");
    private static BigInteger Integer(string value, CancellationToken token)
    {
        string ascii = DecimalAscii(value, token);
        // CPython's default decimal integer conversion ceiling, including leading zeroes.
        if (ascii.Length > 4300) throw new CatalogDecodeException("Combat integer exceeds decimal digit limit");
        return BigInteger.Parse(ascii, NumberStyles.None, CultureInfo.InvariantCulture);
    }
    private static string DecimalAscii(string value, CancellationToken token, bool allowDot = false)
    {
        var result = new StringBuilder(value.Length);
        foreach (Rune rune in value.EnumerateRunes())
        {
            token.ThrowIfCancellationRequested();
            result.Append(allowDot && rune.Value == '.' ? '.' : (char)('0' + (int)Rune.GetNumericValue(rune)));
        }
        return result.ToString();
    }
}
