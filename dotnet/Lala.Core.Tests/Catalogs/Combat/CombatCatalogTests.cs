using System.Collections.Immutable;
using System.Globalization;
using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Inventory;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs.Combat;

public sealed class CombatCatalogTests
{
    [Theory]
    [MemberData(nameof(CombatCatalogPythonVectors.Cases), MemberType = typeof(CombatCatalogPythonVectors))]
    public void Retained_python_values_errors_and_explicit_typed_deltas_match(string name, JsonElement row)
    {
        Assert.NotEmpty(name);
        using var session = ParserDiagnostics.BeginSession();
        var rawError = row.GetProperty("raw_error");
        string? delta = Text(row, "typed_error");
        if (rawError.ValueKind != JsonValueKind.Null || delta is not null)
        {
            var error = Assert.Throws<CatalogDecodeException>(() => Parse(row));
            Assert.Equal(delta ?? rawError.GetProperty("message").GetString(), error.Message);
            Assert.Null(error.InnerException);
        }
        else
        {
            object parsed = Parse(row);
            Assert.True(JsonNode.DeepEquals(JsonNode.Parse(row.GetProperty("raw_expected").GetRawText()), Project(parsed)), name);
            if (parsed is CombatCatalogData catalog)
            {
                string? projectionError = Text(row, "projection_error");
                if (projectionError is not null) Assert.Equal(projectionError,
                    Assert.Throws<CatalogDecodeException>(() => catalog.ToKnowledgeSnapshot()).Message);
                else VerifyKnowledgeProjection(catalog);
            }
        }
        var supportedDiagnostics = row.GetProperty("raw_diagnostics").EnumerateArray().Where(observation =>
            observation.GetProperty("parser").GetString()!.EndsWith("normal_attack_catalog.parse_npcs", StringComparison.Ordinal) ||
            observation.GetProperty("parser").GetString() == "synthetic.combat_parent").ToArray();
        Assert.Equal(supportedDiagnostics.Length, session.Run.Events.Length);
        for (int index = 0; index < supportedDiagnostics.Length; index++)
        {
            var expected = JsonNode.Parse(supportedDiagnostics[index].GetRawText())!;
            if (expected["error_type"] is not null) expected["error_type"] = nameof(CatalogDecodeException);
            var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(session.Run.Events[index]), default).AsSpan());
            LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => name + ": " + actual);
        }
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(CombatCatalogPythonVectors.Sources), MemberType = typeof(CombatCatalogPythonVectors))]
    public void Retained_sources_are_pinned_ignoring_only_checkout_CRLF(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int index = 0; index < source.Length; index++)
            if (source[index] != 13 || index + 1 == source.Length || source[index + 1] != 10) normalized.WriteByte(source[index]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void All_fixed_gates_and_public_surface_exclude_arbitrary_source_or_layout_pins()
    {
        Assert.Equal("452e32903a686f22b8e98c1707efca80a45dcf73fd4f1bd5e7e08b38ae3db92c", CombatCatalogParser.ReviewedDefineSha256);
        Assert.Equal("4c0366884264b14765192c2b7d1644439898edfc06bf29dea988f6de6bf75d88", CombatCatalogParser.ReviewedFightUnitSha256);
        Assert.Equal("ed6383251b4f0fb9f7d9eb85c99346a268b99bdded839f6957f083c4b7f0545c", SkillDataParser.ReviewedSha256);
        Assert.Equal("edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c", NormalAttackCatalogParser.ReviewedNpcSha256);
        Assert.Equal("5195d5ee8ae201dea55439274914930551176c3fcf50d735e03b09c5d04acbb4", ItemDataParser.Reviewed1296Sha256);
        var methods = typeof(CombatCatalogParser).GetMethods(BindingFlags.Public | BindingFlags.Static);
        Assert.Equal(new[] { "BuildCatalog", "ParseConstants" }, methods.Select(method => method.Name).Order().ToArray());
        Assert.DoesNotContain(methods.SelectMany(method => method.GetParameters()), parameter =>
            parameter.ParameterType == typeof(bool) || parameter.Name!.Contains("hash", StringComparison.OrdinalIgnoreCase) ||
            parameter.Name.Contains("pin", StringComparison.OrdinalIgnoreCase) || parameter.Name.Contains("layout", StringComparison.OrdinalIgnoreCase));
        Assert.Empty(typeof(CombatCatalogData).GetConstructors());
        Assert.Empty(typeof(CombatCatalogConstants).GetConstructors());
        Assert.Equal(CombatCatalogPythonVectors.VectorCount, CombatCatalogPythonVectors.Cases().Count());
    }

    [Fact]
    public void Every_synthetic_constants_and_catalog_case_fails_the_unchanged_public_gates()
    {
        foreach (object[] fixture in CombatCatalogPythonVectors.Cases())
        {
            var row = (JsonElement)fixture[1];
            Assert.Equal("Unreviewed combat Lua text", Assert.Throws<CatalogDecodeException>(() =>
                CombatCatalogParser.ParseConstants(Text(row, "define")!, Text(row, "fight")!)).Message);
            if (Text(row, "mode")!.StartsWith("build", StringComparison.Ordinal))
                Assert.Equal("Unreviewed combat ItemData", Assert.Throws<CatalogDecodeException>(() =>
                    CombatCatalogParser.BuildCatalog(Raw(row, "skill"), Raw(row, "npc"), Raw(row, "item"),
                        Names(row), Text(row, "define")!, Text(row, "fight")!)).Message);
        }
    }

    [Fact]
    public void Parsed_rows_are_detached_immutable_and_keep_every_source_field()
    {
        var row = Fixture("base-catalog");
        byte[] skills = Raw(row, "skill"), npcs = Raw(row, "npc"), items = Raw(row, "item");
        var names = new Dictionary<uint, string?> { [1001] = "  技能😀\0  " };
        var result = CombatCatalogParser.BuildCatalogLayout(skills, npcs, items, names, Text(row, "define")!, Text(row, "fight")!);
        Array.Fill(skills, (byte)255); Array.Fill(npcs, (byte)255); Array.Fill(items, (byte)255); names[1001] = "changed";
        Assert.Equal("  技能😀\0  ", result.Skills[101].Name);
        Assert.Equal(71, result.Skills[101].Fields.Count);
        Assert.Equal("NPC私密😀", result.Npcs[321].Name);
        Assert.Equal(new uint[] {101, 0, 65535, 4, 5}, result.Npcs[321].Skills);
        Assert.Equal("物品😀", result.Items[100].Name);
        Assert.Equal(140, result.Items[100].Special);
        Assert.Equal(new ItemAttribute(25, 2, int.MinValue), result.Items[100].Attributes[0]);
        Assert.Equal(new ItemAttribute(26, 255, int.MaxValue), result.Items[100].Attributes[1]);
        Assert.Equal(15, result.Constants.Characters.Length);
        Assert.Equal(5, result.Constants.ElementWeights.Count);
        Assert.All(result.Constants.ElementWeights.Values, matrixRow => Assert.Equal(5, matrixRow.Count));
        Assert.Empty(result.Skills.Clear()); Assert.Single(result.Skills);
        Assert.Empty(result.Items.Clear()); Assert.Single(result.Items);
        Assert.Empty(result.Npcs.Clear()); Assert.Single(result.Npcs);
        Assert.Empty(result.SkillKeys.Clear()); Assert.Single(result.SkillKeys);
        Assert.Empty(result.Constants.Characters.Clear()); Assert.Equal(15, result.Constants.Characters.Length);
        var snapshot = result.ToKnowledgeSnapshot();
        Assert.NotSame(CombatResourceCatalog.Empty, snapshot);
        // A new caller DTO has no verification flag to forge or transfer to resource activation.
        Assert.DoesNotContain(typeof(CombatResourceCatalog).GetProperties(), property =>
            property.Name.Contains("Verified", StringComparison.OrdinalIgnoreCase) || property.Name.Contains("Trusted", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Cancellation_precedes_parsing_hashing_projection_and_diagnostics()
    {
        var row = Fixture("base-catalog"); var data = (CombatCatalogData)Parse(row);
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        foreach (Action action in new Action[]
        {
            () => CombatCatalogParser.ParseConstants("", "", cancelled.Token),
            () => CombatCatalogParser.ParseConstantsLayout("", "", cancelled.Token),
            () => CombatCatalogParser.Block("", "T", cancelled.Token),
            () => CombatCatalogParser.Enum("", "T", cancelled.Token),
            () => CombatCatalogParser.BuildCatalog([], [], [], new Dictionary<uint, string?>(), "", "", cancelled.Token),
            () => CombatCatalogParser.BuildCatalogLayout([], [], [], new Dictionary<uint, string?>(), "", "", cancelled.Token),
            () => data.ToKnowledgeSnapshot(cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(action);
            Assert.Equal(cancelled.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Lua_byte_bounds_strict_encoding_and_item_size_reject_without_unsafe_normalization()
    {
        Assert.Equal(2 * 1024 * 1024, CombatCatalogParser.MaxLuaBytes);
        foreach (var text in new[] { new string('a', CombatCatalogParser.MaxLuaBytes + 1), new string('界', CombatCatalogParser.MaxLuaBytes / 3 + 1) })
        {
            Assert.Equal("Combat Lua text exceeds byte limit", Assert.Throws<CatalogDecodeException>(() => CombatCatalogParser.ParseConstants(text, "")).Message);
            Assert.Equal("Combat Lua text exceeds byte limit", Assert.Throws<CatalogDecodeException>(() => CombatCatalogParser.ParseConstantsLayout("", text)).Message);
        }
        Assert.Equal("Invalid combat Lua Unicode text", Assert.Throws<CatalogDecodeException>(() => CombatCatalogParser.ParseConstants("\ud800", "")).Message);
        byte[] huge = new byte[ItemDataParser.MaxBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        Assert.Throws<CatalogDecodeException>(() => CombatCatalogParser.BuildCatalog([], [], huge, new Dictionary<uint, string?>(), "", ""));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 100000);
    }

    [Fact]
    public void Source_duplicate_enum_keys_are_rejected_before_integer_conversion()
    {
        string value = new('9', 4301);
        Assert.Equal("Duplicate enum key", Assert.Throws<CatalogDecodeException>(() =>
            CombatCatalogParser.Enum("T={A=" + value + ",A=1}", "T")).Message);
    }

    [Fact]
    public void Inherited_missing_skill_and_item_diagnostics_are_not_fabricated()
    {
        using var session = ParserDiagnostics.BeginSession();
        var data = (CombatCatalogData)Parse(Fixture("base-catalog"));
        var observation = Assert.Single(session.Run.Events);
        Assert.Equal("wlre.services.world.normal_attack_catalog.parse_npcs", observation.Definition.Parser);
        string report = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("私密", report); Assert.DoesNotContain("技能", report); Assert.DoesNotContain("物品", report);
        Assert.False(session.Run.AssetsReady); Assert.False(session.Run.CanSendPackets);
    }

    private static void VerifyKnowledgeProjection(CombatCatalogData catalog)
    {
        var snapshot = catalog.ToKnowledgeSnapshot();
        Assert.Same(catalog.Skills, snapshot.Skills); Assert.Same(catalog.Npcs, snapshot.Npcs); Assert.Same(catalog.SkillKeys, snapshot.SkillKeys);
        Assert.Equal(catalog.Items.Count, snapshot.Items.Count);
        foreach (var (id, item) in catalog.Items)
        {
            var projected = snapshot.Items[id];
            Assert.Equal(item.Kind, projected.Kind); Assert.Equal(item.Restrict, projected.Restrict);
            Assert.Equal(item.FitType, projected.FitType); Assert.Equal(item.SkillLink, projected.SkillLink);
            Assert.Equal(item.Attributes.Select(value => new CombatResourceAttribute(value.Kind, value.Value)), projected.Attributes);
        }
        Assert.Equal(catalog.Constants.Characters.Select(value => new CombatResourceCharacter((int)value.Sex, (int)value.Head,
            (uint)value.Skill, (ushort)value.Body)), snapshot.Characters);
    }

    private static object Parse(JsonElement row)
    {
        string mode = Text(row, "mode")!, define = Text(row, "define")!, fight = Text(row, "fight")!;
        return mode switch
        {
            "block-layout" => CombatCatalogParser.Block(define, Text(row, "target")!),
            "enum-layout" => CombatCatalogParser.Enum(define, Text(row, "target")!),
            "constants-layout" => CombatCatalogParser.ParseConstantsLayout(define, fight),
            "constants-public" => CombatCatalogParser.ParseConstants(define, fight),
            "build-nested-layout" => ParserDiagnostics.Run(new("synthetic.combat_parent", "parent-v1"), [], () =>
            {
                ParserDiagnostics.Checkpoint(offset: 7, field: "outer");
                return CombatCatalogParser.BuildCatalogLayout(Raw(row, "skill"), Raw(row, "npc"), Raw(row, "item"), Names(row), define, fight);
            }),
            "build-layout" => CombatCatalogParser.BuildCatalogLayout(Raw(row, "skill"), Raw(row, "npc"), Raw(row, "item"), Names(row), define, fight),
            "build-public" => CombatCatalogParser.BuildCatalog(Raw(row, "skill"), Raw(row, "npc"), Raw(row, "item"), Names(row), define, fight),
            _ => throw new InvalidOperationException(mode)
        };
    }
    private static JsonNode? Project(object value)
    {
        if (value is string text) return JsonValue.Create(text);
        if (value is IReadOnlyDictionary<string, BigInteger> enumeration)
            return new JsonObject(enumeration.Select(pair => KeyValuePair.Create<string, JsonNode?>(pair.Key, Number(pair.Value))));
        if (value is CombatCatalogConstants constants)
            return new JsonObject { ["characters"] = new JsonArray(constants.Characters.Select(character => (JsonNode?)new JsonObject
            {
                ["sex"] = Number(character.Sex), ["head"] = Number(character.Head), ["skill"] = Number(character.Skill), ["body"] = Number(character.Body)
            }).ToArray()), ["element_weights"] = new JsonObject(constants.ElementWeights.Select(pair =>
                KeyValuePair.Create<string, JsonNode?>(Key(pair.Key), new JsonObject(pair.Value.Select(cell =>
                    KeyValuePair.Create<string, JsonNode?>(Key(cell.Key), double.IsPositiveInfinity(cell.Value) ? JsonValue.Create("Infinity") : JsonValue.Create(cell.Value))))))) };
        var data = (CombatCatalogData)value;
        var result = (JsonObject)Project(data.Constants)!;
        result["skills"] = new JsonObject(data.Skills.Select(pair =>
        {
            var fields = JsonSerializer.SerializeToNode(pair.Value.Fields)!.AsObject(); fields["name"] = pair.Value.Name;
            return KeyValuePair.Create<string, JsonNode?>(Key(pair.Key), fields);
        }));
        result["keys"] = JsonSerializer.SerializeToNode(data.SkillKeys.ToDictionary(pair => Key(pair.Key), pair => pair.Value));
        result["npcs"] = JsonSerializer.SerializeToNode(data.Npcs.ToDictionary(pair => Key(pair.Key), pair => new { name = pair.Value.Name, skills = pair.Value.Skills }));
        result["items"] = JsonSerializer.SerializeToNode(data.Items.ToDictionary(pair => Key(pair.Key), pair => new
        {
            name = pair.Value.Name, kind = pair.Value.Kind,
            attributes = pair.Value.Attributes.Select(attribute => new { kind = attribute.Kind, effect = attribute.Effect, value = attribute.Value }),
            special = pair.Value.Special, restrict = pair.Value.Restrict, skill_link = pair.Value.SkillLink, fit_type = pair.Value.FitType
        }));
        return result;
    }
    private static JsonNode Number(BigInteger value) => JsonNode.Parse(value.ToString(CultureInfo.InvariantCulture))!;
    private static string Key<T>(T value) where T : IFormattable => value.ToString(null, CultureInfo.InvariantCulture);
    private static Dictionary<uint, string?> Names(JsonElement row) => row.GetProperty("texts").EnumerateObject().ToDictionary(
        pair => uint.Parse(pair.Name, CultureInfo.InvariantCulture), pair => pair.Value.ValueKind == JsonValueKind.Null ? null : pair.Value.GetString());
    private static string? Text(JsonElement row, string property) => row.GetProperty(property).ValueKind == JsonValueKind.Null ? null : row.GetProperty(property).GetString();
    private static byte[] Raw(JsonElement row, string property) => Convert.FromBase64String(Text(row, property)!);
    private static JsonElement Fixture(string name) => (JsonElement)CombatCatalogPythonVectors.Cases().First(row => (string)row[0] == name)[1];
}
