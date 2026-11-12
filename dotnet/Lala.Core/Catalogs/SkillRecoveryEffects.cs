namespace Lala.Core.Catalogs;

/// <summary>Only the three recovery categories explicitly described by reviewed SkillData.lua.
/// Unknown is not evidence of no recovery: passive/status effects and amounts are not classified.</summary>
public enum SkillRecoveryKind { Unknown, Hp, Sp, HpAndSp }

/// <summary>Pure interpretation of an observed FightWay from the reviewed skill layout.
/// Does not establish source validity, recovery amount, usable targets or permission to cast.</summary>
public static class SkillRecoveryEffects
{
    public const string ReviewedLuaSha256 = "962e95717ddce2c8d56da622df0e578afbf7bd6c63a19e53a809fb4a283f3228";
    public static SkillRecoveryKind FromFightWay(long? fightWay) => fightWay switch
    {
        6 => SkillRecoveryKind.Sp,
        7 => SkillRecoveryKind.Hp,
        14 => SkillRecoveryKind.HpAndSp,
        _ => SkillRecoveryKind.Unknown
    };
}
