using System.Buffers.Binary;
using System.Collections.Immutable;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Lala.Core.World.Eve;
using Xunit;

namespace Lala.Core.Tests.World.Eve;

public sealed class EveV115Tests
{
    [Theory]
    [MemberData(nameof(EvePythonVectors.Cases), MemberType = typeof(EvePythonVectors), DisableDiscoveryEnumeration = true)]
    public void Retained_python_exact_documents_and_failure_messages(string name, JsonElement row)
    {
        byte[] raw = Raw(row);
        string? source = row.GetProperty("source").GetString();
        if (row.GetProperty("divergence").GetBoolean())
        {
            // This directed source defect is a deliberate rejection, NOT parity success.
            Assert.Equal("duplicate-scene-override-source-bug", name);
            Assert.Equal(JsonValueKind.Null, row.GetProperty("error").ValueKind);
            foreach (var document in row.GetProperty("documents").EnumerateObject())
            {
                using var parsed = JsonDocument.Parse(document.Value.GetString()!);
                Assert.Single(parsed.RootElement.GetProperty("scenes").EnumerateObject());
                int count = parsed.RootElement.GetProperty("record_count").GetInt32();
                int retained = parsed.RootElement.GetProperty("scenes").GetProperty("1").GetArrayLength();
                Assert.True(count > retained); // Source counted both scenes but overwrote one.
            }
            Assert.Equal("Duplicate scene ID or out-of-bounds offset", Assert.Throws<EveDecodeException>(Parse).Message);
            return;
        }
        if (row.GetProperty("error").ValueKind == JsonValueKind.String)
        {
            Assert.Equal(row.GetProperty("error").GetString(), Assert.Throws<EveDecodeException>(Parse).Message);
            return;
        }
        var result = Parse();
        Assert.True(result.Scenes.Select(s => (int)s.SceneId).SequenceEqual(result.Scenes.Select(s => (int)s.SceneId).Order()));
        foreach (var property in row.GetProperty("documents").EnumerateObject())
        {
            byte[] expected = Encoding.UTF8.GetBytes(property.Value.GetString()!);
            Assert.Equal(expected, result.ToJsonUtf8(property.Name).ToArray());
        }
        Assert.Equal(source is null or EveV115Parser.NpcSource, result.IncludesNpcs);
        Assert.Equal(source is null or EveV115Parser.InteractionSource, result.IncludesInteractions);
        EveV115Indexes Parse() => source is null ? EveV115Parser.Parse(raw) : EveV115Parser.Parse(raw, source);
    }

    [Fact]
    public void Embedded_resource_names_are_platform_independent_and_not_satellites()
    {
        var names = typeof(EveV115Tests).Assembly.GetManifestResourceNames()
            .Where(name => name.StartsWith("Lala.Core.Tests.World.Eve.Fixtures.", StringComparison.Ordinal))
            .Order(StringComparer.Ordinal).ToArray();
        Assert.Equal(EvePythonVectors.ResourceCount, names.Length);
        Assert.Equal(Enumerable.Range(1, EvePythonVectors.ResourceCount)
            .Select(index => $"Lala.Core.Tests.World.Eve.Fixtures.eve-v115-{index:000}.json.gz"), names);
    }

    [Fact]
    public void Source_hashes_match_actual_retained_bytes_without_newline_normalization()
    {
        var path = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../wlre/services/world/eve_v115.py"));
        byte[] bytes = File.ReadAllBytes(path);
        string actual = Convert.ToHexStringLower(SHA256.HashData(bytes));
        Assert.True(actual == EvePythonVectors.SourceSha256 || actual == EvePythonVectors.SourceCrlfSha256);
    }

    [Fact]
    public void Snapshot_and_serialization_are_detached_immutable_and_repeatable()
    {
        byte[] raw = Fixture("basic");
        var indexes = EveV115Parser.Parse(raw);
        var before = indexes.ToJsonUtf8(EveV115Parser.NpcSource);
        Array.Fill(raw, (byte)255);
        Assert.Equal(before.ToArray(), indexes.ToJsonUtf8(EveV115Parser.NpcSource).ToArray());
        Assert.Equal(9001u, indexes.Scenes.Single().Npcs.Single().NpcId);
        Assert.Equal(new byte[] { 7 }, indexes.Scenes.Single().Npcs.Single().EventIds);
        Assert.Equal(1, indexes.NpcRecordCount);
        Assert.Equal(1, indexes.InteractionRecordCount);
        var changed = indexes.Scenes[0].Npcs[0].EventIds.SetItem(0, 255);
        Assert.Equal(255, changed[0]);
        Assert.Equal(7, indexes.Scenes[0].Npcs[0].EventIds[0]);
    }

