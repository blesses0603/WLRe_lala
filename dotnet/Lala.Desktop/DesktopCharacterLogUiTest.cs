using System.Collections.Immutable;
using Avalonia.Controls;
using Lala.Core.Gameplay;

namespace Lala.Desktop;

internal static partial class DesktopUiSmokeTest
{
    private sealed partial class Run
    {
        private async Task CharacterLogAsync()
        {
            dashboard.SelectEventTab();
            uint role=fixture.State.Player!.RoleId;
            ImmutableArray<GameServerEvent> entries=[
                new(1,26,4,"gold_snapshot","角色金幣：100",OwnerRoleId:role),
                new(2,22,2,"scene_npc_move","場景 NPC 移動"),
                new(3,12,1,"position_snapshot","其他玩家位置",OwnerRoleId:role+1),
                new(4,90,1,"unimplemented","unimplemented")];
            session.SetServerEvents(session.Generation,entries,role);
            await Settle(dashboard);
            string text=Find<TextBlock>(dashboard,"CharacterEventLog").Text!;
            Check(text.Contains(fixture.State.Player.Name)&&text.Contains("角色金幣：100")&&text.Contains("最近 1 筆"),"dashboard shows the selected character's retained history");
            Check(!text.Contains("場景 NPC")&&!text.Contains("其他玩家")&&!text.Contains("unimplemented")&&!text.Contains("筆伺服器封包"),"dashboard excludes scene noise and global packet totals");
            Check(text.Contains("角色接收紀錄")&&text.Contains("[接收 26-4]"),"incoming protocol notices are not labeled as client transmissions");
            var controls=Enumerable.Range(10,80).Select(i=>new GameServerEvent(i,20,10,"event_continue_permission","收到角色事件接續許可",OwnerRoleId:role))
                .Append(new(90,20,8,"event_end","伺服器事件結束",OwnerRoleId:role))
                .Append(new(91,20,74,"event_rejected","伺服器拒絕事件",OwnerRoleId:role)).ToImmutableArray();
            session.SetServerEvents(session.Generation,controls,role);await Settle(dashboard);
            text=Find<TextBlock>(dashboard,"CharacterEventLog").Text!;
            Check(text.Contains("最近 2 筆")&&text.Contains("80 次接續通知")&&text.Contains("已結束")&&!text.Contains("[接收 20-10]"),"dashboard compacts repetitive event control traffic");
            Check(text.Contains("[接收 20-74]")&&text.Contains("伺服器拒絕事件"),"dashboard preserves event errors as separate visible entries");
        }
    }
}
