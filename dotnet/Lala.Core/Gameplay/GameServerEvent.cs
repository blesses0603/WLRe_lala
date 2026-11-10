using Lala.Core.Protocol;
using Lala.Core.Inventory;

namespace Lala.Core.Gameplay;

/// <summary>Bounded receive receipt and display metadata. No raw packet, chat contents,
/// account credentials or nearby character names are retained in this log.</summary>
public sealed record GameServerEvent(long Sequence, byte Main, byte Sub, string Type, string Description,
    ushort? ItemId = null, int? Count = null, int? Index = null, int? Source = null, int? Code = null,
    uint? Role = null, uint? OtherRole = null)
{
    internal static GameServerEvent From(long sequence, ServerEvent e) => e switch
    {
        ServerSocialEvent { Event: TeamFlagEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊開關已回覆", Code: r.Enabled ? 1 : 2),
        ServerSocialEvent { Event: TeamNoticeEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊請求已回覆", Code: r.Code),
        ServerSocialEvent { Event: TeamAnswerEvent r } => new(sequence, e.Main, e.Sub, e.Type, "組隊對象已回覆", Code: r.Answer, Role: r.RoleId),
        ServerInventoryEvent { Event: CraftAddedEvent r } => new(sequence, e.Main, e.Sub, e.Type, "製作排程已新增", r.Row.ItemId, r.Row.Count, r.Row.Index),
        ServerInventoryEvent { Event: CraftCompletedEvent r } => new(sequence, e.Main, e.Sub, e.Type, "伺服器確認製作完成", Index: r.Index),
        ServerInventoryEvent { Event: CraftFailedEvent r } => new(sequence, e.Main, e.Sub, e.Type, r.Reason, Index: r.Index),
        ServerSocialEvent { Event: AlchemyResultEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"煉金結果：物品 {r.ItemId} × {r.Count}", r.ItemId, r.Count),
        ServerSocialEvent { Event: AlchemySpaceErrorEvent r } => new(sequence, e.Main, e.Sub, e.Type, "伺服器拒絕煉金：空間或條件不足", Code: r.Code),
        ServerSocialEvent { Event: SocialRejectedEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"伺服器拒絕社交操作（代碼 {r.Code}）", Code: r.Code),
        ServerLiveDataEvent { Event: BagAddEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包入包：物品 {r.Item.ItemId} × {r.Item.Count}", r.Item.ItemId, r.Item.Count, r.Item.Index, r.Source),
        ServerLiveDataEvent { Event: BagDeleteEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包扣除：格位 {r.Index} × {r.Count}", Count: r.Count, Index: r.Index),
        ServerLiveDataEvent { Event: BagSnapshotEvent r } => new(sequence, e.Main, e.Sub, e.Type, $"背包完整同步：{r.Items.Length} 格"),
        RoundStartEvent r => new(sequence, e.Main, e.Sub, e.Type, $"戰鬥第 {r.Round} 回合"),
        PositionSnapshotEvent r => new(sequence, e.Main, e.Sub, e.Type, $"伺服器位置：地圖 {r.Scene} ({r.X}, {r.Y})"),
        EventEndEvent => new(sequence, e.Main, e.Sub, e.Type, "伺服器事件結束"),
        InitialDataCompleteEvent => new(sequence, e.Main, e.Sub, e.Type, "世界初始化資料接收完成"),
        _ => new(sequence, e.Main, e.Sub, e.Type, e.Type)
    };
}
