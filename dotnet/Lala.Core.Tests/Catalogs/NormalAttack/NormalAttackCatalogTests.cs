using System.Collections;
using System.Globalization;
using System.Numerics;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Battle;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs.NormalAttack;

public sealed class NormalAttackCatalogTests
{
    [Theory]
    [MemberData(nameof(NormalAttackPythonVectors.Cases), MemberType = typeof(NormalAttackPythonVectors))]
    public void Retained_python_values_rejections_and_npc_observations_match(string name, int fixtureIndex, int rowIndex)
    {
        Assert.NotEmpty(name);
        var row = NormalAttackPythonVectors.ReadCase(fixtureIndex, rowIndex);
        Assert.Equal(name, row.GetProperty("name").GetString());
        using var session = ParserDiagnostics.BeginSession();
        var expectedError = row.GetProperty("error");
        var expectedObservation = row.GetProperty("diagnostic");
        CatalogDecodeException? error = null;
        object? parsed = null;
        if (expectedError.ValueKind == JsonValueKind.Null) parsed = Parse(row);
        else
        {
            error = Assert.Throws<CatalogDecodeException>(() => Parse(row));
            string? expectedMessage = expectedError.GetProperty("message").GetString();
            // Existing ItemDataParser retains the shared reader's established error text.
            // Only pre-NPC ItemData truncation is mapped; all NPC and other errors stay exact.
            if (row.GetProperty("mode").GetString() == "build-layout" &&
                expectedObservation.ValueKind == JsonValueKind.Null &&
                expectedError.GetProperty("type").GetString() == "ItemDataDecodeError" &&
                expectedMessage == "ItemData record truncated") expectedMessage = "Catalog record truncated";
            Assert.Equal(expectedMessage, error.Message);
            Assert.Null(error.InnerException);
        }
        if (parsed is not null) AssertJson(row.GetProperty("expected"), parsed);

        if (expectedObservation.ValueKind == JsonValueKind.Null)
        {
            Assert.Empty(session.Run.Events); // ItemData failure occurs before the NPC parser.
            return;
        }
        var observation = Assert.Single(session.Run.Events);
        var expected = JsonNode.Parse(expectedObservation.GetRawText())!;
        if (expected["error_type"] is not null)
        {
            Assert.Contains(expected["error_type"]!.GetValue<string>(), new[] { "ValueError", "ItemDataDecodeError" });
            expected["error_type"] = nameof(CatalogDecodeException);
            Assert.NotNull(error);
            Assert.Equal(observation, ParserDiagnostics.GetFailure(error));
        }
        else Assert.Null(error);
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observation), default).AsSpan());
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => name + ": " + actual);
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(NormalAttackPythonVectors.Sources), MemberType = typeof(NormalAttackPythonVectors))]
    public void Oracle_source_hashes_ignore_only_CRLF_checkout_conversion(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int index = 0; index < source.Length; index++)
            if (source[index] != 13 || index + 1 == source.Length || source[index + 1] != 10) normalized.WriteByte(source[index]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void Production_pins_and_public_surface_have_no_caller_supplied_source_bypass()
    {
        Assert.Equal(NormalAttackPythonVectors.NpcPin, NormalAttackCatalogParser.ReviewedNpcSha256);
        Assert.Equal(NormalAttackPythonVectors.ItemPin, ItemDataParser.Reviewed1296Sha256);
        var methods = typeof(NormalAttackCatalogParser).GetMethods(BindingFlags.Public | BindingFlags.Static);
        Assert.Equal(new[] { "BuildCatalog", "ParseNpcs" }, methods.Select(method => method.Name).Order().ToArray());
        Assert.All(methods.SelectMany(method => method.GetParameters()), parameter =>
            Assert.True(parameter.ParameterType == typeof(ReadOnlySpan<byte>) || parameter.ParameterType == typeof(CancellationToken)));
        Assert.Empty(typeof(NormalAttackCatalogData).GetConstructors());
    }

    [Fact]
    public void Public_entrypoints_reject_all_synthetic_layouts_even_when_internal_parsing_succeeds()
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        var locations = new HashSet<(int Fixture, int Row)>();
        foreach (var fixture in NormalAttackPythonVectors.Cases())
        {
            Assert.Equal(3, fixture.Length);
            string name = Assert.IsType<string>(fixture[0]);
            Assert.InRange(name.Length, 1, 80);
            int fixtureIndex = Assert.IsType<int>(fixture[1]), rowIndex = Assert.IsType<int>(fixture[2]);
            Assert.True(names.Add(name), "Duplicate discovery name: " + name);
            Assert.True(locations.Add((fixtureIndex, rowIndex)), "Duplicate fixture/row index: " + name);
            var row = NormalAttackPythonVectors.ReadCase(fixtureIndex, rowIndex);
            Assert.Equal(name, row.GetProperty("name").GetString());
            byte[] npc = Raw(row, "npc");
            Assert.Equal("NPC 普攻資料格式尚未驗證", Assert.Throws<CatalogDecodeException>(() =>
                NormalAttackCatalogParser.ParseNpcs(npc)).Message);
            if (row.GetProperty("item").ValueKind != JsonValueKind.Null)
                Assert.Equal("物品普攻資料格式尚未驗證", Assert.Throws<CatalogDecodeException>(() =>
                    NormalAttackCatalogParser.BuildCatalog(npc, Raw(row, "item"))).Message);
        }
        Assert.Equal(NormalAttackPythonVectors.VectorCount, NormalAttackPythonVectors.Cases().Count());
        Assert.Equal(NormalAttackPythonVectors.VectorCount, NormalAttackPythonVectors.FixtureCaseCount);
        Assert.Equal(NormalAttackPythonVectors.VectorCount, locations.Count);
    }

    [Fact]
    public void Snapshot_preserves_capture_facts_and_uses_existing_normal_attack_rules_without_activation()
    {
        var row = Fixture("mixed-items");
        var catalog = NormalAttackCatalogParser.BuildCatalogLayout(Raw(row, "npc"), Raw(row, "item"));
        Assert.Equal(-2147483748L, catalog.CatchNets[65535]);
        Assert.Equal(2147483547L, catalog.CatchNets[8]);
        Assert.False(catalog.CatchNets.ContainsKey(1));
        Assert.True(catalog.Npcs[321].CanCatch);
        Assert.Equal(new NormalAttackNpc(1, 2, 3), catalog.NormalAttacks.Npcs[321]);
        Assert.Equal(255, catalog.NormalAttacks.ItemKinds[65535]);
        Assert.Equal(10004, CombatRules.NormalSkill(new(50, null, 0, [0, 0, 8]), 50, catalog.NormalAttacks));
        Assert.Equal(10001, CombatRules.NormalSkill(new(50, null, 0, [0, 0, 1]), 50, catalog.NormalAttacks));
    }

    [Fact]
    public void Inputs_are_detached_and_all_exposed_maps_are_immutable()
    {
        var row = Fixture("basic-catalog");
        byte[] npc = Raw(row, "npc"), item = Raw(row, "item");
        byte[] envelope = new byte[npc.Length + 24];
        npc.CopyTo(envelope, 12);
        var result = NormalAttackCatalogParser.BuildCatalogLayout(envelope.AsSpan(12, npc.Length), item);
        var parsed = NormalAttackCatalogParser.ParseNpcsLayout(npc);
        Array.Fill(envelope, (byte)255);
        Array.Fill(npc, (byte)255);
        Array.Fill(item, (byte)255);
        Assert.Equal(new NormalAttackNpcData(1, 2, 3, true), result.Npcs[321]);
        Assert.Equal(5, result.ItemKinds[100]);
        Assert.Equal(23, result.CatchNets[100]);
        Assert.Equal(new NormalAttackNpcData(1, 2, 3, true), parsed[321]);
        foreach (var map in new object[] { result.Npcs, result.ItemKinds, result.CatchNets, parsed,
                     result.NormalAttacks.Npcs, result.NormalAttacks.ItemKinds })
        {
            var dictionary = Assert.IsAssignableFrom<IDictionary>(map);
            Assert.True(dictionary.IsReadOnly);
            Assert.Throws<NotSupportedException>(dictionary.Clear);
        }
    }

    [Fact]
    public void Every_entrypoint_propagates_cancellation_without_recording_a_parser_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        var row = Fixture("basic-catalog");
        byte[] npc = Raw(row, "npc"), item = Raw(row, "item");
        foreach (var action in new Action[]
        {
            () => NormalAttackCatalogParser.ParseNpcs(npc, cancelled.Token),
            () => NormalAttackCatalogParser.ParseNpcsLayout(npc, cancelled.Token),
            () => NormalAttackCatalogParser.BuildCatalog(npc, item, cancelled.Token),
            () => NormalAttackCatalogParser.BuildCatalogLayout(npc, item, cancelled.Token),
            () => NormalAttackCatalogParser.ParseNpcs([], cancelled.Token),
            () => NormalAttackCatalogParser.BuildCatalog([], [], cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(action);
            Assert.Equal(cancelled.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
        NormalAttackCatalogParser.ParseNpcsLayout(npc);
        Assert.Single(session.Run.Events); // Canceled calls did not leave a diagnostic cursor behind.
    }

    [Fact]
    public void Count_and_text_bounds_derive_the_total_npc_bound_without_a_narrower_format_guess()
    {
        Assert.Equal(4 + 20_000 * (203 + 4 + 2 * 8192), NormalAttackCatalogParser.MaxNpcBytes);
        var row = Fixture("maximum-npc-count");
        Assert.Equal(20_000, NormalAttackCatalogParser.ParseNpcsLayout(Raw(row, "npc")).Count);
        var text = Fixture("both-max-utf16");
        Assert.Single(NormalAttackCatalogParser.ParseNpcsLayout(Raw(text, "npc")));
        var items = Fixture("maximum-item-count");
        Assert.Equal(20_000, NormalAttackCatalogParser.BuildCatalogLayout(Raw(items, "npc"), Raw(items, "item")).ItemKinds.Count);
        byte[] oversizedItem = new byte[ItemDataParser.MaxBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.BuildCatalog([], oversizedItem));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 100_000);
    }

    [Fact]
    public void Optional_diagnostics_are_payload_free_and_keep_the_exact_failure()
    {
        Assert.False(ParserDiagnostics.IsActive);
        var row = Fixture("basic-reviewed-fields");
        byte[] npc = Raw(row, "npc");
        Assert.Single(NormalAttackCatalogParser.ParseNpcsLayout(npc));
        string digest = Convert.ToHexStringLower(SHA256.HashData(npc));
        var error = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcs(npc));
        var observation = ParserDiagnostics.GetFailure(error)!;
        Array.Fill(npc, (byte)255);
        Assert.Equal(digest, observation.Inputs["raw"].Sha256);
        Assert.Empty(observation.Location!);
        Assert.Equal(nameof(CatalogDecodeException), observation.ErrorType);
        using var session = ParserDiagnostics.BeginSession();
        Assert.Empty(session.Run.Events);
        var malformed = Fixture("invalid-name-unicode-00d8");
        var formatError = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcsLayout(Raw(malformed, "npc")));
        Assert.Equal(Assert.Single(session.Run.Events), ParserDiagnostics.GetFailure(formatError));
        string report = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("私密", report);
        Assert.DoesNotContain("Unicode data", report);
        Assert.DoesNotContain("NPC 普攻", report);
    }

    [Fact]
    public void Nested_diagnostics_suppress_success_and_keep_child_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        var parent = new ParserDiagnosticDefinition("synthetic.normal_parent", "parent-v1");
        var row = Fixture("basic-reviewed-fields");
        var result = ParserDiagnostics.Run(parent, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
            var parsed = NormalAttackCatalogParser.ParseNpcsLayout(Raw(row, "npc"));
            var error = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcs([]));
            Assert.Empty(ParserDiagnostics.GetFailure(error)!.Location!);
            return parsed;
        }, rows => new(rows.Count));
        Assert.Single(result);
        Assert.Equal(2, session.Run.Events.Length);
        Assert.True(session.Run.Events[0].Failed);
        Assert.Equal(parent, session.Run.Events[1].Definition);
        Assert.Equal(new BigInteger(1), session.Run.Events[1].RecordCount);
    }

    [Fact]
    public void Caught_child_failure_restores_parent_cursor_before_parent_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        var parent = new ParserDiagnosticDefinition("synthetic.normal_parent", "parent-v1");
        var original = new InvalidOperationException("not retained");
        var error = Assert.Throws<InvalidOperationException>(() => ParserDiagnostics.Run<int>(parent, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
            var child = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcsLayout([]));
            Assert.Equal(BigInteger.Zero, ParserDiagnostics.GetFailure(child)!.Location!["offset"]);
            throw original;
        }));
        Assert.Same(original, error);
        var observation = ParserDiagnostics.GetFailure(error)!;
        Assert.Equal(parent, observation.Definition);
        Assert.Equal(new BigInteger(7), observation.Location!["offset"]);
        Assert.Equal("outer", observation.Location["field"]);
        Assert.Equal(2, session.Run.Events.Length);
    }

    [Fact]
    public async Task Independent_concurrent_calls_keep_diagnostic_inputs_separate()
    {
        var runs = await Task.WhenAll(Enumerable.Range(0, 12).Select(index => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            var row = Fixture("basic-reviewed-fields");
            byte[] npc = Raw(row, "npc");
            npc[^1] = (byte)index; // An ignored byte changes identity, not the reviewed output fields.
            Assert.Single(NormalAttackCatalogParser.ParseNpcsLayout(npc));
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(npc)), observation.Inputs["raw"].Sha256);
            return observation.Inputs["raw"].Sha256;
        })));
        Assert.Equal(12, runs.Distinct().Count());
        Assert.False(ParserDiagnostics.IsActive);
    }

    [Fact]
    public void Diagnostics_and_results_do_not_retain_caller_arrays()
    {
        using var session = ParserDiagnostics.BeginSession();
        var (weak, result, error) = ReleaseCallerInput();
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        Assert.False(weak.IsAlive);
        Assert.Single(result);
        Assert.NotNull(ParserDiagnostics.GetFailure(error));
        Assert.Single(session.Run.Events); // A failure replaces the same parser/input success observation.
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static (WeakReference, IReadOnlyDictionary<ushort, NormalAttackNpcData>, CatalogDecodeException) ReleaseCallerInput()
    {
        byte[] raw = Raw(Fixture("basic-reviewed-fields"), "npc");
        var parsed = NormalAttackCatalogParser.ParseNpcsLayout(raw);
        var error = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcs(raw));
        return (new WeakReference(raw), parsed, error);
    }

    private static object Parse(JsonElement row)
    {
        byte[] npc = Raw(row, "npc");
        string mode = row.GetProperty("mode").GetString()!;
        if (mode.StartsWith("npc", StringComparison.Ordinal))
            return Project(mode == "npc-public" ? NormalAttackCatalogParser.ParseNpcs(npc)
                : NormalAttackCatalogParser.ParseNpcsLayout(npc));
        byte[] item = Raw(row, "item");
        var result = mode == "build-public" ? NormalAttackCatalogParser.BuildCatalog(npc, item)
            : NormalAttackCatalogParser.BuildCatalogLayout(npc, item);
        return new Dictionary<string, object>
        {
            ["npcs"] = Project(result.Npcs),
            ["items"] = result.ItemKinds.ToDictionary(pair => Key(pair.Key), pair => pair.Value),
            ["catch_nets"] = result.CatchNets.ToDictionary(pair => Key(pair.Key), pair => pair.Value)
        };
    }

    private static object Project(IReadOnlyDictionary<ushort, NormalAttackNpcData> rows) => rows.ToDictionary(
        pair => Key(pair.Key), pair => new Dictionary<string, object>
        {
            ["kind"] = pair.Value.Kind, ["bodyType"] = pair.Value.BodyType,
            ["normalAttackKind"] = pair.Value.NormalAttackKind, ["canCatch"] = pair.Value.CanCatch
        });
    private static string Key(ushort id) => id.ToString(CultureInfo.InvariantCulture);
    private static byte[] Raw(JsonElement row, string property) => Convert.FromBase64String(row.GetProperty(property).GetString()!);
    private static JsonElement Fixture(string name) => NormalAttackPythonVectors.FindCase(name);
    private static void AssertJson(JsonElement expected, object actual) =>
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(expected.GetRawText()), JsonSerializer.SerializeToNode(actual)),
            "Retained Python and C# values differ.");
}
