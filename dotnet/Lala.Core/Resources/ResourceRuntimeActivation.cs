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
    internal bool HasEmojis => IsActive && publication.Emojis is not null;
    internal bool TryReadEmoji(byte token,out byte[]? png)=>owner.TryReadEmoji(this,publication,token,out png);
    internal EmojiGalleryRequest? CreateEmojiGallery(Func<bool> accountCurrent)
        => IsActive&&publication.Emojis is {} batch?new(batch,()=>IsActive&&accountCurrent()):null;
    internal bool HasPortraits => IsActive && publication.Portraits is not null;
    internal bool TryReadPortrait(PortraitMaterialKey key, out PortraitCachedImage? image)
        => owner.TryReadPortrait(this, publication, key, out image);
    internal bool TrySelectPortrait(Lala.Core.Protocol.WorldPlayer? player,
        Lala.Core.Inventory.CompanionReceiveSnapshot companions, bool companion,
        out PortraitSelection? selection, out PortraitCachedImage? image)
        => owner.TrySelectPortrait(this, publication, player, companions, companion, out selection, out image);
    internal bool CanLogin => false;
    internal bool CanSendPackets => false;

    // Revocation racing after this read does not erase the returned immutable data. Callers
    // must reacquire on each resource operation; this method cannot authorize external effects.
    internal bool TryReadCatalogs(out OfflineRuntimeCandidate? candidate)
        => owner.TryReadActivatedCatalogs(this, publication, out candidate);
}
