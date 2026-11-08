using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Text;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Resources.Inventory;
using Lala.Core.Tests.Catalogs;
using Lala.Core.Tests.Catalogs.RequiredTables;
using Lala.Core.Tests.Catalogs.SmithStage;
using Lala.Core.Tests.Catalogs.TextBattleTalk;
using Lala.Core.Tests.World.Eve;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.Resources.Inventory;

public sealed class InventoryDerivedRowsTests
{
    // Discover scalar IDs without visiting payload-bearing retained arrays.
    public static IEnumerable<object[]> ItemCases()
    {
        foreach (string name in new[] { "legacy-all-fields", "reviewed-all-fields", "reviewed-skill-link" }) yield return [name];
        for (int index = 0; index < 12; index++)
        {
            yield return [$"reviewed-variation-{index}"];
            if (index != 2) yield return [$"legacy-variation-{index}"];
        }
        yield return ["two-reviewed-records"];
    }

    [Theory]
    [MemberData(nameof(ItemCases))]
    public void Item_fields_match_retained_python_without_faking_reviewed_hash_acceptance(string name)
    {
        var fixture = PythonCatalogVectors.ItemCases().Single(row => (string)row[0]! == name);
        byte[] raw = Convert.FromBase64String((string)fixture[1]!);
        bool reviewed = (bool)fixture[2]!, includeLink = (bool)fixture[3]!;
        using var document = JsonDocument.Parse((string)fixture[4]!);
        if (!reviewed)
        {
            AssertRows(document.RootElement, InventoryDerivedRows.Parse("items_v1", raw));
            return;
        }
        // These bytes are synthetic layout fixtures, never accepted as the independently
        // pinned source. Exercise only the typed row-to-JSON helper for reviewed fields.
        var rows = ItemDataParser.ParseLayout(raw, reviewed, includeLink);
        foreach (var row in document.RootElement.EnumerateObject())
            Assert.Equal(ExpectedJson(row.Value), InventoryDerivedRows.SerializeItemRow(
                rows[ushort.Parse(row.Name, CultureInfo.InvariantCulture)]));
    }

