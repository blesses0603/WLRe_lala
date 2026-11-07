using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Tests.TestSupport;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.World.Eve;

public sealed class EveDoorTests
{
    [Theory]
    [MemberData(nameof(EveDoorPythonVectors.Cases), MemberType = typeof(EveDoorPythonVectors), DisableDiscoveryEnumeration = true)]
    public void Actual_python_values_errors_and_diagnostics_match(string name, int rowIndex)
    {
        var row = EveDoorPythonVectors.ReadCase(rowIndex);
        Assert.Equal(name, row.GetProperty("name").GetString());
        byte[] raw = Raw(row);
        using var session = ParserDiagnostics.BeginSession();
        if (row.GetProperty("divergence").ValueKind != JsonValueKind.Null)
        {
            Assert.Equal("retained-budget", row.GetProperty("divergence").GetString());
            Assert.Equal("passed", row.GetProperty("diagnostic").GetProperty("status").GetString());
            Assert.Equal(1, row.GetProperty("expected").GetProperty("source_scene_count").GetInt32());
            var error = Assert.Throws<EveDoorSourceException>(() => Parse(row, raw));
            Assert.Equal("Eve door projection exceeds retained data limit", error.Message);
            AssertAttachedFailure(Assert.Single(session.Run.Events), error);
            return; // Safety limit is an explicit divergence, not claimed as parity.
        }
        EveDoorSourceException? failure = null;
        if (row.GetProperty("error").ValueKind == JsonValueKind.String)
        {
            failure = Assert.Throws<EveDoorSourceException>(() => Parse(row, raw));
            Assert.Equal(row.GetProperty("error").GetString(), failure.Message);
            Assert.Null(failure.InnerException);
        }
        else
        {
            var result = Parse(row, raw);
            var actual = JsonSerializer.SerializeToNode(SourceValue(result));
            var expected = JsonNode.Parse(row.GetProperty("expected").GetRawText());
            LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => name + ": " + actual);
            Assert.Equal(result.Scenes.Sum(scene => scene.Doors.Length), result.DoorCount);
            Assert.False(result.AssetsReady);
            Assert.False(result.CanSendPackets);
            Assert.False(result.AuthorizesTravel);
            Assert.False(result.AuthorizesRuntime);
            Assert.Equal(row.GetProperty("expected").EnumerateObject().Select(p => ushort.Parse(p.Name, CultureInfo.InvariantCulture)),
                result.Scenes.Select(s => s.SceneId));
        }
        var observed = Assert.Single(session.Run.Events);
        var sourceDiagnostic = JsonNode.Parse(row.GetProperty("diagnostic").GetRawText())!;
        if (failure is not null)
        {
            Assert.Equal("DoorSourceError", sourceDiagnostic["error_type"]!.GetValue<string>());
            sourceDiagnostic["error_type"] = nameof(EveDoorSourceException);
            AssertAttachedFailure(observed, failure);
        }
        var diagnostic = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observed), default).AsSpan());
        LazyAssert.True(JsonNode.DeepEquals(sourceDiagnostic, diagnostic), () => name + ": " + diagnostic);
    }

    [Fact]
    public void Discovery_only_returns_scalar_identifiers_and_sources_are_reviewed()
    {
        var cases = EveDoorPythonVectors.Cases().ToArray();
        Assert.Equal(EveDoorPythonVectors.VectorCount, cases.Length);
        for (int index = 0; index < cases.Length; index++)
        {
            Assert.Equal(2, cases[index].Length);
            Assert.InRange(Assert.IsType<string>(cases[index][0]).Length, 1, 80);
            Assert.Equal(index, Assert.IsType<int>(cases[index][1]));
            Assert.Equal(cases[index][0], EveDoorPythonVectors.ReadCase(index).GetProperty("name").GetString());
        }
        foreach (var (path, expected) in new[]
        {
            ("wlre/services/world/doors_1275.py", EveDoorPythonVectors.SourceSha256),
            ("wlre/services/parser_diagnostics.py", EveDoorPythonVectors.DiagnosticsSha256)
        })
        {
            byte[] bytes = File.ReadAllBytes(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../", path)));
            using var normalized = new MemoryStream();
            for (int i = 0; i < bytes.Length; i++)
                if (bytes[i] != 13 || i + 1 == bytes.Length || bytes[i + 1] != 10) normalized.WriteByte(bytes[i]);
            Assert.Equal(expected, Convert.ToHexStringLower(SHA256.HashData(normalized.ToArray())));
        }
    }

    [Fact]
    public void Every_single_and_double_byte_cp950_input_matches_python()
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Span<byte> input = stackalloc byte[2];
        Span<byte> length = stackalloc byte[2];
        for (int size = 1; size <= 2; size++)
            for (int value = 0; value < (size == 1 ? 256 : 65536); value++)
            {
                if (size == 1) input[0] = (byte)value;
                else BinaryPrimitives.WriteUInt16BigEndian(input, (ushort)value);
                string? decoded = EveDoorCp950.Decode(input[..size]);
                byte[] bytes = decoded is null ? [] : Encoding.UTF8.GetBytes(decoded);
                BinaryPrimitives.WriteUInt16LittleEndian(length, decoded is null ? ushort.MaxValue : (ushort)bytes.Length);
                hash.AppendData(length);
                hash.AppendData(bytes);
            }
        Assert.Equal(EveDoorPythonVectors.CodecSha256, Convert.ToHexStringLower(hash.GetHashAndReset()));
        Assert.Throws<ArgumentOutOfRangeException>(() => EveDoorCp950.Decode(new byte[21]));
    }

    [Fact]
    public void Public_surface_has_no_custom_pin_or_layout_bypass()
    {
        var methods = typeof(EveDoorParser).GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
        var method = Assert.Single(methods);
        Assert.Equal(nameof(EveDoorParser.ParsePinned1275), method.Name);
        Assert.Equal(new[] { typeof(ReadOnlySpan<byte>), typeof(CancellationToken) }, method.GetParameters().Select(p => p.ParameterType));
        Assert.Equal("f5fc56b1d6cf7c00dd20b2f35c04b4cbc60c92ccdb6085fbe465c7e6526745ad", EveDoorParser.SourceSha256);
        var error = Assert.Throws<EveDoorSourceException>(() => EveDoorParser.ParsePinned1275(Fixture("basic")));
        Assert.Equal("1275 Eve.bytes SHA-256 與已確認來源不符", error.Message);
        Assert.Equal("eve-1275-pinned", ParserDiagnostics.GetFailure(error)!.Definition.Schema);
    }

    [Fact]
    public void Caller_buffers_and_nested_outputs_are_detached_and_immutable()
    {
        byte[] raw = Fixture("duplicate-references-and-multiple-doors");
        byte[] envelope = new byte[raw.Length + 10];
        raw.CopyTo(envelope, 5);
        var result = EveDoorParser.ParseLayout(envelope.AsSpan(5, raw.Length));
        var before = JsonSerializer.Serialize(SourceValue(result));
        Array.Fill(raw, (byte)0xff);
        Array.Fill(envelope, (byte)0);
        Assert.Equal(before, JsonSerializer.Serialize(SourceValue(result)));
        var row = result.Scenes[0].Doors[0];
        Assert.Equal(new byte[] { 7, 8, 7 }, row.EventIds);
        Assert.Equal(new byte[] { 7, 8, 7 }, row.TouchEventIds);
        Assert.Same(row.TouchEventRecords[0], row.TouchEventRecords[2]);
        Assert.Same(row.TouchEventRecords[0], result.Scenes[0].Doors[1].TouchEventRecords[0]);
        Assert.True(row.TouchEventRecords[0].DestinationDecoded);
        Assert.False(result.AuthorizesTravel);
        Assert.Throws<NotSupportedException>(() => ((IList<byte>)row.EventIds)[0] = 99);
        Assert.Throws<NotSupportedException>(() => ((IList<EveDoorScene>)result.Scenes).Clear());
        var condition = row.TouchEventRecords[0].Conditions[0];
        Assert.Equal(uint.MaxValue, condition.Data.ParaValue);
        Assert.Equal(int.MinValue, condition.Results[0].ParaValue);
        Assert.Equal(ushort.MaxValue, condition.Data.ParaType);
        Assert.Equal(uint.MaxValue, condition.Data.ParaClass1);
    }

    [Fact]
    public void No_session_success_is_quiet_failure_is_lazy_and_diagnostics_contain_no_names_or_raw()
    {
        Assert.False(ParserDiagnostics.IsActive);
        EveDoorParser.ParseLayout(Fixture("basic"));
        var raw = Fixture("duplicate-door");
        var expected = Convert.ToHexStringLower(SHA256.HashData(raw));
        var failure = Assert.Throws<EveDoorSourceException>(() => EveDoorParser.ParseLayout(raw));
        Array.Fill(raw, (byte)0);
        var observation = ParserDiagnostics.GetFailure(failure)!;
        Assert.True(observation.Failed);
        Assert.Equal(expected, observation.Inputs["raw"].Sha256);
        string report = Encoding.UTF8.GetString(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observation), default).AsSpan());
        Assert.DoesNotContain("Touch", report);
        Assert.DoesNotContain("Convey", report);
        Assert.DoesNotContain(failure.Message, report);
        Assert.False(ParserDiagnostics.IsActive);
        using var session = ParserDiagnostics.BeginSession();
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Cancellation_propagates_without_diagnostics_or_partial_success()
    {
        using var session = ParserDiagnostics.BeginSession();
        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        foreach (var invoke in new Action[]
        {
            () => EveDoorParser.ParseLayout(Fixture("basic"), cancelled.Token),
            () => EveDoorParser.ParsePinned1275(Fixture("basic"), cancelled.Token),
            () => EveDoorParser.ParseLayout([], cancelled.Token),
            () => EveDoorParser.ParsePinned1275([], cancelled.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(invoke);
            Assert.Equal(cancelled.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(session.Run.Events);
    }

    [Fact]
    public void Oversized_input_is_rejected_without_an_oversized_snapshot()
    {
        Assert.Throws<EveDoorSourceException>(() => EveDoorParser.ParseLayout([]));
        byte[] raw = new byte[EveDoorParser.MaxSourceBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        var error = Assert.Throws<EveDoorSourceException>(() => EveDoorParser.ParseLayout(raw));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 1024 * 1024);
        Assert.Equal("Eve 表頭或大小無效", error.Message);
        Assert.Equal(raw.Length, ParserDiagnostics.GetFailure(error)!.Inputs["raw"].Size);
    }

    [Fact]
    public void Door_parser_preserves_source_scope_instead_of_importing_all_section_validation()
    {
        foreach (string name in new[] { "npc-zero-id-and-duplicate-indices-ignored", "unparsed-later-sections-opaque",
            "identical-overlap-is-source-valid", "directory-0", "directory-8" })
        {
            byte[] raw = Fixture(name);
            EveDoorParser.ParseLayout(raw);
            Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw));
        }
    }

    private static void AssertAttachedFailure(ParserDiagnosticEvent observed, Exception error)
    {
        // Sessions detach observations when storing them. The attached failure must
        // retain every diagnostic field, not the same object identity.
        var attached = Assert.IsType<ParserDiagnosticEvent>(ParserDiagnostics.GetFailure(error));
        var expected = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(observed), default).AsSpan());
        var actual = JsonNode.Parse(ParserDiagnosticJson.Serialize(ParserDiagnosticRun.Project(attached), default).AsSpan());
        LazyAssert.True(JsonNode.DeepEquals(expected, actual), () => "Attached diagnostic differs: " + actual);
    }

    private static EveDoorProjection Parse(JsonElement row, byte[] raw) =>
        row.GetProperty("operation").GetString() == "pinned" ? EveDoorParser.ParsePinned1275(raw) : EveDoorParser.ParseLayout(raw);
    private static byte[] Raw(JsonElement row)
    {
        byte[] raw = Convert.FromBase64String(row.GetProperty("raw").GetString()!);
        Array.Resize(ref raw, raw.Length + row.GetProperty("zero_padding").GetInt32());
        return raw;
    }
    private static byte[] Fixture(string name)
    {
        var id = EveDoorPythonVectors.Cases().Single(row => (string)row[0] == name);
        return Raw(EveDoorPythonVectors.ReadCase((int)id[1]));
    }

    // Test-only source-shaped projection. Production exposes typed immutable values,
    // not mutable dictionaries or a serialized destination/command authorization.
    internal static Dictionary<string, object> SourceValue(EveDoorProjection projection) =>
        projection.Scenes.ToDictionary(scene => scene.SceneId.ToString(CultureInfo.InvariantCulture),
            scene => (object)scene.Doors.Select(Door).ToArray(), StringComparer.Ordinal);
    private static Dictionary<string, object?> Name(EveDoorName name) => new()
        { ["name"] = name.Name, ["name_bytes"] = name.NameBytes, ["name_valid"] = name.NameValid };
    private static Dictionary<string, object?> Door(EveDoorRow row)
    {
        var value = Name(row.Name);
        value["index"] = row.Index; value["x"] = row.X; value["y"] = row.Y; value["event_ids"] = row.EventIds;
        value["right"] = row.Right; value["bottom"] = row.Bottom; value["sign_type"] = row.SignType;
        value["sign_x"] = row.SignX; value["sign_y"] = row.SignY;
        value["col_x"] = row.ColX; value["col_y"] = row.ColY; value["col_z"] = row.ColZ;
        value["touch_event_ids"] = row.TouchEventIds;
        value["touch_event_records"] = row.TouchEventRecords.Select(Event).ToArray();
        return value;
    }
    private static Dictionary<string, object?> Event(EveDoorTouchEvent row)
    {
        var value = Name(row.Name);
        value["index"] = row.Index; value["occur_type"] = row.OccurType;
        value["conditions"] = row.Conditions.Select(condition => new { data = Parameter(condition.Data),
            results = condition.Results.Select(Parameter).ToArray() }).ToArray();
        value["convey_transfers"] = row.ConveyTransfers.Select(Transfer).ToArray();
        value["missing_convey_ids"] = row.MissingConveyIds;
        value["destination_decoded"] = row.DestinationDecoded;
        return value;
    }
    private static Dictionary<string, object?> Transfer(EveDoorTransfer row)
    {
        var value = Name(row.Convey.Name);
        value["convey_id"] = row.Convey.ConveyId; value["destination"] = row.Convey.Destination;
        value["arrival_x"] = row.Convey.ArrivalX; value["arrival_y"] = row.Convey.ArrivalY;
        value["condition"] = Parameter(row.Condition);
        return value;
    }
    private static object Parameter(EveDoorConditionData data) => new { id = data.Id, para_main = data.ParaMain,
        para_kind = data.ParaKind, para_style = data.ParaStyle, para_type = data.ParaType, para_operator = data.ParaOperator,
        para_value = data.ParaValue, group_number = data.GroupNumber, para_class1 = data.ParaClass1, para_class2 = data.ParaClass2 };
    private static object Parameter(EveDoorResultData data) => new { id = data.Id, para_main = data.ParaMain,
        para_kind = data.ParaKind, para_style = data.ParaStyle, para_type = data.ParaType, para_operator = data.ParaOperator,
        para_value = data.ParaValue, group_number = data.GroupNumber, para_class1 = data.ParaClass1, para_class2 = data.ParaClass2 };
}
