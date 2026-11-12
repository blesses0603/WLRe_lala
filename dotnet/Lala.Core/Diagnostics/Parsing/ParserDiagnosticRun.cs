using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.Json;

namespace Lala.Core.Diagnostics.Parsing;

/// <summary>Thread-safe, bounded, in-memory report builder. Baselines are display-only, never trust inputs.</summary>
public sealed class ParserDiagnosticRun
{
    public const int MaxEntries = 128;
    public const int MaxReportBytes = 256 * 1024;
    public const int MaxInputs = 16;
    public const int MaxIdentities = 128;
    public const int MaxCoverageEntries = 128;
    private readonly object gate = new();
    private readonly List<ParserDiagnosticEvent> events = [];
    private readonly List<string> identities = [];
    private readonly Dictionary<string, string> coverage = new(StringComparer.Ordinal);
    private long droppedEvents;

    public ImmutableArray<ParserDiagnosticEvent> Events { get { lock (gate) return [.. events]; } }
    public long DroppedEvents { get { lock (gate) return droppedEvents; } }
    public bool AssetsReady => false;
    public bool CanSendPackets => false;

    internal void Record(ParserDiagnosticEvent observation)
    {
        lock (gate)
        {
            int existing = events.FindIndex(e => e.Definition.Parser == observation.Definition.Parser &&
                e.Variant == observation.Variant && SameInputs(e.Inputs, observation.Inputs));
            if (existing >= 0 && events[existing].Failed) return;
            observation = observation with { Identity = identities.LastOrDefault() };
            if (existing >= 0) events[existing] = observation;
            else events.Add(observation);
            if (events.Count > MaxEntries)
            {
                int victim = events.FindIndex(e => !e.Failed);
                events.RemoveAt(victim < 0 ? 0 : victim);
                droppedEvents++;
            }
        }
    }

    public void RecordIdentity(string identity)
    {
        if (!DiagnosticLabels.Digest(identity)) return;
        lock (gate)
            if (identities.Count < MaxIdentities && !identities.Contains(identity, StringComparer.Ordinal)) identities.Add(identity);
    }

    public void RecordCoverage(string codeOwnedName, string status)
    {
        if (!DiagnosticLabels.Name(codeOwnedName) || status is not ("passed" or "failed" or "not_available")) return;
        lock (gate)
        {
            bool exists = coverage.TryGetValue(codeOwnedName, out var old);
            if (old == "failed" || exists && status == "not_available" || !exists && coverage.Count >= MaxCoverageEntries) return;
            coverage[codeOwnedName] = status;
        }
    }

