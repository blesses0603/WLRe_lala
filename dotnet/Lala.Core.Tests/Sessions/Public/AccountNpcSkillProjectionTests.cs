using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

public sealed class AccountNpcSkillProjectionTests
{
    [Fact]
    public void NullRemainsUnknownAndProjectionPreservesOrderedZeroAndDuplicateSlots()
    {
        Assert.Null(AccountRuntime.ProjectNpcSkills(null));
        var rows = new Dictionary<uint, CombatResourceNpc>
            { [501] = new() { Skills = [10, 0, 10, 20, 30] } };
        var projection = AccountRuntime.ProjectNpcSkills(rows)!;
        rows.Clear();
        Assert.Equal(new uint[] { 10, 0, 10, 20, 30 }, projection[501]);
        Assert.Throws<NotSupportedException>(() =>
            ((IDictionary<uint, ImmutableArray<uint>>)projection).Clear());
    }

    [Theory]
    [InlineData(0, "valid")]
    [InlineData(65536, "valid")]
    [InlineData(501, "short")]
    [InlineData(501, "default")]
    [InlineData(501, "oversized")]
    [InlineData(501, "null")]
    public void MalformedProjectionRemainsUnknown(uint id, string mode)
    {
        var row = new CombatResourceNpc { Skills = mode switch
        {
            "short" => [1], "default" => default, "oversized" => [1, 2, 3, 4, 65536],
            _ => [1, 2, 3, 4, 5]
        } };
        Assert.Null(AccountRuntime.ProjectNpcSkills(new Dictionary<uint, CombatResourceNpc>
            { [42] = new() { Skills = [1, 2, 3, 4, 5] }, [id] = mode == "null" ? null! : row }));
    }
}
