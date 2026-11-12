using System.Collections;
using System.Collections.Immutable;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Xunit;

namespace Lala.Core.Tests.Catalogs.RequiredTables;

public sealed partial class RequiredTableParityTests
{
    [Fact]
    public void Scalar_discovery_has_no_payloads_and_every_runtime_lookup_is_unique()
    {
        var ids = new HashSet<int>(); var names = new HashSet<string>();
        foreach (var args in RequiredTableOracleCases.CaseIds())
        {
            int id = Assert.IsType<int>(Assert.Single(args));
            Assert.True(ids.Add(id));
            var row = RequiredTableOracleCases.Case(id);
            string name = row.GetProperty("name").GetString()!;
            Assert.True(names.Add(name)); Assert.InRange(name.Length, 1, 80);
            Assert.All(name, character => Assert.InRange((int)character, 32, 126));
        }
        Assert.Equal(RequiredTableOracleCases.VectorCount, ids.Count);
        Assert.Equal(16, RequiredTableOracleCases.ResourceRefs().Count());
    }

    [Fact]
    public void Results_own_source_bytes_and_all_nested_collections_are_immutable()
    {
        var fixture = Fixture("compose-basic");
        var sources = SourceMap(fixture);
        var result = OfflineRuntimeTableDecoder.Decode(sources);
        foreach (string key in sources.Keys.ToArray())
        {
            Assert.True(System.Runtime.InteropServices.MemoryMarshal.TryGetArray(sources[key], out var bytes));
            Array.Fill(bytes.Array!, (byte)255);
        }
        sources.Clear();
        Assert.Equal("甲😀", result.Talks[1].Text);
        Assert.Equal(ushort.MaxValue, result.Talks[1].VoiceId);
        Assert.Equal("任務", result.Expedition.Tasks[1].Name);
        Assert.Equal("地區", result.Expedition.Tasks[1].AreaLabel);
        Assert.Equal(0, result.Npcs[1].Original);
        Assert.Equal(int.MinValue, result.Expedition.Tasks[1].Exp);
        Assert.False(result.Talks is IDictionary);
        Assert.False(result.Npcs is IDictionary);
        Assert.False(result.Expedition.Tasks is IDictionary);
        Assert.False(result.Expedition.Levels is IDictionary);
        Assert.False(result.Expedition.SourceSha256 is IDictionary);
        var row = result.Expedition.Tasks[1];
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)row.Condition)[0] = 42);
        Assert.Throws<NotSupportedException>(() => ((IList<ExpeditionRecommendation>)row.Recommendations).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)row.Recommendations[0].Condition).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ExpeditionReward>)row.Rewards).Clear());
        var changed = row with { Condition = row.Condition.SetItem(0, 99), Name = "changed" };
        Assert.Equal(99, changed.Condition[0]); Assert.Equal(0, row.Condition[0]);
        Assert.Equal("任務", result.Expedition.Tasks[1].Name);
        Assert.True(result.Npcs.ContainsKey(1)); Assert.False(result.Npcs.TryGetValue(0, out _));
        Assert.True(result.Npcs.TryGetValue(1, out var npc)); Assert.Equal(result.Npcs[1], npc);
        Assert.Throws<KeyNotFoundException>(() => result.Npcs[0]);
        Assert.Equal(result.Npcs.Keys, ((IEnumerable)result.Npcs).Cast<KeyValuePair<ushort, ExpeditionNpcData>>().Select(pair => pair.Key));
        var textMap = Assert.IsAssignableFrom<IDictionary>(result.Texts);
        Assert.True(textMap.IsReadOnly); Assert.Throws<NotSupportedException>(textMap.Clear);
    }

    [Fact]
    public void Attach_names_is_an_owned_new_projection_and_does_not_mutate_prior_catalog()
    {
        var fixture = Fixture("attach-basic");
        byte[] tasks = Raw(fixture, "tasks"), levels = Raw(fixture, "levels"), text = Raw(fixture, "text");
        var plain = ExpeditionCatalogParser.ParseCatalog(tasks, levels);
        var named = ExpeditionCatalogParser.AttachNames(plain, text);
        Assert.Null(plain.Tasks[1].Name); Assert.Null(plain.Tasks[1].AreaLabel);
        Assert.Equal("任務", named.Tasks[1].Name);
        Assert.Equal(2, plain.SourceSha256.Count); Assert.Equal(3, named.SourceSha256.Count);
        Assert.Equal(new[] { "AdventureData_C", "AdventureLvData_C", "TextData_C" }, named.SourceSha256.Keys);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(text)), named.SourceSha256["TextData_C"]);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(tasks)), plain.SourceSha256["AdventureData_C"]);
        Array.Fill(tasks, (byte)0); Array.Fill(levels, (byte)0); Array.Fill(text, (byte)0);
        Assert.Equal(ushort.MaxValue, plain.Tasks[1].Minutes); Assert.Equal("任務", named.Tasks[1].Name);
        Assert.Same(plain.Levels, named.Levels); // Sharing internally immutable owned values is safe.
    }

    [Fact]
    public void Snapshot_reads_accept_subspans_without_using_envelope_bytes()
    {
        var fixture = Fixture("talk-order");
        byte[] raw = Raw(fixture, "raw"); byte[] envelope = new byte[raw.Length + 17];
        raw.CopyTo(envelope, 7);
        var result = TalkDataParser.Parse(envelope.AsSpan(7, raw.Length));
        Array.Fill(envelope, (byte)0);
        Assert.Equal(new ushort[] { 65535, 0, 1 }, result.Keys);
        Assert.Equal(result.Keys, result.Select(pair => pair.Key));
        Assert.All(result.Values, row => Assert.Equal("甲😀", row.Text));
    }

    [Fact]
    public void Cancelled_tokens_win_before_validation_and_do_not_become_parser_failures()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var source = new CancellationTokenSource(); source.Cancel();
        var fixture = Fixture("attach-basic");
        // Build this before the cancellation checks; its successful observation is intentional.
        var catalog = ExpeditionCatalogParser.ParseCatalog(Raw(fixture, "tasks"), Raw(fixture, "levels"));
        int prior = session.Run.Events.Length;
        foreach (Action action in new Action[]
        {
            () => TalkDataParser.Parse([], source.Token),
            () => ExpeditionCatalogParser.ParseCatalog([], [], source.Token),
            () => ExpeditionCatalogParser.ParseNpcs([], [], source.Token),
            () => ExpeditionCatalogParser.AttachNames(catalog, [], source.Token),
            () => ExpeditionCatalogParser.AttachNames(null!, [], source.Token),
            () => OfflineRuntimeTableDecoder.Decode(new Dictionary<string, ReadOnlyMemory<byte>>(), source.Token),
            () => OfflineRuntimeTableDecoder.Decode(null!, source.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(action);
            Assert.Equal(source.Token, error.CancellationToken); Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Equal(prior, session.Run.Events.Length);
        Assert.All(session.Run.Events, entry => Assert.False(entry.Failed));
    }

    [Fact]
    public void Mid_composition_cancellation_never_returns_partial_results_or_a_failed_parser_observation()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var source = new CancellationTokenSource();
        var sources = new OnReadSources(SourceMap(Fixture("compose-basic")), key =>
        {
            if (key == "AdventureData_C") source.Cancel();
        });
        Assert.Throws<OperationCanceledException>(() => OfflineRuntimeTableDecoder.Decode(sources, source.Token));
        Assert.Equal(new[] { "talk-v1", "text-v1" }, session.Run.Events.Select(entry => entry.Definition.Schema));
        Assert.All(session.Run.Events, entry => Assert.False(entry.Failed));
    }

    [Fact]
    public void Composer_source_access_order_ignores_dictionary_order_and_unrelated_claims()
    {
        var map = SourceMap(Fixture("compose-basic")).Reverse().ToDictionary(pair => pair.Key, pair => pair.Value);
        map["verified_1275_official_bundle"] = new byte[] { 1 };
        map["source_sha256"] = new byte[] { 1 };
        var order = new List<string>();
        var result = OfflineRuntimeTableDecoder.Decode(new OnReadSources(map, order.Add));
        Assert.Equal(OfflineRuntimeTableDecoder.Sources, order);
        Assert.Equal(new[] { "AdventureData_C", "AdventureLvData_C", "NpcData_C", "NpcCareerData_C" }, result.Expedition.SourceSha256.Keys);
        Assert.Equal("supplied_offline_tables", result.SourceKind);
        Assert.False(result.HasVerifiedProvenance); Assert.False(result.AssetsReady);
        Assert.False(result.CanSendPackets); Assert.False(result.RuntimeAdmitted);
    }

    [Fact]
    public void Missing_and_oversized_sources_reject_at_their_stage_without_copying_doomed_input()
    {
        foreach (string source in OfflineRuntimeTableDecoder.Sources)
        {
            var map = SourceMap(Fixture("compose-basic")); map.Remove(source);
            var missing = Assert.Throws<CatalogDecodeException>(() => OfflineRuntimeTableDecoder.Decode(map));
            Assert.Equal("Missing offline raw table: " + source, missing.Message);
            Assert.Null(ParserDiagnostics.GetFailure(missing));
            map = SourceMap(Fixture("compose-basic")); map[source] = new byte[OfflineRuntimeTableDecoder.MaxSourceBytes + 1];
            long before = GC.GetAllocatedBytesForCurrentThread();
            var oversized = Assert.Throws<CatalogDecodeException>(() => OfflineRuntimeTableDecoder.Decode(map));
            Assert.Equal("Oversized offline raw table: " + source, oversized.Message);
            Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 1_000_000);
            Assert.Null(ParserDiagnostics.GetFailure(oversized));
        }
        var invalidFirst = SourceMap(Fixture("compose-basic")); invalidFirst["TalkData_C"] = ReadOnlyMemory<byte>.Empty;
        invalidFirst.Remove("TextData_C");
        Assert.Equal("TalkData_C 大小不合法", Assert.Throws<CatalogDecodeException>(() => OfflineRuntimeTableDecoder.Decode(invalidFirst)).Message);
    }

    [Fact]
    public void Oversized_talk_and_attach_text_retain_original_diagnostic_without_copying()
    {
        byte[] oversized = new byte[TalkDataParser.MaxBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        var error = Assert.Throws<CatalogDecodeException>(() => TalkDataParser.Parse(oversized));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 200_000);
        Assert.Equal(oversized.Length, ParserDiagnostics.GetFailure(error)!.Inputs["raw"].Size);
        var fixture = Fixture("attach-basic");
        var catalog = ExpeditionCatalogParser.ParseCatalog(Raw(fixture, "tasks"), Raw(fixture, "levels"));
        before = GC.GetAllocatedBytesForCurrentThread();
        error = Assert.Throws<CatalogDecodeException>(() => ExpeditionCatalogParser.AttachNames(catalog, oversized));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 200_000);
        Assert.Equal("text-v1", ParserDiagnostics.GetFailure(error)!.Definition.Schema);
        Assert.Equal(oversized.Length, ParserDiagnostics.GetFailure(error)!.Inputs["text_data"].Size);
    }

    [Fact]
    public void New_raw_decoders_expose_no_caller_hash_bypass_and_do_not_replace_reviewed_normal_attack_pins()
    {
        foreach (Type type in new[] { typeof(TalkDataParser), typeof(ExpeditionCatalogParser), typeof(OfflineRuntimeTableDecoder) })
            Assert.All(type.GetMethods(BindingFlags.Public | BindingFlags.Static).SelectMany(method => method.GetParameters()),
                parameter => Assert.False(parameter.ParameterType == typeof(string)));
        var fixture = Fixture("npcs-basic");
        var error = Assert.Throws<CatalogDecodeException>(() => NormalAttackCatalogParser.ParseNpcs(Raw(fixture, "npc")));
        Assert.Equal("NPC 普攻資料格式尚未驗證", error.Message);
        Assert.Equal("edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c", NormalAttackCatalogParser.ReviewedNpcSha256);
    }

    [Fact]
    public void Diagnostics_remain_payload_free_and_nested_failures_restore_parent_cursor()
    {
        using var session = ParserDiagnostics.BeginSession();
        var fixture = Fixture("compose-basic");
        OfflineRuntimeTableDecoder.Decode(SourceMap(fixture));
        string report = Encoding.UTF8.GetString(session.Run.BuildReports().Latest.AsSpan());
        Assert.DoesNotContain("任務", report); Assert.DoesNotContain("地區", report);
        Assert.DoesNotContain("base64", report); Assert.DoesNotContain("message", report);
        var definition = new ParserDiagnosticDefinition("synthetic.required_tables", "synthetic-v1");
        var error = Assert.Throws<InvalidOperationException>(() => ParserDiagnostics.Run<int>(definition, [], () =>
        {
            ParserDiagnostics.Checkpoint(offset: 67, field: "outer");
            Assert.Throws<CatalogDecodeException>(() => ExpeditionCatalogParser.ParseNpcs([], []));
            throw new InvalidOperationException("not retained");
        }));
        Assert.Equal(new System.Numerics.BigInteger(67), ParserDiagnostics.GetFailure(error)!.Location!["offset"]);
        Assert.Equal("outer", ParserDiagnostics.GetFailure(error)!.Location!["field"]);
    }

    [Fact]
    public async Task Concurrent_source_observations_are_isolated_and_retained_bytes_are_exact()
    {
        var results = await Task.WhenAll(Enumerable.Range(0, 8).Select(index => Task.Run(() =>
        {
            using var session = ParserDiagnostics.BeginSession();
            byte[] raw = Raw(Fixture("talk-basic"), "raw");
            System.Buffers.Binary.BinaryPrimitives.WriteUInt16LittleEndian(raw.AsSpan(4), (ushort)index);
            TalkDataParser.Parse(raw);
            var observation = Assert.Single(session.Run.Events);
            Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(raw)), observation.Inputs["raw"].Sha256);
            return observation.Inputs["raw"].Sha256;
        })));
        Assert.Equal(8, results.Distinct().Count()); Assert.False(ParserDiagnostics.IsActive);
    }

    private sealed class OnReadSources(IReadOnlyDictionary<string, ReadOnlyMemory<byte>> sources, Action<string> onRead)
        : IReadOnlyDictionary<string, ReadOnlyMemory<byte>>
    {
        public int Count => sources.Count;
        public IEnumerable<string> Keys => sources.Keys;
        public IEnumerable<ReadOnlyMemory<byte>> Values => sources.Values;
        public ReadOnlyMemory<byte> this[string key] => sources[key];
        public bool ContainsKey(string key) => sources.ContainsKey(key);
        public bool TryGetValue(string key, out ReadOnlyMemory<byte> value) { onRead(key); return sources.TryGetValue(key, out value); }
        public IEnumerator<KeyValuePair<string, ReadOnlyMemory<byte>>> GetEnumerator() => sources.GetEnumerator();
        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();
    }
}
