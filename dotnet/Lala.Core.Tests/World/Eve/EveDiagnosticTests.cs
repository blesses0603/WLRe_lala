using System.Numerics;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Diagnostics.Parsing;
using Xunit;

namespace Lala.Core.Tests.World.Eve;

using Lala.Core.World.Eve;

public sealed class EveDiagnosticTests
{
    private const string SingleParser = "wlre.services.world.eve_v115.derive_eve_index";
    private const string BothParser = "wlre.services.world.eve_v115.derive_eve_indexes";
    private static readonly ParserDiagnosticDefinition Parent = new("synthetic.parent", "parent-v1");

    [Theory]
    [MemberData(nameof(EveDiagnosticPythonVectors.Cases), MemberType = typeof(EveDiagnosticPythonVectors), DisableDiscoveryEnumeration = true)]
    public void Direct_typed_and_serialized_calls_match_actual_python_decorators(string name, int fixtureIndex, int rowIndex, int observationIndex)
    {
        var row = EvePythonVectors.ReadCase(fixtureIndex, rowIndex);
        Assert.Equal(name, row.GetProperty("name").GetString());
        var expected = EveDiagnosticPythonVectors.ReadExpected(fixtureIndex, rowIndex, observationIndex);
        var raw = Raw(row);
        string? source = row.GetProperty("source").GetString();
        foreach (bool serialized in new[] { false, true })
        {
            using var session = ParserDiagnostics.BeginSession();
            EveDecodeException? error = null;
            try { Invoke(raw, source, serialized); }
            catch (EveDecodeException caught) { error = caught; }
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(source is null ? BothParser : SingleParser, observation.Definition.Parser);
            Assert.Equal("eve-v115", observation.Definition.Schema);
            if (row.GetProperty("divergence").GetBoolean())
            {
                // Retained source silently overwrites duplicate scenes. Keep the safer C# rejection.
                Assert.Equal("duplicate-scene-override-source-bug", name);
                Assert.Equal("passed", expected.GetProperty("status").GetString());
                Assert.NotNull(error);
                Assert.Equal("Duplicate scene ID or out-of-bounds offset", error.Message);
                Assert.True(observation.Failed);
                Assert.Equal("scene_header", observation.Location!["field"]);
                Assert.Equal(new BigInteger(24), observation.Location["offset"]);
                Assert.Equal(new BigInteger(2), observation.Location["record"]);
                Assert.Equal(expected.GetProperty("inputs").GetProperty("raw").GetProperty("sha256").GetString(), observation.Inputs["raw"].Sha256);
                continue;
            }
            var sourceEvent = JsonNode.Parse(expected.GetRawText())!;
            if (sourceEvent["error_type"] is not null)
            {
                // The C# API keeps its already-public exception type; labels name that actual type.
                Assert.Equal("EveDecodeError", sourceEvent["error_type"]!.GetValue<string>());
                sourceEvent["error_type"] = nameof(EveDecodeException);
                Assert.NotNull(error);
                Assert.Equal(row.GetProperty("error").GetString(), error.Message);
                Assert.Null(error.InnerException);
                Assert.Equal(observation, ParserDiagnostics.GetFailure(error));
            }
            else Assert.Null(error);
            var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observation), default).AsSpan());
            Assert.True(JsonNode.DeepEquals(sourceEvent, actual), name + ": " + actual);
        }
    }

    [Fact]
    public void Observations_are_tied_to_the_current_retained_sources_and_full_corpus()
    {
        Assert.Equal(EvePythonVectors.VectorCount, EveDiagnosticPythonVectors.VectorCount);
        var cases = EveDiagnosticPythonVectors.Cases().ToArray();
        Assert.Equal(EveDiagnosticPythonVectors.VectorCount, cases.Length);
        for (int index = 0; index < cases.Length; index++)
        {
            var identifiers = cases[index];
            Assert.Equal(4, identifiers.Length);
            Assert.InRange(Assert.IsType<string>(identifiers[0]).Length, 1, 80);
            int fixtureIndex = Assert.IsType<int>(identifiers[1]);
            int rowIndex = Assert.IsType<int>(identifiers[2]);
            Assert.Equal(index, Assert.IsType<int>(identifiers[3]));
            // Preserve the full name/source/count alignment check without passing JSON to xUnit.
            _ = EveDiagnosticPythonVectors.ReadExpected(fixtureIndex, rowIndex, index);
        }
        foreach (var (path, expected) in new[]
        {
            ("wlre/services/world/eve_v115.py", EveDiagnosticPythonVectors.EveSourceSha256),
            ("wlre/services/parser_diagnostics.py", EveDiagnosticPythonVectors.DiagnosticsSourceSha256)
        })
        {
            byte[] bytes = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
            using var normalized = new MemoryStream();
            for (int i = 0; i < bytes.Length; i++)
                if (bytes[i] != 13 || i + 1 == bytes.Length || bytes[i + 1] != 10) normalized.WriteByte(bytes[i]);
            Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
        }
    }

    [Fact]
    public void No_session_success_is_quiet_and_failure_is_attached_without_changing_error()
    {
        Assert.False(ParserDiagnostics.IsActive);
        byte[] raw = Fixture("basic");
        var parsed = EveV115Parser.Parse(raw);
        Assert.Equal(1, parsed.NpcRecordCount);
        Assert.Equal(parsed.ToJsonUtf8(EveV115Parser.NpcSource).ToArray(), EveV115Parser.DeriveIndex(raw, EveV115Parser.NpcSource).ToArray());
        var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(Fixture("invalid-form-0")));
        var failure = Assert.IsType<ParserDiagnosticEvent>(ParserDiagnostics.GetFailure(error));
        Assert.Equal(BothParser, failure.Definition.Parser);
        Assert.True(failure.Failed);
        Assert.Equal(nameof(EveDecodeException), failure.ErrorType);
        Assert.Equal("scene", failure.Location!["field"]);
        Assert.False(ParserDiagnostics.IsActive);
        using var fresh = ParserDiagnostics.BeginSession();
        Assert.Empty(fresh.Run.Events);
    }

    [Fact]
    public void Nested_sessions_share_events_and_outer_parsers_suppress_child_success_only()
    {
        using var session = ParserDiagnostics.BeginSession();
        using (var nested = ParserDiagnostics.BeginSession())
        {
            Assert.Same(session.Run, nested.Run);
            EveV115Parser.Parse(Fixture("basic"));
        }
        Assert.Single(session.Run.Events);
        var original = new object();
        var returned = ParserDiagnostics.Run(Parent, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 9, field: "outer", profile: "parent-v2");
            EveV115Parser.DeriveIndex(Fixture("basic"), EveV115Parser.NpcSource);
            var failure = Assert.Throws<EveDecodeException>(() => EveV115Parser.DeriveIndex(Fixture("invalid-form-0"), EveV115Parser.InteractionSource));
            Assert.Equal(SingleParser, ParserDiagnostics.GetFailure(failure)!.Definition.Parser);
            return original;
        });
        Assert.Same(original, returned);
        Assert.Equal(3, session.Run.Events.Length);
        Assert.True(session.Run.Events[1].Failed);
        Assert.Equal(EveV115Parser.InteractionSource, session.Run.Events[1].Variant);
        Assert.Equal("parent-v2", session.Run.Events[2].SelectedSchema);
        Assert.DoesNotContain(session.Run.Events, e => e.Variant == EveV115Parser.NpcSource);
    }

    [Fact]
    public void Rethrown_child_failure_preserves_exception_identity_and_restores_parent_cursor()
    {
        using var session = ParserDiagnostics.BeginSession();
        EveDecodeException? caught = null;
        var error = Assert.Throws<EveDecodeException>(() => ParserDiagnostics.Run<int>(Parent, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
            try { EveV115Parser.Parse(Fixture("invalid-form-0")); }
            catch (EveDecodeException child) { caught = child; throw; }
            return 0;
        }));
        Assert.Same(caught, error);
        Assert.Equal(2, session.Run.Events.Length);
        Assert.Equal(BothParser, session.Run.Events[0].Definition.Parser);
        Assert.Equal("scene", session.Run.Events[0].Location!["field"]);
        Assert.Equal(Parent, ParserDiagnostics.GetFailure(error)!.Definition);
        Assert.Equal(new BigInteger(7), ParserDiagnostics.GetFailure(error)!.Location!["offset"]);
        Assert.Equal("outer", session.Run.Events[1].Location!["field"]);
    }

    [Fact]
    public void Span_runner_keeps_result_and_exception_identity_and_success_is_lazy_without_session()
    {
        Assert.False(ParserDiagnostics.IsActive);
        var original = new object();
        Assert.Same(original, ParserDiagnostics.RunWithRaw(Parent, [], _ => original,
            _ => throw new InvalidOperationException("must not summarize"), null, default));
        var originalError = new InvalidDataException("message must not be retained");
        var error = Assert.Throws<InvalidDataException>(() => ParserDiagnostics.RunWithRaw<int>(Parent, [1, 2],
            _ => throw originalError, _ => new(), null, default));
        Assert.Same(originalError, error);
        Assert.Equal(2, ParserDiagnostics.GetFailure(error)!.Inputs["raw"].Size);
        Assert.False(ParserDiagnostics.IsActive);
    }

    [Fact]
    public async Task Independent_concurrent_entrypoints_do_not_leak_sessions_or_cursors()
    {
        var runs = await Task.WhenAll(Enumerable.Range(0, 12).Select(index => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            byte[] raw = Fixture("basic");
            raw[0] = (byte)index;
            EveV115Parser.DeriveIndexes(raw);
            var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw, "unknown"));
            var success = session.Run.Events[0];
            var failure = session.Run.Events[1];
            Assert.Equal(success.Inputs["raw"], failure.Inputs["raw"]);
            Assert.Equal(failure, ParserDiagnostics.GetFailure(error));
            Assert.Empty(failure.Location!);
            return session.Run;
        })));
        Assert.Equal(12, runs.Distinct().Count());
        Assert.Equal(12, runs.Select(run => run.Events[0].Inputs["raw"].Sha256).Distinct().Count());
        Assert.False(ParserDiagnostics.IsActive);
    }

    [Fact]
    public void All_entrypoints_propagate_cancellation_without_layout_failure_or_partial_success()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        byte[] raw = Fixture("basic");
        foreach (var parse in new Action[]
        {
            () => EveV115Parser.Parse(raw, cancelled.Token),
            () => EveV115Parser.Parse(raw, EveV115Parser.NpcSource, cancelled.Token),
            () => EveV115Parser.DeriveIndexes(raw, cancelled.Token),
            () => EveV115Parser.DeriveIndex(raw, EveV115Parser.InteractionSource, cancelled.Token),
            () => EveV115Parser.Parse([], cancelled.Token),
            () => EveV115Parser.Parse(new byte[EveV115Parser.MaxSourceBytes + 1], cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(parse);
            Assert.Equal(cancelled.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
        // Also exercise cancellation between parser return and diagnostic summarization/hashing.
        using var during = new CancellationTokenSource();
        Assert.Throws<OperationCanceledException>(() => ParserDiagnostics.RunWithRaw(Parent, raw, _ =>
        { during.Cancel(); return 5; }, count => new(count), null, during.Token));
        Assert.Empty(session.Run.Events);
        EveV115Parser.Parse(raw);
        Assert.Single(session.Run.Events); // The cancelled cursor was restored.
    }

    [Fact]
    public void Caller_owned_spans_are_detached_and_only_current_input_digests_enter_reports()
    {
        using var session = ParserDiagnostics.BeginSession();
        var raw = Fixture("basic");
        byte[] envelope = new byte[raw.Length + 32];
        raw.CopyTo(envelope, 16);
        var parsed = EveV115Parser.Parse(envelope.AsSpan(16, raw.Length));
        var first = Assert.Single(session.Run.Events);
        Assert.Equal(raw.Length, first.Inputs["raw"].Size);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), first.Inputs["raw"].Sha256);
        Array.Fill(envelope, (byte)255);
        Assert.Equal(9001u, parsed.Scenes[0].Npcs[0].NpcId);
        raw[0] ^= 1; // Ignored source bytes still change the digest, not the parse result.
        EveV115Parser.Parse(raw);
        Assert.Equal(2, session.Run.Events.Length);
        Assert.NotEqual(first.Inputs["raw"], session.Run.Events[1].Inputs["raw"]);
        raw = Fixture("invalid-form-0");
        string failureDigest = Convert.ToHexStringLower(SHA256.HashData(raw));
        var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.DeriveIndex(raw, "secret/path\n"));
        Array.Fill(raw, (byte)0);
        var failure = ParserDiagnostics.GetFailure(error)!;
        Assert.Equal(failureDigest, failure.Inputs["raw"].Sha256);
        Assert.Null(failure.Variant);
        string json = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("secret", json);
        Assert.DoesNotContain("IGNORED", json);
        Assert.DoesNotContain("Unknown requested", json);
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Fact]
    public void Oversized_failure_is_hashed_without_allocating_an_oversized_snapshot()
    {
        using var session = ParserDiagnostics.BeginSession();
        Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse([])); // Warm diagnostic statics.
        byte[] raw = new byte[EveV115Parser.MaxSourceBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 100_000);
        var failure = ParserDiagnostics.GetFailure(error)!;
        Assert.Equal(raw.Length, failure.Inputs["raw"].Size);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), failure.Inputs["raw"].Sha256);
        Assert.Empty(failure.Location!);
    }

    [Fact]
    public void Neither_success_nor_failure_diagnostics_keep_caller_input_alive()
    {
        using var session = ParserDiagnostics.BeginSession();
        var (input, result, error) = RunAndReleaseInput();
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        Assert.False(input.IsAlive);
        Assert.Equal(9001u, result.Scenes[0].Npcs[0].NpcId);
        Assert.NotNull(ParserDiagnostics.GetFailure(error));
        Assert.Equal(2, session.Run.Events.Length);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static (WeakReference Input, EveV115Indexes Result, EveDecodeException Error) RunAndReleaseInput()
    {
        byte[] raw = Fixture("basic");
        var result = EveV115Parser.Parse(raw);
        var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw, "private/path"));
        return (new WeakReference(raw), result, error);
    }

    private static void Invoke(byte[] raw, string? source, bool serialized)
    {
        if (serialized)
        {
            if (source is null) EveV115Parser.DeriveIndexes(raw);
            else EveV115Parser.DeriveIndex(raw, source);
        }
        else if (source is null) EveV115Parser.Parse(raw);
        else EveV115Parser.Parse(raw, source);
    }
    private static byte[] Raw(JsonElement row)
    {
        var raw = Convert.FromBase64String(row.GetProperty("raw").GetString()!);
        Array.Resize(ref raw, raw.Length + row.GetProperty("zero_padding").GetInt32());
        return raw;
    }
    private static byte[] Fixture(string name)
    {
        var identifiers = EvePythonVectors.Cases().First(row => (string)row[0] == name);
        return Raw(EvePythonVectors.ReadCase((int)identifiers[1], (int)identifiers[2]));
    }
}
