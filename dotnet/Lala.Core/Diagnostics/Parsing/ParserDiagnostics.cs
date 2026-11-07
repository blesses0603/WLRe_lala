using System.Collections.Immutable;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;

namespace Lala.Core.Diagnostics.Parsing;

/// <summary>
/// Optional in-memory instrumentation. No payload, result object, exception, or path is retained.
/// Labels must be code-owned. Nothing here selects a parser profile or enables a runtime.
/// </summary>
public static class ParserDiagnostics
{
    private sealed class Cursor
    {
        private readonly object gate = new();
        private ImmutableDictionary<string, object> fields = ImmutableDictionary<string, object>.Empty;
        internal void Set(string key, object value) { lock (gate) fields = fields.SetItem(key, value); }
        internal ImmutableDictionary<string, object> Snapshot() { lock (gate) return fields; }
    }
    private static readonly AsyncLocal<ParserDiagnosticRun?> CurrentRun = new();
    private static readonly AsyncLocal<Cursor?> CurrentCursor = new();
    // Weak keys do not prolong exception lifetime; values contain neither exception nor message.
    private static readonly ConditionalWeakTable<Exception, ParserDiagnosticEvent> Failures = new();
    private static readonly object FailureGate = new();

    public static bool IsActive => CurrentRun.Value is not null;

    /// <summary>Nested sessions share the current run. Dispose in LIFO order in the creating async context.</summary>
    public static ParserDiagnosticSession BeginSession()
    {
        var existing = CurrentRun.Value;
        var run = existing ?? new ParserDiagnosticRun();
        CurrentRun.Value = run;
        return new ParserDiagnosticSession(run, existing);
    }

    public sealed class ParserDiagnosticSession : IDisposable
    {
        private readonly ParserDiagnosticRun? previous;
        internal ParserDiagnosticSession(ParserDiagnosticRun run, ParserDiagnosticRun? previous) => (Run, this.previous) = (run, previous);
        public ParserDiagnosticRun Run { get; }
        public void Dispose()
        {
            // Context-local restoration, not a shared disposed bit, also works across Task.Run copies.
            if (ReferenceEquals(CurrentRun.Value, Run)) CurrentRun.Value = previous;
        }
    }

    public static void Checkpoint(BigInteger? offset = null, string? field = null, BigInteger? record = null,
        BigInteger? expected = null, BigInteger? actual = null, BigInteger? expectedMax = null,
        string? constraint = null, string? profile = null)
    {
        var cursor = CurrentCursor.Value;
        if (cursor is null) return;
        void Number(string key, BigInteger? value)
        { if (value is { } number && number >= 0 && number <= long.MaxValue) cursor.Set(key, number); }
        Number("offset", offset); Number("record", record); Number("expected", expected);
        Number("actual", actual); Number("expected_max", expectedMax);
        if (DiagnosticLabels.Profile(profile)) cursor.Set("profile", profile![..Math.Min(64, profile!.Length)]);
        if (DiagnosticLabels.Field(field)) cursor.Set("field", field![..Math.Min(64, field!.Length)]);
        if (DiagnosticLabels.Constraint(constraint)) cursor.Set("constraint", constraint!);
    }

    /// <summary>Python's read sizes allow arbitrary nonnegative integers; general positions stop at Int64.MaxValue.</summary>
    public static void ReadCheckpoint(BigInteger offset, BigInteger size, BigInteger available)
    {
        var cursor = CurrentCursor.Value;
        if (cursor is null) return;
        Checkpoint(offset: offset);
        if (size >= 0) cursor.Set("requested_bytes", size);
        if (available >= 0) cursor.Set("available_bytes", available);
    }

    public static void RecordIdentity(string identity) => CurrentRun.Value?.RecordIdentity(identity);
    public static void RecordCoverage(string codeOwnedName, string status) => CurrentRun.Value?.RecordCoverage(codeOwnedName, status);
    public static ParserDiagnosticEvent? GetFailure(Exception error) => Failures.TryGetValue(error, out var value) ? value : null;

    /// <summary>
    /// Parser runs exactly once. Successful results are not inspected outside a session or in a nested parser.
    /// Failure hashing is lazy outside sessions. Byte results without byte inputs use the textasset digest.
    /// Cancellation is cooperative and is propagated, never recorded as a layout/parser failure.
    /// sourceVariant/assetName/manifestPackage are optional whitelisted labels, never paths or decoded text.
    /// </summary>
    public static T Run<T>(ParserDiagnosticDefinition definition, IReadOnlyList<ParserDiagnosticInput> inputs,
        Func<T> parse, Func<T, ParserResultSummary>? summarize = null, string? sourceVariant = null,
        string? assetName = null, Func<T, string?>? manifestPackage = null, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(inputs);
        ArgumentNullException.ThrowIfNull(parse);
        return RunCore(definition, inputs, _ => parse(), DigestInputs, summarize,
            sourceVariant, assetName, manifestPackage, cancellationToken);
    }

