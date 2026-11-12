using System.Buffers.Binary;
using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lala.Core.Catalogs;
using Lala.Core.Tests.TestSupport;
using Xunit;

namespace Lala.Core.Tests.Catalogs;

public sealed class CatalogParserTests
{
    [Theory]
    [MemberData(nameof(PythonCatalogVectors.ItemCases), MemberType = typeof(PythonCatalogVectors))]
    public void ItemLayoutMatchesPython(string name, string base64, bool reviewed, bool link, string? expected)
    {
        Assert.NotEmpty(name);
        byte[] raw = Convert.FromBase64String(base64);
        if (expected is null)
        {
            Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ParseLayout(raw, reviewed, link));
            return;
        }
        var rows = ItemDataParser.ParseLayout(raw, reviewed, link);
        AssertJson(expected, rows.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => Project(pair.Value)));
        if (!reviewed)
            AssertJson(expected, ItemDataParser.Parse(raw).ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => Project(pair.Value)));
    }

    [Theory]
    [MemberData(nameof(PythonCatalogVectors.SkillCases), MemberType = typeof(PythonCatalogVectors))]
    public void SkillLayoutMatchesEveryPythonField(string name, string base64, string? expected)
    {
        Assert.NotEmpty(name);
        byte[] raw = Convert.FromBase64String(base64);
        if (expected is null)
        {
            Assert.Throws<CatalogDecodeException>(() => SkillDataParser.ParseLayout(raw));
            return;
        }
        var rows = SkillDataParser.ParseLayout(raw);
        AssertJson(expected, rows.ToDictionary(pair => pair.Key.ToString(CultureInfo.InvariantCulture), pair => pair.Value.Fields));
        foreach (var (id, row) in rows)
        {
            Assert.Equal(id, row.Id);
            Assert.Equal(row.Fields["Name"], row.NameTextId);
            Assert.Equal(row.Fields["Key"], (uint)row.Key);
            Assert.Equal(71, row.Fields.Count);
        }
    }

    [Theory]
    [MemberData(nameof(PythonCatalogVectors.StackCases), MemberType = typeof(PythonCatalogVectors))]
    public void StackRulesMatchPython(int id, int fit, int kind, int special, int available, int limited,
        int uses, int flags, int attr1, int attr2, bool? expected)
    {
        var row = new ItemStackInput(fit, kind, special, available, limited, uses, flags, attr1, attr2);
        if (expected is null)
            Assert.Throws<ArgumentOutOfRangeException>(() => ItemStackRules.CanOverlap(id, row));
        else
            Assert.Equal(expected.Value, ItemStackRules.CanOverlap(id, row));
    }

    [Fact]
    public void PublicReviewedEntrypointsRejectEverySyntheticFixture()
    {
        foreach (var vector in PythonCatalogVectors.ItemCases())
        {
            byte[] raw = Convert.FromBase64String((string)vector[1]!);
            Assert.Throws<CatalogDecodeException>(() => ItemDataParser.Parse(raw, ItemDataParser.Reviewed1296Version));
            Assert.Throws<CatalogDecodeException>(() => ItemDataParser.Parse(raw, includeSkillLink: true));
        }
        foreach (var vector in PythonCatalogVectors.SkillCases())
        {
            byte[] raw = Convert.FromBase64String((string)vector[1]!);
            Assert.Throws<CatalogDecodeException>(() => SkillDataParser.Parse(raw));
        }
    }

    [Theory]
    [InlineData("1262_2026_10_14_15_00_34_84")]
    [InlineData("1275_2026_10_21_18_27_33_84")]
    [InlineData("1286_2026_10_29_13_42_37_94")]
    public void LegacyVersionCannotExposeReviewedSemanticsOrAcceptReviewedSource(string version)
    {
        var row = Assert.Single(ItemDataParser.Parse(ItemBytes(), version)).Value;
        Assert.Null(row.ReviewedDetails);
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ValidateSource(version, true, false));
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.Parse(ItemBytes(), version, true));
    }

    [Theory]
    [InlineData("")]
    [InlineData("1296")]
    [InlineData("1297_2026_11_05_00_00_00_00")]
    [InlineData("1296_2026_11_04_13_34_19_13 ")]
    public void UnknownVersionsFailClosed(string version) =>
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.Parse(ItemBytes(), version));

    [Fact]
    public void SourcePolicyAllowsOnlyExactReviewedAndLegacyCombinations()
    {
        ItemDataParser.ValidateSource(null, true, true);
        ItemDataParser.ValidateSource(null, false, false);
        ItemDataParser.ValidateSource(ItemDataParser.Reviewed1296Version, true, true);
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ValidateSource(ItemDataParser.Reviewed1296Version, false, false));
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ValidateSource(null, false, true));
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ParseLayout(ItemBytes(), false, true));
    }

    [Fact]
    public void AllTruncationOffsetsFailWithoutLeakingContentOrReturningPartialRows()
    {
        foreach (bool reviewed in new[] { false, true })
        {
            byte[] raw = ItemBytes(reviewed);
            for (int length = 0; length < raw.Length; length++)
            {
                var error = Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ParseLayout(raw.AsSpan(0, length), reviewed));
                Assert.DoesNotContain("測試", error.Message);
            }
        }
        byte[] skill = SkillBytes();
        for (int length = 0; length < skill.Length; length++)
            Assert.Throws<CatalogDecodeException>(() => SkillDataParser.ParseLayout(skill.AsSpan(0, length)));
    }

    [Fact]
    public void OversizedInputsAreRejectedBeforeAllocationAndHashing()
    {
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.Parse(new byte[ItemDataParser.MaxBytes + 1]));
        Assert.Throws<CatalogDecodeException>(() => SkillDataParser.Parse(new byte[SkillDataParser.MaxBytes + 1]));
        Assert.Throws<CatalogDecodeException>(() => ItemDataParser.ParseLayout(new byte[ItemDataParser.MaxBytes + 1], false));
        Assert.Throws<CatalogDecodeException>(() => SkillDataParser.ParseLayout(new byte[SkillDataParser.MaxBytes + 1]));
    }

    [Fact]
    public void MaximumReviewedRecordCountsAreAcceptedByBoundedLayouts()
    {
        byte[] item = ItemBytes();
        // Locate ID independently from the variable UTF-16 name and kind-name byte lengths.
        int cursor = 2 + BinaryPrimitives.ReadUInt16LittleEndian(item.AsSpan(4));
        cursor += 1;
        cursor += 2 + BinaryPrimitives.ReadUInt16LittleEndian(item.AsSpan(4 + cursor));
        byte[] allItems = RepeatWithIds(item, cursor, ItemDataParser.MaxItems);
        Assert.Equal(ItemDataParser.MaxItems, ItemDataParser.Parse(allItems).Count);
        byte[] allSkills = RepeatWithIds(SkillBytes(), 7, SkillDataParser.MaxSkills);
        Assert.Equal(SkillDataParser.MaxSkills, SkillDataParser.ParseLayout(allSkills).Count);
    }

    [Fact]
    public void ReturnedRowsDoNotExposeMutableCollectionsOrRetainInputBytes()
    {
        byte[] raw = ItemBytes(true);
        var rows = ItemDataParser.ParseLayout(raw, true, true);
        var row = Assert.Single(rows).Value;
        var details = Assert.IsType<ReviewedItemDetails>(row.ReviewedDetails);
        Array.Fill(raw, (byte)0);
        Assert.Equal("測試蘋果😀", row.Name);
        Assert.Equal(-17, details.Attributes[0].Value);
        Assert.Equal((ushort)65535, details.Spares[4]);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, ItemDataRow>)rows).Clear());
        Assert.Throws<NotSupportedException>(() => ((IList<ItemAttribute>)details.Attributes)[0] = new(0, 0, 0));
        Assert.Throws<NotSupportedException>(() => ((IList<ushort>)details.Spares)[0] = 0);

        byte[] skill = SkillBytes();
        var skills = SkillDataParser.ParseLayout(skill);
        var first = Assert.Single(skills).Value;
        Array.Fill(skill, (byte)255);
        Assert.Equal((ushort)1, first.Id);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, SkillDataRow>)skills).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<string, uint>)first.Fields)["ID"] = 99);
    }

    [Fact]
    public void CancellationIsPropagatedAndNeverConvertedToDecodeFailure()
    {
        using var source = new CancellationTokenSource();
        source.Cancel();
        var token = source.Token;
        Assert.Throws<OperationCanceledException>(() => ItemDataParser.Parse(ItemBytes(), cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => ItemDataParser.ParseLayout(ItemBytes(), false, cancellationToken: token));
        Assert.Throws<OperationCanceledException>(() => SkillDataParser.Parse(SkillBytes(), token));
        Assert.Throws<OperationCanceledException>(() => SkillDataParser.ParseLayout(SkillBytes(), token));
    }

    [Fact]
    public void ReaderChecksCancellationBetweenFieldsAndNeverAdvancesAfterCancellation()
    {
        using var source = new CancellationTokenSource();
        var reader = new CatalogReader(new byte[8], source.Token);
        Assert.Equal(0u, reader.UInt32());
        source.Cancel();
        try
        {
            reader.UInt16();
            Assert.Fail("Read should observe cancellation");
        }
        catch (OperationCanceledException) { }
        Assert.Equal(4, reader.Position);
    }

    [Fact]
    public void NullStackInputCannotBeTreatedAsStackable() =>
        Assert.Throws<ArgumentNullException>(() => ItemStackRules.CanOverlap(50000, null!));

    private static byte[] ItemBytes(bool reviewed = false) =>
        Convert.FromBase64String((string)PythonCatalogVectors.ItemCases().ElementAt(reviewed ? 1 : 0)[1]!);

    private static byte[] SkillBytes() =>
        Convert.FromBase64String((string)PythonCatalogVectors.SkillCases().First()[1]!);

    private static byte[] RepeatWithIds(byte[] source, int idOffset, int count)
    {
        int recordLength = source.Length - 4;
        byte[] result = new byte[4 + count * recordLength];
        BinaryPrimitives.WriteUInt32LittleEndian(result, (uint)count);
        for (int index = 0; index < count; index++)
        {
            source.AsSpan(4).CopyTo(result.AsSpan(4 + index * recordLength));
            BinaryPrimitives.WriteUInt16LittleEndian(result.AsSpan(4 + index * recordLength + idOffset), (ushort)(index + 1));
        }
        return result;
    }

    private static void AssertJson<T>(string expected, T actual)
    {
        JsonNode? actualNode = JsonSerializer.SerializeToNode(actual);
        LazyAssert.True(JsonNode.DeepEquals(JsonNode.Parse(expected), actualNode),
            () => $"Expected {expected}\nActual {actualNode?.ToJsonString()}");
    }

    private static Dictionary<string, object> Project(ItemDataRow row)
    {
        var result = new Dictionary<string, object>
        {
            ["name"] = row.Name, ["price"] = row.Price, ["sell_price"] = row.SellPrice,
            ["restrict"] = row.Restrict, ["open_used"] = row.OpenUsed, ["need_level"] = row.NeedLevel
        };
        if (row.ReviewedDetails is not { } details) return result;
        foreach (var (key, value) in new Dictionary<string, object>
        {
            ["unknown_tail_1296_hex"] = details.UnknownTail1296Hex,
            ["kind"] = details.Kind, ["order"] = details.Order, ["icon_id"] = details.IconId,
            ["shop_icon_id"] = details.ShopIconId,
            ["attributes"] = details.Attributes.Select(a => new { kind = a.Kind, effect = a.Effect, value = a.Value }),
            ["flags2"] = details.Flags2, ["is_pvp_time_over"] = details.IsPvpTimeOver,
            ["material"] = details.Material, ["level"] = details.Level, ["fit_type"] = details.FitType,
            ["special"] = details.Special, ["spares"] = details.Spares,
            ["size_l"] = details.SizeL, ["size_w"] = details.SizeW, ["size_h"] = details.SizeH,
            ["item_w"] = details.ItemW, ["item_h"] = details.ItemH,
            ["available_time"] = details.AvailableTime, ["limited_time"] = details.LimitedTime,
            ["use_count"] = details.UseCount, ["style_bank_set_sort_id"] = details.StyleBankSetSortId,
            ["stackable"] = details.Stackable
        }) result.Add(key, value);
        if (details.SkillLink is { } link) result.Add("skill_link", link);
        return result;
    }
}
