using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Lala.Core.Storage;

namespace Lala.Core.Social.Ark;

/// <summary>Caller-observed version fields only, never proof of catalog authenticity or activation.</summary>
public sealed record ArkCandidatePackageObservation(string? Name, string? FullVersion, string? ManifestSha256);
public sealed record ArkCandidateVersionObservation(string? DataVersion,
    ImmutableArray<ArkCandidatePackageObservation> Packages);

/// <summary>Unconfirmed reviewed evidence. Even a user-reviewed candidate may be wrong and
/// grants no permission to answer, claim an attempt, persist evidence, or send a command.</summary>
public sealed record ArkCandidateDecision(uint? Answer, string Status, string Reason,
    string Source, string Revision)
{
    public override string ToString() => $"{nameof(ArkCandidateDecision)} ({Status})";
}

/// <summary>IDs and exact content digest only. Official question/option text is never bundled.</summary>
public sealed record ArkReviewedCandidate(uint Question, uint Answer, ImmutableArray<uint> Options, string Fingerprint);

/// <summary>Pure port of ark_candidates.py. The immutable built-in index is checked as a whole
/// before any lookup. No storage, receive reducer, execution, or runtime catalog activation.</summary>
public static class ArkReviewedCandidates
{
    private static readonly Lazy<ArkCandidateIndex> BuiltIn = new(() => new(ArkCandidateData.BuiltIn));
    public static ImmutableDictionary<uint, ArkReviewedCandidate> Index => BuiltIn.Value.Entries;
    public static ArkCandidateDecision Resolve(ArkQuestionSnapshot question, ArkCandidateVersionObservation? identity) =>
        BuiltIn.Value.Resolve(question, identity);
}

// Internal injection seam for retained-Python synthetic differential tests. Callers cannot
// replace the reviewed index, manufacture provenance, or bypass the built-in data digest.
internal sealed partial record ArkCandidateData(string DataVersion, string PackageVersion, string ManifestSha256,
    string TextSha256, string SourceSha256, string ReviewRevision, string IndexSha256,
    ImmutableArray<ArkReviewedCandidate> Questions, ImmutableDictionary<uint, string> Quarantined,
    ImmutableDictionary<uint, string> UserReviewed);

internal sealed class ArkCandidateIndex
{
    private const string BadContent = "候選題庫內容校驗失敗，請人工選答";
    private const string BadIndex = "候選題庫索引無效，請人工選答";
    private const string BadRange = "候選題庫範圍不完整，請人工選答";
    private static readonly ImmutableHashSet<uint> Expected = Enumerable.Range(0, 20).Select(n => 63901u + 5u * (uint)n)
        .Concat(Enumerable.Range(0, 180).Select(n => 103505u + 5u * (uint)n)).ToImmutableHashSet();
    private readonly ArkCandidateData data;
    internal ImmutableDictionary<uint, ArkReviewedCandidate> Entries { get; }

    internal ArkCandidateIndex(ArkCandidateData data)
    {
        ArgumentNullException.ThrowIfNull(data);
        if (!ValidAnnotations(data.Quarantined) || !ValidAnnotations(data.UserReviewed) || data.Questions.IsDefault ||
            ComputeDigest(data) != data.IndexSha256)
            throw new InvalidDataException(BadContent);
        var result = ImmutableDictionary.CreateBuilder<uint, ArkReviewedCandidate>();
        foreach (var entry in data.Questions)
        {
            if (entry is null || !Expected.Contains(entry.Question) || result.ContainsKey(entry.Question) ||
                entry.Options.IsDefault || entry.Options.Length != 4 || !entry.Options.Contains(entry.Answer) ||
                entry.Options.Any(i => i == 0) || entry.Options.Distinct().Count() != 4 ||
                entry.Fingerprint is not { Length: 64 } digest || digest.Any(c => !(c is >= '0' and <= '9' or >= 'a' and <= 'f')))
                throw new InvalidDataException(BadIndex);
            result.Add(entry.Question, entry);
        }
        if (!Expected.SetEquals(result.Keys) || !data.Quarantined.Keys.All(Expected.Contains) ||
            !data.UserReviewed.Keys.All(Expected.Contains) || data.UserReviewed.Keys.Any(data.Quarantined.ContainsKey))
            throw new InvalidDataException(BadRange);
        this.data = data;
        Entries = result.ToImmutable();
    }

