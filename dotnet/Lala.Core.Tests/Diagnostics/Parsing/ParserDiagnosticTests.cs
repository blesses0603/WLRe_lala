using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.State;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Diagnostics.Parsing;

public sealed class ParserDiagnosticTests
{
    private static readonly ParserDiagnosticDefinition Definition = new("synthetic.parse", "schema-v1");
    private static readonly DateTimeOffset Now = new(2026, 11, 7, 1, 2, 3, TimeSpan.Zero);
    private sealed class ValueError(string message) : Exception(message);

    [Theory]
    [MemberData(nameof(ParserDiagnosticPythonVectors.Cases), MemberType = typeof(ParserDiagnosticPythonVectors))]
    public void ExactPythonDifferential(string kind, string name, string json)
    {
        var row = JsonNode.Parse(json)!;
        var data = row["data"];
        var expected = row["expected"];
        switch (kind)
        {
            case "baseline":
                using (var doc = JsonDocument.Parse(data!.ToJsonString()))
                    Assert.Equal(expected!.GetValue<bool>(), ParserDiagnosticJson.ValidateBaseline(doc.RootElement) is not null);
                break;
            case "checkpoint":
            case "read":
                var exception = Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(Definition, [], () =>
                {
                    ApplyCheckpoint(data!["initial"]!);
                    if (data["initial"]!["requested_bytes"] is { } requested)
                        ParserDiagnostics.ReadCheckpoint(-1, Number(requested) ?? -1, -1);
                    if (kind == "checkpoint") ApplyCheckpoint(data["changes"]!);
                    else ParserDiagnostics.ReadCheckpoint(Number(data["offset"]) ?? -1, Number(data["size"]) ?? -1, Number(data["available"]) ?? -1);
                    throw new ValueError("synthetic discarded message");
                }));
                AssertJson(expected, ParserDiagnosticJson.Serialize(ParserDiagnostics.GetFailure(exception)!.Location!
                    .ToDictionary(p => p.Key, p => (object?)p.Value), default), name);
                break;
            case "count":
                var summary = ParserResultSummary.FromSourceValue(Value(data));
                Assert.Equal(Number(expected!["count"]), summary.RecordCount);
                Assert.Equal(expected["rejected"]!.GetValue<bool>(), summary.Rejected);
                break;
            case "wrapped":
                CheckWrapped(name, expected!);
                break;
            case "run":
                var run = new ParserDiagnosticRun();
                foreach (var step in data!["actions"]!.AsArray())
                {
                    if (step!["event"] is { } e) run.Record(Event(e));
                    else if (step["identity"] is { } identity) run.RecordIdentity(identity.GetValue<string>());
                    else foreach (var pair in step["coverage"]!.AsObject()) run.RecordCoverage(pair.Key, pair.Value!.GetValue<string>());
                }
                var reports = run.BuildReports(Convert.FromBase64String(data["prior"]!.GetValue<string>()), Now);
                AssertBytes(expected!["latest"], reports.Latest, name + " latest");
                AssertBytes(expected["baseline"], reports.LastSuccess, name + " baseline");
                Assert.False(run.AssetsReady); Assert.False(run.CanSendPackets);
                Assert.False(reports.AssetsReady); Assert.False(reports.CanSendPackets);
                break;
            default: Assert.Fail(kind); break;
        }
    }

    [Fact]
    public void SourceDigestNormalizesCrLfBytesOnly()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "wlre/services/parser_diagnostics.py"))) directory = directory.Parent;
        Assert.NotNull(directory);
        byte[] bytes = File.ReadAllBytes(Path.Combine(directory.FullName, "wlre/services/parser_diagnostics.py"));
        using var normalized = new MemoryStream();
        for (int i = 0; i < bytes.Length; i++)
            if (bytes[i] != 13 || i + 1 == bytes.Length || bytes[i + 1] != 10) normalized.WriteByte(bytes[i]);
        Assert.Equal(ParserDiagnosticPythonVectors.SourceSha256, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void SuccessfulCallsOutsideSessionRemainLazyAndPreserveResultIdentity()
    {
        var original = new object();
        int calls = 0;
        var result = ParserDiagnostics.Run(Definition, new PoisonInputList(), () => { calls++; return original; }, _ => throw new Exception("must not inspect"));
        Assert.Same(original, result); Assert.Equal(1, calls); Assert.False(ParserDiagnostics.IsActive);
    }

    [Fact]
    public void FailurePreservesExceptionIdentityAndContainsOnlyDigestsAndWhitelistedCheckpoints()
    {
        byte[] raw = Encoding.UTF8.GetBytes("SECRET_RESOURCE_CONTENT");
        var error = new ValueError("secret exception message and /private/files/path");
        Assert.Same(error, Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(Definition, [new("raw", raw)], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 9, field: "record_length", profile: "profile-v2", constraint: "even_length");
            ParserDiagnostics.Checkpoint(field: "/private/file", profile: "secret/value", constraint: "UPPER");
            ParserDiagnostics.ReadCheckpoint(9, 12, 2);
            throw error;
        })));
        var failure = ParserDiagnostics.GetFailure(error)!;
        Assert.Equal("ValueError", failure.ErrorType);
        Assert.Equal(9, (BigInteger)failure.Location!["offset"]);
        Assert.Equal("record_length", failure.Location["field"]);
        Assert.Equal(raw.Length, failure.Inputs["raw"].Size);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), failure.Inputs["raw"].Sha256);
        string json = Encoding.UTF8.GetString(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(failure), default).AsSpan());
        Assert.DoesNotContain("SECRET", json); Assert.DoesNotContain("private", json); Assert.DoesNotContain("exception message", json);
        Array.Fill(raw, (byte)0); // The diagnostic owns no source bytes.
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes("SECRET_RESOURCE_CONTENT"))), failure.Inputs["raw"].Sha256);
    }

    [Fact]
    public void NestedSessionsAndNestedParsersRetainSwallowedFailuresButSuppressChildSuccesses()
    {
        ParserDiagnosticRun run;
        using (var outer = ParserDiagnostics.BeginSession())
        {
            run = outer.Run;
            using (var nested = ParserDiagnostics.BeginSession()) Assert.Same(run, nested.Run);
            ParserDiagnostics.Run(Definition, [new("raw", new byte[] { 1 })], () =>
            {
                ParserDiagnostics.Checkpoint(profile: "parent-v1");
                ParserDiagnostics.Run(new("synthetic.child_ok", "child-v1"), [], () => 3, _ => throw new Exception("nested summaries are lazy"));
                var error = Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(new("synthetic.child_bad", "child-v1"), [], () =>
                { ParserDiagnostics.Checkpoint(field: "header", offset: 7); throw new ValueError("not retained"); }));
                Assert.Equal("header", ParserDiagnostics.GetFailure(error)!.Location!["field"]);
                return StateValue.Map(("status", StateValue.Scalar("layout_unrecognized")));
            });
            Assert.Equal(2, run.Events.Length);
            Assert.All(run.Events, e => Assert.True(e.Failed));
            Assert.Equal("parent-v1", run.Events[1].SelectedSchema);
        }
        Assert.False(ParserDiagnostics.IsActive);
        using var fresh = ParserDiagnostics.BeginSession();
        Assert.Empty(fresh.Run.Events); Assert.NotSame(run, fresh.Run);
    }

    [Fact]
    public void FailureAssociationTracksRethrownExceptionLikePythonOuterWrapper()
    {
        using var session = ParserDiagnostics.BeginSession();
        var error = Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(Definition, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 2);
            return ParserDiagnostics.Run<int>(new("synthetic.child", "child-v1"), [], () =>
            { ParserDiagnostics.Checkpoint(offset: 4); throw new ValueError("not retained"); });
        }));
        Assert.Equal(Definition, ParserDiagnostics.GetFailure(error)!.Definition);
        Assert.Equal(2, (BigInteger)ParserDiagnostics.GetFailure(error)!.Location!["offset"]);
        Assert.Equal(2, session.Run.Events.Length);
        Assert.Equal(4, (BigInteger)session.Run.Events[0].Location!["offset"]);
    }

    [Fact]
    public async Task SeparateConcurrentSessionsAndSharedConcurrentRunKeepCursorIsolation()
    {
        var separate = await Task.WhenAll(Enumerable.Range(0, 24).Select(i => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            var error = Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(Definition, [], () =>
            { ParserDiagnostics.Checkpoint(offset: i); throw new ValueError("not retained"); }));
            Assert.Equal(i, (BigInteger)ParserDiagnostics.GetFailure(error)!.Location!["offset"]);
            return session.Run;
        })));
        Assert.Equal(24, separate.Distinct().Count()); Assert.False(ParserDiagnostics.IsActive);
        using var shared = ParserDiagnostics.BeginSession();
        await Task.WhenAll(Enumerable.Range(0, 96).Select(i => Task.Run(() =>
            ParserDiagnostics.Run(new("synthetic.concurrent_" + i, "schema-v1"), [], () =>
            { ParserDiagnostics.Checkpoint(profile: "profile-" + i); return i; }, count => new(count)))));
        Assert.Equal(96, shared.Run.Events.Length);
        Assert.All(shared.Run.Events, e => Assert.Equal("profile-" + e.RecordCount, e.SelectedSchema));
    }

    [Fact]
    public void VariantsAreWhitelistedAndBytesFallbackDoesNotRetainReturnedBytes()
    {
        using var session = ParserDiagnostics.BeginSession();
        byte[] bytes = [1, 2, 3];
        Assert.Same(bytes, ParserDiagnostics.Run(Definition, [], () => bytes, sourceVariant: "EventData.NewNpc", assetName: "Known_1.bytes"));
        Assert.Equal("Known_1.bytes", session.Run.Events[0].Variant);
        Assert.Equal(3, session.Run.Events[0].Inputs["textasset"].Size);
        ParserDiagnostics.Run(new("synthetic.parse_manifest", "schema-v1"), [], () => 0,
            sourceVariant: "/private/path", assetName: "private/secret.bytes", manifestPackage: _ => "MainPackage");
        Assert.Equal("MainPackage", session.Run.Events[1].Variant);
        ParserDiagnostics.Run(new("synthetic.other", "schema-v1"), [], () => 0,
            sourceVariant: "secret", assetName: "秘密.bytes", manifestPackage: _ => "MainPackage");
        Assert.Null(session.Run.Events[2].Variant);
    }

    [Fact]
    public void CancellationAndOptionalInstrumentationFailuresDoNotTurnIntoLayoutEvidence()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        Assert.Throws<OperationCanceledException>(() => ParserDiagnostics.Run(Definition, [], () => 1, cancellationToken: cancelled.Token));
        var error = new OperationCanceledException();
        Assert.Same(error, Assert.Throws<OperationCanceledException>(() => ParserDiagnostics.Run<int>(Definition, [], () => throw error)));
        Assert.Null(ParserDiagnostics.GetFailure(error)); Assert.Empty(session.Run.Events);
        Assert.Throws<OperationCanceledException>(() => session.Run.BuildReports(cancellationToken: cancelled.Token));
        Assert.Equal(17, ParserDiagnostics.Run(Definition, [], () => 17, _ => throw new InvalidOperationException("secret")));
        var original = new ValueError("original");
        Assert.Same(original, Assert.Throws<ValueError>(() => ParserDiagnostics.Run<int>(Definition, new PoisonInputList(), () => throw original)));
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void AdditionalMetadataAdmissionLimitsAreExplicitAndNeverEvictExistingFailureStatus()
    {
        var run = new ParserDiagnosticRun();
        for (int i = 0; i < 512; i++) { run.RecordIdentity(i.ToString("x64")); run.RecordCoverage("feature_" + i, "passed"); }
        run.RecordCoverage("feature_0", "failed"); run.RecordCoverage("feature_0", "passed");
        run.RecordCoverage("/private/path", "failed"); run.RecordCoverage("secret", "sensitive payload");
        var root = JsonNode.Parse(run.BuildReports(checkedAtUtc: Now).Latest.AsSpan())!;
        Assert.Equal(128, root["coverage"]!.AsObject().Count);
        Assert.Equal("failed", root["coverage"]!["feature_0"]!.GetValue<string>());
        Assert.Equal(8, root["identities"]!.AsArray().Count);
        Assert.Equal(127.ToString("x64"), root["identities"]![7]!.GetValue<string>());
    }

    [Theory]
    [InlineData(16, false)]
    [InlineData(17, false)]
    [InlineData(16, true)]
    [InlineData(17, true)]
    public void LiveInputAdmissionBoundaryNeverChangesParserResultOrOriginalFailure(int count, bool fails)
    {
        using var session = ParserDiagnostics.BeginSession();
        var inputs = Enumerable.Range(0, count).Select(i => new ParserDiagnosticInput("raw_" + i, new byte[] { (byte)i })).ToArray();
        var result = new object();
        var error = new ValueError("SYNTHETIC_DISCARDED_EXCEPTION");
        int calls = 0;
        object Parse() { calls++; if (fails) throw error; return result; }
        if (fails) Assert.Same(error, Assert.Throws<ValueError>(() => ParserDiagnostics.Run(Definition, inputs, Parse)));
        else Assert.Same(result, ParserDiagnostics.Run(Definition, inputs, Parse));
        Assert.Equal(1, calls);
        if (count == ParserDiagnosticRun.MaxInputs)
        {
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(count, observation.Inputs.Count);
            Assert.Equal(fails, observation.Failed);
            foreach (var input in inputs)
            {
                Assert.Equal(1, observation.Inputs[input.Name].Size);
                Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(input.Bytes.Span)), observation.Inputs[input.Name].Sha256);
            }
            Assert.Equal(fails, ParserDiagnostics.GetFailure(error) is not null);
        }
        else
        {
            Assert.Empty(session.Run.Events);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        // Refused instrumentation neither poisons the session nor leaves a nested parser cursor active.
        ParserDiagnostics.Run(new("synthetic.after_input_boundary", "schema-v1"), [], () => 1);
        Assert.Equal(count == ParserDiagnosticRun.MaxInputs ? 2 : 1, session.Run.Events.Length);
        Assert.False(session.Run.AssetsReady); Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [InlineData(64, true)]
    [InlineData(65, false)]
    public void BaselineNestingLimitAppliesToIgnoredMetadataAtTheExactBoundary(int depth, bool accepted)
    {
        // The root object contributes one level; each ignored array adds one more.
        string ignored = new string('[', depth - 1) + "0" + new string(']', depth - 1);
        byte[] raw = Encoding.UTF8.GetBytes(BaselineWithIgnored(ignored));
        using var wellFormed = JsonDocument.Parse(raw, new JsonDocumentOptions { MaxDepth = 128 });
        Assert.Equal(JsonValueKind.Object, wellFormed.RootElement.ValueKind);
        AssertBaselineAdmission(raw, accepted);
    }

    [Theory]
    [InlineData("utf8", false)]
    [InlineData("utf8", true)]
    [InlineData("utf16le", false)]
    [InlineData("utf16le", true)]
    [InlineData("utf16be", false)]
    [InlineData("utf16be", true)]
    [InlineData("utf32le", false)]
    [InlineData("utf32le", true)]
    [InlineData("utf32be", false)]
    [InlineData("utf32be", true)]
    public void StrictBaselineDecodingRejectsRawSurrogatesButAcceptsValidSupplementaryUnicode(string name, bool bom)
    {
        Encoding encoding = name switch
        {
            "utf8" => new UTF8Encoding(true, true),
            "utf16le" => new UnicodeEncoding(false, true, true),
            "utf16be" => new UnicodeEncoding(true, true, true),
            "utf32le" => new UTF32Encoding(false, true, true),
            "utf32be" => new UTF32Encoding(true, true, true),
            _ => throw new InvalidOperationException()
        };
        const string marker = "SYNTHETIC_MARKER";
        string json = BaselineWithIgnored("\"" + marker + "\"");
        int position = json.IndexOf(marker, StringComparison.Ordinal);
        byte[] Encode(byte[] scalarBytes) => [.. (bom ? encoding.GetPreamble() : []),
            .. encoding.GetBytes(json[..position]), .. scalarBytes, .. encoding.GetBytes(json[(position + marker.Length)..])];
        AssertBaselineAdmission(Encode(encoding.GetBytes("\U00010000")), true);
        foreach (bool low in new[] { false, true })
        {
            // These code-unit bytes are constructed directly so Encoding cannot replace them before the test.
            byte[] surrogateBytes = name switch
            {
                "utf8" => [0xed, low ? (byte)0xb0 : (byte)0xa0, 0x80],
                "utf16le" => [0, low ? (byte)0xdc : (byte)0xd8],
                "utf16be" => [low ? (byte)0xdc : (byte)0xd8, 0],
                "utf32le" => [0, low ? (byte)0xdc : (byte)0xd8, 0, 0],
                "utf32be" => [0, 0, low ? (byte)0xdc : (byte)0xd8, 0],
                _ => throw new InvalidOperationException()
            };
            AssertBaselineAdmission(Encode(surrogateBytes), false);
        }
    }

    [Theory]
    [InlineData("\\ud800")]
    [InlineData("\\udc00")]
    public void EscapedSurrogatesInIgnoredJsonMetadataDoNotTriggerTheByteDecoderDelta(string escape)
    {
        // ASCII JSON escapes are not malformed byte encoding; ignored content must remain ignored.
        AssertBaselineAdmission(Encoding.UTF8.GetBytes(BaselineWithIgnored("\"" + escape + "\"")), true);
    }

    private static string BaselineWithIgnored(string ignored) => "{\"ignored\":" + ignored +
        ",\"parsers\":{\"synthetic.parse:default\":{\"schema\":\"schema-v1\",\"selected_schema\":\"schema-v1\"," +
        "\"inputs\":{\"raw\":{\"size\":1,\"sha256\":\"" + new string('a', 64) + "\"}},\"record_count\":1,\"identity\":null}}}";

    private static void AssertBaselineAdmission(byte[] raw, bool accepted)
    {
        Assert.Equal(accepted ? 1 : 0, ParserDiagnosticJson.ReadBaseline(raw, default).Count);
        var reports = new ParserDiagnosticRun().BuildReports(raw, Now);
        var baseline = JsonNode.Parse(reports.LastSuccess.AsSpan())!;
        Assert.Equal(accepted ? 1 : 0, baseline["parsers"]!.AsObject().Count);
        Assert.Empty(JsonNode.Parse(reports.Latest.AsSpan())!["parsers"]!.AsArray());
        Assert.DoesNotContain("ignored", Encoding.UTF8.GetString(reports.LastSuccess.AsSpan()));
        Assert.False(reports.AssetsReady); Assert.False(reports.CanSendPackets);
    }

    [Fact]
    public void SerializerCapsEachDocumentAtExactByteBoundaryAndNeverWritesPartialJson()
    {
        var exact = ParserDiagnosticJson.Serialize(new Dictionary<string, object?> { ["x"] = new string('a', ParserDiagnosticRun.MaxReportBytes - 9) }, default);
        Assert.Equal(ParserDiagnosticRun.MaxReportBytes, exact.Length);
        Assert.NotNull(JsonNode.Parse(exact.AsSpan()));
        Assert.Empty(ParserDiagnosticJson.Serialize(new Dictionary<string, object?> { ["x"] = new string('a', ParserDiagnosticRun.MaxReportBytes - 8) }, default));
        Assert.Empty(ParserDiagnosticJson.Serialize(new Dictionary<string, object?> { ["x"] = BigInteger.One << (ParserDiagnosticRun.MaxReportBytes * 8) }, default));
    }

    [Fact]
    public void DiagnosticEventsAndReportSnapshotsCannotBeChangedByLaterRuns()
    {
        using var session = ParserDiagnostics.BeginSession();
        ParserDiagnostics.RecordIdentity(new string('a', 64));
        ParserDiagnostics.Run(Definition, [new("raw", new byte[] {1})], () => 1, count => new(count));
        var snapshot = session.Run.Events;
        var report = session.Run.BuildReports(checkedAtUtc: Now);
        ParserDiagnostics.RecordIdentity(new string('b', 64));
        ParserDiagnostics.Run(Definition, [new("raw", new byte[] {2})], () => 2, count => new(count));
        Assert.Single(snapshot); Assert.Equal(new string('a', 64), snapshot[0].Identity);
        Assert.Single(JsonNode.Parse(report.Latest.AsSpan())!["parsers"]!.AsArray());
        var next = session.Run.BuildReports(report.LastSuccess.AsSpan(), Now);
        Assert.False(next.AssetsReady); Assert.False(next.CanSendPackets);
    }

    private static void CheckWrapped(string scenario, JsonNode expected)
    {
        using var session = ParserDiagnostics.BeginSession();
        byte[] raw = Encoding.UTF8.GetBytes("SYNTHETIC_INPUT_BYTES");
        IReadOnlyList<ParserDiagnosticInput> inputs = scenario == "bytes_fallback" ? [] : [new("raw", raw)];
        try
        {
            ParserDiagnostics.Run<object>(new(scenario == "manifest" ? "synthetic.parse_manifest" : "synthetic.parse", "schema-v1"), inputs, () =>
            {
                ParserDiagnostics.Checkpoint(offset: 3, field: "header", profile: "profile-v1");
                switch (scenario)
                {
                    case "failure": throw new ValueError("SECRET_EXCEPTION_MESSAGE");
                    case "list": return StateValue.List(StateValue.Scalar(0), StateValue.Scalar(0), StateValue.Scalar(0));
                    case "tuple": return StateValue.Tuple(StateValue.Map(("metadata", StateValue.Scalar("discarded"))), StateValue.List(StateValue.Scalar(1), StateValue.Scalar(2)));
                    case "negative_count": return StateValue.Map(("record_count", StateValue.Scalar(-7)));
                    case "rejected": return StateValue.Map(("status", StateValue.Scalar("unsupported_table")));
                    case "bytes_fallback": return Encoding.UTF8.GetBytes("SYNTHETIC_RETURNED_BYTES");
                    case "manifest": return StateValue.Map(("header", StateValue.Map(("package_name", StateValue.Scalar("MainPackage")))), ("asset_count", StateValue.Scalar(4)));
                    case "nested":
                        try
                        {
                            ParserDiagnostics.Run<int>(new("synthetic.child", "child-v1"), inputs, () =>
                            { ParserDiagnostics.Checkpoint(offset: 8, field: "child_header"); throw new ValueError("SECRET_CHILD_MESSAGE"); });
                        }
                        catch (ValueError) { }
                        return StateValue.Map(("status", StateValue.Scalar("layout_unrecognized")));
                    default: throw new InvalidOperationException();
                }
            }, manifestPackage: _ => "MainPackage");
        }
        catch (ValueError) { }
        var report = session.Run.BuildReports(checkedAtUtc: Now);
        AssertBytes(expected["latest"], report.Latest, scenario + " wrapper latest");
        AssertBytes(expected["baseline"], report.LastSuccess, scenario + " wrapper baseline");
    }

    private static ParserDiagnosticEvent Event(JsonNode e) => new(new(e["parser"]!.GetValue<string>(), e["schema"]!.GetValue<string>()),
        e["inputs"]!.AsObject().ToImmutableDictionary(p => p.Key, p => new ParserInputDigest(p.Value!["size"]!.GetValue<long>(), p.Value["sha256"]!.GetValue<string>())),
        e["status"]!.GetValue<string>() == "failed", e["variant"]?.GetValue<string>(), Number(e["record_count"]), e["selected_schema"]?.GetValue<string>(),
        e["error_type"]?.GetValue<string>(), e["location"]?.AsObject().ToImmutableDictionary(p => p.Key, p => (object?)Number(p.Value) ?? p.Value!.GetValue<string>()));
    private static void ApplyCheckpoint(JsonNode node) => ParserDiagnostics.Checkpoint(Number(node["offset"]), Text(node["field"]), Number(node["record"]),
        Number(node["expected"]), Number(node["actual"]), Number(node["expected_max"]), Text(node["constraint"]), Text(node["profile"]));
    private static string? Text(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text) ? text : null;
    private static BigInteger? Number(JsonNode? node) => node is JsonValue &&
        BigInteger.TryParse(node.ToJsonString(), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var number) ? number : null;
    private static StateValue Value(JsonNode? node)
    {
        if (node is null) return StateValue.Null;
        if (node is JsonObject map)
        {
            if (map["$tuple"] is JsonArray tuple) return StateValue.Tuple(tuple.Select(Value));
            if (map["$float"] is { } value) return StateValue.Scalar(value.GetValue<string>() == "nan" ? double.NaN : double.PositiveInfinity);
            return StateValue.Map(map.Select(p => KeyValuePair.Create(p.Key, Value(p.Value))));
        }
        if (node is JsonArray array) return StateValue.List(array.Select(Value));
        if (node.AsValue().TryGetValue<bool>(out bool boolean)) return StateValue.Scalar(boolean);
        if (Text(node) is { } text) return StateValue.Scalar(text);
        if (Number(node) is { } integer) return StateValue.Scalar(integer);
        return StateValue.Scalar(double.Parse(node.ToJsonString(), CultureInfo.InvariantCulture));
    }
    private static void AssertBytes(JsonNode? encoded, ImmutableArray<byte> actual, string name)
    {
        if (encoded is null) { Assert.Empty(actual); return; }
        byte[] expected = Convert.FromBase64String(encoded.GetValue<string>());
        Assert.True(expected.AsSpan().SequenceEqual(actual.AsSpan()), name + " differs: " + Encoding.UTF8.GetString(actual.AsSpan()));
    }
    private static void AssertJson(JsonNode? expected, ImmutableArray<byte> actual, string name) =>
        LazyAssert.True(JsonNode.DeepEquals(expected, JsonNode.Parse(actual.AsSpan())), () => name + ": " + Encoding.UTF8.GetString(actual.AsSpan()));
    private sealed class PoisonInputList : IReadOnlyList<ParserDiagnosticInput>
    {
        public int Count => throw new InvalidOperationException("must not inspect");
        public ParserDiagnosticInput this[int index] => throw new NotSupportedException();
        public IEnumerator<ParserDiagnosticInput> GetEnumerator() => throw new NotSupportedException();
        System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
