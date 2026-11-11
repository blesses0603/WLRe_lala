using System.Collections.Immutable;
using Lala.Core.Catalogs;
using Lala.Core.Inventory;
using Lala.Core.State;

namespace Lala.Core.Gameplay;

internal static class AutomaticBattleRound
{
    internal sealed record Entry(GameAction Action,GameActionPlan Plan);
    internal static ImmutableArray<Entry> Plan(ServiceStateSnapshot source,OfflineRuntimeCandidate catalogs,GameAutomationSettings options,string resourceKey,double now,ImmutableHashSet<Lala.Core.Battle.BattleSlot>? submitted=null)
    {
        var battle=source.Local.Battle;var player=source.Player!;var state=source;var entries=ImmutableArray.CreateBuilder<Entry>();
        var reserved=source.Bag.Reserved;
        state=CommandState.With(state,bag:source.Bag with{Reserved=reserved});
        var team=source.Party.OwnTeam(player.RoleId);
        bool missing=options.RequiredParty.Any(id=>id!=player.RoleId&&team?.Members.Contains(id)!=true);
        foreach(var unit in battle.Units.OrderBy(u=>u.Layout.Col).ThenBy(u=>u.Layout.Row))
        {
            if(unit.Exited||unit.Hp is not >0||unit.Layout.Pid!=player.RoleId&&unit.Layout.MasterId!=player.RoleId||battle.CommandAt(unit.Slot) is not null||submitted?.Contains(unit.Slot)==true)continue;
            var action=new GameAction("battle",missing?"escape":"auto",unit.Layout.Pid,battle.Round!.Value,X:unit.Layout.Col,Y:unit.Layout.Row,
                Scene:player.Scene,BattleProfile:unit.Layout.Pid==player.RoleId?options.Player:options.Partner,BattleCount:battle.BattleCount);
            var plan=ManualGameCommands.Plan(action,state,catalogs,now,resourceKey);entries.Add(new(action,plan));
            if(plan.BattleItem is {} item)
            {reserved=reserved.SetItem(item.Index,reserved.GetValueOrDefault(item.Index)+1);state=CommandState.With(state,bag:state.Bag with{Reserved=reserved});}
        }
        return entries.ToImmutable();
    }
}