    [Fact]
    public void Item_source_pin_is_not_bypassed_and_legacy_rows_keep_source_order()
    {
        var reviewed = PythonCatalogVectors.ItemCases().Single(row => (string)row[0]! == "reviewed-all-fields");
        byte[] unpinned = Convert.FromBase64String((string)reviewed[1]!);
        var failure = Assert.Throws<CatalogDecodeException>(() => InventoryDerivedRows.Parse("items_v1", unpinned));
        Assert.Equal("ItemData record layout changed or trailing bytes", failure.Message);
        Assert.NotNull(ParserDiagnostics.GetFailure(failure));

        var legacy = PythonCatalogVectors.ItemCases().Single(row => (string)row[0]! == "legacy-all-fields");
        byte[] first = Convert.FromBase64String((string)legacy[1]!);
        byte[] raw = new byte[4 + (first.Length - 4) * 2];
        BinaryPrimitives.WriteInt32LittleEndian(raw, 2);
        first.AsSpan(4).CopyTo(raw.AsSpan(4)); first.AsSpan(4).CopyTo(raw.AsSpan(first.Length));
        int kindName = 4 + 2 + BinaryPrimitives.ReadUInt16LittleEndian(first.AsSpan(4)) + 1;
        int itemId = kindName + 2 + BinaryPrimitives.ReadUInt16LittleEndian(first.AsSpan(kindName));
        BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(first.Length + itemId - 4), 1);
        var result = InventoryDerivedRows.Parse("items_v1", raw);
        Assert.Equal(new[] { "321", "1" }, result.Select(row => row.Key));
        Assert.Equal(result[0].Value, result[1].Value); // Item ID is the key, not a JSON field.
        using var rowDocument = JsonDocument.Parse(result[0].Value);
        Assert.Equal(6, rowDocument.RootElement.EnumerateObject().Count());
        Assert.False(rowDocument.RootElement.TryGetProperty("skill_link", out _));
        Assert.False(rowDocument.RootElement.TryGetProperty("item_id", out _));
    }

    public static IEnumerable<object[]> SmithStageCases()
    {
        foreach (string name in new[] { "reviewed-basic", "reviewed-35-basic", "stage-basic", "stage-source-order" })
            yield return [name];
        for (int index = 0; index < 40; index++)
        {
            yield return [$"seeded-reviewed35-{index}"];
            yield return [$"seeded-stage-{index}"];
        }
    }

    [Theory]
    [MemberData(nameof(SmithStageCases))]
    public void Smith_and_stage_exact_sorted_json_matches_python_source_fields_and_order(string name)
    {
        var fixture = SmithStagePythonVectors.FindCase(name);
        bool stage = fixture.GetProperty("mode").GetString() == "stage";
        var result = InventoryDerivedRows.Parse(stage ? "scenes_v1" : "smith_v1", Raw(fixture));
        var expected = fixture.GetProperty("expected");
        if (stage) AssertRows(expected, result);
        else
        {
            var rows = expected.EnumerateArray().ToArray();
            Assert.Equal(rows.Length, result.Length);
            for (int index = 0; index < rows.Length; index++)
            {
                var row = rows[index];
                var key = row.TryGetProperty("recipe_id", out var recipe) ? recipe :
                    row.TryGetProperty("candidate_row_key", out var candidate) ? candidate : row.GetProperty("item_id");
                Assert.Equal(key.GetRawText(), result[index].Key);
                Assert.Equal(ExpectedJson(row), result[index].Value);
            }
            if (name == "reviewed-basic")
                Assert.All(result, row =>
                {
                    Assert.DoesNotContain("recipe_id", row.Value);
                    Assert.DoesNotContain("candidate_row_key", row.Value);
                    Assert.Contains("\"read_only\":", row.Value);
                });
        }
    }

    [Theory]
    [InlineData("talk-basic")]
    [InlineData("talk-order")]
    public void Talk_projects_text_and_voice_only_in_source_order(string name)
    {
        var fixture = Enumerable.Range(0, RequiredTableOracleCases.VectorCount)
            .Select(RequiredTableOracleCases.Case).First(row => row.GetProperty("name").GetString() == name);
        byte[] raw = Convert.FromBase64String(fixture.GetProperty("inputs").GetProperty("raw").GetProperty("base64").GetString()!);
        AssertRows(fixture.GetProperty("expected"), InventoryDerivedRows.Parse("talk_v1", raw));
    }

    [Theory]
    [InlineData("text-basic")]
    [InlineData("text-empty")]
    [InlineData("text-embedded-nul")]
    [InlineData("text-bom")]
    [InlineData("text-non-bmp")]
    [InlineData("text-ascii")]
    [InlineData("text-newline")]
    [InlineData("text-maximum-even-length")]
    [InlineData("text-key-source-order")]
    public void Text_is_a_json_string_with_exact_python_escaping_and_source_order(string name)
    {
        var fixture = TextBattleTalkPythonVectors.FindCase(name);
        AssertRows(fixture.GetProperty("expected"), InventoryDerivedRows.Parse("text_v1", Raw(fixture)));
    }

    [Fact]
    public void Text_ascii_html_del_nuls_and_non_bmp_escape_exactly_without_locale_changes()
    {
        const string input = "<>&+'\"\\\b\f\n\r\t\0\u007f甲😀";
        byte[] text = Encoding.Unicode.GetBytes(input);
        byte[] raw = new byte[10 + text.Length];
        BinaryPrimitives.WriteInt32LittleEndian(raw, 1);
        BinaryPrimitives.WriteUInt32LittleEndian(raw.AsSpan(4), uint.MaxValue);
        BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(8), (ushort)text.Length);
        text.CopyTo(raw, 10);
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            var row = Assert.Single(InventoryDerivedRows.Parse("text_v1", raw));
            Assert.Equal("4294967295", row.Key);
            Assert.Equal("\"<>&+'\\\"\\\\\\b\\f\\n\\r\\t\\u0000\\u007f\\u7532\\ud83d\\ude00\"", row.Value);
        }
        finally { CultureInfo.CurrentCulture = previous; }
    }

    [Theory]
    [InlineData("basic")]
    [InlineData("all-empty")]
    [InlineData("every-section-variable-arrays")]
    [InlineData("max-field-widths")]
    [InlineData("zero-index-coordinates-event-item")]
    [InlineData("unsorted-header-byte-numeric-lexical-order")]
    [InlineData("invalid-form-0")]
    [InlineData("duplicate-npc-index")]
    [InlineData("duplicate-interaction-index")]
    [InlineData("duplicate-scene-override-source-bug")]
    public void Eve_sources_independently_follow_derived_json_order_and_reject_duplicates(string name)
    {
        foreach (var id in EvePythonVectors.Cases().Where(row => (string)row[0] == name))
        {
            var fixture = EvePythonVectors.ReadCase((int)id[1], (int)id[2]);
            string? source = fixture.GetProperty("source").GetString();
            if (source is null) continue;
            string inventorySource = source == EveV115Parser.NpcSource ? "eve_npc_v1" : "eve_interact_v1";
            byte[] raw = Convert.FromBase64String(fixture.GetProperty("raw").GetString()!);
            Array.Resize(ref raw, raw.Length + fixture.GetProperty("zero_padding").GetInt32());
            if (fixture.GetProperty("divergence").GetBoolean())
            {
                Assert.Equal("Duplicate scene ID or out-of-bounds offset",
                    Assert.Throws<EveDecodeException>(() => InventoryDerivedRows.Parse(inventorySource, raw)).Message);
                continue;
            }
            if (fixture.GetProperty("error").ValueKind == JsonValueKind.String)
            {
                Assert.Equal(fixture.GetProperty("error").GetString(),
                    Assert.Throws<EveDecodeException>(() => InventoryDerivedRows.Parse(inventorySource, raw)).Message);
                continue;
            }
            using var expected = JsonDocument.Parse(fixture.GetProperty("documents").GetProperty(source).GetString()!);
            var rows = expected.RootElement.GetProperty("scenes").EnumerateObject()
                .SelectMany(scene => scene.Value.EnumerateArray().Select(row => KeyValuePair.Create(
                    scene.Name + ":" + row.GetProperty("index").GetRawText(), ExpectedJson(row)))).ToArray();
            using var session = ParserDiagnostics.BeginSession();
            Assert.Equal(rows, InventoryDerivedRows.Parse(inventorySource, raw));
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal("wlre.services.world.eve_v115.derive_eve_index", observation.Definition.Parser);
            Assert.Null(observation.RecordCount);
        }
    }

    [Fact]
    public void Cancellation_precedes_source_validation_and_never_returns_partial_rows()
    {
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        foreach (string source in new[] { "items_v1", "smith_v1", "talk_v1", "text_v1", "scenes_v1", "eve_npc_v1", "eve_interact_v1", "unknown" })
            Assert.Equal(cancelled.Token, Assert.Throws<OperationCanceledException>(
                () => InventoryDerivedRows.Parse(source, [], cancelled.Token)).CancellationToken);
        using var midstream = new CancellationTokenSource();
        Assert.Throws<OperationCanceledException>(() => InventoryDerivedRows.Project(CancelRows(), midstream.Token));
        IEnumerable<KeyValuePair<string, object?>> CancelRows()
        {
            yield return new("1", "first");
            midstream.Cancel();
            yield return new("2", "second");
        }
    }

    [Fact]
    public void Serializer_quotas_are_fatal_invalid_data_and_not_source_parse_failures()
    {
        using var session = ParserDiagnostics.BeginSession();
        string exactly = new('x', InventoryDerivedRows.MaximumRowJsonBytes - 2);
        Assert.Equal(InventoryDerivedRows.MaximumRowJsonBytes,
            Assert.Single(InventoryDerivedRows.Project([new("1", exactly)])).Value.Length);
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.Project([new("1", exactly + "x")]));
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.Project([new("1", new string('甲', 43_691))]));
        InventoryDerivedRows.ValidateViewLimits(1_000_000, 64L * 1024 * 1024);
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.ValidateViewLimits(1_000_001, 2));
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.ValidateViewLimits(1, 64L * 1024 * 1024 + 1));
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Shared_report_serializer_sorts_recursively_by_python_unicode_order_with_own_budget()
    {
        using var document = JsonDocument.Parse("""{"😀":{"z":false,"a":[-2147483648,4294967295,null]},"":"甲<>&+","a":true}""");
        Assert.Equal("{\"a\":true,\"\\ue000\":\"\\u7532<>&+\",\"\\ud83d\\ude00\":{\"a\":[-2147483648,4294967295,null],\"z\":false}}",
            InventoryDerivedRows.CanonicalJson(document.RootElement));
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.CanonicalJson(document.RootElement, maximumBytes: 10));

        string large = JsonSerializer.Serialize(new string('x', InventoryDerivedRows.MaximumRowJsonBytes));
        using var largeDocument = JsonDocument.Parse(large);
        Assert.Equal(large, InventoryDerivedRows.CanonicalJson(largeDocument.RootElement));
        Assert.Throws<InvalidDataException>(() => InventoryDerivedRows.CanonicalJson(
            largeDocument.RootElement, maximumBytes: InventoryDerivedRows.MaximumRowJsonBytes));
    }

    [Theory]
    [InlineData("items_v1")]
    [InlineData("smith_v1")]
    [InlineData("talk_v1")]
    [InlineData("text_v1")]
    [InlineData("scenes_v1")]
    public void Catalog_parse_failures_keep_original_type_and_diagnostics(string source)
    {
        var failure = Assert.Throws<CatalogDecodeException>(() => InventoryDerivedRows.Parse(source, []));
        Assert.NotNull(ParserDiagnostics.GetFailure(failure));
        Assert.Null(failure.InnerException);
    }

    private static byte[] Raw(JsonElement fixture) =>
        Convert.FromBase64String(fixture.GetProperty("raw").GetProperty("base64").GetString()!);

    private static void AssertRows(JsonElement expected, ImmutableArray<KeyValuePair<string, string>> actual) =>
        Assert.Equal(expected.EnumerateObject().Select(row => KeyValuePair.Create(row.Name, ExpectedJson(row.Value))), actual);

    // Preserve each primitive's exact retained Python JSON spelling, sorting only objects.
    // This oracle projection neither uses the production serializer nor re-encodes strings.
    private static string ExpectedJson(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Object => "{" + string.Join(",", value.EnumerateObject()
            .OrderBy(property => property.Name, StringComparer.Ordinal)
            .Select(property => JsonSerializer.Serialize(property.Name) + ":" + ExpectedJson(property.Value))) + "}",
        JsonValueKind.Array => "[" + string.Join(",", value.EnumerateArray().Select(ExpectedJson)) + "]",
        _ => value.GetRawText()
    };
}
