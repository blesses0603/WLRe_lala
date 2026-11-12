using System.Globalization;
using Lala.Core.Battle;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Battle;

public class CombatRulesTests
{
    [Theory]
    [MemberData(nameof(PythonCombatVectors.NormalCases), MemberType = typeof(PythonCombatVectors))]
    public void MatchesPythonNormalAttackAndRefusals(string name, int item, int? weapon, uint pid,
        uint? master, uint change, int? npcKind, int body, int attack, int equipmentCount, int? expected, string? error)
    {
        _ = name;
        var unit = new CombatUnitSnapshot(pid, master, change, new[] {0, 0, item}.Take(equipmentCount));
        var items = new Dictionary<int, int>();
        if (weapon.HasValue) items[item] = weapon.Value;
        var npcs = new Dictionary<uint, NormalAttackNpc>();
        if (npcKind.HasValue) npcs[pid] = new(npcKind.Value, body, attack);
        var catalog = new NormalAttackCatalogSnapshot(items, npcs);
        if (error is not null)
            Assert.Equal(error, Assert.Throws<ProtocolException>(() => CombatRules.NormalSkill(unit, 123, catalog)).Message);
        else Assert.Equal(expected, CombatRules.NormalSkill(unit, 123, catalog));
    }
    [Theory]
    [MemberData(nameof(PythonCombatVectors.EffectCases), MemberType = typeof(PythonCombatVectors))]
    public void MatchesPythonEffectText(int kind, long value, int sign, string? attribute, string? expected) =>
        Assert.Equal(expected, CombatRules.EffectText(new(kind, value, sign, attribute)));

    [Fact]
    public void CatalogAndEquipmentAreOwnedSnapshots()
    {
        int[] equipment = [0, 0, 50000];
        var unit = new CombatUnitSnapshot(123, null, 0, equipment);
        var items = new Dictionary<int, int> { [50000] = 4 };
        var npcs = new Dictionary<uint, NormalAttackNpc>();
        var catalog = new NormalAttackCatalogSnapshot(items, npcs);
        items[50000] = 11; equipment[2] = 0;
        Assert.Equal(10019, CombatRules.NormalSkill(unit, 123, catalog));
    }
    [Fact]
    public void EffectFormattingDoesNotDependOnCulture()
    {
        var old = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("ar-SA");
            Assert.Equal("屬性999=-7（sign -1）", CombatRules.EffectText(new(999, -7, -1)));
        }
        finally { CultureInfo.CurrentCulture = old; }
    }
}
