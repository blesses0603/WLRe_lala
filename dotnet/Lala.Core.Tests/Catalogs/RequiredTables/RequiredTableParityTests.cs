using System.Buffers.Binary;
using System.Collections;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs.RequiredTables;

public sealed partial class RequiredTableParityTests
{
    [Theory]
    [MemberData(nameof(RequiredTableOracleCases.CaseIds), MemberType = typeof(RequiredTableOracleCases))]
    public void Actual_decorated_python_values_rejection_order_and_diagnostics_match(int id)
    {
        var row = RequiredTableOracleCases.Case(id);
        Assert.Equal(id, row.GetProperty("id").GetInt32());
        using var session = ParserDiagnostics.BeginSession();
        Exception? error = null;
        if (row.GetProperty("error").ValueKind == JsonValueKind.Null)
        {
            var expected = JsonNode.Parse(row.GetProperty("expected").GetRawText())!;
            if (row.GetProperty("mode").GetString() == "compose")
            {
                // The exact runtime binding block returns these trusted-runtime labels. This
                // offline API deliberately omits them; supplied maps cannot grant provenance.
                expected["expedition"]!.AsObject().Remove("revision");
                expected["expedition"]!.AsObject().Remove("source_kind");
            }
            var actual = JsonSerializer.SerializeToNode(Parse(row))!;
            Assert.True(JsonNode.DeepEquals(expected, actual), row.GetProperty("name").GetString());
            AssertOrderedKeys(expected, actual);
        }
        else
        {
            error = Record.Exception(() => Parse(row));
            Assert.NotNull(error);
            if (row.GetProperty("error").GetProperty("type").GetString() == "UnicodeDecodeError")
                Assert.IsType<DecoderFallbackException>(error); // strict codec exception, platform-specific message
            else
            {
                Assert.IsType<CatalogDecodeException>(error);
                Assert.Equal(row.GetProperty("error").GetProperty("message").GetString(), error.Message);
            }
            Assert.Null(error.InnerException);
        }
        var expectedEvents = row.GetProperty("diagnostics");
        Assert.Equal(expectedEvents.GetArrayLength(), session.Run.Events.Length);
        for (int i = 0; i < expectedEvents.GetArrayLength(); i++) AssertDiagnostic(expectedEvents[i], session.Run.Events[i]);
        if (error is not null)
        {
            if (row.GetProperty("failure").ValueKind == JsonValueKind.Null) Assert.Null(ParserDiagnostics.GetFailure(error));
            else AssertDiagnostic(row.GetProperty("failure"), ParserDiagnostics.GetFailure(error)!, false);
        }
        Assert.False(session.Run.AssetsReady);
        Assert.False(session.Run.CanSendPackets);
    }

    [Theory]
    [MemberData(nameof(RequiredTableOracleCases.SourceRefs), MemberType = typeof(RequiredTableOracleCases))]
    public void Actual_source_hash_normalizes_only_CRLF(string path, string expected)
    {
        byte[] source = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
        using var normalized = new MemoryStream();
        for (int i = 0; i < source.Length; i++)
            if (source[i] != 13 || i + 1 == source.Length || source[i + 1] != 10) normalized.WriteByte(source[i]);
        Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
    }

