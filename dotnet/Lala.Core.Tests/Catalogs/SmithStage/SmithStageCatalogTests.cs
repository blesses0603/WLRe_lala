using System.Buffers.Binary;
using System.Collections;
using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Xunit;

namespace Lala.Core.Tests.Catalogs.SmithStage;

public sealed class SmithStageCatalogTests
{
    [Theory]
    [MemberData(nameof(SmithStagePythonVectors.Cases), MemberType = typeof(SmithStagePythonVectors))]
    public void Actual_decorated_python_values_errors_order_and_diagnostics_match(string name, int fixture, int index)
    {
        var row = SmithStagePythonVectors.ReadCase(fixture, index);
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
        var expected = row.GetProperty("diagnostics");
        Assert.Equal(expected.GetArrayLength(), session.Run.Events.Length);
        for (int i = 0; i < expected.GetArrayLength(); i++) AssertDiagnostic(expected[i], session.Run.Events[i]);
        if (error is not null)
            AssertDiagnostic(row.GetProperty("failure"), ParserDiagnostics.GetFailure(error)!, includeIdentity: false);
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(SmithStagePythonVectors.Sources), MemberType = typeof(SmithStagePythonVectors))]
    public void Oracle_source_hashes_ignore_only_CRLF_checkout_conversion(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void Discovery_contains_unique_bounded_scalar_ids_and_lazy_resource_coordinates()
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        var positions = new HashSet<(int, int)>();
        foreach (var entry in SmithStagePythonVectors.Cases())
        {
            Assert.Equal(3, entry.Length);
            string name = Assert.IsType<string>(entry[0]);
            Assert.InRange(name.Length, 1, 80);
            Assert.All(name, character => Assert.InRange((int)character, 32, 126));
            int fixture = Assert.IsType<int>(entry[1]), index = Assert.IsType<int>(entry[2]);
            Assert.True(names.Add(name)); Assert.True(positions.Add((fixture, index)));
            Assert.Equal(name, SmithStagePythonVectors.ReadCase(fixture, index).GetProperty("name").GetString());
        }
        Assert.Equal(SmithStagePythonVectors.VectorCount, names.Count);
        Assert.Equal(names.Count, SmithStagePythonVectors.FixtureCaseCount);
    }

    [Fact]
    public void Ordered_results_are_owned_immutable_and_do_not_expose_frozen_map_order()
    {
        byte[] raw = Raw(Fixture("smith33-source-order"));
        byte[] envelope = new byte[raw.Length + 9]; raw.CopyTo(envelope, 5);
        var recipes = SmithDataParser.Parse33(envelope.AsSpan(5, raw.Length));
        Array.Fill(raw, (byte)255); Array.Fill(envelope, (byte)255);
        Assert.Equal(new ushort[] { 65535, 90, 1, 65534 }, recipes.Keys);
        Assert.Equal(recipes.Keys, recipes.Values.Select(row => row.ItemId));
        Assert.Equal(recipes.Keys, ((IEnumerable)recipes).Cast<KeyValuePair<ushort, SmithRecipe>>().Select(pair => pair.Key));
        Assert.False(recipes is IDictionary); Assert.False(recipes is IDictionary<ushort, SmithRecipe>);
        Assert.True(recipes.ContainsKey(90)); Assert.True(recipes.TryGetValue(90, out var recipe));
        Assert.Same(recipes[90], recipe); Assert.False(recipes.TryGetValue(0, out _));
        Assert.Throws<KeyNotFoundException>(() => recipes[0]);
        Assert.Throws<NotSupportedException>(() => ((IList<SmithMaterial>)recipes[90].Materials)[0] = new(99, 0));
        var copy = recipes[90] with { ItemId = 42, Materials = recipes[90].Materials.SetItem(0, new(99, 0)) };
        Assert.Equal(42, copy.ItemId); Assert.Equal(90, recipes[90].ItemId);
        Assert.Equal(20, recipes[90].Materials[0].ItemId);
        Assert.All(recipes.Values, row => { Assert.Null(row.RecipeId); Assert.Null(row.CandidateRowKey); Assert.Null(row.ReadOnly); });

        var stages = StageDataParser.Parse(Raw(Fixture("stage-source-order")));
        Assert.Equal(new ushort[] { 65535, 90, 0, 1, 65534 }, stages.Keys);
        Assert.Equal(stages.Keys, stages.Values.Select(row => row.Id));
        Assert.False(stages is IDictionary); Assert.False(stages is IDictionary<ushort, StageDataRow>);
        Assert.Equal(stages.Keys, ((IEnumerable)stages).Cast<KeyValuePair<ushort, StageDataRow>>().Select(pair => pair.Key));
        Assert.True(stages.TryGetValue(0, out var stage)); Assert.Same(stages[0], stage);
    }

    [Fact]
    public void Candidate_rows_keep_duplicate_outputs_keys_order_and_optional_timed_field()
    {
        var rows = SmithDataParser.ParseCandidate(Raw(Fixture("candidate-basic")));
        Assert.Equal(new ushort[] { 123, 123 }, rows.Select(row => row.ItemId));
        Assert.Equal(new ushort?[] { 90, 1 }, rows.Select(row => row.RecipeId));
        Assert.Equal(rows.Select(row => row.RecipeId), rows.Select(row => row.CandidateRowKey));
        Assert.Equal(new[] { 1, 2 }, rows.Select(row => row.Order));
        Assert.All(rows, row => Assert.Null(row.ReadOnly));
        Assert.Throws<NotSupportedException>(() => ((IList<SmithRecipe>)rows)[0] = rows[1]);
        var marked = SmithDataParser.MarkTimedRecipes(rows);
        Assert.Equal(new bool?[] { false, true }, marked.Select(row => row.ReadOnly));
        Assert.All(rows, row => Assert.Null(row.ReadOnly));
        Assert.NotSame(rows[0], marked[0]);
        Assert.Equal(marked.ToArray(), SmithDataParser.MarkTimedRecipes(marked).ToArray());
        using var session = ParserDiagnostics.BeginSession();
        Assert.Empty(SmithDataParser.MarkTimedRecipes([]));
        Assert.Equal("Recipe time condition is missing or invalid", Assert.Throws<CatalogDecodeException>(() =>
            SmithDataParser.MarkTimedRecipes(default)).Message);
        Assert.Throws<CatalogDecodeException>(() => SmithDataParser.MarkTimedRecipes([null!]));
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Nested_reviewed_failure_records_each_source_cursor_and_preserves_outer_cursor()
    {
        using var session = ParserDiagnostics.BeginSession();
        var definition = new ParserDiagnosticDefinition("synthetic.smith_parent", "parent-v1");
        var original = new InvalidOperationException("private exception text");
        Assert.Same(original, Assert.Throws<InvalidOperationException>(() => ParserDiagnostics.Run<int>(definition, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
            Assert.Equal(2, SmithDataParser.ParseRecords(Raw(Fixture("reviewed-35-basic"))).Length);
            Assert.Empty(session.Run.Events);
            var failure = Assert.Throws<CatalogDecodeException>(() => SmithDataParser.ParseRecords(Raw(Fixture("reviewed-late-zero-item-35"))));
            Assert.Equal(3, session.Run.Events.Length);
            Assert.Equal(new BigInteger(39), ParserDiagnostics.GetFailure(failure)!.Location!["offset"]);
            Assert.Equal("smith-35-v1", ParserDiagnostics.GetFailure(failure)!.Location!["profile"]);
            Assert.False(ParserDiagnostics.GetFailure(failure)!.Location!.ContainsKey("record"));
            throw original;
        })));
        Assert.Equal(4, session.Run.Events.Length);
        Assert.Equal(new BigInteger(7), ParserDiagnostics.GetFailure(original)!.Location!["offset"]);
        Assert.Equal("outer", ParserDiagnostics.GetFailure(original)!.Location!["field"]);
    }

    [Fact]
    public void Cancellation_precedes_validation_and_is_never_a_layout_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        foreach (var action in new Action[]
        {
            () => SmithDataParser.Parse33([], cancelled.Token),
            () => SmithDataParser.ParseCandidate([], cancelled.Token),
            () => SmithDataParser.ParseRecords([], cancelled.Token),
            () => SmithDataParser.MarkTimedRecipes(default, cancelled.Token),
            () => StageDataParser.Parse([], cancelled.Token),
            () => SmithDataParser.ParseRecords(Raw(Fixture("reviewed-35-basic")), cancelled.Token),
            () => StageDataParser.Parse(Raw(Fixture("stage-basic")), cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(action);
            Assert.Equal(cancelled.Token, error.CancellationToken); Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
        Assert.Empty(SmithDataParser.ParseRecords([0, 0, 0, 0]));
        Assert.Equal("smith-33-v1", Assert.Single(session.Run.Events).SelectedSchema);
    }

    [Fact]
    public void Oversized_inputs_do_not_copy_and_preserve_count_before_layout_or_trailing_checks()
    {
        byte[] smith = new byte[SmithDataParser.MaxBytes + 1];
        byte[] stage = new byte[StageDataParser.MaxBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        var smithError = Assert.Throws<CatalogDecodeException>(() => SmithDataParser.Parse33(smith));
        var stageError = Assert.Throws<CatalogDecodeException>(() => StageDataParser.Parse(stage));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 200_000);
        Assert.Equal("1275 配方筆數或長度不符", smithError.Message);
        Assert.Equal($"unexpected trailing bytes: {stage.Length - 4}", stageError.Message);
        Assert.Equal(smith.Length, ParserDiagnostics.GetFailure(smithError)!.Inputs["data"].Size);
        Assert.Equal(stage.Length, ParserDiagnostics.GetFailure(stageError)!.Inputs["data"].Size);
        Assert.Empty(ParserDiagnostics.GetFailure(smithError)!.Location!);
        Assert.Equal(new BigInteger(4), ParserDiagnostics.GetFailure(stageError)!.Location!["offset"]);
    }

    [Fact]
    public void Diagnostics_release_arrays_and_do_not_retain_payload_or_raw_error_messages()
    {
        using var session = ParserDiagnostics.BeginSession();
        var (weak, error) = ReleaseInput();
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        Assert.False(weak.IsAlive);
        Assert.NotNull(ParserDiagnostics.GetFailure(error));
        string report = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("private-catalog-sentinel", report);
        Assert.DoesNotContain("重複", report); Assert.DoesNotContain("need", report);
        Assert.DoesNotContain("base64", report); Assert.DoesNotContain("message", report);
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static (WeakReference, CatalogDecodeException) ReleaseInput()
    {
        byte[] raw = Encoding.UTF8.GetBytes("private-catalog-sentinel");
        BinaryPrimitives.WriteInt32LittleEndian(raw, 1);
        var error = Assert.Throws<CatalogDecodeException>(() => StageDataParser.Parse(raw));
        return (new WeakReference(raw), error);
    }

    [Fact]
    public async Task Concurrent_diagnostics_remain_isolated_and_non_authorizing()
    {
        var hashes = await Task.WhenAll(Enumerable.Range(1, 12).Select(index => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            byte[] raw = Raw(Fixture("smith33-item-1"));
            BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(4), (ushort)index);
            Assert.Single(SmithDataParser.Parse33(raw));
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), observation.Inputs["data"].Sha256);
            Assert.False(session.Run.AssetsReady); Assert.False(session.Run.CanSendPackets);
            return observation.Inputs["data"].Sha256;
        })));
        Assert.Equal(12, hashes.Distinct().Count()); Assert.False(ParserDiagnostics.IsActive);
    }

    private static object Parse(JsonElement row)
    {
        object result = ParseRows(row);
        if (!row.GetProperty("summary").GetBoolean()) return result;
        int count = result is IDictionary map ? map.Count : ((Array)result).Length;
        return new { count, sha256 = Convert.ToHexStringLower(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(result))) };
    }

    private static object ParseRows(JsonElement row)
    {
        byte[] raw = Raw(row);
        string mode = row.GetProperty("mode").GetString()!;
        if (mode == "stage")
        {
            var stages = StageDataParser.Parse(raw);
            if (!row.GetProperty("summary").GetBoolean()) Assert.Equal(row.GetProperty("expected").EnumerateObject().Select(p => ushort.Parse(p.Name, CultureInfo.InvariantCulture)), stages.Keys);
            return stages.ToDictionary(pair => pair.Key, pair => (object)new
            {
                id = pair.Value.Id, name_id = pair.Value.NameId, model_id = pair.Value.ModelId,
                max_members = pair.Value.MaxMembers, min_members = pair.Value.MinMembers,
                min_level = pair.Value.MinLevel, time_minutes = pair.Value.TimeMinutes, tag = pair.Value.Tag,
                room_capacity = pair.Value.RoomCapacity, group = pair.Value.Group, flag = pair.Value.Flag,
                pos_x_ratio = pair.Value.PosXRatio, pos_y_ratio = pair.Value.PosYRatio,
                map_width = pair.Value.MapWidth, map_height = pair.Value.MapHeight,
                small_offset_x = pair.Value.SmallOffsetX, small_offset_y = pair.Value.SmallOffsetY
            });
        }
        if (mode == "smith33")
        {
            var recipes = SmithDataParser.Parse33(raw);
            if (!row.GetProperty("summary").GetBoolean()) Assert.Equal(row.GetProperty("expected").EnumerateObject().Select(p => ushort.Parse(p.Name, CultureInfo.InvariantCulture)), recipes.Keys);
            return recipes.ToDictionary(pair => pair.Key, pair => Project(pair.Value));
        }
        var rows = mode switch
        {
            "candidate" => SmithDataParser.ParseCandidate(raw),
            "reviewed" => SmithDataParser.ParseRecords(raw),
            "mark33" => SmithDataParser.MarkTimedRecipes(SmithDataParser.Parse33(raw).Values.ToImmutableArray()),
            _ => throw new InvalidDataException("Unknown retained fixture mode")
        };
        return rows.Select(Project).ToArray();
    }

    private static Dictionary<string, object> Project(SmithRecipe row)
    {
        var result = new Dictionary<string, object>
        {
            ["item_id"] = row.ItemId, ["design_id"] = row.DesignId, ["skill"] = row.Skill,
            ["tool_id"] = row.ToolId, ["output"] = row.Output,
            ["materials"] = row.Materials.Select(material => new { item_id = material.ItemId, count = material.Count }).ToArray(),
            ["seconds"] = row.Seconds, ["skill_level"] = row.SkillLevel, ["suggest"] = row.Suggest,
            ["time_id"] = row.TimeId, ["limit_kind"] = row.LimitKind, ["mark_id"] = row.MarkId,
            ["limit_times"] = row.LimitTimes, ["order"] = row.Order
        };
        if (row.RecipeId is { } recipe) result["recipe_id"] = recipe;
        if (row.CandidateRowKey is { } key) result["candidate_row_key"] = key;
        if (row.ReadOnly is { } readOnly) result["read_only"] = readOnly;
        return result;
    }

    private static void AssertDiagnostic(JsonElement expectedElement, ParserDiagnosticEvent actualEvent, bool includeIdentity = true)
    {
        Assert.NotNull(actualEvent);
        var expected = JsonNode.Parse(expectedElement.GetRawText())!;
        if (expected["error_type"] is not null)
        {
            Assert.Contains(expected["error_type"]!.GetValue<string>(), new[] { "ValueError", "ProtocolError", "PreviewError" });
            expected["error_type"] = nameof(CatalogDecodeException);
        }
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(actualEvent), default).AsSpan())!;
        if (!includeIdentity) actual.AsObject().Remove("identity");
        Assert.True(JsonNode.DeepEquals(expected, actual), "Retained Python and C# diagnostics differ: " + actual);
    }
    private static JsonElement Fixture(string name) => SmithStagePythonVectors.FindCase(name);
    private static byte[] Raw(JsonElement row)
    {
        var spec = row.GetProperty("raw");
        if (spec.TryGetProperty("base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        int count = spec.GetProperty("count").GetInt32();
        string kind = spec.GetProperty("kind").GetString()!;
        int width = kind.StartsWith("stage-", StringComparison.Ordinal) ? 76 : kind == "smith33-rows" ? 33 : 35;
        byte[] result = new byte[4 + count * width];
        BinaryPrimitives.WriteInt32LittleEndian(result, count);
        for (int index = 0; index < count; index++)
        {
            var record = result.AsSpan(4 + index * width, width);
            if (width == 76)
            {
                record.Fill(1);
                BinaryPrimitives.WriteUInt16LittleEndian(record, (ushort)(kind == "stage-rows" ? count - index : 456));
                continue;
            }
            ushort item = (ushort)(width == 33 ? index + 1 : 123);
            if (width == 35)
            {
                BinaryPrimitives.WriteUInt16LittleEndian(record, (ushort)(index + 1));
                record = record[2..];
            }
            BinaryPrimitives.WriteUInt16LittleEndian(record, item);
            BinaryPrimitives.WriteUInt16LittleEndian(record[2..], 257);
            record[4] = 1;
            BinaryPrimitives.WriteUInt16LittleEndian(record[5..], 257);
            record[7] = 1;
            for (int slot = 0; slot < 5; slot++)
            {
                BinaryPrimitives.WriteUInt16LittleEndian(record[(8 + 3 * slot)..], (ushort)(20 + slot));
                record[10 + 3 * slot] = 1;
            }
            record[23] = 5;
            BinaryPrimitives.WriteUInt16LittleEndian(record[24..], 257);
            record[26] = record[27] = 1;
            BinaryPrimitives.WriteUInt16LittleEndian(record[28..], (ushort)(kind == "reviewed-rows" ? index % 2 : 0));
            record[30] = record[31] = record[32] = 1;
        }
        return result;
    }
    private static void AssertJson(JsonElement expected, object actual) => Assert.True(
        JsonNode.DeepEquals(JsonNode.Parse(expected.GetRawText()), JsonSerializer.SerializeToNode(actual)), "Retained Python and C# results differ.");
}