    /// <summary>
    /// Reads only supplied baseline bytes. Corrupt, oversized and invalid rows are ignored.
    /// Both outputs use Python's ASCII/sorted/default-spaced JSON representation and independent byte caps.
    /// No filesystem/default-path access, persistence, catalog activation, or packet authorization occurs.
    /// </summary>
    public ParserDiagnosticDocuments BuildReports(ReadOnlySpan<byte> priorBaseline = default,
        DateTimeOffset? checkedAtUtc = null, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var baseline = ParserDiagnosticJson.ReadBaseline(priorBaseline, cancellationToken);
        ParserDiagnosticEvent[] snapshot;
        string[] identitySnapshot;
        Dictionary<string, object?> coverageSnapshot;
        long dropped;
        lock (gate)
        {
            snapshot = [.. events];
            identitySnapshot = [.. identities.TakeLast(8)];
            coverageSnapshot = coverage.ToDictionary(p => p.Key, p => (object?)p.Value, StringComparer.Ordinal);
            dropped = droppedEvents;
        }
        var projected = new List<object?>();
        foreach (var observation in snapshot)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var row = Project(observation);
            baseline.TryGetValue(BaselineKey(observation), out var old);
            row["comparison"] = observation.Inputs.Count == 0 ? "input_unavailable" : old is null ? "no_baseline" :
                SameInputs(old.Inputs, observation.Inputs) ? "same_source" : "source_changed";
            if (old is not null)
            {
                row["schema_changed"] = observation.SelectedSchema is not null && old.SelectedSchema != observation.SelectedSchema;
                row["previous_success"] = old.Project();
                if (old.RecordCount is { } previousCount && observation.RecordCount is { } count)
                    row["record_count_delta"] = count - previousCount;
                row["size_delta"] = observation.Inputs.Where(p => old.Inputs.ContainsKey(p.Key))
                    .ToDictionary(p => p.Key, p => (object?)(new BigInteger(p.Value.Size) - old.Inputs[p.Key].Size), StringComparer.Ordinal);
            }
            projected.Add(row);
        }
        // All comparisons use the pre-session baseline; only then do successes update it.
        foreach (var observation in snapshot)
            if (!observation.Failed && observation.Inputs.Count > 0)
                baseline[BaselineKey(observation)] = new(observation.Definition.Schema, observation.SelectedSchema,
                    observation.Inputs, observation.RecordCount, observation.Identity);
        var latest = new Dictionary<string, object?>
        {
            ["schema_version"] = 1,
            ["checked_at_utc"] = (checkedAtUtc ?? DateTimeOffset.UtcNow).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'", CultureInfo.InvariantCulture),
            ["identities"] = identitySnapshot, ["parsers"] = projected, ["coverage"] = coverageSnapshot,
            ["dropped_events"] = dropped, ["assets_ready"] = false, ["can_send_packets"] = false
        };
        var lastSuccess = new Dictionary<string, object?>
        { ["parsers"] = baseline.TakeLast(MaxEntries).ToDictionary(p => p.Key, p => (object?)p.Value.Project(), StringComparer.Ordinal) };
        return new(ParserDiagnosticJson.Serialize(latest, cancellationToken), ParserDiagnosticJson.Serialize(lastSuccess, cancellationToken));
    }

    internal static Dictionary<string, object?> Project(ParserDiagnosticEvent value)
    {
        var row = new Dictionary<string, object?>
        {
            ["parser"] = value.Definition.Parser, ["schema"] = value.Definition.Schema,
            ["status"] = value.Failed ? "failed" : "passed", ["inputs"] = ProjectInputs(value.Inputs), ["identity"] = value.Identity
        };
        if (value.Variant is not null) row["variant"] = value.Variant;
        if (value.ErrorType is not null)
        {
            row["error_type"] = value.ErrorType;
            row["location"] = value.Location!.ToDictionary(p => p.Key, p => (object?)p.Value, StringComparer.Ordinal);
        }
        else { row["record_count"] = value.RecordCount; row["selected_schema"] = value.SelectedSchema; }
        return row;
    }
    internal static Dictionary<string, object?> ProjectInputs(ImmutableDictionary<string, ParserInputDigest> inputs) => inputs
        .ToDictionary(p => p.Key, p => (object?)new Dictionary<string, object?> { ["size"] = p.Value.Size, ["sha256"] = p.Value.Sha256 }, StringComparer.Ordinal);
    private static bool SameInputs(ImmutableDictionary<string, ParserInputDigest> a, ImmutableDictionary<string, ParserInputDigest> b) =>
        a.Count == b.Count && a.All(p => b.TryGetValue(p.Key, out var value) && value == p.Value);
    private static string BaselineKey(ParserDiagnosticEvent e) => e.Definition.Parser + ":" + (e.Variant ?? "default");
}

internal sealed record ParserBaseline(string Schema, string? SelectedSchema,
    ImmutableDictionary<string, ParserInputDigest> Inputs, BigInteger? RecordCount, string? Identity)
{
    internal Dictionary<string, object?> Project() => new()
    {
        ["schema"] = Schema, ["selected_schema"] = SelectedSchema, ["inputs"] = ParserDiagnosticRun.ProjectInputs(Inputs),
        ["record_count"] = RecordCount, ["identity"] = Identity
    };
}

internal static class ParserDiagnosticJson
{
    internal static Dictionary<string, ParserBaseline> ReadBaseline(ReadOnlySpan<byte> bytes, CancellationToken token)
    {
        var result = new Dictionary<string, ParserBaseline>(StringComparer.Ordinal);
        using var document = Read(bytes, token);
        if (document is null || document.RootElement.ValueKind != JsonValueKind.Object ||
            !document.RootElement.TryGetProperty("parsers", out var parsers) || parsers.ValueKind != JsonValueKind.Object) return result;
        // Python JSON dictionaries retain the first insertion position but use the last duplicate value.
        foreach (var item in parsers.EnumerateObject())
        {
            token.ThrowIfCancellationRequested();
            string name;
            try { name = item.Name; } catch (InvalidOperationException) { continue; }
            if (!DiagnosticLabels.BaselineKey(name)) continue;
            var finalValue = parsers.GetProperty(name);
            var row = ValidateBaseline(finalValue);
            if (row is not null) result[name] = row;
        }
        return result;
    }

