using Lala.Core.Catalogs;

namespace Lala.Core.Resources;

/// <summary>
/// Owner-issued, revocable resource-only selection. This handle is distinct from historical
/// bootstrap success. Every read checks the exact owner, publication and activation reference.
/// Returned immutable catalogs are point-in-time data, never a reusable authorization token.
/// No account, protocol, optional-source, UI or packet capability is established here.
/// </summary>
internal sealed class ResourceRuntimeActivation(ResourceRuntimeOwner owner, ResourceRuntimePublication publication)
{
    internal long Generation => publication.Generation;
    internal ManifestIdentity Identity => publication.Identity;
    internal bool IsActive => owner.IsCurrentActivation(this, publication);
    internal bool HasItemImages => IsActive && publication.ItemImages is not null;
    internal bool TryReadItemImage(ushort itemId, out byte[]? png) => owner.TryReadItemImage(this, publication, itemId, out png);
    internal bool CanLogin => false;
    internal bool CanSendPackets => false;

    // Revocation racing after this read does not erase the returned immutable data. Callers
    // must reacquire on each resource operation; this method cannot authorize external effects.
    internal bool TryReadCatalogs(out OfflineRuntimeCandidate? candidate)
        => owner.TryReadActivatedCatalogs(this, publication, out candidate);
}
