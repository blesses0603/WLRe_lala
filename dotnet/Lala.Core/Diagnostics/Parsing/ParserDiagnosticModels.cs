using System.Collections.Immutable;
using System.Numerics;
using System.Text.RegularExpressions;
using Lala.Core.State;

namespace Lala.Core.Diagnostics.Parsing;

/// <summary>Code-owned identifiers only. Never construct these labels from resource text or paths.</summary>
public sealed record ParserDiagnosticDefinition
{
    public ParserDiagnosticDefinition(string parser, string schema)
    {
        if (!DiagnosticLabels.Parser(parser) || !DiagnosticLabels.Schema(schema))
            throw new ArgumentException("Invalid code-owned parser diagnostic identifier.");
        Parser = parser;
        Schema = schema;
    }
    public string Parser { get; }
    public string Schema { get; }
}

/// <summary>Transient borrowed input. Only its size and SHA-256 can enter a diagnostic event.</summary>
public readonly record struct ParserDiagnosticInput(string Name, ReadOnlyMemory<byte> Bytes);
public sealed record ParserInputDigest(long Size, string Sha256);

/// <summary>Display-only summary, not a layout selection or an authorization decision.</summary>
public sealed record ParserResultSummary(BigInteger? RecordCount = null, bool Rejected = false)
{
    /// <summary>Matches Python's exact list/tuple/dict count precedence, including negative integer counts.</summary>
    public static ParserResultSummary FromSourceValue(StateValue value)
    {
        BigInteger? count = null;
        bool rejected = false;
        if (value.Kind == StateValueKind.List) count = value.SequenceValue.Length;
        else if (value.Kind == StateValueKind.Tuple)
        {
            if (value.SequenceValue.Length == 2 && value[1].Kind == StateValueKind.List)
                count = value[1].SequenceValue.Length;
        }
        else if (value.Kind == StateValueKind.Map)
        {
            var map = value.MapValue;
            rejected = map.TryGetValue("status", out var status) && status.Kind == StateValueKind.Scalar &&
                status.ScalarValue is string text && text is "layout_unrecognized" or "unsupported_table";
            foreach (var key in new[] { "record_count", "task_count", "asset_count", "scene_count" })
                if (map.TryGetValue(key, out var item) && DiagnosticLabels.Integer(item, out var integer))
                { count = integer; break; }
            if (count is null)
                foreach (var key in new[] { "tasks", "records" })
                    if (map.TryGetValue(key, out var item) && item.Kind is StateValueKind.List or StateValueKind.Map)
                    { count = item.Kind == StateValueKind.List ? item.SequenceValue.Length : item.MapValue.Count; break; }
            count ??= map.Count;
        }
        return new(count, rejected);
    }
}

/// <summary>Deeply immutable, payload-free observation. Cannot authorize resource or runtime use.</summary>
public sealed record ParserDiagnosticEvent
{
    internal ParserDiagnosticEvent(ParserDiagnosticDefinition definition,
        ImmutableDictionary<string, ParserInputDigest> inputs, bool failed, string? variant = null,
        BigInteger? recordCount = null, string? selectedSchema = null, string? errorType = null,
        ImmutableDictionary<string, object>? location = null)
    {
        Definition = definition;
        Inputs = inputs;
        Failed = failed;
        Variant = variant;
        RecordCount = recordCount;
        SelectedSchema = selectedSchema;
        ErrorType = errorType;
        Location = location;
    }
    public ParserDiagnosticDefinition Definition { get; }
    public ImmutableDictionary<string, ParserInputDigest> Inputs { get; }
    public bool Failed { get; }
    public string? Variant { get; }
    public BigInteger? RecordCount { get; }
    public string? SelectedSchema { get; }
    public string? ErrorType { get; }
    public ImmutableDictionary<string, object>? Location { get; }
    public string? Identity { get; internal init; }
}

/// <summary>Each document is independently empty when its 256 KiB serialization limit was exceeded.</summary>
public sealed record ParserDiagnosticDocuments(ImmutableArray<byte> Latest, ImmutableArray<byte> LastSuccess)
{
    public bool AssetsReady => false;
    public bool CanSendPackets => false;
}

internal static class DiagnosticLabels
{
    private static bool Match(string? value, string pattern) => value is not null &&
        Regex.IsMatch(value, "\\A(?:" + pattern + ")\\z", RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);
    internal static bool Parser(string? value) => Match(value, "[a-zA-Z0-9_.:]{1,120}");
    internal static bool Schema(string? value) => Match(value, "[a-zA-Z0-9.-]{1,80}");
    internal static bool BaselineKey(string? value) => Match(value, "[a-zA-Z0-9_.:-]{1,200}");
    internal static bool Name(string? value) => Match(value, "[a-zA-Z_][a-zA-Z_0-9]{0,63}");
    internal static bool Digest(string? value) => Match(value, "[0-9a-f]{64}");
    internal static bool Profile(string? value) => value is not null && value.Length > 0 &&
        value.All(c => char.IsAsciiLetterOrDigit(c) || c == '-') && value.Any(char.IsAsciiLetterOrDigit);
    internal static bool Field(string? value) => value is not null && value.Length > 0 &&
        value.All(c => char.IsAsciiLetterOrDigit(c) || c == '_') && value.Any(char.IsAsciiLetterOrDigit);
    internal static bool Constraint(string? value) => Match(value, "[a-z0-9_]{1,64}");
    internal static bool AssetVariant(string? value) => Match(value, "[a-zA-Z0-9_]{1,64}\\.bytes");
    internal static bool Integer(StateValue value, out BigInteger result)
    {
        object? scalar = value.Kind == StateValueKind.Scalar ? value.ScalarValue : null;
        result = scalar switch
        {
            BigInteger b => b, sbyte b => b, byte b => b, short b => b, ushort b => b,
            int b => b, uint b => b, long b => b, ulong b => b, _ => default
        };
        return scalar is BigInteger or sbyte or byte or short or ushort or int or uint or long or ulong;
    }
}
