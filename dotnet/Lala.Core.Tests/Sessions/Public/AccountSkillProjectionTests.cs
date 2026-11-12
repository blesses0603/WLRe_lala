using Lala.Core.Catalogs;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed class AccountSkillProjectionTests
{
    // Internal synthetic rows test projection only, never source verification or admission.
    private static SkillDataRow Row(ushort id, ushort key) => new(new()
        { ["ID"] = id, ["Key"] = key, ["Name"] = 0 });

    [Fact]
    public void MissingSkillsRemainUnknown()
        => Assert.Null(AccountRuntime.ProjectSkillKeys(null));

    [Fact]
    public void NonzeroUniqueKeysAreMappedWithoutInventedItemFits()
    {
        var rows = new Dictionary<ushort, SkillDataRow>
            { [10] = Row(10, 5), [11] = Row(11, 0), [12] = Row(12, 0) };
        var result = Assert.IsType<Lala.Core.Inventory.CombatKnowledgeCatalog>(AccountRuntime.ProjectSkillKeys(rows));
        Assert.Equal(10u, Assert.Single(result.SkillKeys).Value);
        Assert.True(result.SkillKeys.ContainsKey(5));
        Assert.Empty(result.ItemFitTypes);
        rows.Clear();
        Assert.Single(result.SkillKeys); // Projection owns its immutable mapping.
    }

    [Fact]
    public void AmbiguousKeysAndMismatchedIdsRemainUnknown()
    {
        Assert.Null(AccountRuntime.ProjectSkillKeys(new Dictionary<ushort, SkillDataRow>
            { [10] = Row(10, 5), [11] = Row(11, 5) }));
        Assert.Null(AccountRuntime.ProjectSkillKeys(new Dictionary<ushort, SkillDataRow>
            { [10] = Row(11, 5) }));
    }
}
