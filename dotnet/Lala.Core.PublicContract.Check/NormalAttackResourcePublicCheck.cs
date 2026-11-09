using Lala.Core.Battle;
using Lala.Core.Sessions;

// External consumer: no test assembly friendship and no catalog construction bypass.
internal static class NormalAttackResourcePublicCheck
{
    internal static int? NormalSkill(AccountRuntimePublication? publication, CombatUnitSnapshot unit, uint playerId)
        => publication?.Catalogs?.OptionalNormalAttackCatalog is { } catalog
            ? CombatRules.NormalSkill(unit, playerId, catalog.NormalAttacks) : null;

    internal static void Run()
    {
        if (NormalSkill(null, new(7, null, 0, [0, 0, 0]), 7) is not null)
            throw new InvalidOperationException("Unavailable catalog must not invent normal-attack evidence");
    }
}
