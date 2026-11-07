using System.Collections;
using System.Collections.Immutable;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Tests.TestSupport;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.Catalogs.RuntimeCandidate;

public sealed class RuntimeCandidateTests
{
    private const string LegacyVersion = "1286_2026_10_29_13_42_37_94";

    [Theory]
    [MemberData(nameof(RuntimeCandidateOracleCases.CaseIds), MemberType = typeof(RuntimeCandidateOracleCases))]
    public void Exact_runtime_blocks_and_binding_functions_match_actual_python(int id)
    {
        var fixture = RuntimeCandidateOracleCases.Case(id);
        string name = fixture.GetProperty("name").GetString()!;
        var expectedError = fixture.GetProperty("error");
        using var diagnosticSession = ParserDiagnostics.BeginSession();
        if (expectedError.ValueKind != JsonValueKind.Null)
        {
            var error = Record.Exception(() => Parse(fixture));
            Assert.NotNull(error);
            Assert.True(error is CatalogDecodeException or EveDecodeException or EveDoorSourceException, name);
            Assert.Equal(expectedError.GetProperty("message").GetString(), error.Message);
        }
        else
        {
            var actual = JsonSerializer.SerializeToNode(Parse(fixture));
            var expected = JsonNode.Parse(fixture.GetProperty("expected").GetRawText());
            LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => name + "\n" + actual?.ToJsonString());
            AssertOrder(expected!, actual!);
        }
        // Check the newly ported outer recipe diagnostic, leaving existing raw parser
        // diagnostic behavior to their own exhaustive retained-oracle test families.
        var recipeDiagnostic = fixture.GetProperty("recipe_diagnostic");
        if (recipeDiagnostic.ValueKind != JsonValueKind.Null)
        {
            var observed = Assert.Single(diagnosticSession.Run.Events.Where(e => e.Definition.Schema == "runtime-recipes-v1"));
            var expected = JsonNode.Parse(recipeDiagnostic.GetRawText())!;
            if (observed.Failed) expected["error_type"] = nameof(CatalogDecodeException);
            var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observed), default).AsSpan());
            LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => name + ": " + actual);
        }
    }

    [Theory]
    [MemberData(nameof(RuntimeCandidateOracleCases.SourceRefs), MemberType = typeof(RuntimeCandidateOracleCases))]
    public void Source_pins_normalize_CRLF_only(string path, string expected)
    {
        byte[] raw = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < raw.Length; i++)
        {
            if (raw[i] == 13 && i + 1 < raw.Length && raw[i + 1] == 10) continue;
            normalized.WriteByte(raw[i]);
        }
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void All_ten_outputs_are_owned_atomic_and_non_authorizing()
    {
        var map = Sources(RuntimeCandidateOracleCases.Case(0));
        var result = OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion);
        foreach (var memory in map.Values)
        {
            Assert.True(System.Runtime.InteropServices.MemoryMarshal.TryGetArray(memory, out var bytes));
            Array.Fill(bytes.Array!, (byte)0xff);
        }
        map.Clear();
        Assert.Equal(new ushort[] { 123, 20, 99 }, result.Items.Keys);
        Assert.Equal("甲😀", result.Talks[1].Text);
        Assert.Equal("任務", result.Expedition.Tasks[1].Name);
        Assert.Equal("場景😀", result.SceneNames[500]);
        Assert.Equal(new ushort[] { 99 }, result.Recipes.Products.Keys);
        Assert.Equal(new ushort?[] { 9, 2, 6 }, result.Recipes.Catalog.Select(r => r.Recipe.RecipeId));
        Assert.Equal(new byte[] { 255, 255, 1 }, result.Recipes.Catalog.Select(r => r.OpenUsed));
        Assert.Equal(1, result.Doors.DoorCount);
        var touch = Assert.Single(Assert.Single(result.Doors.Scenes[0].Doors).TouchEventRecords);
        Assert.True(touch.DestinationDecoded); Assert.Equal(58001, Assert.Single(touch.ConveyTransfers).Convey.Destination);
        Assert.Equal(uint.MaxValue, touch.Conditions[0].Data.ParaValue);
        Assert.Equal(int.MinValue, touch.Conditions[0].Results[0].ParaValue);
        Assert.False(result.Doors.AuthorizesTravel);
        Assert.Equal(0, result.Npcs[1].Original); // No invented cross-NPC referential requirement.
        Assert.Equal(9001u, result.EveIndexes.Scenes[0].Npcs[0].NpcId);
        Assert.False(result.Items is IDictionary); Assert.False(result.SceneNames is IDictionary);
        Assert.False(result.SourceSha256 is IDictionary); Assert.False(result.Recipes.Products is IDictionary);
        Assert.Throws<NotSupportedException>(() => ((IList<RuntimeRecipe>)result.Recipes.Catalog).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<SmithMaterial>)result.Recipes.Catalog[0].Recipe.Materials).Clear());
        Assert.True(result.RequiredTablesStructurallyComplete);
        Assert.Equal("supplied_offline_tables", result.SourceKind);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.RuntimeAdmitted);
        Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets);
        Assert.Contains("SkillData", result.UnavailableOptionalSources);
        Assert.Contains("portal_metadata", result.UnavailableOptionalSources);
        Assert.Contains("images", result.UnavailableOptionalSources);
        Assert.Contains("daily", result.UnavailableOptionalSources);
        Assert.Contains("guild", result.UnavailableOptionalSources);
        Assert.Contains("Ark", result.UnavailableOptionalSources);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources, result.SourceSha256.Keys);
    }

    [Fact]
    public void Snapshot_order_precedes_parsing_missing_is_not_empty_and_extra_claims_are_ignored()
    {
        var map = Sources(RuntimeCandidateOracleCases.Case(0)).Reverse().ToDictionary(p => p.Key, p => p.Value);
        map["source_sha256"] = new byte[] { 1 }; map["verified_official"] = new byte[] { 1 };
        var observed = new List<string>();
        var result = OfflineRuntimeCandidateDecoder.Decode(new ObservedSources(map, observed.Add), LegacyVersion);
        Assert.Equal(OfflineRuntimeCandidateDecoder.Sources, observed);
        Assert.False(result.HasVerifiedProvenance);
        map["Eve"] = ReadOnlyMemory<byte>.Empty; map.Remove("NpcCareerData_C");
        Assert.Equal("Missing offline raw table: NpcCareerData_C", Assert.Throws<CatalogDecodeException>(() =>
            OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion)).Message);
        map["NpcCareerData_C"] = ReadOnlyMemory<byte>.Empty;
        Assert.Equal("Missing or oversized Eve source", Assert.Throws<EveDecodeException>(() =>
            OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion)).Message);
        foreach (string name in OfflineRuntimeCandidateDecoder.Sources)
        {
            var missing = Sources(RuntimeCandidateOracleCases.Case(0)); missing.Remove(name);
            Assert.Equal("Missing offline raw table: " + name, Assert.Throws<CatalogDecodeException>(() =>
                OfflineRuntimeCandidateDecoder.Decode(missing, LegacyVersion)).Message);
        }
    }

    [Fact]
    public void Oversized_payload_rejects_before_copying_and_cancellation_wins_before_validation()
    {
        var map = Sources(RuntimeCandidateOracleCases.Case(0));
        map["Eve"] = new byte[OfflineRuntimeCandidateDecoder.MaxSourceBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        Assert.Equal("Oversized offline raw table: Eve", Assert.Throws<CatalogDecodeException>(() =>
            OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion)).Message);
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 100_000);
        using var source = new CancellationTokenSource(); source.Cancel();
        using var diagnostics = ParserDiagnostics.BeginSession();
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeCandidateDecoder.Decode(null!, null!, source.Token));
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion, source.Token));
        Assert.Empty(diagnostics.Run.Events);
    }

    [Fact]
    public void Cancellation_during_snapshot_never_parses_or_publishes_a_partial_candidate()
    {
        var map = Sources(RuntimeCandidateOracleCases.Case(0));
        using var source = new CancellationTokenSource();
        using var diagnostics = ParserDiagnostics.BeginSession();
        var observed = new ObservedSources(map, key => { if (key == "NpcCareerData_C") source.Cancel(); });
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeCandidateDecoder.Decode(observed, LegacyVersion, source.Token));
        Assert.Empty(diagnostics.Run.Events);
    }

    [Fact]
    public void Failed_candidate_does_not_mutate_prior_result_and_public_reviewed_pin_cannot_be_overridden()
    {
        var map = Sources(RuntimeCandidateOracleCases.Case(0));
        var prior = OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion);
        map["NpcCareerData_C"] = ReadOnlyMemory<byte>.Empty;
        Assert.Throws<CatalogDecodeException>(() => OfflineRuntimeCandidateDecoder.Decode(map, LegacyVersion));
        Assert.Equal("任務", prior.Expedition.Tasks[1].Name);
        map = Sources(RuntimeCandidateOracleCases.Case(0));
        map["source_sha256"] = Encoding.ASCII.GetBytes(ItemDataParser.Reviewed1296Sha256);
        Assert.Equal("ItemData 1296 source digest mismatch", Assert.Throws<CatalogDecodeException>(() =>
            OfflineRuntimeCandidateDecoder.Decode(map, ItemDataParser.Reviewed1296Version)).Message);
        Assert.All(typeof(OfflineRuntimeCandidateDecoder).GetMethods().Where(m => m.DeclaringType == typeof(OfflineRuntimeCandidateDecoder)),
            method => Assert.DoesNotContain(method.GetParameters(), p => p.Name!.Contains("hash", StringComparison.OrdinalIgnoreCase)));
    }

    private static object Parse(JsonElement fixture)
    {
        var sources = Sources(fixture);
        string version = fixture.GetProperty("version").GetString()!;
        return fixture.GetProperty("mode").GetString() switch
        {
            "compose" => Project(OfflineRuntimeCandidateDecoder.Decode(sources, version)),
            "recipes" => ProjectRecipes(RuntimeCandidateBindings.Recipes(sources["SmithData_C"].Span,
                ItemDataParser.ParseForRuntimeCandidate(sources["ItemData_C"].Span, version, default), default)),
            "scenes" => RuntimeCandidateBindings.SceneNames(StageDataParser.Parse(sources["ScenesData_C"].Span),
                TextDataParser.Parse(sources["TextData_C"].Span), default),
            _ => throw new InvalidOperationException()
        };
    }

    private static object Project(OfflineRuntimeCandidate value) => new
    {
        npc = JsonDocument.Parse(value.EveIndexes.ToJsonUtf8(EveV115Parser.NpcSource).AsMemory()).RootElement,
        interacts = JsonDocument.Parse(value.EveIndexes.ToJsonUtf8(EveV115Parser.InteractionSource).AsMemory()).RootElement,
        items = value.Items.Select(p => new object[] { p.Key, p.Value.OpenUsed }),
        talks = value.Talks.Select(p => new object[] { p.Key, p.Value.Text, p.Value.VoiceId }), texts = value.Texts,
        products = value.Recipes.Products.ToDictionary(p => p.Key, p => Recipe(p.Value)),
        catalog = value.Recipes.Catalog.Select(Recipe),
        stages = value.Stages.Select(p => new object[] { p.Key, p.Value.NameId, p.Value.ModelId }),
        door_counts = value.Doors.Scenes.Select(p => new object[] { p.SceneId, p.Doors.Length }),
        door_summaries = value.Doors.Scenes.SelectMany(scene => scene.Doors.Select(door => new object[]
        {
            scene.SceneId, door.Index, door.TouchEventIds.Select(id => (int)id), door.TouchEventRecords.Select(e => new object[]
                { e.Index, e.DestinationDecoded, e.ConveyTransfers.Select(t => t.Convey.Destination) })
        })),
        scene_names = value.SceneNames,
        tasks = value.Expedition.Tasks.Select(p => new object?[] { p.Key, p.Value.Name, p.Value.AreaLabel }),
        level_ids = value.Expedition.Levels.Keys,
        npcs = value.Npcs.ToDictionary(p => p.Key, p => new { element = p.Value.Element, kind = p.Value.Kind, original = p.Value.Original }),
        expedition_hashes = value.Expedition.SourceSha256, hashes = value.SourceSha256
    };
    private static object ProjectRecipes(RuntimeRecipeCandidate value) => new
    {
        products = value.Products.ToDictionary(p => p.Key, p => Recipe(p.Value)), catalog = value.Catalog.Select(Recipe)
    };
    private static Dictionary<string, object?> Recipe(RuntimeRecipe value)
    {
        var r = value.Recipe;
        var row = new Dictionary<string, object?>
        {
            ["item_id"] = r.ItemId, ["design_id"] = r.DesignId, ["skill"] = r.Skill, ["tool_id"] = r.ToolId,
            ["output"] = r.Output, ["materials"] = r.Materials.Select(m => new { item_id = m.ItemId, count = m.Count }),
            ["seconds"] = r.Seconds, ["skill_level"] = r.SkillLevel, ["suggest"] = r.Suggest, ["time_id"] = r.TimeId,
            ["limit_kind"] = r.LimitKind, ["mark_id"] = r.MarkId, ["limit_times"] = r.LimitTimes, ["order"] = r.Order
        };
        if (r.RecipeId is not null) { row["recipe_id"] = r.RecipeId; row["candidate_row_key"] = r.CandidateRowKey; }
        if (r.ReadOnly is not null) row["read_only"] = r.ReadOnly;
        row["open_used"] = value.OpenUsed;
        return row;
    }
    private static Dictionary<string, ReadOnlyMemory<byte>> Sources(JsonElement fixture) => fixture.GetProperty("inputs")
        .EnumerateObject().ToDictionary(p => p.Name, p => (ReadOnlyMemory<byte>)Convert.FromBase64String(p.Value.GetString()!), StringComparer.Ordinal);
    private static void AssertOrder(JsonNode expected, JsonNode actual)
    {
        if (expected is JsonObject obj && actual is JsonObject other)
        {
            Assert.Equal(obj.Select(p => p.Key), other.Select(p => p.Key));
            foreach (var (key, value) in obj) if (value is not null) AssertOrder(value, other[key]!);
        }
        else if (expected is JsonArray array && actual is JsonArray otherArray)
            for (int i = 0; i < array.Count; i++) if (array[i] is { } value) AssertOrder(value, otherArray[i]!);
    }
    private sealed class ObservedSources(IReadOnlyDictionary<string, ReadOnlyMemory<byte>> inner, Action<string> callback)
        : IReadOnlyDictionary<string, ReadOnlyMemory<byte>>
    {
        public ReadOnlyMemory<byte> this[string key] => inner[key];
        public IEnumerable<string> Keys => inner.Keys;
        public IEnumerable<ReadOnlyMemory<byte>> Values => inner.Values;
        public int Count => inner.Count;
        public bool ContainsKey(string key) => inner.ContainsKey(key);
        public bool TryGetValue(string key, out ReadOnlyMemory<byte> value) { callback(key); return inner.TryGetValue(key, out value); }
        public IEnumerator<KeyValuePair<string, ReadOnlyMemory<byte>>> GetEnumerator() => inner.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
