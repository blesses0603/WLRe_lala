using Lala.Core.Protocol;
using Lala.Core.Inventory;

namespace Lala.Core.Gameplay;

/// <summary>Bounded receive receipt and display metadata. No raw packet, chat contents,
/// account credentials or nearby character names are retained in this log.</summary>
public sealed record GameServerEvent(long Sequence, byte Main, byte Sub, string Type, string Description,
    ushort? ItemId = null, int? Count = null, int? Index = null, int? Source = null, int? Code = null,
    uint? Role = null, uint? OtherRole = null, string? Resource = null, System.Collections.Immutable.ImmutableArray<byte> Targets = default, string? ContentFingerprint = null,
    uint? OwnerRoleId = null)
{
    public System.Collections.Immutable.ImmutableArray<ExpeditionReward> Rewards { get; init; } = [];
    public System.Collections.Immutable.ImmutableArray<Lala.Core.Instances.InstanceAward> InstanceAwards { get; init; } = [];
    internal static GameServerEvent From(long sequence,ServerEvent e,Packet packet)
    {
        var result=From(sequence,e);
        // Only event-flow content; no chat, login or credential payload is retained.
        return packet.Main==20||e is SceneNpcVisibilityEvent
            ?result with{ContentFingerprint=Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(packet.Payload.Span))}:result;
    }
    internal static GameServerEvent From(long sequence, ServerEvent e) => e switch
    {
        ServerInstanceEvent{Event:Lala.Core.Instances.CoopRewardReceiptEvent r}=>new(sequence,e.Main,e.Sub,e.Type,"協力獎勵明細已回覆"){InstanceAwards=r.Awards},
        ServerLiveDataEvent{Event:ShopPurchaseResultEvent r}=>new(sequence,e.Main,e.Sub,e.Type,"購買回覆",Code:r.Result),
        ServerLiveDataEvent{Event:BagSellEvent r}=>new(sequence,e.Main,e.Sub,e.Type,"伺服器確認販售",Index:r.Index,Count:r.Count),
        ServerLiveDataEvent{Event:SaleNoticeEvent r}=>new(sequence,e.Main,e.Sub,e.Type,"販售回覆",Code:r.Result),
        ServerExpeditionEvent{Event:ExpeditionResultEvent r} => new(sequence,e.Main,e.Sub,e.Type,"遠征結果已回覆",Index:r.Index,Code:r.Result){Rewards=r.Rewards},
        ServerExpeditionEvent{Event:ExpeditionRejectedEvent r} => new(sequence,e.Main,e.Sub,e.Type,"伺服器拒絕遠征操作",Code:r.Code),
        SceneNpcMoveEvent r => new(sequence,e.Main,e.Sub,e.Type,$"場景 NPC {r.Index} 移動至 ({r.X}, {r.Y})",Index:r.Index,Code:r.Speed),
        SceneNpcVisibilityEvent r => new(sequence,e.Main,e.Sub,e.Type,$"場景 NPC {r.Index} {(r.Visible ? "顯示" : "隱藏")}",Index:r.Index,Count:r.Duration,Code:r.Visible?1:0),
        AttributeSetEvent { Entity: "self" } r => new(sequence,e.Main,e.Sub,e.Type,$"角色屬性 {r.Attribute}：{r.Value}"),
        WalkEvent r => new(sequence,e.Main,e.Sub,e.Type,$"角色位置：({r.X}, {r.Y})",Role:unchecked((uint)r.RoleId)),
        EventContinuePermissionEvent => new(sequence,e.Main,e.Sub,e.Type,"收到角色事件接續許可"),
        EventRejectedEvent r => new(sequence,e.Main,e.Sub,e.Type,r.Reason,Code:r.ReasonCode),
        GoldSnapshotEvent r => new(sequence,e.Main,e.Sub,e.Type,$"角色金幣：{r.Amount}"),
        GoldDeltaEvent r => new(sequence,e.Main,e.Sub,e.Type,$"角色金幣變動：{r.Delta}"),
        ServerSocialEvent { Event: TeamFlagEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊開關已回覆", Code: r.Enabled ? 1 : 2),
        ServerSocialEvent { Event: TeamNoticeEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊請求已回覆", Code: r.Code),
        ServerSocialEvent { Event: TeamAnswerEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊對象已回覆", Code: r.Answer, Role: r.RoleId),
        ServerInventoryEvent { Event: CraftAddedEvent r } => new(sequence, e.Main, e.Sub, e.Type, "製作排程已新增", r.Row.ItemId, r.Row.Count, r.Row.Index),
        ServerInventoryEvent { Event: CraftCompletedEvent r } => new(sequence, e.Main, e.Sub, e.Type, "伺服器確認製作完成", Index: r.Index),
        ServerInventoryEvent { Event: CraftFailedEvent r } => new(sequence, e.Main, e.Sub, e.Type, r.Reason, Index: r.Index),
        ServerInventoryEvent { Event: PotionUsedEvent r } => new(sequence, e.Main, e.Sub, e.Type, "儲存槽使用回覆", Resource: r.Resource, Targets: r.Targets),
        ServerLiveDataEvent { Event: ItemUseResultEvent r } => new(sequence, e.Main, e.Sub, e.Type, "物品使用回覆", ItemId: r.ItemId, Index: r.NpcIndex, Code: r.Result),
        ServerSocialEvent { Event: AlchemyResultEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"煉金結果：物品 {r.ItemId} × {r.Count}", r.ItemId, r.Count),
        ServerSocialEvent { Event: AlchemySpaceErrorEvent r } => new(sequence, e.Main, e.Sub, e.Type, "伺服器拒絕煉金：空間或條件不足", Code: r.Code),
        ServerSocialEvent { Event: SocialRejectedEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"伺服器拒絕社交操作（代碼 {r.Code}）", Code: r.Code),
        ServerLiveDataEvent { Event: BagAddEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包入包：物品 {r.Item.ItemId} × {r.Item.Count}", r.Item.ItemId, r.Item.Count, r.Item.Index, r.Source),
        ServerLiveDataEvent { Event: BagDeleteEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包扣除：格位 {r.Index} × {r.Count}", Count: r.Count, Index: r.Index),
        ServerLiveDataEvent { Event: BagSnapshotEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包完整同步：{r.Items.Length} 格"),
        RoundStartEvent r => new(sequence, e.Main, e.Sub, e.Type, $"戰鬥第 {r.Round} 回合"),
        PositionSnapshotEvent r => new(sequence, e.Main, e.Sub, e.Type, $"伺服器位置：地圖 {r.Scene} ({r.X}, {r.Y})",Role:r.RoleId),
        EventEndEvent => new(sequence, e.Main, e.Sub, e.Type, "伺服器事件結束"),
        InitialDataCompleteEvent => new(sequence, e.Main, e.Sub, e.Type, "世界初始化資料接收完成"),
        _ => new(sequence, e.Main, e.Sub, e.Type, e.Type)
    };
}