    internal static ParserBaseline? ValidateBaseline(JsonElement row)
    {
        if (!Keys(row, "schema", "selected_schema", "inputs", "record_count", "identity")) return null;
        string? schema = Text(row.GetProperty("schema")), selected = Text(row.GetProperty("selected_schema"));
        if (!DiagnosticLabels.Schema(schema) || !DiagnosticLabels.Schema(selected)) return null;
        var countValue = row.GetProperty("record_count");
        BigInteger? count = null;
        if (countValue.ValueKind != JsonValueKind.Null)
        {
            if (!Integer(countValue, out var n) || n < 0 || n > 2147483648L) return null;
            count = n;
        }
        var identityValue = row.GetProperty("identity");
        string? identity = Text(identityValue);
        if (identityValue.ValueKind != JsonValueKind.Null && !DiagnosticLabels.Digest(identity)) return null;
        var inputObject = row.GetProperty("inputs");
        if (inputObject.ValueKind != JsonValueKind.Object) return null;
        var inputs = ImmutableDictionary.CreateBuilder<string, ParserInputDigest>(StringComparer.Ordinal);
        foreach (var property in inputObject.EnumerateObject())
        {
            string name;
            try { name = property.Name; } catch (InvalidOperationException) { return null; }
            var input = inputObject.GetProperty(name);
            if (!DiagnosticLabels.Name(name) || !Keys(input, "size", "sha256") ||
                !Integer(input.GetProperty("size"), out var size) || size < 0 || size > long.MaxValue) return null;
            string? digest = Text(input.GetProperty("sha256"));
            if (!DiagnosticLabels.Digest(digest)) return null;
            inputs[name] = new((long)size, digest!);
            if (inputs.Count > ParserDiagnosticRun.MaxInputs) return null;
        }
        return new(schema!, selected, inputs.ToImmutable(), count, identity);
    }

    internal static JsonDocument? Read(ReadOnlySpan<byte> bytes, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (bytes.IsEmpty || bytes.Length > ParserDiagnosticRun.MaxReportBytes) return null;
        try
        {
            // Match json.loads(bytes): BOM and zero-byte detection for UTF-8, UTF-16 and UTF-32.
            Encoding encoding = new UTF8Encoding(false, true);
            int skip = 0;
            if (bytes.StartsWith(new byte[] { 0, 0, 254, 255 })) { encoding = new UTF32Encoding(true, false, true); skip = 4; }
            else if (bytes.StartsWith(new byte[] { 255, 254, 0, 0 })) { encoding = new UTF32Encoding(false, false, true); skip = 4; }
            else if (bytes.StartsWith(new byte[] { 254, 255 })) { encoding = new UnicodeEncoding(true, false, true); skip = 2; }
            else if (bytes.StartsWith(new byte[] { 255, 254 })) { encoding = new UnicodeEncoding(false, false, true); skip = 2; }
            else if (bytes.StartsWith(new byte[] { 239, 187, 191 })) skip = 3;
            else if (bytes.Length >= 4)
            {
                if (bytes[0] == 0) encoding = bytes[1] == 0 ? new UTF32Encoding(true, false, true) : new UnicodeEncoding(true, false, true);
                else if (bytes[1] == 0) encoding = bytes[2] == 0 && bytes[3] == 0 ? new UTF32Encoding(false, false, true) : new UnicodeEncoding(false, false, true);
            }
            else if (bytes.Length == 2)
            {
                if (bytes[0] == 0) encoding = new UnicodeEncoding(true, false, true);
                else if (bytes[1] == 0) encoding = new UnicodeEncoding(false, false, true);
            }
            string text = ReplacePythonNonFinite(encoding.GetString(bytes[skip..]));
            var document = JsonDocument.Parse(text, new JsonDocumentOptions { MaxDepth = 64 });
            if (token.IsCancellationRequested) { document.Dispose(); token.ThrowIfCancellationRequested(); }
            return document;
        }
        catch (Exception error) when (error is JsonException or DecoderFallbackException or InvalidOperationException or ArgumentException) { return null; }
    }

