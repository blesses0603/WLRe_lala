using System.Buffers.Binary;
using System.Collections;
using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.World.Eve;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs.SourceAdapters;

public sealed class CatalogSourceAdapterTests
{
    [Theory]
    [MemberData(nameof(SourceAdapterPythonVectors.Cases), MemberType = typeof(SourceAdapterPythonVectors))]
    public void Actual_decorated_python_source_pipeline_matches(string name, int fixture, int index)
    {
        var row = SourceAdapterPythonVectors.ReadCase(fixture, index);
        Assert.Equal(name, row.GetProperty("name").GetString());
        using var session = ParserDiagnostics.BeginSession();
        CatalogAdapterException? error = null;
        if (row.GetProperty("error").ValueKind == JsonValueKind.Null)
            AssertJson(row.GetProperty("expected"), Execute(row));
        else
        {
            error = Assert.Throws<CatalogAdapterException>(() => Execute(row));
            Assert.Equal(row.GetProperty("error").GetProperty("message").GetString(), error.Message);
            Assert.Null(error.InnerException);
        }
        var expected = row.GetProperty("diagnostics");
        Assert.Equal(expected.GetArrayLength(), session.Run.Events.Length);
        for (int i = 0; i < expected.GetArrayLength(); i++) AssertDiagnostic(expected[i], session.Run.Events[i]);
        if (error is not null)
        {
            if (row.GetProperty("failure").ValueKind == JsonValueKind.Null) Assert.Null(ParserDiagnostics.GetFailure(error));
            else AssertDiagnostic(row.GetProperty("failure"), ParserDiagnostics.GetFailure(error)!, includeIdentity: false);
        }
        Assert.False(session.Run.AssetsReady); Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(SourceAdapterPythonVectors.Sources), MemberType = typeof(SourceAdapterPythonVectors))]
    public void Source_hashes_normalize_only_CRLF(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    private static object Execute(JsonElement row)
    {
        var args = row.GetProperty("args");
        string mode = row.GetProperty("mode").GetString()!;
        if (mode == "contract") return Project(Contract(args)!);
        if (mode == "selected")
        {
            var result = CatalogSourceAdapters.ParseSelected(Text(args, "catalog_key"), Versions(args), Contracts(args), Payloads(args));
            Assert.Equal(CatalogSourceAdapters.Features, result.Keys);
            Assert.False(result is IDictionary);
            return result.ToDictionary(pair => pair.Key, pair => Project(pair.Value));
        }
        var catalog = CatalogSourceAdapters.ParseFeature(Text(args, "catalog_key"), Versions(args),
            Contract(args.GetProperty("contract")), Raw(args.GetProperty("raw")));
        object projected = Project(catalog);
        if (row.GetProperty("summary").GetBoolean())
            return new { record_count = catalog.RecordCount, sha256 = Convert.ToHexStringLower(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(projected))) };
        return projected;
    }
    private static string? Text(JsonElement element, string key) => element.GetProperty(key).GetString();
    private static CatalogSourceContract? Contract(JsonElement value) => value.ValueKind == JsonValueKind.Null ? null :
        new(Text(value, "feature"), Text(value, "source_name"), Text(value, "schema_id"), Text(value, "expected_sha256"), Text(value, "package"), Text(value, "package_version"));
    private static IReadOnlyDictionary<string, string>? Versions(JsonElement args) =>
        args.GetProperty("package_versions").ValueKind == JsonValueKind.Null ? null :
        args.GetProperty("package_versions").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!);
    private static IReadOnlyDictionary<string, CatalogSourceContract>? Contracts(JsonElement args) =>
        args.GetProperty("contracts").ValueKind == JsonValueKind.Null ? null :
        args.GetProperty("contracts").EnumerateObject().ToDictionary(p => p.Name, p => Contract(p.Value)!);
    private static IReadOnlyDictionary<string, ReadOnlyMemory<byte>>? Payloads(JsonElement args) =>
        args.GetProperty("source_payloads").ValueKind == JsonValueKind.Null ? null :
        args.GetProperty("source_payloads").EnumerateObject().ToDictionary(p => p.Name, p => (ReadOnlyMemory<byte>)Raw(p.Value));
    private static object Project(CatalogSourceContract value) => new { feature = value.Feature, source_name = value.SourceName,
        schema_id = value.SchemaId, expected_sha256 = value.ExpectedSha256, package = value.Package, package_version = value.PackageVersion };
    private static object Project(ParsedSourceCatalog value)
    {
        Assert.False(value.AssetsReady); Assert.False(value.CanSendPackets);
        return new { catalog_key = value.CatalogKey, feature = value.Feature, source_name = value.SourceName,
            schema_id = value.SchemaId, source_sha256 = value.SourceSha256, record_count = value.RecordCount,
            records = Project(value.Records), can_send_packets = value.CanSendPackets, assets_ready = value.AssetsReady };
    }
    private static object Project(CatalogSourceRecords records) => records switch
    {
        EveIndexSourceRecords index => index.Scenes.ToDictionary(pair => pair.Key, pair => pair.Value),
        SmithMapSourceRecords map => map.Rows.ToDictionary(pair => pair.Key, pair => Project(pair.Value)),
        SmithListSourceRecords list => list.Rows.Select(Project).ToArray(),
        StageSourceRecords stages => stages.Rows.ToDictionary(pair => pair.Key, pair => (object)new
        {
            id = pair.Value.Id, name_id = pair.Value.NameId, model_id = pair.Value.ModelId,
            max_members = pair.Value.MaxMembers, min_members = pair.Value.MinMembers,
            min_level = pair.Value.MinLevel, time_minutes = pair.Value.TimeMinutes, tag = pair.Value.Tag,
            room_capacity = pair.Value.RoomCapacity, group = pair.Value.Group, flag = pair.Value.Flag,
            pos_x_ratio = pair.Value.PosXRatio, pos_y_ratio = pair.Value.PosYRatio,
            map_width = pair.Value.MapWidth, map_height = pair.Value.MapHeight,
            small_offset_x = pair.Value.SmallOffsetX, small_offset_y = pair.Value.SmallOffsetY
        }),
        ItemSourceRecords items => items.Rows.ToDictionary(pair => pair.Key, pair => (object)new
        {
            name = pair.Value.Name, price = pair.Value.Price, sell_price = pair.Value.SellPrice,
            restrict = pair.Value.Restrict, open_used = pair.Value.OpenUsed, need_level = pair.Value.NeedLevel
        }),
        _ => throw new InvalidDataException("Unexpected result kind")
    };
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
            string kind = expected["error_type"]!.GetValue<string>();
            Assert.Contains(kind, new[] { "CatalogAdapterError", "ValueError", "ProtocolError", "PreviewError", "ItemDataDecodeError" });
            expected["error_type"] = kind == "CatalogAdapterError" ? nameof(CatalogAdapterException) : nameof(CatalogDecodeException);
        }
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(actualEvent), default).AsSpan())!;
        if (!includeIdentity) actual.AsObject().Remove("identity");
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => "Retained Python/C# diagnostics differ. Expected: " + expected + " Actual: " + actual);
    }
    private static void AssertJson(JsonElement expected, object actual)
    {
        var actualJson = JsonSerializer.SerializeToElement(actual);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(expected.GetRawText()), JsonNode.Parse(actualJson.GetRawText())),
            "Retained Python/C# results differ.");
        AssertOrder(expected, actualJson);
    }
    private static void AssertOrder(JsonElement expected, JsonElement actual)
    {
        if (expected.ValueKind == JsonValueKind.Object)
        {
            Assert.Equal(expected.EnumerateObject().Select(p => p.Name), actual.EnumerateObject().Select(p => p.Name));
            foreach (var property in expected.EnumerateObject()) AssertOrder(property.Value, actual.GetProperty(property.Name));
        }
        else if (expected.ValueKind == JsonValueKind.Array)
            for (int i = 0; i < expected.GetArrayLength(); i++) AssertOrder(expected[i], actual[i]);
    }
    private static byte[] Raw(JsonElement spec)
    {
        if (spec.TryGetProperty("base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        int count = spec.GetProperty("count").GetInt32();
        string kind = spec.GetProperty("kind").GetString()!;
        if (kind == "repeat-byte") return Enumerable.Repeat(spec.GetProperty("value").GetByte(), count).ToArray();
        if (kind is "npc-rows" or "shop-rows")
        {
            using var stream = new MemoryStream();
            using (var writer = new Utf8JsonWriter(stream))
            {
                writer.WriteStartObject(); writer.WriteNumber("schema_version", 1);
                writer.WriteString("source", kind == "npc-rows" ? EveV115Parser.NpcSource : EveV115Parser.InteractionSource);
                writer.WriteStartObject("scenes");
                for (int start = 0; start < count; start += 4096)
                {
                    writer.WriteStartArray((start / 4096).ToString(CultureInfo.InvariantCulture));
                    for (int i = 0; i < Math.Min(4096, count - start); i++)
                    {
                        writer.WriteStartObject(); writer.WriteNumber("index", i);
                        if (kind == "npc-rows")
                        { writer.WriteNumber("npc_id", 42); writer.WriteNumber("x", 150); writer.WriteNumber("y", 200); }
                        else
                        {
                            writer.WriteNumber("form_kind", 3); writer.WriteStartArray("items"); writer.WriteStartObject();
                            writer.WriteNumber("id", 1); writer.WriteNumber("text_id", 68); writer.WriteNumber("database_kind", 2); writer.WriteNumber("kind", 3);
                            writer.WriteEndObject(); writer.WriteEndArray();
                        }
                        writer.WriteEndObject();
                    }
                    writer.WriteEndArray();
                }
                writer.WriteEndObject(); writer.WriteNumber("record_count", count); writer.WriteEndObject();
            }
            return stream.ToArray();
        }
        if (kind == "item-rows")
        {
            using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
            writer.Write(count);
            for (int i = 0; i < count; i++)
            {
                writer.Write((ushort)2); writer.Write(Encoding.Unicode.GetBytes("A")); writer.Write((byte)1);
                writer.Write((ushort)4); writer.Write(Encoding.Unicode.GetBytes("雜物")); writer.Write((ushort)(i + 1));
                writer.Write(new byte[2 + 2 + 2 + 4 * 2 + 2 * (2 + 1 + 4) + 4 + 4 * 4 * 4]);
                writer.Write((byte)0); writer.Write((byte)10); writer.Write((uint)125); writer.Write((uint)55); writer.Write((byte)2); writer.Write((ushort)16);
                writer.Write(new byte[4 + 1 + 4 + 2 + 5 * 2]); writer.Write((ushort)0);
                writer.Write(new byte[3 + 2 + 1 + 1]); writer.Write(new byte[1 + 2 + 2 + 2 + 2 + 1 + 1 + 1]);
                writer.Write(new byte[1 + 1 + 1 + 2 + 2 + 2 + 2 + 2]); writer.Write(new byte[6 * 4]);
                writer.Write(new byte[2 + 2 + 1 + 1 + 1 + 1 + 1 + 1 + 2 + 1]); writer.Write(new byte[5 * 2]); writer.Write(new byte[1 + 2 + 2 + 2]);
            }
            return stream.ToArray();
        }
        int width = kind == "stage-rows" ? 76 : kind == "smith33-rows" ? 33 : 35;
        byte[] result = new byte[4 + count * width]; BinaryPrimitives.WriteInt32LittleEndian(result, count);
        for (int i = 0; i < count; i++)
        {
            var record = result.AsSpan(4 + i * width, width);
            if (width == 76) { record.Fill(1); BinaryPrimitives.WriteUInt16LittleEndian(record, (ushort)(count - i)); continue; }
            ushort item = (ushort)(width == 33 ? i + 1 : 123);
            if (width == 35) { BinaryPrimitives.WriteUInt16LittleEndian(record, (ushort)(i + 1)); record = record[2..]; }
            BinaryPrimitives.WriteUInt16LittleEndian(record, item); BinaryPrimitives.WriteUInt16LittleEndian(record[2..], 257);
            record[4] = 1; BinaryPrimitives.WriteUInt16LittleEndian(record[5..], 257); record[7] = 1;
            for (int slot = 0; slot < 5; slot++)
            { BinaryPrimitives.WriteUInt16LittleEndian(record[(8 + 3 * slot)..], (ushort)(20 + slot)); record[10 + 3 * slot] = 1; }
            record[23] = 5; BinaryPrimitives.WriteUInt16LittleEndian(record[24..], 257); record[26] = record[27] = 1;
            BinaryPrimitives.WriteUInt16LittleEndian(record[28..], (ushort)(width == 35 ? i % 2 : 0)); record[30] = record[31] = record[32] = 1;
        }
        return result;
    }

    [Fact]
    public void Discovery_is_unique_bounded_and_scalar_only()
    {
        var names = new HashSet<string>(); var positions = new HashSet<(int, int)>();
        foreach (var row in SourceAdapterPythonVectors.Cases())
        {
            Assert.Equal(3, row.Length); string name = Assert.IsType<string>(row[0]);
            Assert.InRange(name.Length, 1, 80); Assert.All(name, c => Assert.InRange((int)c, 32, 126));
            int f = Assert.IsType<int>(row[1]), i = Assert.IsType<int>(row[2]);
            Assert.True(names.Add(name)); Assert.True(positions.Add((f, i)));
            Assert.Equal(name, SourceAdapterPythonVectors.ReadCase(f, i).GetProperty("name").GetString());
        }
        Assert.Equal(SourceAdapterPythonVectors.VectorCount, names.Count);
        Assert.Equal(names.Count, SourceAdapterPythonVectors.FixtureCaseCount);
    }

    [Fact]
    public void Five_feature_result_is_ordered_owned_and_never_authorizes_runtime()
    {
        var args = SourceAdapterPythonVectors.FindCase("selected-all-five").GetProperty("args");
        var payloads = Payloads(args)!; var contracts = Contracts(args)!;
        var selected = CatalogSourceAdapters.ParseSelected(Text(args, "catalog_key"), Versions(args), contracts, payloads);
        Assert.Equal(CatalogSourceAdapters.Features, selected.Keys);
        Assert.Equal(selected.Keys, ((IEnumerable)selected).Cast<KeyValuePair<string, ParsedSourceCatalog>>().Select(p => p.Key));
        Assert.False(selected is IDictionary<string, ParsedSourceCatalog>);
        Assert.True(selected.TryGetValue("npc", out var npc)); Assert.Same(selected["npc"], npc);
        Assert.False(selected.TryGetValue("extra", out _)); Assert.Throws<KeyNotFoundException>(() => selected["extra"]);
        foreach (var raw in payloads.Values)
            if (System.Runtime.InteropServices.MemoryMarshal.TryGetArray(raw, out var segment)) segment.AsSpan().Fill(255);
        var items = Assert.IsType<ItemSourceRecords>(selected["items"].Records);
        Assert.Equal(new ushort[] { 90, 1 }, items.Rows.Keys);
        Assert.False(items.Rows is IDictionary<ushort, ItemDataRow>);
        var smith = Assert.IsType<SmithMapSourceRecords>(selected["crafting"].Records);
        Assert.All(smith.Rows.Values, row => Assert.Null(row.ReadOnly));
        var index = Assert.IsType<EveIndexSourceRecords>(npc!.Records);
        Assert.Equal(new[] { "90", "1" }, index.Scenes.Keys);
        Assert.False(index.Scenes is IDictionary<string, ImmutableArray<JsonElement>>);
        Assert.Throws<NotSupportedException>(() => ((IList<JsonElement>)index.Scenes["90"])[0] = default);
        Assert.All(selected.Values, value => { Assert.False(value.AssetsReady); Assert.False(value.CanSendPackets); });
    }

    [Fact]
    public void Mutating_source_after_a_sliced_parse_cannot_change_owned_rows()
    {
        var args = SourceAdapterPythonVectors.FindCase("npc-extra-fields").GetProperty("args");
        byte[] bytes = Raw(args.GetProperty("raw")); byte[] envelope = new byte[bytes.Length + 12]; bytes.CopyTo(envelope, 5);
        var result = CatalogSourceAdapters.ParseFeature(Text(args, "catalog_key"), Versions(args), Contract(args.GetProperty("contract")), envelope.AsSpan(5, bytes.Length));
        Array.Fill(bytes, (byte)0); Array.Fill(envelope, (byte)0);
        var rows = Assert.IsType<EveIndexSourceRecords>(result.Records);
        Assert.Equal("雪😀", rows.Scenes["90"][0].GetProperty("extra").GetProperty("text").GetString());
        Assert.Equal("123456789012345678901234567890", rows.Scenes["90"][0].GetProperty("extra").GetProperty("large").GetRawText());
    }

    [Fact]
    public void Eve_parser_outputs_feed_both_json_adapters_without_runtime_admission()
    {
        var eve = Lala.Core.Tests.World.Eve.EvePythonVectors.ReadCase(0, 0);
        var indexes = EveV115Parser.Parse(Convert.FromBase64String(eve.GetProperty("raw").GetString()!));
        var args = SourceAdapterPythonVectors.FindCase("selected-all-five").GetProperty("args");
        var contracts = Contracts(args)!.ToDictionary(p => p.Key, p => p.Value);
        var payloads = Payloads(args)!.ToDictionary(p => p.Key, p => p.Value);
        foreach (bool npcs in new[] { true, false })
        {
            byte[] raw = indexes.ToJsonUtf8(npcs ? EveV115Parser.NpcSource : EveV115Parser.InteractionSource).ToArray();
            string feature = npcs ? "npc" : "shops";
            var old = contracts[feature];
            contracts[feature] = new(feature, old.SourceName, old.SchemaId, Digest(raw), old.Package, old.PackageVersion);
            payloads[old.SourceName] = raw;
        }
        var selected = CatalogSourceAdapters.ParseSelected(Text(args, "catalog_key"), Versions(args), contracts, payloads);
        Assert.Equal(CatalogSourceAdapters.Features, selected.Keys);
        foreach (bool npcs in new[] { true, false })
        {
            var result = selected[npcs ? "npc" : "shops"];
            Assert.Equal(1, result.RecordCount); Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
            var scene = Assert.Single(indexes.Scenes);
            var row = Assert.IsType<EveIndexSourceRecords>(result.Records).Scenes[scene.SceneId.ToString(CultureInfo.InvariantCulture)][0];
            Assert.Equal(npcs ? scene.Npcs[0].Index : scene.Interactions[0].Index, row.GetProperty("index").GetUInt16());
            Assert.Equal(npcs ? scene.Npcs[0].EventCount : scene.Interactions[0].LinkNumber,
                row.GetProperty(npcs ? "event_count" : "link_number").GetInt32());
        }
    }

    [Fact]
    public void Cancellation_precedes_validation_and_is_not_parser_failure()
    {
        using var session = ParserDiagnostics.BeginSession(); using var cancel = new CancellationTokenSource(); cancel.Cancel();
        Assert.Throws<OperationCanceledException>(() => CatalogSourceAdapters.ParseFeature(null, null, null, [], cancel.Token));
        Assert.Throws<OperationCanceledException>(() => CatalogSourceAdapters.ParseSelected(null, null, null, null, cancel.Token));
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Oversized_payload_is_rejected_without_copy_and_exact_validation_precedence_remains()
    {
        byte[] raw = new byte[CatalogSourceAdapters.MaxSourceBytes + 1];
        var contract = new CatalogSourceContract("npc", "Eve", "eve-npc-json-v1", new('0', 64), "MainPackage", "v");
        var versions = new Dictionary<string, string> { ["MainPackage"] = "v" };
        long before = GC.GetAllocatedBytesForCurrentThread();
        var error = Assert.Throws<CatalogAdapterException>(() => CatalogSourceAdapters.ParseFeature(new('a', 64), versions, contract, raw));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 200_000);
        Assert.Equal("Missing or oversized source payload", error.Message);
        Assert.Equal(raw.Length, ParserDiagnostics.GetFailure(error)!.Inputs["raw"].Size);
        Assert.Equal("A verified versioned Catalog key is required", Assert.Throws<CatalogAdapterException>(() => CatalogSourceAdapters.ParseFeature("bad", null, null, raw)).Message);
        Assert.Equal("Catalog/package source revision mismatch", Assert.Throws<CatalogAdapterException>(() => CatalogSourceAdapters.ParseFeature(new('a', 64), null, null, raw)).Message);
    }

    [Theory]
    [InlineData("NaN")]
    [InlineData("Infinity")]
    [InlineData("1e999")]
    [InlineData("\"\\ud800\"")]
    public void Explicit_strict_json_delta_rejects_non_RFC_or_nonfinite_values(string extra)
    {
        byte[] raw = Encoding.UTF8.GetBytes("{\"schema_version\":1,\"source\":\"EventData.NewNpc\",\"scenes\":{},\"record_count\":0,\"extra\":" + extra + "}");
        Assert.Equal("Invalid UTF-8/JSON index", Assert.Throws<CatalogAdapterException>(() => ParseNpc(raw)).Message);
    }

    [Fact]
    public void Depth_and_integer_limits_apply_even_to_ignored_or_overwritten_fields()
    {
        foreach (string extra in new[] { new string('[', 65) + "0" + new string(']', 65), new string('1', 4301) + ",\"extra\":0" })
        {
            byte[] raw = Encoding.UTF8.GetBytes("{\"schema_version\":1,\"source\":\"EventData.NewNpc\",\"scenes\":{},\"record_count\":0,\"extra\":" + extra + "}");
            Assert.Equal("Invalid UTF-8/JSON index", Assert.Throws<CatalogAdapterException>(() => ParseNpc(raw)).Message);
        }
    }
    private static string Digest(byte[] raw) => Convert.ToHexStringLower(SHA256.HashData(raw));
    private static ParsedSourceCatalog ParseNpc(byte[] raw) => CatalogSourceAdapters.ParseFeature(new('a', 64),
        new Dictionary<string, string> { ["DataPackage"] = "v" },
        new("npc", "Eve", "eve-npc-json-v1", Digest(raw), "DataPackage", "v"), raw);
}
