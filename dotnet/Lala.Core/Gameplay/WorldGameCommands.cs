using Lala.Core.Catalogs;
using Lala.Core.Protocol;
using Lala.Core.State;
using Lala.Core.World.Portals;

namespace Lala.Core.Gameplay;

internal static partial class ManualGameCommands
{
    private static GameActionPlan ContinueEvent(ServiceStateSnapshot s)
    {
        var session = s.Local.Session;
        Require(s.Local.Battle.Active != true && session.EventFlow.Blocked && !session.EventFlow.AwaitingResponse &&
            !session.NpcDialogue.Active && session.EventFlow.LastSource is "S20-7" or "S20-10" or "S20-11" or "S20-13" or "S20-14" or "S20-15" or "S20-16" or "S20-17", "尚未收到可接續事件的伺服器通知。");
        return new(new(20, 6), "npc", "接續遊戲事件", next => CommandState.With(next,
            local: new(next.Local.Session with { EventFlow = next.Local.Session.EventFlow with
                { AwaitingResponse = true, RequestsSent = next.Local.Session.EventFlow.RequestsSent + 1, LastSource = "C20-6" } }, next.Local.World, next.Local.Battle)),
            next => !next.Local.Session.EventFlow.AwaitingResponse);
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
