using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.Protocol;

// A genuine external consumer: this assembly has no InternalsVisibleTo access.
internal static class CraftingPreflightPublicCheck
{
    public static void Run()
    {
        var recipes = CraftingPreflightContext.FromCallerSuppliedRows([
            new(new SmithRecipe(500, 0, 0, 39001, 3, [new(100, 2), new(100, 1)], 30,
                0, 0, 0, 0, 0, 0, 1, RecipeId: 42, CandidateRowKey: 42), 0)]);
        var crafting = new CraftingReceiveSnapshot
        {
            Crafting = new() { Ready = true, Pending = "synthetic observation", Uncertain = true },
            Furniture = new()
            {
                Ready = true, Owner = 7, ItemOrder = [9, 2],
                Items = ImmutableDictionary<ushort, CraftFurnitureSnapshot>.Empty
                    .Add(9, new(9, 39001, 0, 0, 0)).Add(2, new(2, 39001, 0, 0, 0))
            }
        };
        var record = new ItemSave(2, 100, 1, 0, 1, 123, null, null, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, [], false, 0, 0, null);
        var bag = new BagReceiveSnapshot
        {
            Ready = true, Reliable = true, Items = ImmutableDictionary<byte, BagItemSnapshot>.Empty.Add(2, new(record, 2, 4, 0))
        };
        var storage = new RoomStorageSnapshot
        {
            Materials = new() { Ready = true, Items = ImmutableDictionary<ushort, StorageItemSnapshot>.Empty.Add(10, new(10, 100, 100)) }
        };
        var result = CraftingMaterialPreflight.Evaluate(recipes, 500, 2, 7, crafting, bag, storage);
        Require(result.Success && result.ToolIndex == 2 && result.Recipe?.Recipe.RecipeId == 42);
        Require(result.Needs is [{ ItemId: 100, Count: var required }] && required == 6);
        Require(result.Allocations is [
            { Source: CraftingMaterialSource.Bag, Index: 2, Count: 4, Before: var before, Serial: 123 },
            { Source: CraftingMaterialSource.Materials, Index: 10, Count: 2, Serial: null }] && before == 4);
        Require(!result.CanSendPackets && !recipes.CanSendPackets && recipes.UsesRecipeIds);
        Require(ReferenceEquals(crafting, result.Crafting) && ReferenceEquals(bag, result.Bag) && ReferenceEquals(storage, result.Storage));
        Require(bag.Reserved.IsEmpty && bag.Holds.IsEmpty && storage.Materials.Holds.IsEmpty && crafting.Crafting.Queue.IsEmpty);
        Require(result.Crafting.Crafting is { Pending: "synthetic observation", Uncertain: true });
        Require(result.ToString() == nameof(CraftingPreflightResult));
        Console.WriteLine("Public crafting material preflight contract passed; offline observations only.");
    }
    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidOperationException("Crafting preflight public contract failed.");
    }
}
