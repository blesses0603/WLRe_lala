using System.Collections.Frozen;
using System.Collections.Immutable;
using Lala.Core.Catalogs;

namespace Lala.Core.Inventory;

public enum CraftingPreflightSource { CallerSuppliedOfflineRows, OfflineRuntimeCandidate }

/// <summary>An owned, bounded recipe observation, never verified provenance, an activated
/// catalog or command authority. Product lookup excludes every ambiguous product, just as
/// RuntimeRecipeCandidate.Products does. Official identity comes from RecipeId, never from
/// product ID, version number or row position. CandidateRowKey is not a fallback identity.</summary>
public sealed class CraftingPreflightContext
{
    private readonly FrozenDictionary<ushort, RuntimeRecipe> products;
    private readonly FrozenSet<ushort> ambiguousProducts;

    private CraftingPreflightContext(ImmutableArray<RuntimeRecipe> rows, CraftingPreflightSource source)
    {
        if (rows.IsDefault || rows.Length > SmithDataParser.MaxRecords)
            throw new ArgumentException("Missing or oversized recipe observations", nameof(rows));
        var keyed = false;
        var legacy = false;
        var identities = new HashSet<ushort>();
        var grouped = new Dictionary<ushort, List<RuntimeRecipe>>();
        foreach (var value in rows)
        {
            if (value?.Recipe is not { } recipe || recipe.ItemId == 0 || recipe.Materials.IsDefault ||
                recipe.Materials.Length > 5 || recipe.Materials.Any(material => material is null || material.ItemId == 0 || material.Count == 0))
                throw new ArgumentException("Incomplete or invalid recipe observations", nameof(rows));
            if (recipe.RecipeId is { } identity)
            {
                keyed = true;
                if (identity == 0 || !identities.Add(identity) ||
                    recipe.CandidateRowKey is { } candidate && candidate != identity)
                    throw new ArgumentException("Invalid or duplicate recipe identity", nameof(rows));
            }
            else
            {
                legacy = true;
                if (recipe.CandidateRowKey is not null)
                    throw new ArgumentException("Candidate key is not a confirmed recipe identity", nameof(rows));
            }
            if (!grouped.TryGetValue(recipe.ItemId, out var matches)) grouped.Add(recipe.ItemId, matches = []);
            matches.Add(value);
        }
        if (keyed && legacy) throw new ArgumentException("Mixed recipe identity layouts", nameof(rows));
        Catalog = rows;
        Source = source;
        UsesRecipeIds = keyed;
        products = grouped.Where(pair => pair.Value.Count == 1).ToFrozenDictionary(pair => pair.Key, pair => pair.Value[0]);
        ambiguousProducts = grouped.Where(pair => pair.Value.Count != 1).Select(pair => pair.Key).ToFrozenSet();
    }

    public static CraftingPreflightContext FromCallerSuppliedRows(ImmutableArray<RuntimeRecipe> rows) =>
        new(rows, CraftingPreflightSource.CallerSuppliedOfflineRows);

    /// <summary>Reuses the runtime's immutable joined ItemData/Smith rows. The runtime
    /// candidate is still offline data; this adapter does not establish current resources.</summary>
    public static CraftingPreflightContext FromRuntime(RuntimeRecipeCandidate recipes)
    {
        ArgumentNullException.ThrowIfNull(recipes);
        return new(recipes.Catalog, CraftingPreflightSource.OfflineRuntimeCandidate);
    }

    public ImmutableArray<RuntimeRecipe> Catalog { get; }
    public CraftingPreflightSource Source { get; }
    public bool UsesRecipeIds { get; }
    public bool CanSendPackets => false;
    internal RuntimeRecipe? Find(ushort itemId) => products.GetValueOrDefault(itemId);
    internal bool IsAmbiguous(ushort itemId) => ambiguousProducts.Contains(itemId);
    public override string ToString() => nameof(CraftingPreflightContext);
}
