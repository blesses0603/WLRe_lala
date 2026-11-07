using System.Collections.Frozen;
using Lala.Core.Protocol;

namespace Lala.Core.Inventory;

public sealed record CraftingRecipeIdentity(int? RecipeId, int ItemId)
{
    public override string ToString() => nameof(CraftingRecipeIdentity);
}

/// <summary>Explicit immutable identity snapshot, never an activated or verified runtime.
/// Callers must independently validate runtime provenance before selecting a layout.
/// Selection matches active_recipe_catalog: empty/all-legacy rows select legacy decoding;
/// any recipe-keyed row requires every row to be keyed. No revision is guessed from a packet.</summary>
public sealed class CraftingScheduleContext
{
    private readonly FrozenDictionary<ushort, ushort>? items;
    private CraftingScheduleContext(Dictionary<ushort, ushort>? identities) => items = identities?.ToFrozenDictionary();
    public static CraftingScheduleContext Legacy { get; } = new(null);
    internal bool UsesRecipeIds => items is not null;

    public static CraftingScheduleContext FromRuntimeRows(IEnumerable<CraftingRecipeIdentity> rows)
    {
        ArgumentNullException.ThrowIfNull(rows);
        var snapshot = rows.ToArray();
        if (!snapshot.Any(row => row.RecipeId.HasValue)) return Legacy;
        if (snapshot.Any(row => !row.RecipeId.HasValue))
            throw new ProtocolException("目前配方識別欄位不一致，請重新同步資源");
        var identities = new Dictionary<ushort, ushort>();
        foreach (var row in snapshot)
        {
            if (row.RecipeId is not (>= 1 and <= ushort.MaxValue) || row.ItemId is < 1 or > ushort.MaxValue
                || !identities.TryAdd((ushort)row.RecipeId.Value, (ushort)row.ItemId))
                throw new ArgumentException("Invalid or duplicate recipe identity");
        }
        return new(identities);
    }

    internal ushort ItemFor(ushort recipeId) => items!.TryGetValue(recipeId, out var itemId) ? itemId
        : throw new ProtocolException("新版製作排程包含未知配方，請重新同步資源");
}
