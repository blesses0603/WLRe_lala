using Lala.Core.Catalogs;
using System.Collections.Immutable;

namespace Lala.Core.Resources;

/// <summary>
/// Owner-issued, revocable resource-only selection. This handle is distinct from historical
/// bootstrap success. Every read checks the exact owner, publication and activation reference.
/// Returned immutable catalogs are point-in-time data, never a reusable authorization token.
/// No account, protocol, optional-source, UI or packet capability is established here.
/// </summary>
internal sealed class ResourceRuntimeActivation(ResourceRuntimeOwner owner, ResourceRuntimePublication publication)
{
    private readonly object npcGate=new();
    private ushort? npcScene;private ImmutableArray<SceneNpcEntry> npcRows=[];
    internal SceneNpcRosterRequest? CreateNpcRoster(ushort scene,Func<bool> accountCurrent)
    {
        if(!IsActive||!publication.Candidate.Stages.ContainsKey(scene)||!publication.Candidate.EveIndexes.IncludesNpcs)return null;
        ImmutableArray<SceneNpcEntry> rows;
        lock(npcGate)
        {
            if(npcScene!=scene)
            {
                var source=publication.Candidate.EveIndexes.Scenes.FirstOrDefault(s=>s.SceneId==scene)?.Npcs??[];
                try{npcRows=SceneNpcRosterRequest.Build(source,publication.Candidate.ReviewedNpcs);}
                catch(ResourceValidationException){npcRows=default;}
                npcScene=scene;
            }
            rows=npcRows;
        }
        return !rows.IsDefault&&IsActive?new(scene,publication.Identity.Key+":"+Generation+":"+scene,rows,()=>IsActive&&accountCurrent()):null;
    }
    internal long Generation => publication.Generation;
    internal ManifestIdentity Identity => publication.Identity;
    internal bool IsActive => owner.IsCurrentActivation(this, publication);
    internal bool HasItemImages => IsActive && publication.ItemImages is not null;
    internal bool TryReadItemImage(ushort itemId, out byte[]? png) => owner.TryReadItemImage(this, publication, itemId, out png);
    internal bool HasEmojis => IsActive && publication.Emojis is not null;
    internal bool TryReadEmoji(byte token,out byte[]? png)=>owner.TryReadEmoji(this,publication,token,out png);
    internal EmojiGalleryRequest? CreateEmojiGallery(Func<bool> accountCurrent)
        => IsActive&&publication.Emojis is {} batch?new(batch,()=>IsActive&&accountCurrent()):null;
    internal SmallMapRenderRequest? CreateSmallMap(ushort scene,Func<bool> accountCurrent)
        =>IsActive&&publication.SmallMaps is {} maps&&publication.Candidate.Stages.TryGetValue(scene,out var stage)&&maps.Contains(stage.ModelId)
            ?new(maps,stage.ModelId,()=>IsActive&&accountCurrent(),SmallMapProjection.Create(stage)):null;
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
