using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Social.Ark;

namespace Lala.Core.Storage;

/// <summary>Content address only: it carries no catalog trust, permission to send, or server proof.</summary>
public sealed record ArkQuestionIdentity(string Catalog, string Role, string Fingerprint, string CanonicalPayload)
{
    public override string ToString() => nameof(ArkQuestionIdentity);

    /// <summary>Recomputes Python's ensure_ascii=False, sorted-key, compact JSON identity.
    /// Only option order is ignored. Award/selection/known-answer fields are not identity.</summary>
    public static ArkQuestionIdentity Create(ArkCatalogToken token, BigInteger role, ArkQuestionSnapshot question)
    {
        ArgumentNullException.ThrowIfNull(token);
        if (!token.Attempted || token.IdentityKey is not { Length: 64 } key ||
            key.Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')) || role <= 0 || role.GetByteCount() > 1787)
            throw new ArgumentException("Question catalog and role identity must be complete.");
        string roleNumber = role.ToString(CultureInfo.InvariantCulture);
        if (roleNumber.Length > 4300) throw new ArgumentException("Role exceeds Python decimal serialization limit.");
        var payload = Payload(question);
        return new(key, Digest("[\"ark-role-v1\"," + roleNumber + "]"),
            Digest(payload), payload);
    }

    internal static string Payload(ArkQuestionSnapshot question)
    {
        ArgumentNullException.ThrowIfNull(question);
        if (question.Question == 0 || question.Options.IsDefault || question.Labels.IsDefault ||
            question.Options.Length != 4 || question.Labels.Length != 4 ||
            question.Options.Any(i => i == 0) || question.Options.Distinct().Count() != 4 ||
            !ValidText(question.Text, 32768) || question.Labels.Any(s => !ValidText(s, 32768)))
            throw new ArgumentException("Question requires an ID, exact text, and four distinct labeled options.");
        var output = new StringBuilder("{\"options\":[");
        bool first = true;
        foreach (var pair in question.Options.Zip(question.Labels).OrderBy(p => p.First))
        {
            if (!first) output.Append(',');
            first = false;
            output.Append('[').Append(pair.First.ToString(CultureInfo.InvariantCulture)).Append(',');
            Quote(output, pair.Second);
            output.Append(']');
        }
        output.Append("],\"question\":").Append(question.Question.ToString(CultureInfo.InvariantCulture)).Append(",\"text\":");
        Quote(output, question.Text);
        return output.Append('}').ToString();
    }

    internal static bool ValidMetadata(string? value) => ValidText(value, 1024) &&
        value == value!.Trim() && !value!.Any(c => c < 32 || c == 127);

    // Python len counts Unicode scalars, not UTF-16 code units. Python UTF-8 encoding
    // also rejects unpaired surrogates; do not silently replace them before hashing.
    private static bool ValidText(string? value, int maximum)
    {
        if (string.IsNullOrEmpty(value) || value.Length > maximum * 2) return false;
        int count = 0;
        for (int i = 0; i < value.Length; i++)
        {
            if (++count > maximum) return false;
            if (char.IsHighSurrogate(value[i]))
            {
                if (++i == value.Length || !char.IsLowSurrogate(value[i])) return false;
            }
            else if (char.IsLowSurrogate(value[i])) return false;
        }
        return true;
    }

    private static string Digest(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));

    private static void Quote(StringBuilder output, string value)
    {
        output.Append('"');
        foreach (char c in value)
            output.Append(c switch
            {
                '"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
                < ' ' => "\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture), _ => c.ToString()
            });
        output.Append('"');
    }
}
