using System.Buffers.Binary;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Lala.Core.Catalogs;
using Lala.Core.Diagnostics.Parsing;
using Lala.Core.Inventory;
using Lala.Core.Tests.Catalogs.Combat;
using Xunit;

namespace Lala.Core.Tests.Catalogs.ReviewedNpcs;

public sealed class ReviewedNpcCatalogTests
{
    [Fact]
    public void Extracted_projection_matches_retained_combat_oracle()
    {
        var fixture = (JsonElement)CombatCatalogPythonVectors.Cases().Single(row => (string)row[0] == "base-catalog")[1];
        byte[] raw = Convert.FromBase64String(fixture.GetProperty("npc").GetString()!);
        var rows = ReviewedNpcCatalogParser.ParseLayout(raw);
        Assert.Equal("NPC私密😀", rows[321].Name);
        Assert.Equal(new uint[] { 101, 0, 65535, 4, 5 }, rows[321].Skills);
    }

    [Fact]
    public void Names_and_all_five_slots_are_detached_immutable_and_not_normalized()
    {
        byte[] raw = Table(Record(1, "  \uFEFF甲\0😀  \0\0", [0, 101, 101, ushort.MaxValue, 5]));
        byte[] envelope = new byte[raw.Length + 11]; raw.CopyTo(envelope, 5);
        var rows = ReviewedNpcCatalogParser.ParseLayout(envelope.AsSpan(5, raw.Length));
        Array.Fill(raw, (byte)255); Array.Fill(envelope, (byte)255);
        Assert.Equal("  \uFEFF甲\0😀  ", rows[1].Name);
        Assert.Equal(new uint[] { 0, 101, 101, 65535, 5 }, rows[1].Skills);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<uint, CombatResourceNpc>)rows).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<uint>)rows[1].Skills)[0] = 9);
        Assert.Empty(rows.Clear()); Assert.Single(rows);
        Assert.Equal(0u, rows[1].Skills[0]);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    public void Each_skill_slot_preserves_its_two_little_endian_bytes(int slot)
    {
        ushort[] skills = [0, 0, 0, 0, 0]; skills[slot] = 0xAB12;
        var row = ReviewedNpcCatalogParser.ParseLayout(Table(Record(ushort.MaxValue, "", skills)))[ushort.MaxValue];
        Assert.Equal(skills.Select(value => (uint)value), row.Skills);
        Assert.Equal("", row.Name);
    }

    [Theory]
    [InlineData("")]
    [InlineData("\0\0")]
    [InlineData(" ")]
    [InlineData("\uFEFF甲\0乙😀\0")]
    public void Reviewed_name_semantics_preserve_empty_bom_and_interior_nuls(string name)
        => Assert.Equal(name.TrimEnd('\0'), ReviewedNpcCatalogParser.ParseLayout(Table(Record(1, name)))[1].Name);

    [Fact]
    public void Both_utf16_fields_are_validated_and_source_text_limit_is_preserved()
    {
        string maximum = new('甲', ItemDataParser.MaxTextBytes / 2);
        byte[] maxText = Encoding.Unicode.GetBytes(maximum);
        var rows = ReviewedNpcCatalogParser.ParseLayout(Table(RecordBytes(1, maxText, maxText)));
        Assert.Equal(maximum, rows[1].Name);
        foreach (byte[] invalid in new byte[][] { [0], [0, 0xD8], [0, 0xDC], new byte[ItemDataParser.MaxTextBytes + 2] })
        {
            Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(Table(RecordBytes(1, invalid, []))));
            Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(Table(RecordBytes(1, [], invalid))));
        }
    }

    [Fact]
    public void Truncation_invalid_counts_ids_duplicates_and_trailing_bytes_reject()
    {
        byte[] raw = Table(Record(1, "甲😀"));
        for (int length = 0; length < raw.Length; length++)
            Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(raw.AsSpan(0, length)));
        Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout([.. raw, 0]));
        Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(Table(Record(0))));
        Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(Table(Record(1), Record(1))));
        foreach (uint count in new uint[] { 0, NormalAttackCatalogParser.MaxNpcs + 1, uint.MaxValue })
        {
            byte[] invalid = new byte[4]; BinaryPrimitives.WriteUInt32LittleEndian(invalid, count);
            Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.ParseLayout(invalid));
        }
    }

    [Fact]
    public void Production_keeps_the_fixed_reviewed_gate_with_no_public_override()
    {
        Assert.Equal("edd827d228cbd5306dfcfbda150f5194406b87b45481fb930544218057aca31c", NormalAttackCatalogParser.ReviewedNpcSha256);
        byte[] raw = Table(Record(1, "NPC", [1, 2, 3, 4, 5]));
        Assert.Single(ReviewedNpcCatalogParser.ParseLayout(raw));
        Assert.Equal("NPC 普攻資料格式尚未驗證", Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.Parse(raw)).Message);
        Assert.Throws<CatalogDecodeException>(() => ReviewedNpcCatalogParser.Parse([]));
        var method = Assert.Single(typeof(ReviewedNpcCatalogParser).GetMethods(BindingFlags.Public | BindingFlags.Static));
        Assert.Equal("Parse", method.Name);
        Assert.All(method.GetParameters(), parameter => Assert.True(
            parameter.ParameterType == typeof(ReadOnlySpan<byte>) || parameter.ParameterType == typeof(CancellationToken)));
    }

    [Fact]
    public void Cancellation_precedes_hashing_layout_and_diagnostics()
    {
        using var stop = new CancellationTokenSource(); stop.Cancel();
        using var diagnostics = ParserDiagnostics.BeginSession();
        foreach (Action parse in new Action[]
        {
            () => ReviewedNpcCatalogParser.Parse([], stop.Token),
            () => ReviewedNpcCatalogParser.ParseLayout([], stop.Token)
        })
        {
            var error = Assert.Throws<OperationCanceledException>(parse);
            Assert.Equal(stop.Token, error.CancellationToken);
            Assert.Null(ParserDiagnostics.GetFailure(error));
        }
        Assert.Empty(diagnostics.Run.Events);
    }

    internal static byte[] Table(params byte[][] records)
    {
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
        writer.Write((uint)records.Length);
        foreach (byte[] record in records) writer.Write(record);
        return stream.ToArray();
    }

    internal static byte[] Record(ushort id, string name = "", ushort[]? skills = null)
        => RecordBytes(id, Encoding.Unicode.GetBytes(name), [], skills);

    private static byte[] RecordBytes(ushort id, byte[] name, byte[] second, ushort[]? skills = null)
    {
        using var stream = new MemoryStream(); using var writer = new BinaryWriter(stream);
        writer.Write((ushort)name.Length); writer.Write(name);
        writer.Write((ushort)second.Length); writer.Write(second);
        byte[] fields = new byte[NormalAttackCatalogParser.NpcFieldBytes];
        BinaryPrimitives.WriteUInt16LittleEndian(fields.AsSpan(1), id);
        for (int slot = 0; slot < 5; slot++)
            BinaryPrimitives.WriteUInt16LittleEndian(fields.AsSpan(75 + 2 * slot), skills?[slot] ?? 0);
        writer.Write(fields);
        return stream.ToArray();
    }
}
