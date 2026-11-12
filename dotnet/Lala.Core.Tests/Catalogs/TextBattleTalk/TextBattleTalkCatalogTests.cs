using System.Buffers.Binary;
using System.Collections;
using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs.TextBattleTalk;

public sealed class TextBattleTalkCatalogTests
{
    [Theory]
    [MemberData(nameof(TextBattleTalkPythonVectors.Cases), MemberType = typeof(TextBattleTalkPythonVectors))]
    public void Actual_decorated_python_values_errors_order_and_diagnostics_match(string name, int fixture, int index)
    {
        var row = TextBattleTalkPythonVectors.ReadCase(fixture, index);
        Assert.Equal(name, row.GetProperty("name").GetString());
        using var session = ParserDiagnostics.BeginSession();
        CatalogDecodeException? error = null;
        if (row.GetProperty("error").ValueKind == JsonValueKind.Null)
            AssertJson(row.GetProperty("expected"), Parse(row));
        else
        {
            error = Assert.Throws<CatalogDecodeException>(() => Parse(row));
            Assert.Equal(row.GetProperty("error").GetProperty("message").GetString(), error.Message);
            Assert.Null(error.InnerException);
        }
        var expectedEvents = row.GetProperty("diagnostics");
        Assert.Equal(expectedEvents.GetArrayLength(), session.Run.Events.Length);
        for (int eventIndex = 0; eventIndex < expectedEvents.GetArrayLength(); eventIndex++)
            AssertDiagnostic(expectedEvents[eventIndex], session.Run.Events[eventIndex]);
        if (error is not null)
        {
            if (row.GetProperty("failure").ValueKind == JsonValueKind.Null)
                Assert.Null(ParserDiagnostics.GetFailure(error));
            else AssertDiagnostic(row.GetProperty("failure"), ParserDiagnostics.GetFailure(error)!, includeIdentity: false);
        }
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(TextBattleTalkPythonVectors.Sources), MemberType = typeof(TextBattleTalkPythonVectors))]
    public void Oracle_source_hashes_ignore_only_CRLF_checkout_conversion(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void Public_surface_keeps_fixed_pin_without_a_hash_override_or_layout_access()
    {
        Assert.Equal(TextBattleTalkPythonVectors.NpcPin, NpcBattleTalkCatalogParser.ReviewedSha256);
        var methods = typeof(NpcBattleTalkCatalogParser).GetMethods(BindingFlags.Public | BindingFlags.Static);
        Assert.Equal(new[] { "BuildCatalog", "ParseKnownBattleTalk" }, methods.Select(method => method.Name).Order());
        Assert.All(methods.SelectMany(method => method.GetParameters()), parameter =>
            Assert.True(parameter.ParameterType == typeof(ReadOnlySpan<byte>) || parameter.ParameterType == typeof(CancellationToken)));
        Assert.Equal("Parse", Assert.Single(typeof(TextDataParser).GetMethods(BindingFlags.Public | BindingFlags.Static)).Name);
    }

    [Fact]
    public void Every_synthetic_quote_input_fails_the_unmodified_public_pin_first()
    {
        foreach (var entry in TextBattleTalkPythonVectors.Cases())
        {
            var row = TextBattleTalkPythonVectors.ReadCase((int)entry[1], (int)entry[2]);
            if (row.GetProperty("mode").GetString() == "text") continue;
            byte[] raw = Raw(row, "raw");
            var error = Assert.Throws<CatalogDecodeException>(() => NpcBattleTalkCatalogParser.ParseKnownBattleTalk(raw));
            Assert.Equal("NpcTalkData 來源指紋未經審核；拒絕推測新格式", error.Message);
            Assert.Equal("source_fingerprint", ParserDiagnostics.GetFailure(error)!.Location!["field"]);
            if (row.GetProperty("text").ValueKind != JsonValueKind.Null)
                Assert.Equal(error.Message, Assert.Throws<CatalogDecodeException>(() =>
                    NpcBattleTalkCatalogParser.BuildCatalog(raw, Raw(row, "text"))).Message);
        }
    }

    [Fact]
    public void Discovery_contains_unique_bounded_scalar_ids_and_no_parsed_payloads()
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        var positions = new HashSet<(int, int)>();
        foreach (var entry in TextBattleTalkPythonVectors.Cases())
        {
            Assert.Equal(3, entry.Length);
            string name = Assert.IsType<string>(entry[0]);
            Assert.InRange(name.Length, 1, 80);
            Assert.All(name, character => Assert.InRange((int)character, 32, 126));
            int fixture = Assert.IsType<int>(entry[1]), index = Assert.IsType<int>(entry[2]);
            Assert.True(names.Add(name));
            Assert.True(positions.Add((fixture, index)));
            Assert.Equal(name, TextBattleTalkPythonVectors.ReadCase(fixture, index).GetProperty("name").GetString());
        }
        Assert.Equal(TextBattleTalkPythonVectors.VectorCount, names.Count);
        Assert.Equal(names.Count, TextBattleTalkPythonVectors.FixtureCaseCount);
    }

    [Fact]
    public void Owned_results_preserve_zero_empty_BOM_NUL_and_both_group_and_row_order()
    {
        var source = Fixture("npc-source-order");
        byte[] raw = Raw(source, "raw");
        byte[] envelope = new byte[raw.Length + 12];
        raw.CopyTo(envelope, 5);
        var groups = NpcBattleTalkCatalogParser.ParseLayout(envelope.AsSpan(5, raw.Length));
        Array.Fill(envelope, (byte)255);
        Array.Fill(raw, (byte)255);
        Assert.Equal(new ushort[] { 90, 1, 65535 }, groups.Keys);
        Assert.Equal(groups.Keys, groups.Select(pair => pair.Key));
        Assert.Equal(new uint[] { 9, 7, 8, 5, 6 }, groups.Values.SelectMany(rows => rows).Select(row => row.TextId));
        Assert.Equal(new uint[] { 9, 7 }, groups[90].Select(row => row.TextId));
        Assert.True(groups.ContainsKey(90));
        Assert.False(groups.TryGetValue(0, out _));
        Assert.True(groups.TryGetValue(90, out var copy));
        Assert.Equal(groups[90], copy);
        Assert.Throws<KeyNotFoundException>(() => groups[0]);
        Assert.False(groups is IDictionary);
        Assert.False(groups is IDictionary<ushort, ImmutableArray<NpcBattleTalkRow>>);
        Assert.Throws<NotSupportedException>(() => ((IList<NpcBattleTalkRow>)groups[90])[0] = new(1, 1, 1, 1));
        var changedCopy = groups[90].SetItem(0, groups[90][0] with { TextId = 42 });
        Assert.Equal(42u, changedCopy[0].TextId);
        Assert.Equal(9u, groups[90][0].TextId);
        Assert.Equal(groups.Keys, ((IEnumerable)groups).Cast<KeyValuePair<ushort, ImmutableArray<NpcBattleTalkRow>>>().Select(pair => pair.Key));

        foreach (var (name, expected) in new[] { ("empty", ""), ("nul-only", "\0\0"),
                     ("embedded-nul", "甲\0乙\0"), ("bom", "\ufeff甲\ufffe") })
        {
            byte[] text = Raw(Fixture("text-" + name), "raw");
            var texts = TextDataParser.Parse(text);
            Array.Fill(text, (byte)255);
            Assert.Equal(expected, texts[0]);
            var dictionary = Assert.IsAssignableFrom<IDictionary>(texts);
            Assert.True(dictionary.IsReadOnly);
            Assert.Throws<NotSupportedException>(dictionary.Clear);
        }
    }

    [Fact]
    public void Missing_reference_has_no_invented_builder_observation_and_empty_text_is_valid()
    {
        using var session = ParserDiagnostics.BeginSession();
        var fixture = Fixture("build-missing-reference");
        var error = Assert.Throws<CatalogDecodeException>(() =>
            NpcBattleTalkCatalogParser.BuildCatalogLayout(Raw(fixture, "raw"), Raw(fixture, "text")));
        Assert.Null(ParserDiagnostics.GetFailure(error));
        Assert.Equal(2, session.Run.Events.Length);
        Assert.All(session.Run.Events, entry => Assert.False(entry.Failed));
        Assert.Equal(new[] { "npc-battle-talk-known-v1", "text-v1" }, session.Run.Events.Select(entry => entry.Definition.Schema));
        var empty = Fixture("build-empty-text-valid");
        Assert.Equal(2, Assert.Single(NpcBattleTalkCatalogParser.BuildCatalogLayout(Raw(empty, "raw"), Raw(empty, "text"))).Value.Length);
    }

    [Fact]
    public void Typed_cancellation_precedes_validation_and_never_records_parser_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var fixture = Fixture("build-basic");
        byte[] raw = Raw(fixture, "raw"), text = Raw(fixture, "text");
        foreach (var action in new Action[]
        {
            () => TextDataParser.Parse(text, cancelled.Token),
            () => TextDataParser.Parse([], cancelled.Token),
            () => NpcBattleTalkCatalogParser.ParseKnownBattleTalk(raw, cancelled.Token),
            () => NpcBattleTalkCatalogParser.ParseLayout(raw, cancelled.Token),
            () => NpcBattleTalkCatalogParser.BuildCatalog(raw, text, cancelled.Token),
            () => NpcBattleTalkCatalogParser.BuildCatalogLayout(raw, text, cancelled.Token),
            () => NpcBattleTalkCatalogParser.BuildCatalog([], [], cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(action);
            Assert.Equal(cancelled.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
        Assert.Equal(2, TextDataParser.Parse(text).Count);
        Assert.Single(session.Run.Events);
    }

    [Fact]
    public void Oversized_text_rejects_without_copying_the_input_and_keeps_named_digest()
    {
        byte[] oversized = new byte[TextDataParser.MaxBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        var error = Assert.Throws<CatalogDecodeException>(() => TextDataParser.Parse(oversized));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 200_000);
        Assert.Equal(oversized.Length, ParserDiagnostics.GetFailure(error)!.Inputs["text_data"].Size);
        Assert.Empty(ParserDiagnostics.GetFailure(error)!.Location!);
    }

    [Fact]
    public void Nested_success_is_suppressed_child_failure_retains_location_and_parent_cursor_is_restored()
    {
        using var session = ParserDiagnostics.BeginSession();
        var parent = new ParserDiagnosticDefinition("synthetic.text_parent", "parent-v1");
        var original = new InvalidOperationException("not retained");
        var fixture = Fixture("build-basic");
        Assert.Same(original, Assert.Throws<InvalidOperationException>(() => ParserDiagnostics.Run<int>(parent, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
            NpcBattleTalkCatalogParser.BuildCatalogLayout(Raw(fixture, "raw"), Raw(fixture, "text"));
            var child = Assert.Throws<CatalogDecodeException>(() => TextDataParser.Parse([1, 0, 0, 0, 0]));
            Assert.Equal(new BigInteger(4), ParserDiagnostics.GetFailure(child)!.Location!["offset"]);
            throw original;
        })));
        Assert.Equal(2, session.Run.Events.Length);
        Assert.Equal(new BigInteger(7), ParserDiagnostics.GetFailure(original)!.Location!["offset"]);
        Assert.Equal("outer", ParserDiagnostics.GetFailure(original)!.Location!["field"]);
    }

    [Fact]
    public void Diagnostics_never_retain_text_payload_exception_messages_or_caller_arrays()
    {
        using var session = ParserDiagnostics.BeginSession();
        var (weak, result, error) = ReleaseCallerInput();
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        Assert.False(weak.IsAlive);
        Assert.Equal("台詞私密甲😀\0", result[100]);
        Assert.NotNull(ParserDiagnostics.GetFailure(error));
        string report = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("台詞", report);
        Assert.DoesNotContain("\\u79c1", report);
        Assert.DoesNotContain("來源", report);
        Assert.DoesNotContain("base64", report);
        Assert.DoesNotContain("message", report);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static (WeakReference, IReadOnlyDictionary<uint, string>, CatalogDecodeException) ReleaseCallerInput()
    {
        byte[] raw = Raw(Fixture("text-basic"), "raw");
        var result = TextDataParser.Parse(raw);
        var error = Assert.Throws<CatalogDecodeException>(() => NpcBattleTalkCatalogParser.ParseKnownBattleTalk(raw));
        return (new WeakReference(raw), result, error);
    }

    [Fact]
    public async Task Concurrent_observations_do_not_cross_inputs_or_leak_cursor_state()
    {
        var hashes = await Task.WhenAll(Enumerable.Range(0, 12).Select(index => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            byte[] raw = Raw(Fixture("text-empty"), "raw");
            BinaryPrimitives.WriteUInt32LittleEndian(raw.AsSpan(4), (uint)index);
            Assert.Single(TextDataParser.Parse(raw));
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), observation.Inputs["text_data"].Sha256);
            return observation.Inputs["text_data"].Sha256;
        })));
        Assert.Equal(12, hashes.Distinct().Count());
        Assert.False(ParserDiagnostics.IsActive);
    }

    private static object Parse(JsonElement row)
    {
        byte[] raw = Raw(row, "raw");
        string mode = row.GetProperty("mode").GetString()!;
        if (mode == "text")
        {
            var texts = TextDataParser.Parse(raw);
            if (row.GetProperty("summary").GetBoolean()) return SummarizeTexts(texts);
            Assert.Equal(row.GetProperty("expected").EnumerateObject().Select(property => uint.Parse(property.Name, CultureInfo.InvariantCulture)), texts.Keys);
            return texts;
        }
        var result = mode switch
        {
            "parse-public" => NpcBattleTalkCatalogParser.ParseKnownBattleTalk(raw),
            "parse-layout" => NpcBattleTalkCatalogParser.ParseLayout(raw),
            "build-public" => NpcBattleTalkCatalogParser.BuildCatalog(raw, Raw(row, "text")),
            "build-layout" => NpcBattleTalkCatalogParser.BuildCatalogLayout(raw, Raw(row, "text")),
            _ => throw new InvalidDataException("Unknown retained fixture mode")
        };
        return result.Select(pair => new { group = pair.Key, rows = pair.Value.Select(value => new
        { text_id = value.TextId, kind = value.Kind, parameter = value.Parameter, duration = value.Duration }).ToArray() }).ToArray();
    }

    private static object SummarizeTexts(IReadOnlyDictionary<uint, string> texts)
    {
        using var keys = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var values = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Span<byte> header = stackalloc byte[8];
        foreach (var (key, value) in texts)
        {
            byte[] encoded = Encoding.Unicode.GetBytes(value);
            BinaryPrimitives.WriteUInt32LittleEndian(header, key);
            BinaryPrimitives.WriteUInt32LittleEndian(header[4..], (uint)encoded.Length);
            keys.AppendData(header[..4]);
            values.AppendData(header);
            values.AppendData(encoded);
        }
        return new { count = texts.Count, keys_sha256 = Convert.ToHexStringLower(keys.GetHashAndReset()),
            values_sha256 = Convert.ToHexStringLower(values.GetHashAndReset()), first_key = texts.Keys.First(), last_key = texts.Keys.Last() };
    }

    private static void AssertDiagnostic(JsonElement expectedElement, ParserDiagnosticEvent actualEvent, bool includeIdentity = true)
    {
        Assert.NotNull(actualEvent);
        var expected = JsonNode.Parse(expectedElement.GetRawText())!;
        if (expected["error_type"] is not null)
        {
            Assert.Contains(expected["error_type"]!.GetValue<string>(), new[] { "ValueError", "ProtocolError" });
            expected["error_type"] = nameof(CatalogDecodeException);
        }
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(actualEvent), default).AsSpan())!;
        if (!includeIdentity) actual.AsObject().Remove("identity");
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => "Retained Python and C# diagnostics differ: " + actual);
    }

    private static JsonElement Fixture(string name) => TextBattleTalkPythonVectors.FindCase(name);
    private static void AssertJson(JsonElement expected, object actual) => Assert.True(
        JsonNode.DeepEquals(JsonNode.Parse(expected.GetRawText()), JsonSerializer.SerializeToNode(actual)), "Retained Python and C# results differ.");
    private static byte[] Raw(JsonElement row, string name)
    {
        var spec = row.GetProperty(name);
        if (spec.TryGetProperty("base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        string kind = spec.GetProperty("kind").GetString()!;
        if (kind == "zeros") return new byte[spec.GetProperty("size").GetInt32()];
        using var stream = new MemoryStream();
        Span<byte> header = stackalloc byte[6];
        if (kind == "empty-records")
        {
            int count = spec.GetProperty("count").GetInt32();
            BinaryPrimitives.WriteInt32LittleEndian(header, count);
            stream.Write(header[..4]);
            BinaryPrimitives.WriteUInt16LittleEndian(header[4..], 0);
            for (int i = 0; i < count; i++)
            {
                BinaryPrimitives.WriteUInt32LittleEndian(header, (uint)i);
                stream.Write(header);
            }
        }
        else if (kind == "maximum-size")
        {
            stream.Write(new byte[4]);
            int available = TextDataParser.MaxBytes - 4, count = 0;
            while (available > 0)
            {
                int size = Math.Min(65534, available - 6);
                BinaryPrimitives.WriteUInt32LittleEndian(header, (uint)count++);
                BinaryPrimitives.WriteUInt16LittleEndian(header[4..], (ushort)size);
                stream.Write(header);
                stream.Write(Encoding.Unicode.GetBytes(new string('字', size / 2)));
                available -= size + 6;
            }
            stream.Position = 0;
            BinaryPrimitives.WriteInt32LittleEndian(header, count);
            stream.Write(header[..4]);
        }
        else throw new InvalidDataException("Unknown retained input recipe");
        return stream.ToArray();
    }
}