    internal ArkCandidateDecision Resolve(ArkQuestionSnapshot question, ArkCandidateVersionObservation? identity)
    {
        ArgumentNullException.ThrowIfNull(question);
        ArkCandidateDecision Decision(uint? answer, string status, string reason = "", string source = "reviewed_import") =>
            // Python Decision captures its revision default when the source module is imported.
            new(answer, status, reason, source, ArkCandidateData.BuiltIn.ReviewRevision);
        // Preserve Python ordering: uncovered IDs do not inspect version or question text;
        // mismatched versions do not fingerprint even a malformed covered question.
        if (!Entries.TryGetValue(question.Question, out var entry)) return Decision(null, "not_covered");
        var packages = identity is not null && !identity.Packages.IsDefault
            ? identity.Packages.Where(p => p?.Name == "DataPackage").ToArray() : [];
        if (identity?.DataVersion != data.DataVersion || packages.Length != 1 ||
            packages[0].FullVersion != data.PackageVersion || packages[0].ManifestSha256 != data.ManifestSha256)
            return Decision(null, "version_mismatch", "候選庫尚未審核此官方資料版本");
        // This is fingerprint(question), independent of role/catalog token. Do not invent a
        // token or role just to call the persistence identity API.
        var actual = Digest(ArkQuestionIdentity.Payload(question));
        if (!question.Options.Order().SequenceEqual(entry.Options) || actual != entry.Fingerprint)
            return Decision(null, "changed", "題目或完整選項內容與審核版本不符");
        if (data.Quarantined.TryGetValue(question.Question, out var reason))
            return Decision(null, "quarantined", reason);
        if (data.UserReviewed.TryGetValue(question.Question, out reason))
            return Decision(entry.Answer, "candidate", reason, "user_reviewed");
        return Decision(entry.Answer, "candidate", "人工審核候選，尚未經伺服器確認，仍可能答錯");
    }

    private static bool ValidAnnotations(ImmutableDictionary<uint, string>? annotations) =>
        annotations is not null && annotations.Values.All(value => !string.IsNullOrEmpty(value));

    // Python ensure_ascii=False, sort_keys=True, compact separators. Integer dictionary
    // keys sort numerically BEFORE conversion to JSON strings. No Unicode normalization.
    internal static string ComputeDigest(ArkCandidateData data)
    {
        var output = new StringBuilder("{\"data_ver\":");
        Quote(output, data.DataVersion);
        output.Append(",\"manifest\":"); Quote(output, data.ManifestSha256);
        output.Append(",\"quarantined\":"); Annotations(output, data.Quarantined);
        output.Append(",\"questions\":[");
        if (data.Questions.IsDefault) throw new InvalidDataException(BadIndex);
        bool first = true;
        foreach (var row in data.Questions)
        {
            if (row is null || row.Options.IsDefault) throw new InvalidDataException(BadIndex);
            if (!first) output.Append(','); first = false;
            output.Append('[').Append(Number(row.Question)).Append(',').Append(Number(row.Answer)).Append(",[")
                .AppendJoin(',', row.Options.Select(Number)).Append("],");
            Quote(output, row.Fingerprint); output.Append(']');
        }
        output.Append("],\"revision\":"); Quote(output, data.ReviewRevision);
        output.Append(",\"source\":"); Quote(output, data.SourceSha256);
        output.Append(",\"text\":"); Quote(output, data.TextSha256);
        output.Append(",\"user_reviewed\":"); Annotations(output, data.UserReviewed);
        output.Append(",\"version\":"); Quote(output, data.PackageVersion);
        return Digest(output.Append('}').ToString());
    }

    private static string Number(uint value) => value.ToString(CultureInfo.InvariantCulture);
    private static string Digest(string value) => Convert.ToHexStringLower(SHA256.HashData(new UTF8Encoding(false, true).GetBytes(value)));
    private static void Annotations(StringBuilder output, ImmutableDictionary<uint, string> values)
    {
        output.Append('{'); bool first = true;
        foreach (var (id, value) in values.OrderBy(p => p.Key))
        {
            if (!first) output.Append(','); first = false;
            Quote(output, Number(id)); output.Append(':'); Quote(output, value);
        }
        output.Append('}');
    }
    private static void Quote(StringBuilder output, string? value)
    {
        if (value is null) { output.Append("null"); return; }
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
