using Lala.Core.Battle;
using Lala.Core.Gameplay;
using Lala.Core.Protocol;
using Lala.Core.State;
using Xunit;

namespace Lala.Core.Tests.Resources;

public sealed partial class ResourceRuntimeBootstrapTests
{
    private static ServiceStateSnapshot SubmissionState(int battle=1,ushort round=1)
    {
        var state=GameState();uint role=state.Player!.RoleId;
        BattleUnit Unit(uint pid,uint master,byte col)=>new(1,1,pid,0,master,col,1,100,50,100,50,1,1,0,0,0,0,0,0,0,0,"synthetic",[]);
        return CommandState.With(state,local:new(state.Local.Session,state.Local.World,new(){Active=true,BattleCount=battle,Round=round,
            Units=[new(Unit(role,0,1)),new(Unit(60001,role,2))]}));
    }
    [Fact]
    public void Write_guard_is_once_per_unit_round_and_survives_local_command_history_replacement()
    {
        var s=SubmissionState();uint role=s.Player!.RoleId;var guard=new BattleSubmissionGuard();
        var action=new GameAction("battle","defend",role,1,X:1,Y:1,BattleCount:1);
        guard.Admit(s,action);
        Assert.Throws<ProtocolException>(()=>guard.Admit(SubmissionState(),action));
        guard.Admit(s,action with{Target=60001,X=2});
        guard.Admit(SubmissionState(round:2),action with{Index=2});
        Assert.Throws<ProtocolException>(()=>guard.Admit(s,action));
        Assert.Throws<ProtocolException>(()=>guard.Admit(SubmissionState(battle:2),action));
        guard.Admit(SubmissionState(battle:2),action with{BattleCount=2});
    }
    [Fact]
    public void A_new_formal_connection_has_an_independent_battle_epoch()
    {
        var s=SubmissionState();var guard=new BattleSubmissionGuard();var action=new GameAction("battle","defend",s.Player!.RoleId,1,X:1,Y:1,BattleCount:1);
        var first=Guid.NewGuid();guard.Admit(s,action,first);
        Assert.Throws<ProtocolException>(()=>guard.Admit(s,action,first));guard.Admit(s,action,Guid.NewGuid());
    }

    [Fact]
    public void Write_guard_rejects_unowned_or_replaced_units_without_consuming_valid_slot()
    {
        var s=SubmissionState();var guard=new BattleSubmissionGuard();
        var a=new GameAction("battle","defend",s.Player!.RoleId+1,1,X:1,Y:1,BattleCount:1);
        Assert.Throws<ProtocolException>(()=>guard.Admit(s,a));
        guard.Admit(s,a with{Target=s.Player.RoleId});
    }
}
