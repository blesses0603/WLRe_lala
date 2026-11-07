using System.Buffers.Binary;
using System.Collections.Immutable;
using Lala.Core.World.Eve;
using Lala.Core.Diagnostics.Parsing;
using System.Numerics;

namespace Lala.Core.Catalogs;

public sealed record RuntimeRecipe(SmithRecipe Recipe, byte OpenUsed);

/// <summary>All recipe identities, plus only unambiguous products for the legacy product lookup.</summary>
public sealed class RuntimeRecipeCandidate
{
    internal RuntimeRecipeCandidate(ImmutableArray<RuntimeRecipe> catalog,
        IReadOnlyDictionary<ushort, RuntimeRecipe> products) => (Catalog, Products) = (catalog, products);
    public ImmutableArray<RuntimeRecipe> Catalog { get; }
    public IReadOnlyDictionary<ushort, RuntimeRecipe> Products { get; }
}

// Only parser-produced data reaches these helpers. Caller maps cannot act as provenance or
// replace ItemData's mandatory reviewed-source policy in the public all-ten-table composer.
internal static class RuntimeCandidateBindings
{
    private static readonly ParserDiagnosticDefinition RecipeDiagnostic =
        new("wlre.services.world.dynamic_bundle_runtime.parse_runtime_recipes", "runtime-recipes-v1");
    internal static RuntimeRecipeCandidate Recipes(ReadOnlySpan<byte> raw,
        IReadOnlyDictionary<ushort, ItemDataRow> items, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        return ParserDiagnostics.RunWithRaw(RecipeDiagnostic, raw, bytes =>
        {
            try { return ReadRecipes(bytes, items, token); }
            catch (CatalogDecodeException error)
            {
                // Python outer diagnostics retain the nested parser's numeric pos, not payloads.
                if (ParserDiagnostics.GetFailure(error)?.Location is { } location &&
                    location.TryGetValue("offset", out var value) && value is BigInteger offset)
                    ParserDiagnostics.Checkpoint(offset: offset);
                throw;
            }
        }, rows => new(rows.Catalog.Length), null, token);
    }

    private static RuntimeRecipeCandidate ReadRecipes(ReadOnlySpan<byte> raw,
        IReadOnlyDictionary<ushort, ItemDataRow> items, CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        if (raw.Length < 4) throw new CatalogDecodeException("Missing Smith table");
        int count = BinaryPrimitives.ReadInt32LittleEndian(raw);
        if (count is < 1 or > SmithDataParser.MaxRecords)
            throw new CatalogDecodeException("Invalid Smith record count");
        var rows = SmithDataParser.ParseRecords(raw, token);
        var counts = new Dictionary<ushort, int>();
        foreach (var row in rows)
        {
            token.ThrowIfCancellationRequested();
            counts[row.ItemId] = counts.GetValueOrDefault(row.ItemId) + 1;
        }
        var all = ImmutableArray.CreateBuilder<RuntimeRecipe>(rows.Length);
        foreach (var row in rows)
        {
            token.ThrowIfCancellationRequested();
            if (!items.TryGetValue(row.ItemId, out var item) ||
                row.Materials.Any(material => !items.ContainsKey(material.ItemId) || material.Count == 0))
                throw new CatalogDecodeException("Recipe references missing ItemData");
            all.Add(new(row, item.OpenUsed));
        }
        var products = new Dictionary<ushort, RuntimeRecipe>();
        foreach (var row in all)
        {
            token.ThrowIfCancellationRequested();
            if (counts[row.Recipe.ItemId] == 1) products.Add(row.Recipe.ItemId, row);
        }
        token.ThrowIfCancellationRequested();
        return new(all.MoveToImmutable(), new OrderedCatalog<ushort, RuntimeRecipe>(products, products.Keys));
    }

    internal static void CheckShopItems(EveV115Indexes indexes,
        IReadOnlyDictionary<ushort, ItemDataRow> items, CancellationToken token)
    {
        foreach (var scene in indexes.Scenes)
            foreach (var interaction in scene.Interactions)
            {
                token.ThrowIfCancellationRequested();
                if (interaction.FormKind is not (2 or 3)) continue;
                foreach (var offer in interaction.Items)
                    if (offer.Kind == 3 && (offer.DatabaseKind != 2 || !items.ContainsKey(offer.TextId)))
                        throw new CatalogDecodeException("商店商品缺少同版 ItemData 來源");
            }
    }

    internal static IReadOnlyDictionary<ushort, string> SceneNames(IReadOnlyDictionary<ushort, StageDataRow> stages,
        IReadOnlyDictionary<uint, string> texts, CancellationToken token)
    {
        var result = new Dictionary<ushort, string>();
        foreach (var (id, stage) in stages)
        {
            token.ThrowIfCancellationRequested();
            if (stage.NameId == 0 || !texts.TryGetValue(stage.NameId, out string? name) ||
                CodepointLength(name) > 160 || name.Any(value => value < 32)) continue;
            string trimmed = PythonStrip(name);
            if (trimmed.Length != 0) result.Add(id, trimmed);
        }
        token.ThrowIfCancellationRequested();
        return new OrderedCatalog<ushort, string>(result, result.Keys);
    }

    private static bool PythonSpace(char value) => value is >= '\u0009' and <= '\u000d'
        or >= '\u001c' and <= '\u0020' or '\u0085' or '\u00a0' or '\u1680'
        or >= '\u2000' and <= '\u200a' or '\u2028' or '\u2029' or '\u202f' or '\u205f' or '\u3000';
    private static string PythonStrip(string value)
    {
        int start = 0, end = value.Length;
        while (start < end && PythonSpace(value[start])) start++;
        while (end > start && PythonSpace(value[end - 1])) end--;
        return value[start..end];
    }
    private static int CodepointLength(string value)
    {
        int length = 0;
        foreach (var unused in value.EnumerateRunes()) length++;
        return length;
    }
}
