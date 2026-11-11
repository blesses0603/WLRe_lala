using Lala.Core.Catalogs;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.World.Portals;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static GameActionPlan ContinueEvent(GameAction action,ServiceStateSnapshot s,double now)
    {
        var session = s.Local.Session;
        bool post=action.Operation=="post_battle";
        if(post)Require(session.PostBattle is{Phase:"exit_delay"} p&&p.Role==s.Player?.RoleId&&p.Scene==s.Player?.Scene&&p.Battle==action.BattleCount
            &&p.ExitPacket.ToString(System.Globalization.CultureInfo.InvariantCulture)==action.Key&&now>=p.Due,"戰後接續尚未到時或已使用。");
        else Require(!session.PostBattle.Pending||session.PostBattle.Phase=="synchronizing","請等待戰後退場流程。");
        Require(s.Local.Battle.Active != true && (post||session.EventFlow.Blocked) && !session.EventFlow.AwaitingResponse &&
            !session.NpcDialogue.Active && (post||session.EventFlow.LastSource is "S20-7" or "S20-10" or "S20-11" or "S20-13" or "S20-14" or "S20-15" or "S20-16" or "S20-17"), "尚未收到可接續事件的伺服器通知。");
        bool replied=false;
        return new(new(20, 6, [0]), "event", "接續遊戲事件", next => CommandState.With(next,
            local: new(next.Local.Session with { PostBattle=post?next.Local.Session.PostBattle with{Phase="awaiting_response"}:next.Local.Session.PostBattle,
                EventFlow = next.Local.Session.EventFlow with
                { Blocked=true,AwaitingResponse = true, RequestsSent = next.Local.Session.EventFlow.RequestsSent + 1, LastSource = "C20-6" } }, next.Local.World, next.Local.Battle)),
            next => replied&&!next.Local.Session.EventFlow.AwaitingResponse)
        { ObserveReceipt=receipt=>
            {
                if(receipt.Type=="event_rejected")throw new ProtocolException("伺服器拒絕事件接續。");
                if(receipt.Type is "event_end" or "event_continue_permission" or "event_active")replied=true;
            } };
    }

    private static GameActionPlan Portal(GameAction a, ServiceStateSnapshot s, OfflineRuntimeCandidate c)
    {
        Require(a.Index is > 0 and <= ushort.MaxValue && a.Scene == s.Player!.Scene, "請重新選擇目前地圖的傳點。");
        var key = new EventPortalKey(a.Scene, (ushort)a.Index);
        var source = c.PortalObservations.Reconciled;
        Require(!source.Issues.ContainsKey(key) && source.Destinations.TryGetValue(key, out var destination) &&
            destination.DestinationVerified && destination.Destination is > 0 && destination.Destination == a.Target,
            "此出口尚未取得同版、無衝突的目的地資料。");
        Require(c.Doors.Scenes.Any(scene => scene.SceneId == a.Scene && scene.Doors.Any(door => door.Index == a.Index)), "找不到同版出口索引。");
        Require(s.Party.OwnTeam(s.Player!.RoleId) is not {} team || team.LeaderId == s.Player.RoleId, "隊員請跟隨隊長換圖。");
        var origin = s.Local.World.Location.Confirmed;
        return new(new(20, 8, new PacketWriter().U16(a.Index).Build()), "npc", "通過出口",
            next => CommandState.With(next, local: new(next.Local.Session with
                { EventFlow = next.Local.Session.EventFlow with { Blocked = true, AwaitingResponse = true, LastSource = "C20-8" } }, next.Local.World, next.Local.Battle)),
            next => next.Player?.Scene == a.Target && next.Local.World.Location.ConfirmedIsCurrent &&
                next.Local.World.Location.Confirmed is {} fix && !Equals(fix, origin));
    }
}