    // Span entrypoints can reject oversized inputs without first copying them into memory.
    // Synchronous only: neither the span nor the callback enters an observation or escapes this call.
    internal static T RunWithRaw<T>(ParserDiagnosticDefinition definition, ReadOnlySpan<byte> raw,
        Func<ReadOnlySpan<byte>, T> parse, Func<T, ParserResultSummary> summarize,
        string? sourceVariant, CancellationToken cancellationToken, string inputName = "raw") =>
        RunCore<ReadOnlySpan<byte>, T>(definition, raw, parse,
            (bytes, token) => ImmutableDictionary<string, ParserInputDigest>.Empty.Add(inputName, Digest(bytes, token)),
            summarize, sourceVariant, null, null, cancellationToken);

    private static T RunCore<TInput, T>(ParserDiagnosticDefinition definition, TInput input,
        Func<TInput, T> parse,
        Func<TInput, CancellationToken, ImmutableDictionary<string, ParserInputDigest>> digestInputs,
        Func<T, ParserResultSummary>? summarize, string? sourceVariant, string? assetName,
        Func<T, string?>? manifestPackage, CancellationToken cancellationToken) where TInput : allows ref struct
    {
        cancellationToken.ThrowIfCancellationRequested();
        var run = CurrentRun.Value;
        var parent = CurrentCursor.Value;
        var cursor = new Cursor();
        CurrentCursor.Value = cursor;
        string? variant = sourceVariant is "EventData.NewNpc" or "EventData.NewInteract" ? sourceVariant : null;
        if (DiagnosticLabels.AssetVariant(assetName)) variant = assetName;
        try
        {
            T result;
            try { result = parse(input); }
            catch (OperationCanceledException) { throw; }
            catch (Exception error)
            {
                // An instrumentation failure must not replace the parser's original exception.
                try
                {
                    var digests = digestInputs(input, CancellationToken.None);
                    string errorType = error.GetType().Name;
                    if (!DiagnosticLabels.Name(errorType)) errorType = "Exception";
                    var observation = new ParserDiagnosticEvent(definition, digests, true, variant,
                        errorType: errorType, location: cursor.Snapshot());
                    lock (FailureGate) { Failures.Remove(error); Failures.Add(error, observation); }
                    run?.Record(observation);
                }
                catch (Exception diagnosticError) when (OptionalFailure(diagnosticError)) { }
                throw;
            }
            if (run is not null && parent is null)
            {
                cancellationToken.ThrowIfCancellationRequested();
                try
                {
                    var summary = summarize?.Invoke(result) ?? (result is State.StateValue value
                        ? ParserResultSummary.FromSourceValue(value) : new ParserResultSummary());
                    var digests = digestInputs(input, cancellationToken);
                    if (result is byte[] bytes && digests.Count == 0)
                        digests = digests.Add("textasset", Digest(bytes, cancellationToken));
                    var state = cursor.Snapshot();
                    var selected = state.TryGetValue("profile", out var profile) ? (string)profile : definition.Schema;
                    if (definition.Parser.EndsWith(".parse_manifest", StringComparison.Ordinal) && manifestPackage is not null)
                    {
                        var package = manifestPackage(result);
                        if (package is "MainPackage" or "DataPackage") variant = package;
                    }
                    run.Record(new ParserDiagnosticEvent(definition, digests, summary.Rejected, variant,
                        summary.RecordCount, selected));
                }
                catch (Exception diagnosticError) when (OptionalFailure(diagnosticError)) { }
            }
            return result;
        }
        finally { CurrentCursor.Value = parent; }
    }

    private static bool OptionalFailure(Exception error) => error is not OperationCanceledException and not OutOfMemoryException;
    internal static ImmutableDictionary<string, ParserInputDigest> DigestInputs(IReadOnlyList<ParserDiagnosticInput> inputs, CancellationToken cancellationToken)
    {
        if (inputs.Count > ParserDiagnosticRun.MaxInputs) throw new ArgumentException("Too many diagnostic inputs.");
        var result = ImmutableDictionary.CreateBuilder<string, ParserInputDigest>(StringComparer.Ordinal);
        foreach (var input in inputs)
        {
            if (!DiagnosticLabels.Name(input.Name)) throw new ArgumentException("Invalid code-owned input label.");
            result.Add(input.Name, Digest(input.Bytes.Span, cancellationToken));
        }
        return result.ToImmutable();
    }
    private static ParserInputDigest Digest(ReadOnlySpan<byte> bytes, CancellationToken cancellationToken)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        const int chunkSize = 64 * 1024;
        int size = bytes.Length;
        while (!bytes.IsEmpty)
        {
            cancellationToken.ThrowIfCancellationRequested();
            int count = Math.Min(chunkSize, bytes.Length);
            hash.AppendData(bytes[..count]);
            bytes = bytes[count..];
        }
        cancellationToken.ThrowIfCancellationRequested();
        return new(size, Convert.ToHexStringLower(hash.GetHashAndReset()));
    }
}