    private static string ReplacePythonNonFinite(string text)
    {
        // Python's decoder accepts these constants even in ignored metadata. Represent as non-integer numbers.
        var output = new StringBuilder(text.Length);
        bool quoted = false, escaped = false;
        for (int i = 0; i < text.Length; i++)
        {
            char c = text[i];
            if (quoted)
            {
                output.Append(c);
                if (escaped) escaped = false;
                else if (c == '\\') escaped = true;
                else if (c == '"') quoted = false;
                continue;
            }
            if (c == '"') { quoted = true; output.Append(c); continue; }
            int length = text.AsSpan(i).StartsWith("-Infinity", StringComparison.Ordinal) ? 9 :
                text.AsSpan(i).StartsWith("Infinity", StringComparison.Ordinal) ? 8 :
                text.AsSpan(i).StartsWith("NaN", StringComparison.Ordinal) ? 3 : 0;
            bool startBoundary = i == 0 || " \t\r\n[:,{".Contains(text[i - 1]);
            bool endBoundary = i + length == text.Length || length > 0 && " \t\r\n,]}".Contains(text[i + length]);
            if (length > 0 && startBoundary && endBoundary) { output.Append("1e999"); i += length - 1; }
            else if (c == '-' || char.IsAsciiDigit(c))
            {
                int end = i + 1;
                while (end < text.Length && (char.IsAsciiDigit(text[end]) || text[end] is '.' or 'e' or 'E' or '+' or '-')) end++;
                var number = text.AsSpan(i, end - i);
                if (number.IndexOfAny('.', 'e', 'E') < 0 && number.Length - (c == '-' ? 1 : 0) > 4300)
                    throw new JsonException("Diagnostic integer exceeds the source decoder limit.");
                output.Append(number); i = end - 1;
            }
            else output.Append(c);
        }
        return output.ToString();
    }
    private static bool Keys(JsonElement value, params string[] keys)
    {
        if (value.ValueKind != JsonValueKind.Object) return false;
        try { return value.EnumerateObject().Select(p => p.Name).ToHashSet(StringComparer.Ordinal).SetEquals(keys); }
        catch (InvalidOperationException) { return false; }
    }
    private static string? Text(JsonElement value)
    {
        if (value.ValueKind != JsonValueKind.String) return null;
        try { return value.GetString(); } catch (InvalidOperationException) { return null; }
    }
    private static bool Integer(JsonElement value, out BigInteger result)
    {
        result = default;
        return value.ValueKind == JsonValueKind.Number && BigInteger.TryParse(value.GetRawText(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out result);
    }

    private sealed class LimitException : Exception;
    internal static ImmutableArray<byte> Serialize(object value, CancellationToken token)
    {
        var text = new StringBuilder();
        void Append(string piece)
        {
            if (piece.Length > ParserDiagnosticRun.MaxReportBytes - text.Length) throw new LimitException();
            text.Append(piece);
        }
        void Quote(string value)
        {
            Append("\"");
            foreach (char c in value)
                Append(c switch
                {
                    '"' => "\\\"", '\\' => "\\\\", '\b' => "\\b", '\f' => "\\f", '\n' => "\\n", '\r' => "\\r", '\t' => "\\t",
                    < ' ' or >= '\x7f' => "\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture), _ => c.ToString()
                });
            Append("\"");
        }
        void Write(object? item)
        {
            token.ThrowIfCancellationRequested();
            switch (item)
            {
                case null: Append("null"); break;
                case bool b: Append(b ? "true" : "false"); break;
                case string s: Quote(s); break;
                case BigInteger n:
                    // CPython's standard JSON integer limit is 4,300 decimal digits. Bound conversion too.
                    if (n.GetByteCount() > 1787) throw new LimitException();
                    string number = n.ToString(CultureInfo.InvariantCulture);
                    if (number.Length - (n.Sign < 0 ? 1 : 0) > 4300) throw new LimitException();
                    Append(number); break;
                case int n: Append(n.ToString(CultureInfo.InvariantCulture)); break;
                case long n: Append(n.ToString(CultureInfo.InvariantCulture)); break;
                case IReadOnlyDictionary<string, object?> map:
                    Append("{"); bool firstKey = true;
                    foreach (var pair in map.OrderBy(p => p.Key, StringComparer.Ordinal))
                    {
                        if (!firstKey) Append(", "); firstKey = false;
                        Quote(pair.Key); Append(": "); Write(pair.Value);
                    }
                    Append("}"); break;
                case IEnumerable<object?> list:
                    Append("["); bool firstItem = true;
                    foreach (var entry in list) { if (!firstItem) Append(", "); firstItem = false; Write(entry); }
                    Append("]"); break;
                default: throw new InvalidOperationException("Unsupported diagnostic value.");
            }
        }
        try { Write(value); return [.. Encoding.ASCII.GetBytes(text.ToString())]; }
        catch (LimitException) { return []; }
    }
}