    [Fact]
    public void Both_and_single_derivation_are_byte_identical_and_selected_only()
    {
        var raw = Fixture("basic");
        var both = EveV115Parser.DeriveIndexes(raw);
        foreach (var entry in both) Assert.Equal(entry.Value.ToArray(), EveV115Parser.DeriveIndex(raw, entry.Key).ToArray());
        var npcs = EveV115Parser.Parse(raw, EveV115Parser.NpcSource);
        Assert.Empty(npcs.Scenes[0].Interactions);
        Assert.Throws<EveDecodeException>(() => npcs.ToJsonUtf8(EveV115Parser.InteractionSource));
        Assert.Throws<EveDecodeException>(() => npcs.ToJsonUtf8("anything"));
        Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw, null!));
    }

    [Fact]
    public void Cancellation_never_returns_a_partial_result()
    {
        var raw = Fixture("basic");
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        Assert.Throws<OperationCanceledException>(() => EveV115Parser.Parse(raw, cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => EveV115Parser.Parse(raw, EveV115Parser.NpcSource, cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => EveV115Parser.DeriveIndex(raw, EveV115Parser.NpcSource, cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => EveV115Parser.DeriveIndexes(raw, cancellation.Token));
        var parsed = EveV115Parser.Parse(raw);
        Assert.Throws<OperationCanceledException>(() => parsed.ToJsonUtf8(EveV115Parser.NpcSource, cancellation.Token));
        Assert.Throws<OperationCanceledException>(() => EveV115Parser.Parse(Array.Empty<byte>(), cancellation.Token));
    }

    [Fact]
    public void Read_failure_contains_only_numeric_location_and_code_owned_section()
    {
        var raw = Fixture("basic");
        raw[24 + 4 + 2 + 2 + 20 + 1 + 4 + 4] = 255;
        var error = Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw));
        var location = Assert.IsType<EveParseLocation>(error.Location);
        Assert.Equal((ushort)500, location.SceneId);
        Assert.Equal(EveSection.Npc, location.Section);
        Assert.Equal(1, location.Record);
        Assert.Equal(255, location.RequestedBytes);
        Assert.InRange(location.Offset, 24, raw.Length);
        Assert.Equal(raw.Length - location.Offset, location.AvailableBytes);
        Assert.DoesNotContain("IGNORED!", error.Message);
        Assert.Null(error.InnerException);
        Assert.Equal("eve-v115", EveDecodeException.Schema);
    }

    [Fact]
    public void Source_byte_cap_checked_before_copying_and_uint_offsets_cannot_overflow()
    {
        var raw = new byte[EveV115Parser.MaxSourceBytes + 1];
        long before = GC.GetAllocatedBytesForCurrentThread();
        Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw));
        Assert.InRange(GC.GetAllocatedBytesForCurrentThread() - before, 0, 100_000);
        raw = Fixture("basic");
        BinaryPrimitives.WriteUInt32LittleEndian(raw.AsSpan(16), uint.MaxValue);
        BinaryPrimitives.WriteUInt32LittleEndian(raw.AsSpan(20), uint.MaxValue);
        Assert.Equal("Duplicate scene ID or out-of-bounds offset", Assert.Throws<EveDecodeException>(() => EveV115Parser.Parse(raw)).Message);
    }

    [Fact]
    public void Serialization_is_culture_independent_and_lexicographically_orders_scene_keys()
    {
        var old = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            var raw = Fixture("unsorted-header-byte-numeric-lexical-order");
            var indexes = EveV115Parser.Parse(raw);
            Assert.Equal(new ushort[] { 1, 2, 10, 100 }, indexes.Scenes.Select(s => s.SceneId));
            using var json = JsonDocument.Parse(indexes.ToJsonUtf8(EveV115Parser.NpcSource).AsMemory());
            Assert.Equal(new[] { "1", "10", "100", "2" }, json.RootElement.GetProperty("scenes").EnumerateObject().Select(p => p.Name));
        }
        finally { CultureInfo.CurrentCulture = old; }
    }

    private static byte[] Raw(JsonElement row)
    {
        var raw = Convert.FromBase64String(row.GetProperty("raw").GetString()!);
        Array.Resize(ref raw, raw.Length + row.GetProperty("zero_padding").GetInt32());
        return raw;
    }

    private static byte[] Fixture(string name)
    {
        var row = (JsonElement)EvePythonVectors.Cases().First(row => (string)row[0] == name)[1];
        return Raw(row);
    }
}
