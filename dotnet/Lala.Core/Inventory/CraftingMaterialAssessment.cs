using Lala.Core.Sessions;

namespace Lala.Core.Inventory;

public enum CraftingMaterialAssessmentOutcome
{
    Evaluated, NoPublication, CatalogsUnavailable, RoleIdentityUnknown
}

/// <summary>Historical material query tied to one exact receive/catalog publication.
/// Evaluated means only that the offline helper ran, not success or readiness to craft.
/// Preflight retains pending/uncertain source observations, but does not enforce the
/// command wrapper's battle, event, coordination or pending-operation gates.</summary>
public sealed class CraftingMaterialAssessment
{
    internal CraftingMaterialAssessment(AccountRuntimePublicationSnapshot basis, ushort itemId,
        int batchCount, CraftingMaterialAssessmentOutcome outcome, CraftingPreflightResult? preflight)
        => (Basis, ItemId, BatchCount, Outcome, Preflight) = (basis, itemId, batchCount, outcome, preflight);
    public AccountRuntimePublicationSnapshot Basis { get; }
    public ushort ItemId { get; }
    public int BatchCount { get; }
    public CraftingMaterialAssessmentOutcome Outcome { get; }
    public CraftingPreflightResult? Preflight { get; }
    public bool ResourceHeld => true;
    public bool CanSendCommands => false;
    public override string ToString() => nameof(CraftingMaterialAssessment);
}

internal static class CraftingMaterialInspection
{
    internal static CraftingMaterialAssessment Inspect(AccountRuntimePublicationSnapshot basis,
        ushort itemId, int batchCount)
    {
        CraftingMaterialAssessment Missing(CraftingMaterialAssessmentOutcome outcome) =>
            new(basis, itemId, batchCount, outcome, null);
        if (basis.Publication is not { Receive.Phase: AccountReceivePhase.Running } publication)
            return Missing(CraftingMaterialAssessmentOutcome.NoPublication);
        if (publication.Catalogs is not { } catalogs)
            return Missing(CraftingMaterialAssessmentOutcome.CatalogsUnavailable);
        var state = publication.Receive.State;
        // Unlike the offline helper's null == null comparison, identity must be known.
        // Zero remains known: there is no source-backed nonzero role gate here.
        if (state.Player?.RoleId is not uint roleId)
            return Missing(CraftingMaterialAssessmentOutcome.RoleIdentityUnknown);
        var recipes = CraftingPreflightContext.FromRuntime(catalogs.Recipes);
        var preflight = CraftingMaterialPreflight.Evaluate(recipes, itemId, batchCount,
            roleId, state.Crafting, state.Bag, state.Storage.Storage);
        return new(basis, itemId, batchCount, CraftingMaterialAssessmentOutcome.Evaluated, preflight);
    }
}
