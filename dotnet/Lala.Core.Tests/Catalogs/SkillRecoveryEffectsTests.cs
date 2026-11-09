using Lala.Core.Catalogs;
using Xunit;

namespace Lala.Core.Tests.Catalogs;

public sealed class SkillRecoveryEffectsTests
{
    [Theory]
    [InlineData(6, SkillRecoveryKind.Sp)]
    [InlineData(7, SkillRecoveryKind.Hp)]
    [InlineData(14, SkillRecoveryKind.HpAndSp)]
    public void ReviewedEffectBranchesAreDistinct(long way, SkillRecoveryKind expected)
    {
        Assert.Equal(expected, SkillRecoveryEffects.FromFightWay(way));
        var fields = new Dictionary<string,uint> { ["FightWay"] = (uint)way, ["ReduceSP"] = 65535,
            ["VariableA"] = 65535, ["VariableB"] = 65535, ["TargetKind"] = 0 };
        var row = new SkillDataRow(fields);
        fields["FightWay"] = 0;
        Assert.Equal(expected,row.RecoveryKind);
    }

    [Fact]
    public void EveryOtherByteIsUnknownRatherThanEvidenceOfNoRecovery()
    {
        for (var value = 0; value <= byte.MaxValue; value++)
            if (value is not (6 or 7 or 14)) Assert.Equal(SkillRecoveryKind.Unknown,SkillRecoveryEffects.FromFightWay(value));
        foreach (long? value in new long?[] { null,-1,long.MinValue,long.MaxValue,256 })
            Assert.Equal(SkillRecoveryKind.Unknown,SkillRecoveryEffects.FromFightWay(value));
    }

    [Fact]
    public void CostTargetPassiveStatusAndVariablesDoNotEstablishRecovery()
    {
        var row = new SkillDataRow(new() { ["FightWay"] = 1,["ReduceSP"] = 100,["TargetKind"] = 1,
            ["HitStatus"] = 241,["VariableA"] = 999,["VariableB"] = 999,["VariableC"] = 100,["VariableD"] = 999 });
        Assert.Equal(SkillRecoveryKind.Unknown,row.RecoveryKind);
        // A plausible synthetic row still cannot cross the production source gate.
        Assert.Throws<CatalogDecodeException>(() => SkillDataParser.Parse(new byte[129]));
    }
}
