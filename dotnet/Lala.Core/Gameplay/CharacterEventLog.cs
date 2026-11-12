using System.Collections.Immutable;
using Lala.Core.Inventory;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>Display history, separate from lossless state processing and bounded action receipts.
/// Unknown ownership is excluded. Nearby/NPC traffic cannot evict the character's history.</summary>
internal static class CharacterEventLog
{
    internal static GameServerEvent Scope(GameServerEvent receipt, ServerEvent e,
        ServiceStateSnapshot before, ServiceStateSnapshot after)
    {
        if (after.Player?.RoleId is not { } role) return receipt;
        bool ownBattle = (before.Local.Battle.Active == true && before.Local.Battle.Units.Any(u => u.Layout.Pid == role))
            || (after.Local.Battle.Active == true && after.Local.Battle.Units.Any(u => u.Layout.Pid == role));
        bool own = e switch
        {
            PositionSnapshotEvent r => r.RoleId == role,
            WalkEvent r => unchecked((uint)r.RoleId) == role,
            AttributeSetEvent r => r.Entity == "self",
            ServerLayoutEvent { Event: WorldPlayerEvent r } => r.Player.RoleId == role,
            ServerLayoutEvent { Event: BattleStartEvent r } => r.Units.Any(u => u.Pid == role),
            ServerLayoutEvent { Event: BattleUnitsEvent } => ownBattle,
            RoundStartEvent or AttackResultEvent or WinnerEvent or BattleAttributeSetEvent or BattleUnitExitEvent => ownBattle,
            FightExitEvent r => r.RoleId == role,
            GoldDeltaEvent or GoldSnapshotEvent or GoldLimitEvent or AttributeAllocationSuccessEvent
                or EventContinuePermissionEvent or NpcEffectEvent or EventActiveEvent or EventEndEvent or EventRejectedEvent
                or InitialDataCompleteEvent => true,
            ServerLiveDataEvent { Event: BagSnapshotEvent or BagAddEvent or BagDeleteEvent or BagSellEvent
                or PlayerCombatDataEvent or PlayerEquipDataEvent or StarInfoEvent or ItemUseResultEvent
                or ShopPurchaseResultEvent or SaleNoticeEvent } => true,
            ServerInventoryEvent { Event: StorageGarageInitialEvent or StorageGarageAddEvent or StorageGarageDeleteEvent
                or StorageMaterialsEvent or StorageMaterialsDeleteEvent or StorageMoveResultEvent or StorageParametersEvent
                or StorageExpandedEvent or StorageErrorEvent or PotionBalanceEvent or PotionBalanceAddEvent or PotionUsedEvent
                or PotionItemUpdateEvent or CraftSnapshotEvent or CraftAddedEvent or CraftStartedEvent or CraftPausedEvent
                or CraftDeletedEvent or CraftCompletedEvent or CraftFailedEvent or CraftHumanEvent or CraftSwappedEvent } => true,
            ServerSocialEvent { Event: TeamApplicationEvent or TeamInviteEvent or TeamAnswerEvent or TeamFlagEvent
                or TeamNoticeEvent or TeamLeaderOfferEvent or TeamLeaderAnswerEvent
                or AlchemyResultEvent or AlchemySpaceErrorEvent or SocialRejectedEvent } => true,
            ServerSocialEvent { Event: TeamJoinEvent r } => r.RoleId == role || r.LeaderId == role,
            ServerSocialEvent { Event: TeamLeaveEvent r } => r.RoleId == role,
            ServerActivityEvent r => r.Event.Roles is null,
            ServerExpeditionEvent or ServerTimeCubeEvent => true,
            ServerDailyTaskEvent { Event: not Lala.Core.Automation.TaskUnknownUpdate } => true,
            _ => false
        };
        return own ? receipt with { OwnerRoleId = role } : receipt;
    }

    internal static ImmutableArray<GameServerEvent> Append(ImmutableArray<GameServerEvent> history,
        GameServerEvent receipt, uint? currentRole)
    {
        if (currentRole is null) return [];
        if (!history.IsEmpty && history[0].OwnerRoleId != currentRole) history = [];
        if (receipt.OwnerRoleId != currentRole) return history;
        if (history.Length == 200) history = history.RemoveAt(0);
        return history.Add(receipt);
    }
}
