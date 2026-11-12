using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed class AccountEquipmentProjectionTests
{
    // Internal synthetic rows exercise projection only. They are not source fingerprints,
    // parser admission fixtures, or a way to mark unreviewed resource bytes as reviewed.
    private static ItemDataRow Item(ushort id, byte? fit) => new(id, "synthetic", 0, 0, 0, 0, 0,
        fit is { } value ? new ReviewedItemDetails { FitType = value, Kind = 99 } : null);
    private static SkillDataRow Skill(ushort id, ushort key) => new(new()
        { ["ID"] = id, ["Key"] = key, ["Name"] = 0 });

    [Fact]
    public void ReviewedFitsAndIndependentSkillsOwnImmutableMappings()
    {
        var items = new Dictionary<ushort, ItemDataRow>
            { [42] = Item(42, 3), [43] = Item(43, 0), [44] = Item(44, 11), [45] = Item(45, null) };
        var skills = new Dictionary<ushort, SkillDataRow>
            { [10] = Skill(10, 5), [11] = Skill(11, 0) };

        var catalog = Assert.IsType<CombatKnowledgeCatalog>(AccountRuntime.ProjectKnowledgeCatalog(items, skills));
        Assert.Equal(3, catalog.ItemFitTypes.Count);
        Assert.Equal(3, catalog.ItemFitTypes[42]);
        Assert.Equal(0, catalog.ItemFitTypes[43]);
        Assert.Equal(11, catalog.ItemFitTypes[44]); // Slot normalization belongs to the reducer.
        Assert.False(catalog.ItemFitTypes.ContainsKey(45));
        Assert.Equal(10u, Assert.Single(catalog.SkillKeys).Value);
        Assert.True(catalog.SkillKeys.ContainsKey(5));

        items[42] = Item(42, 9);
        items.Clear();
        skills.Clear();
        Assert.Equal(3, catalog.ItemFitTypes.Count);
        Assert.Equal(3, catalog.ItemFitTypes[42]);
        Assert.Single(catalog.SkillKeys);
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, int>)catalog.ItemFitTypes).Clear());
        Assert.Throws<NotSupportedException>(() => ((IDictionary<ushort, uint>)catalog.SkillKeys).Clear());
    }

    [Fact]
    public void EmptyOrUnreviewedItemsWithoutSkillsRemainUnknown()
    {
        Assert.Null(AccountRuntime.ProjectKnowledgeCatalog(new Dictionary<ushort, ItemDataRow>(), null));
        Assert.Null(AccountRuntime.ProjectKnowledgeCatalog(new Dictionary<ushort, ItemDataRow>
            { [42] = Item(42, null) }, null));
    }

    [Fact]
    public void UnreviewedItemsDoNotInventFitsWhenSkillsAreKnown()
    {
        var catalog = Assert.IsType<CombatKnowledgeCatalog>(AccountRuntime.ProjectKnowledgeCatalog(
            new Dictionary<ushort, ItemDataRow> { [42] = Item(42, null) },
            new Dictionary<ushort, SkillDataRow> { [10] = Skill(10, 5) }));
        Assert.Empty(catalog.ItemFitTypes);
        Assert.Equal(10u, catalog.SkillKeys[5]);
    }

    [Theory]
    [InlineData("missing")]
    [InlineData("empty")]
    [InlineData("ambiguous")]
    [InlineData("mismatched")]
    public void MissingOrInvalidOptionalSkillsNeverEraseReviewedFits(string mode)
    {
        IReadOnlyDictionary<ushort, SkillDataRow>? skills = mode switch
        {
            "missing" => null,
            "empty" => new Dictionary<ushort, SkillDataRow>(),
            "ambiguous" => new Dictionary<ushort, SkillDataRow> { [10] = Skill(10, 5), [11] = Skill(11, 5) },
            _ => new Dictionary<ushort, SkillDataRow> { [10] = Skill(11, 5) }
        };
        var catalog = Assert.IsType<CombatKnowledgeCatalog>(AccountRuntime.ProjectKnowledgeCatalog(
            new Dictionary<ushort, ItemDataRow> { [42] = Item(42, 3) }, skills));
        Assert.Equal(3, Assert.Single(catalog.ItemFitTypes).Value);
        Assert.True(catalog.ItemFitTypes.ContainsKey(42));
        Assert.Empty(catalog.SkillKeys);
    }

    [Theory]
    [InlineData("reviewed-mismatch")]
    [InlineData("unreviewed-mismatch")]
    [InlineData("null-row")]
    [InlineData("zero-id")]
    public void InvalidItemIdentityDiscardsTheWholeFitMapButPreservesValidSkills(string mode)
    {
        var items = new Dictionary<ushort, ItemDataRow> { [42] = Item(42, 3) };
        if (mode == "zero-id") items[0] = Item(0, 1);
        else items[99] = mode switch
        {
            "reviewed-mismatch" => Item(100, 11),
            "unreviewed-mismatch" => Item(100, null),
            _ => null!
        };
        var skills = new Dictionary<ushort, SkillDataRow> { [10] = Skill(10, 5) };

        var catalog = Assert.IsType<CombatKnowledgeCatalog>(AccountRuntime.ProjectKnowledgeCatalog(items, skills));
        Assert.Empty(catalog.ItemFitTypes);
        Assert.Equal(10u, catalog.SkillKeys[5]);
        Assert.Null(AccountRuntime.ProjectKnowledgeCatalog(items, null));
    }

    [Fact]
    public void NullItemMapIsRejectedWithoutChangingCallerData()
    {
        var skills = new Dictionary<ushort, SkillDataRow> { [10] = Skill(10, 5) };
        Assert.Throws<ArgumentNullException>(() => AccountRuntime.ProjectKnowledgeCatalog(null!, skills));
        Assert.Equal((ushort)10, Assert.Single(skills).Value.Id);
    }
}
