using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Xunit;

namespace Lala.Core.Tests.Catalogs.Instance;

public sealed class InstanceCatalogTests
{
    [Theory]
    [MemberData(nameof(InstancePythonVectors.Cases), MemberType = typeof(InstancePythonVectors))]
    public void Retained_python_values_validation_order_and_diagnostics_match(string name, int fixture, int index)
    {
        var row = InstancePythonVectors.ReadCase(fixture, index);
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
        var observations = row.GetProperty("diagnostics");
        Assert.Equal(observations.GetArrayLength(), session.Run.Events.Length);
        for (int i = 0; i < observations.GetArrayLength(); i++)
            AssertDiagnostic(observations[i], session.Run.Events[i]);
        if (row.GetProperty("failure").ValueKind != JsonValueKind.Null)
            AssertDiagnostic(row.GetProperty("failure"), ParserDiagnostics.GetFailure(error!)!, includeIdentity: false);
        else if (error is not null) Assert.Null(ParserDiagnostics.GetFailure(error));
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(InstancePythonVectors.Sources), MemberType = typeof(InstancePythonVectors))]
    public void Oracle_sources_ignore_only_CRLF_checkout_conversion(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    [Fact]
    public void Theory_discovery_uses_unique_bounded_scalar_names_and_lazy_coordinates()
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        var coordinates = new HashSet<(int, int)>();
        foreach (var entry in InstancePythonVectors.Cases())
        {
            Assert.Equal(3, entry.Length);
            string name = Assert.IsType<string>(entry[0]);
            Assert.InRange(name.Length, 1, 80);
            Assert.All(name, character => Assert.InRange((int)character, 32, 126));
            int fixture = Assert.IsType<int>(entry[1]), index = Assert.IsType<int>(entry[2]);
            Assert.True(names.Add(name)); Assert.True(coordinates.Add((fixture, index)));
            Assert.Equal(name, InstancePythonVectors.ReadCase(fixture, index).GetProperty("name").GetString());
        }
        Assert.Equal(InstancePythonVectors.VectorCount, names.Count);
        Assert.Equal(names.Count, InstancePythonVectors.FixtureCaseCount);
    }

    [Fact]
    public void Raw_rows_own_input_and_preserve_all_slots_flags_duplicates_and_source_order()
    {
        byte[] raw = Raw(InstancePythonVectors.FindCase("dungeon-basic"));
        byte[] envelope = new byte[raw.Length + 11]; raw.CopyTo(envelope, 5);
        var dungeons = InstanceCatalogParser.ParseDungeons(envelope.AsSpan(5, raw.Length));
        Array.Fill(raw, (byte)255); Array.Fill(envelope, (byte)255);
        Assert.Equal(new ushort[] { 7, 0 }, dungeons.Select(row => row.Id));
        Assert.All(dungeons, row => Assert.Equal(16, row.Awards.Length));
        Assert.Equal(new byte[] { 1, 8, 9, 16 }, dungeons[0].DoubleAwardSlots);
        Assert.Equal(new byte[] { 2, 7, 10, 15 }, dungeons[0].SpecialAwardSlots);
        Assert.Equal(new InstanceAward(10, 123, 5), dungeons[0].Awards[0]);
        Assert.All(dungeons[0].Awards.Skip(1), award => Assert.Equal(new InstanceAward(0, 0, 0), award));
        Assert.Throws<NotSupportedException>(() => ((IList<DungeonDataRow>)dungeons)[0] = dungeons[1]);
        Assert.Throws<NotSupportedException>(() => ((IList<InstanceAward>)dungeons[0].Awards)[0] = new(1, 2, 3));
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)dungeons[0].DoubleAwardSlots)[0] = 2);
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)dungeons[0].SpecialAwardSlots)[0] = 1);
        var changed = dungeons[0] with { Awards = dungeons[0].Awards.SetItem(0, new(1, 2, 3)) };
        Assert.Equal(1, changed.Awards[0].Kind); Assert.Equal(10, dungeons[0].Awards[0].Kind);
        var events = InstanceCatalogParser.ParseCooperativeEvents(Raw(InstancePythonVectors.FindCase("cooperative-basic")));
        Assert.Equal(new byte[] { 3, 0 }, events.Select(row => row.Id));
        Assert.Equal(new ushort[] { 0, 65535, 32768, 1 }, events[0].FollowerIds);
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)events[0].FollowerIds)[0] = 99);
        Assert.Throws<NotSupportedException>(() => ((IList<CooperativeEventDataRow>)events)[0] = events[1]);
        Assert.Equal(2, InstanceCatalogParser.ParseDungeons(Raw(InstancePythonVectors.FindCase("dungeon-duplicate-id"))).Length);
        Assert.Equal(2, InstanceCatalogParser.ParseCooperativeEvents(Raw(InstancePythonVectors.FindCase("cooperative-duplicate-id"))).Length);
    }

    [Fact]
    public void Bound_preview_is_immutable_and_has_no_authority_or_commands()
    {
        var fixture = InstancePythonVectors.FindCase("bind-basic");
        var stages = Stages(fixture); var texts = Texts(fixture); var items = Items(fixture);
        byte[] dungeons = Input(fixture, "DungeonData_C"), cooperative = Input(fixture, "CooperateEventData_C");
        var preview = InstanceCatalogParser.Bind(dungeons, cooperative, stages, texts, items);
        stages.Clear(); texts.Clear(); items.Clear(); Array.Fill(dungeons, (byte)0); Array.Fill(cooperative, (byte)0);
        Assert.Equal(new byte[] { 1, 2, 3 }, preview.Entries.Select(row => row.Variant));
        Assert.Equal("  官方場景😀\0  ", preview.Entries[0].Name);
        Assert.Equal("協力事件", preview.Entries[1].Name);
        Assert.Equal(new byte[] { 3, 1 }, preview.CooperativeEvents.Select(row => row.Id));
        Assert.Same(preview.CooperativeEvents[0], preview.Entries[1].CooperativeEvent);
        Assert.All(preview.Entries, row => Assert.Null(row.IsOpen));
        Assert.Equal(new ushort[] { 500 }, preview.DeclaredMainMapIds.Order());
        Assert.Single(preview.Entries[0].Awards); Assert.Equal(16, preview.Entries[0].Data.Awards.Length);
        Assert.Throws<NotSupportedException>(() => ((IList<BoundInstanceCatalogRow>)preview.Entries).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<BoundInstanceAward>)preview.Entries[0].Awards).Clear());
        Assert.Throws<NotSupportedException>(() => ((ISet<ushort>)preview.DeclaredMainMapIds).Add(999));
        Assert.DoesNotContain((ushort)999, preview.DeclaredMainMapIds.Add(999).Remove(999));
        Assert.False(preview.AssetsReady); Assert.False(preview.CanSendPackets);
        Assert.Empty(typeof(InstanceCatalogPreview).GetConstructors());
        Assert.All(typeof(InstanceCatalogPreview).GetProperties(), property => Assert.Null(property.SetMethod));
        Assert.All(typeof(InstanceCatalogPreview).GetMethods().Where(method => method.DeclaringType == typeof(InstanceCatalogPreview)),
            method => Assert.StartsWith("get_", method.Name, StringComparison.Ordinal));
    }

    [Fact]
    public void Cancellation_propagates_without_becoming_parser_failure()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var source = new CancellationTokenSource(); source.Cancel();
        var row = InstancePythonVectors.FindCase("bind-basic");
        var error = Assert.Throws<OperationCanceledException>(() => InstanceCatalogParser.ParseDungeons([], source.Token));
        Assert.Null(ParserDiagnostics.GetFailure(error));
        error = Assert.Throws<OperationCanceledException>(() => InstanceCatalogParser.ParseCooperativeEvents([], source.Token));
        Assert.Null(ParserDiagnostics.GetFailure(error));
        error = Assert.Throws<OperationCanceledException>(() => InstanceCatalogParser.Bind(
            Input(row, "DungeonData_C"), Input(row, "CooperateEventData_C"), Stages(row), Texts(row), Items(row), source.Token));
        Assert.Null(ParserDiagnostics.GetFailure(error));
        Assert.Empty(session.Run.Events);
    }

    private static object Parse(JsonElement row)
    {
        switch (row.GetProperty("mode").GetString())
        {
            case "bind":
                var preview = InstanceCatalogParser.Bind(Input(row, "DungeonData_C"), Input(row, "CooperateEventData_C"),
                    Stages(row), Texts(row), Items(row));
                Assert.False(preview.AssetsReady); Assert.False(preview.CanSendPackets);
                return new { records = preview.Entries.Select(Project),
                    cooperative_events = preview.CooperativeEvents.Select(Project),
                    declared_main_map_ids = preview.DeclaredMainMapIds.Order().ToArray() };
            case "dungeon":
                var dungeons = InstanceCatalogParser.ParseDungeons(Raw(row));
                if (!row.GetProperty("summary").GetBoolean()) return dungeons.Select(Project).ToArray();
                foreach (var item in dungeons)
                {
                    Assert.Equal(dungeons[0], item with { Awards = dungeons[0].Awards,
                        DoubleAwardSlots = dungeons[0].DoubleAwardSlots, SpecialAwardSlots = dungeons[0].SpecialAwardSlots });
                    Assert.True(dungeons[0].Awards.SequenceEqual(item.Awards), "Ordered raw award values differ.");
                    Assert.True(dungeons[0].DoubleAwardSlots.SequenceEqual(item.DoubleAwardSlots), "Ordered double-award slots differ.");
                    Assert.True(dungeons[0].SpecialAwardSlots.SequenceEqual(item.SpecialAwardSlots), "Ordered special-award slots differ.");
                }
                return new { count = dungeons.Length, row = Project(dungeons[0]) };
            case "cooperative":
                var events = InstanceCatalogParser.ParseCooperativeEvents(Raw(row));
                if (!row.GetProperty("summary").GetBoolean()) return events.Select(Project).ToArray();
                foreach (var item in events)
                {
                    Assert.Equal(events[0], item with { FollowerIds = events[0].FollowerIds });
                    Assert.True(events[0].FollowerIds.SequenceEqual(item.FollowerIds), "Ordered follower identifiers differ.");
                }
                return new { count = events.Length, row = Project(events[0]) };
            default: throw new InvalidDataException("Unknown synthetic instance fixture mode");
        }
    }

    private static Dictionary<string, object?> Project(DungeonDataRow row) => new()
    {
        ["id"] = row.Id, ["kind"] = row.Kind, ["para_kind"] = row.ParaKind, ["map_id"] = row.MapId,
        ["description_id"] = row.DescriptionId, ["picture"] = row.Picture, ["score_display"] = row.ScoreDisplay,
        ["award_group"] = row.AwardGroup, ["npc_x"] = row.NpcX, ["npc_y"] = row.NpcY,
        ["npc_id"] = row.NpcId, ["quick_id"] = row.QuickId, ["awards"] = row.Awards.Select(Project).ToArray(),
        ["double_award_slots"] = row.DoubleAwardSlots, ["special_award_slots"] = row.SpecialAwardSlots
    };
    private static object Project(InstanceAward row) => new { kind = row.Kind, id = row.Id, value = row.Value };
    private static object Project(CooperativeEventDataRow row) => new
    {
        id = row.Id, text_id = row.TextId, npc_x = row.NpcX, npc_y = row.NpcY, fight_count = row.FightCount,
        step_mark_id = row.StepMarkId, finish_mark_id = row.FinishMarkId, sell_data_id = row.SellDataId,
        follower_ids = row.FollowerIds, follower_reward = Project(row.FollowerReward)
    };
    private static object Project(BoundInstanceCatalogRow row)
    {
        var result = Project(row.Data);
        result["variant"] = row.Variant; result["name"] = row.Name;
        result["min_level"] = row.MinLevel; result["min_members"] = row.MinMembers;
        result["max_members"] = row.MaxMembers; result["time_minutes"] = row.TimeMinutes;
        result["room_count"] = row.RoomCount; result["is_open"] = row.IsOpen;
        result["awards"] = row.Awards.Select(award => new uint[] { award.Slot, award.Kind, award.Id, award.Value }).ToArray();
        result["cooperative_event"] = row.CooperativeEvent is { } cooperative ? Project(cooperative) : null;
        result["creation_supported"] = row.CreationSupported;
        return result;
    }

    private static Dictionary<ushort, StageDataRow> Stages(JsonElement row) =>
        row.GetProperty("metadata").GetProperty("stages").EnumerateObject().ToDictionary(
            pair => ushort.Parse(pair.Name, CultureInfo.InvariantCulture), pair =>
            {
                var stage = pair.Value;
                byte B(string name) => stage.GetProperty(name).GetByte();
                ushort U16(string name) => stage.GetProperty(name).GetUInt16();
                return new StageDataRow(U16("id"), stage.GetProperty("name_id").GetUInt32(), U16("model_id"),
                    B("max_members"), B("min_members"), U16("min_level"), U16("time_minutes"), B("tag"),
                    B("room_capacity"), B("group"), U16("flag"), B("pos_x_ratio"), B("pos_y_ratio"),
                    U16("map_width"), U16("map_height"), U16("small_offset_x"), U16("small_offset_y"));
            });
    private static Dictionary<uint, string?> Texts(JsonElement row) => row.GetProperty("metadata").GetProperty("texts")
        .EnumerateObject().ToDictionary(pair => uint.Parse(pair.Name, CultureInfo.InvariantCulture), pair => pair.Value.GetString());
    private static HashSet<uint> Items(JsonElement row) => row.GetProperty("metadata").GetProperty("item_ids")
        .EnumerateArray().Select(item => item.GetUInt32()).ToHashSet();
    private static byte[] Input(JsonElement row, string name) => Convert.FromBase64String(row.GetProperty("inputs").GetProperty(name).GetString()!);
    private static byte[] Raw(JsonElement row)
    {
        var raw = row.GetProperty("raw");
        if (raw.TryGetProperty("base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        int width = raw.GetProperty("width").GetInt32(), count = raw.GetProperty("count").GetInt32();
        string name = width == InstanceCatalogParser.DungeonRecordBytes ? "dungeon-basic" : "cooperative-basic";
        byte[] first = Raw(InstancePythonVectors.FindCase(name)).AsSpan(4, width).ToArray();
        byte[] bytes = new byte[4 + width * count]; BinaryPrimitives.WriteInt32LittleEndian(bytes, count);
        for (int index = 0; index < count; index++) first.CopyTo(bytes.AsSpan(4 + width * index));
        return bytes;
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
        Assert.True(JsonNode.DeepEquals(expected, actual), "Retained Python and C# diagnostics differ.");
    }
    private static void AssertJson(JsonElement expected, object actual) => Assert.True(
        JsonNode.DeepEquals(JsonNode.Parse(expected.GetRawText()), JsonSerializer.SerializeToNode(actual)),
        "Retained Python and C# results differ.");
}
