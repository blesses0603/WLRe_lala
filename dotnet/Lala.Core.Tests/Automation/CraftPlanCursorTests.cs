using System.Collections.Immutable;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Xunit;

namespace Lala.Core.Tests.Automation;

public sealed class CraftPlanCursorTests
{
    [Fact]
    public void Plan_advances_only_after_one_confirmation_and_retains_position_across_pause()
    {
        var entries = ImmutableArray.Create(new GameCraftPlanEntry(101, 3), new GameCraftPlanEntry(101, 3), new GameCraftPlanEntry(102, 1));
        CraftPlanCursor.Validate(entries); var cursor = new CraftPlanCursor(entries);
        Assert.Equal(0, cursor.Added); Assert.Equal(entries[0], cursor.Next);
        cursor.ConfirmAdded(0);
        Assert.Equal(1, cursor.Added); Assert.Equal(entries[1], cursor.Next);
        Assert.Throws<ProtocolException>(() => cursor.ConfirmAdded(0));
        Assert.Equal(1, cursor.Added); // An old receipt cannot advance the identical next recipe.
        cursor.ConfirmAdded(1); cursor.ConfirmAdded(2);
        Assert.Null(cursor.Next); Assert.Throws<ProtocolException>(() => cursor.ConfirmAdded(3));
    }

    [Fact]
    public void Plan_rejects_unbounded_or_invalid_consumption_drafts()
    {
        CraftPlanCursor.Validate([]);
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate(default));
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate([new(0, 1)]));
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate([new(1, 0)]));
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate([new(1, 256)]));
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate([null!]));
        Assert.Throws<ProtocolException>(() => CraftPlanCursor.Validate([..Enumerable.Repeat(new GameCraftPlanEntry(1, 1), 513)]));
    }
}
