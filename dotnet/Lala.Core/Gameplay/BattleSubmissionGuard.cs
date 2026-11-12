using System.Numerics;
using Lala.Core.Protocol;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

/// <summary>Actual-write guard, independent of UI state, AI restarts and delayed S50 replies.
/// Call only under the account lifecycle gate, immediately before the owned write.</summary>
internal sealed class BattleSubmissionGuard
{
    private (uint Role,BigInteger Battle)? identity;
    private int round;
    private readonly HashSet<(int Col,int Row)> sent=[];
    private Guid? attempt;
    internal bool HasSubmitted(ServiceStateSnapshot state,int col,int row,Guid currentAttempt)=>attempt==currentAttempt
        &&identity==(state.Player!.RoleId,state.Local.Battle.BattleCount)&&round==state.Local.Battle.Round&&sent.Contains((col,row));
    internal void Admit(ServiceStateSnapshot state, GameAction action,Guid? currentAttempt=null)
    {
        if(currentAttempt is {} id&&attempt!=id){attempt=id;identity=null;round=0;sent.Clear();}
        var b=state.Local.Battle;
        if(state.Player is not {} player || b.Active!=true || b.Round is not >0 || action.Index!=b.Round
            || action.BattleCount is {} expected && expected!=b.BattleCount)
            throw new ProtocolException("戰場或回合已改變，舊指令不會送出。");
        var unit=b.Units.FirstOrDefault(u=>u.Layout.Col==action.X&&u.Layout.Row==action.Y);
        if(unit is null||unit.Exited||unit.Hp==0||unit.Layout.Pid!=action.Target
            ||unit.Layout.Pid!=player.RoleId&&unit.Layout.MasterId!=player.RoleId)
            throw new ProtocolException("戰鬥單位已改變，舊指令不會送出。");
        var key=(player.RoleId,b.BattleCount);
        if(identity!=key){identity=key;round=0;sent.Clear();}
        if(b.Round<round)throw new ProtocolException("收到較舊的戰鬥回合，停止重送指令。");
        if(b.Round>round){round=b.Round.Value;sent.Clear();}
        if(b.CommandAt(unit.Slot) is not null||!sent.Add((action.X,action.Y)))
            throw new ProtocolException("本單位本回合已送出指令，等待伺服器結果，不會重送。");
    }
}
