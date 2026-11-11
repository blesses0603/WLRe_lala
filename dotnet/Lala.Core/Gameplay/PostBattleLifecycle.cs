using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal sealed record PostBattleState
{
    internal uint? Role {get;init;}
    internal ushort? Scene {get;init;}
    internal BigInteger Battle {get;init;}
    internal string Phase {get;init;}="idle";
    internal double Due {get;init;}
    internal BigInteger ExitPacket {get;init;}
    internal int? AnnouncedStyle {get;init;}
    internal int? Style {get;init;}
    internal int? CoopCount {get;init;}
    internal bool Pending=>Phase is "fighting" or "exit_delay" or "awaiting_response" or "synchronizing";
}

internal static class PostBattleLifecycle
{
    internal static LocalStateSnapshot Observe(LocalStateSnapshot before,LocalStateSnapshot next,ServerEvent e,double now,int? coopCount)
    {
        var p=before.Session.PostBattle;
        if(before.Player?.RoleId!=next.Player?.RoleId || before.Player?.Scene!=next.Player?.Scene)
            p=new();
        if(e is WarStyleEvent style)p=p with{AnnouncedStyle=style.Value,Style=next.Battle.Active==true?style.Value:p.Style};
        if(e is ServerInstanceEvent{Event:Lala.Core.Instances.CoopFightCountEvent})p=p with{CoopCount=coopCount};
        var battle=next.Battle;
        if(e is ServerLayoutEvent{Event:BattleStartEvent})
        {
            p=p with{Role=next.Player?.RoleId,Scene=next.Player?.Scene,Battle=battle.BattleCount,Phase="fighting",Style=p.AnnouncedStyle??battle.WarStyle,AnnouncedStyle=null,ExitPacket=0};
        }
        bool ownExit=e is FightExitEvent exit&&exit.RoleId==next.Player?.RoleId ||
            e is BattleUnitExitEvent unit&&before.Battle.Units.Any(u=>u.Layout.Col==unit.Col&&u.Layout.Row==unit.Row&&u.Layout.Pid==next.Player?.RoleId);
        var session=next.Session;
        if(ownExit&&p.Phase=="fighting"&&p.Role==next.Player?.RoleId&&p.Battle==battle.BattleCount&&battle.BattleCount>0)
        {
            var own=battle.Units.Where(u=>u.Layout.Pid==next.Player?.RoleId).Select(u=>u.Layout.Col).Distinct().ToArray();
            bool won=own.Length==1&&own[0] is >=1 and <=4&&battle.WinnerSide==(own[0]>2?1:2);
            double delay=(p.Style??battle.WarStyle)==16&&p.CoopCount>1&&won?5:2.5;
            p=p with{Phase="exit_delay",Due=now+delay,ExitPacket=next.PacketCount,CoopCount=(p.Style??battle.WarStyle)==16&&p.CoopCount>0?p.CoopCount-1:p.CoopCount};
        }
        if(e is EventEndEvent&&p.Role==next.Player?.RoleId)p=p with{Phase="completed"};
        else if(e is EventContinuePermissionEvent or EventActiveEvent or NpcEffectEvent&&p.Phase=="awaiting_response")p=p with{Phase="synchronizing"};
        return new(session with{PostBattle=p},next.World,battle);
    }
}
