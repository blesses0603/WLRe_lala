using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed class GameplaySocialCatalogTests
{
    private static Dictionary<string, byte[]> Tables()
    {
        var sell = new PacketWriter().U32(3);
        for (int id = 8; id <= 10; id++) sell.U16(id).U8(0).U8(0).U8(0).U8(5).U16(0).U8(5).U16(0).U16(0).U8(0).U8(0).U8(0).Raw(new byte[24]).U8(0);
        var agent = new PacketWriter().U32(1).U8(1).Raw(new byte[26]);
        for (int i = 0; i < 2; i++) agent.U8(0).U16(0).U32(0).U16(0).U16(0).U8(1).U16(0);
        return new()
        {
            ["UISellData_C"] = sell.Build(),
            ["FormulaData_C"] = new PacketWriter().U32(1).U16(1).U8(2).U16(100).Raw(new byte[22]).Build(),
            ["OrganizationFunctionData_C"] = new PacketWriter().U32(1).U8(1).U32(0).U8(5).Raw(new byte[30]).Build(),
            ["ArkStarData_C"] = new PacketWriter().U32(1).U8(1).Raw(new byte[12]).Build(),
            ["ArkAgentData_C"] = agent.Build(),
            ["ArkFightData_C"] = new PacketWriter().U32(1).U16(1).U8(1).U16(0).Raw(new byte[30]).U8(0).Raw(new byte[45]).U8(1).Build()
        };
    }
    [Fact]
    public void Gameplay_social_metadata_preserves_bounded_official_layouts()
    {
        var catalog = GameSocialCatalog.Parse(Tables(), "synthetic", default);
        Assert.Equal(3, catalog.Sell.Count); Assert.Equal(100, catalog.Formulas[1].Value);
        Assert.Equal(5, catalog.GuildLimits[1]); Assert.Equal(6, catalog.StarPrices[1].Length);
        Assert.Equal(2, catalog.Agents[1].Length); Assert.Equal(5, catalog.Fights[1].Awards.Length);
    }
    [Theory]
    [InlineData("UISellData_C")]
    [InlineData("FormulaData_C")]
    [InlineData("OrganizationFunctionData_C")]
    [InlineData("ArkStarData_C")]
    [InlineData("ArkAgentData_C")]
    [InlineData("ArkFightData_C")]
    public void Gameplay_social_metadata_rejects_truncation_trailing_bytes_and_huge_counts(string name)
    {
        var tables = Tables(); var original = tables[name];
        // Removing the single reviewed Boolean tail is the supported legacy layout;
        // truncate into a real reward field instead.
        tables[name] = original[..^(name == "ArkFightData_C" ? 2 : 1)]; Assert.Throws<ProtocolException>(() => GameSocialCatalog.Parse(tables, "synthetic", default));
        tables[name] = [..original, 255, 255]; Assert.Throws<ProtocolException>(() => GameSocialCatalog.Parse(tables, "synthetic", default));
        tables[name] = [255, 255, 255, 127]; Assert.Throws<ProtocolException>(() => GameSocialCatalog.Parse(tables, "synthetic", default));
    }
}
