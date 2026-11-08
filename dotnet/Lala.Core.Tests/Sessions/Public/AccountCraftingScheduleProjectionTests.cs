using System.Buffers.Binary;
using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.Sessions;
using Xunit;

namespace Lala.Core.Tests.Sessions.Public;

// Synthetic required-table bytes exercise the existing parser and full-catalog projection.
// They do not establish official provenance or bypass resource admission.
internal static class AccountCraftingScheduleFixtures
{
    internal static RuntimeRecipeCandidate Parse(bool keyed)
    {
        ushort[] products = keyed ? [500, 500, 501] : [500, 501];
        int count = products.Length;
        int width = keyed ? SmithDataParser.CandidateRecordBytes : SmithDataParser.LegacyRecordBytes;
        var raw = new byte[4 + count * width];
        BinaryPrimitives.WriteInt32LittleEndian(raw, count);
        for (int i = 0; i < count; i++)
        {
            var row = raw.AsSpan(4 + i * width, width);
            if (keyed)
            {
                BinaryPrimitives.WriteUInt16LittleEndian(row, (ushort)(42 + i));
                row = row[2..];
            }
            BinaryPrimitives.WriteUInt16LittleEndian(row, products[i]);
            row[7] = 1;
            BinaryPrimitives.WriteUInt16LittleEndian(row[24..], 60);
            if (i == 1) BinaryPrimitives.WriteUInt16LittleEndian(row[28..], 1);
        }
        return RuntimeCandidateBindings.Recipes(raw, new Dictionary<ushort, ItemDataRow>
        {
            [500] = new(500, "synthetic", 0, 0, 0, 0, 0, null),
            [501] = new(501, "synthetic", 0, 0, 0, 0, 0, null)
        }, CancellationToken.None);
    }

    internal static byte[] Record(byte index, ushort identity) =>
        new PacketWriter().U8(index).U16(identity).U32(2500).U8(2).U32(60).Build();
}

public sealed class AccountCraftingScheduleProjectionTests
{
    [Fact]
    public void MissingDefaultOrEmptyCatalogNeverSelectsLegacy()
    {
        Assert.Null(AccountRuntime.ProjectCraftingSchedules(null));
        Assert.Null(AccountRuntime.ProjectCraftingSchedules(new(default, new Dictionary<ushort, RuntimeRecipe>())));
        Assert.Null(AccountRuntime.ProjectCraftingSchedules(new([], new Dictionary<ushort, RuntimeRecipe>())));
    }

    [Fact]
    public void ParsedLegacyRowsExplicitlySelectItemIdentities()
    {
        var recipes = AccountCraftingScheduleFixtures.Parse(false);
        Assert.All(recipes.Catalog, row => Assert.Null(row.Recipe.RecipeId));
        var context = AccountRuntime.ProjectCraftingSchedules(recipes);
        Assert.Same(CraftingScheduleContext.Legacy, context);
        var decoded = Assert.IsType<CraftAddedEvent>(CraftingDecoder.Decode(
            new(64, 16, AccountCraftingScheduleFixtures.Record(1, 42)), context));
        Assert.Equal((ushort)42, decoded.Row.ItemId);
        Assert.Null(decoded.Row.RecipeId);
    }

    [Fact]
    public void ParsedKeyedCatalogIncludesDuplicateProductsAndTimedRows()
    {
        var recipes = AccountCraftingScheduleFixtures.Parse(true);
        Assert.Equal(3, recipes.Catalog.Length);
        Assert.Single(recipes.Products);
        Assert.False(recipes.Products.ContainsKey(500));
        Assert.True(recipes.Catalog[1].Recipe.ReadOnly);
        var context = Assert.IsType<CraftingScheduleContext>(AccountRuntime.ProjectCraftingSchedules(recipes));
        Assert.NotSame(CraftingScheduleContext.Legacy, context);
        foreach (var recipe in recipes.Catalog)
        {
            var decoded = Assert.IsType<CraftAddedEvent>(CraftingDecoder.Decode(
                new(64, 16, AccountCraftingScheduleFixtures.Record(1, recipe.Recipe.RecipeId!.Value)), context));
            Assert.Equal(recipe.Recipe.ItemId, decoded.Row.ItemId);
            Assert.Equal(recipe.Recipe.RecipeId, decoded.Row.RecipeId);
        }
    }

    [Theory]
    [InlineData(500)] // A known product is not a known recipe ID.
    [InlineData(65535)]
    public void UnknownRecipeDoesNotFallBackToProductIdentity(ushort id)
    {
        var context = AccountRuntime.ProjectCraftingSchedules(AccountCraftingScheduleFixtures.Parse(true));
        Assert.Throws<ProtocolException>(() => CraftingDecoder.Decode(
            new(64, 16, AccountCraftingScheduleFixtures.Record(1, id)), context));
    }

    [Fact]
    public void MixedIdentityRowsUseExistingContextValidation()
    {
        var keyed = AccountCraftingScheduleFixtures.Parse(true).Catalog[0];
        var legacy = AccountCraftingScheduleFixtures.Parse(false).Catalog[0];
        Assert.Throws<ProtocolException>(() => AccountRuntime.ProjectCraftingSchedules(
            new([keyed, legacy], new Dictionary<ushort, RuntimeRecipe>())));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void DuplicateOrZeroRecipeIdsUseExistingContextValidation(bool zero)
    {
        var row = AccountCraftingScheduleFixtures.Parse(true).Catalog[0];
        ImmutableArray<RuntimeRecipe> rows = zero
            ? [row with { Recipe = row.Recipe with { RecipeId = 0 } }]
            : [row, row];
        Assert.Throws<ArgumentException>(() => AccountRuntime.ProjectCraftingSchedules(
            new(rows, new Dictionary<ushort, RuntimeRecipe>())));
    }
}