    private static void AssertDiagnostic(JsonElement expectedElement, ParserDiagnosticEvent actualEvent, bool identity = true)
    {
        Assert.NotNull(actualEvent);
        var expected = JsonNode.Parse(expectedElement.GetRawText())!;
        if (expected["error_type"] is not null)
        {
            string type = expected["error_type"]!.GetValue<string>();
            Assert.Contains(type, new[] { "ValueError", "ProtocolError", "UnicodeDecodeError" });
            expected["error_type"] = type == "UnicodeDecodeError" ? nameof(DecoderFallbackException) : nameof(CatalogDecodeException);
        }
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(actualEvent), default).AsSpan())!;
        if (!identity) actual.AsObject().Remove("identity");
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => "Diagnostic mismatch: " + actual + " expected: " + expected);
    }

    private static void AssertOrderedKeys(JsonNode? expected, JsonNode? actual)
    {
        if (expected is JsonObject map)
        {
            var other = Assert.IsType<JsonObject>(actual);
            Assert.Equal(map.Select(pair => pair.Key), other.Select(pair => pair.Key));
            foreach (var (key, value) in map) AssertOrderedKeys(value, other[key]);
        }
        else if (expected is JsonArray array)
        {
            var other = Assert.IsType<JsonArray>(actual);
            for (int i = 0; i < array.Count; i++) AssertOrderedKeys(array[i], other[i]);
        }
    }

    private static object Parse(JsonElement row)
    {
        string mode = row.GetProperty("mode").GetString()!;
        bool summary = row.GetProperty("summary").GetBoolean();
        if (mode == "talk")
        {
            var result = TalkDataParser.Parse(Raw(row, "raw"));
            return summary ? Summary(result) : TalkMap(result);
        }
        if (mode == "npcs")
        {
            var result = ExpeditionCatalogParser.ParseNpcs(Raw(row, "npc"), Raw(row, "career"));
            return summary ? Summary(result) : NpcMap(result);
        }
        if (mode is "catalog" or "attach")
        {
            var result = ExpeditionCatalogParser.ParseCatalog(Raw(row, "tasks"), Raw(row, "levels"));
            if (mode == "attach") result = ExpeditionCatalogParser.AttachNames(result, Raw(row, "text"));
            return summary ? Summary(result) : CatalogMap(result);
        }
        if (mode == "compose")
        {
            var result = OfflineRuntimeTableDecoder.Decode(SourceMap(row));
            Assert.False(result.HasVerifiedProvenance);
            Assert.False(result.AssetsReady); Assert.False(result.CanSendPackets); Assert.False(result.RuntimeAdmitted);
            Assert.False(result.Expedition.AssetsReady); Assert.False(result.Expedition.CanSendPackets); Assert.False(result.Expedition.RuntimeAdmitted);
            Assert.Equal("supplied_offline_tables", result.SourceKind);
            var expedition = CatalogMap(result.Expedition);
            expedition.Add("npcs", NpcMap(result.Npcs));
            return new Dictionary<string, object?> { ["talks"] = TalkMap(result.Talks), ["texts"] = result.Texts, ["expedition"] = expedition };
        }
        throw new InvalidDataException("Unknown oracle mode");
    }

    private static Dictionary<string, object?> TaskMap(ExpeditionTaskData row)
    {
        var result = new Dictionary<string, object?>
        {
            ["id"] = row.Id, ["area"] = row.Area, ["area_name"] = row.AreaName, ["difficulty"] = row.Difficulty,
            ["name_id"] = row.NameId, ["description_id"] = row.DescriptionId, ["minutes"] = row.Minutes,
            ["faith_cost"] = row.FaithCost, ["success_rate"] = row.SuccessRate, ["condition"] = row.Condition.ToArray(),
            ["recommendations"] = row.Recommendations.Select(value => new Dictionary<string, object?>
                { ["condition"] = value.Condition.ToArray(), ["bonus"] = value.Bonus }).ToArray(),
            ["expedition_exp"] = row.ExpeditionExp, ["rewards"] = row.Rewards.Select(RewardMap).ToArray(),
            ["special_rate"] = row.SpecialRate, ["special_reward"] = RewardMap(row.SpecialReward), ["exp"] = row.Exp
        };
        if (row.Name is not null) { result.Add("name", row.Name); result.Add("area_label", row.AreaLabel); }
        return result;
    }
    private static object RewardMap(ExpeditionReward row) => new Dictionary<string, object?>
        { ["kind"] = row.Kind, ["id"] = row.Id, ["value"] = row.Value };
    private static object LevelMap(ExpeditionLevelData row) => new Dictionary<string, object?>
        { ["teams"] = row.Teams, ["difficulty"] = row.Difficulty, ["reduction"] = row.Reduction };
    private static object TalkRow(TalkDataRow row) => new Dictionary<string, object?> { ["text"] = row.Text, ["voice_id"] = row.VoiceId };
    private static object NpcRow(ExpeditionNpcData row) => new Dictionary<string, object?> { ["element"] = row.Element, ["kind"] = row.Kind, ["original"] = row.Original };
    private static object TalkMap(IReadOnlyDictionary<ushort, TalkDataRow> rows) => rows.ToDictionary(pair => Key(pair.Key), pair => TalkRow(pair.Value));
    private static object NpcMap(IReadOnlyDictionary<ushort, ExpeditionNpcData> rows) => rows.ToDictionary(pair => Key(pair.Key), pair => NpcRow(pair.Value));
    private static Dictionary<string, object?> CatalogMap(ExpeditionCatalogData catalog) => new()
    {
        ["tasks"] = catalog.Tasks.ToDictionary(pair => Key(pair.Key), pair => TaskMap(pair.Value)),
        ["levels"] = catalog.Levels.ToDictionary(pair => Key(pair.Key), pair => LevelMap(pair.Value)),
        ["source_sha256"] = catalog.SourceSha256
    };
    private static string Key(ushort value) => value.ToString(CultureInfo.InvariantCulture);

    // Stream the full ordered result digest one row at a time. No giant retained JSON or
    // additional projection tree for the 65,535-task and 65,536-talk accepted boundaries.
    private static object Summary(object result)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        int count;
        if (result is ExpeditionCatalogData catalog)
        {
            count = catalog.Tasks.Count;
            Header('d', 3); Emit("tasks"); Header('d', count);
            foreach (var (id, row) in catalog.Tasks) { Emit(Key(id)); Emit(TaskMap(row)); }
            Emit("levels"); Header('d', catalog.Levels.Count);
            foreach (var (id, row) in catalog.Levels) { Emit(Key(id)); Emit(LevelMap(row)); }
            Emit("source_sha256"); Header('d', catalog.SourceSha256.Count);
            foreach (var (key, value) in catalog.SourceSha256) { Emit(key); Emit(value); }
        }
        else if (result is IReadOnlyDictionary<ushort, TalkDataRow> talks)
        {
            count = talks.Count; Header('d', count);
            foreach (var (id, row) in talks) { Emit(Key(id)); Emit(TalkRow(row)); }
        }
        else if (result is IReadOnlyDictionary<ushort, ExpeditionNpcData> npcs)
        {
            count = npcs.Count; Header('d', count);
            foreach (var (id, row) in npcs) { Emit(Key(id)); Emit(NpcRow(row)); }
        }
        else throw new InvalidDataException("Unknown summary");
        return new { sha256 = Convert.ToHexStringLower(hash.GetHashAndReset()), count };

        void Header(char tag, int count)
        {
            Span<byte> bytes = stackalloc byte[5]; bytes[0] = (byte)tag;
            BinaryPrimitives.WriteUInt32LittleEndian(bytes[1..], (uint)count); hash.AppendData(bytes);
        }
        void Emit(object? value)
        {
            switch (value)
            {
                case null: hash.AppendData("n"u8); break;
                case bool boolean: hash.AppendData(boolean ? "t"u8 : "f"u8); break;
                case string text:
                    byte[] encoded = Encoding.UTF8.GetBytes(text); Header('s', encoded.Length); hash.AppendData(encoded); break;
                case IDictionary map:
                    Header('d', map.Count);
                    foreach (DictionaryEntry pair in map) { Emit((string)pair.Key); Emit(pair.Value); } break;
                case Array sequence:
                    Header('l', sequence.Length); foreach (object? item in sequence) Emit(item); break;
                case byte or ushort or uint or int or long:
                    Span<byte> integer = stackalloc byte[9]; integer[0] = (byte)'i';
                    BinaryPrimitives.WriteInt64LittleEndian(integer[1..], Convert.ToInt64(value, CultureInfo.InvariantCulture));
                    hash.AppendData(integer); break;
                default: throw new InvalidDataException("Unknown digest scalar");
            }
        }
    }

    private static Dictionary<string, ReadOnlyMemory<byte>> SourceMap(JsonElement row) => new(StringComparer.Ordinal)
    {
        ["TalkData_C"] = Raw(row, "talk"), ["TextData_C"] = Raw(row, "text"),
        ["AdventureData_C"] = Raw(row, "tasks"), ["AdventureLvData_C"] = Raw(row, "levels"),
        ["NpcData_C"] = Raw(row, "npc"), ["NpcCareerData_C"] = Raw(row, "career")
    };
    private static JsonElement Fixture(string name) => Enumerable.Range(0, RequiredTableOracleCases.VectorCount)
        .Select(RequiredTableOracleCases.Case).First(row => row.GetProperty("name").GetString() == name);
    private static byte[] Raw(JsonElement row, string name)
    {
        var spec = row.GetProperty("inputs").GetProperty(name);
        if (spec.TryGetProperty("base64", out var encoded)) return Convert.FromBase64String(encoded.GetString()!);
        string kind = spec.GetProperty("kind").GetString()!;
        if (kind == "zeros") return new byte[spec.GetProperty("size").GetInt32()];
        int count = spec.GetProperty("count").GetInt32();
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
        writer.Write(count);
        for (int i = 0; i < count; i++)
        {
            switch (kind)
            {
                case "talk-count":
                    writer.Write((ushort)i); writer.Write((ushort)0);
                    writer.Write(new byte[] { 0, 1, 2, 3, 4 }); writer.Write((ushort)i);
                    writer.Write(Enumerable.Range(0, 28).Select(value => (byte)value).ToArray()); break;
                case "task-count":
                    writer.Write((ushort)(i + 1)); writer.Write((byte)255); writer.Write(20u); writer.Write((byte)255);
                    writer.Write(10u); writer.Write(uint.MaxValue); writer.Write(ushort.MaxValue); writer.Write((byte)100);
                    writer.Write(ushort.MaxValue); writer.Write((ushort)0); writer.Write((ushort)1); writer.Write(ushort.MaxValue);
                    for (int j = 0; j < 4; j++)
                    { writer.Write((ushort)j); writer.Write((ushort)(65535 - j)); writer.Write((ushort)(j + 256)); writer.Write((ushort)(65535 - j)); }
                    writer.Write(uint.MaxValue);
                    for (int j = 0; j < 3; j++) { writer.Write((byte)(j * 127)); writer.Write(uint.MaxValue - (uint)j); writer.Write((uint)j); }
                    writer.Write(ushort.MaxValue); writer.Write((byte)255); writer.Write(uint.MaxValue); writer.Write(uint.MaxValue); writer.Write(int.MinValue); break;
                case "level-count":
                    writer.Write((byte)i); writer.Write(uint.MaxValue); writer.Write(0u); writer.Write((byte)7); writer.Write((byte)255);
                    writer.Write((ushort)1000); writer.Write((byte)255); writer.Write((byte)255); break;
                case "npc-over-composition-cap":
                case "npc-count":
                    if (kind == "npc-over-composition-cap")
                    {
                        byte[] nameBytes = Encoding.Unicode.GetBytes(new string('字', 32767));
                        writer.Write((ushort)nameBytes.Length); writer.Write(nameBytes);
                        writer.Write((ushort)nameBytes.Length); writer.Write(nameBytes);
                    }
                    else { writer.Write((ushort)0); writer.Write((ushort)0); }
                    byte[] fields = Enumerable.Range(0, 203).Select(value => (byte)value).ToArray();
                    BinaryPrimitives.WriteUInt16LittleEndian(fields.AsSpan(1), (ushort)(i + 1)); fields[74] = 255; fields[106] = 255;
                    writer.Write(fields); break;
                case "career-count":
                    writer.Write(ushort.MaxValue); writer.Write((ushort)i); writer.Write((ushort)i);
                    writer.Write(Enumerable.Range(0, 11).Select(value => (byte)value).ToArray()); break;
                default: throw new InvalidDataException("Unknown input recipe");
            }
        }
        return stream.ToArray();
    }
}
