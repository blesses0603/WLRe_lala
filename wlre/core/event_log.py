"""Only local-role evidence reaches the event log; unknown broadcasts stay silent."""
import re
from wlre.services.battle.party import own_team, event_text
from wlre.services.battle.combat import attack_lines
from wlre.services.items.combat_resources import item_name, skill_name
from wlre.services.battle.auto_battle import summary as ai_summary
from wlre.services.world.roaming import summary as roaming_summary
from wlre.services.world.map_names import map_label

PHASES={'disconnected':'尚未連線','connected':'已連線','connecting':'連線中','authenticated':'登入驗證成功','role_selection':'請選擇角色','role_selected_awaiting_world':'已選角，等待角色資料','world_received':'角色資料已收到，正在完成登入','world_ready':'角色資料已同步','login_failed':'登入失敗'}
TEXT={'world initialization has not completed':'角色資料尚未同步完成','role selection is not available':'目前無法選角','role is unavailable or locked':'角色不存在或已鎖定','connection_closed':'連線已關閉','disconnected':'尚未連線','world_ready':'角色資料已同步','completed':'已完成','running':'進行中','finished':'已結束','stopped':'已停止','disabled':'已停止','awaiting_response':'等待伺服器回覆','submitted':'已送出','healing':'補給中','waiting':'等待中','pending':'處理中'}
CODES={'S20-8':'事件結束','C20-6 00':'接續事件','S6-1':'移動通知','C6-1':'座標同步','S3-1':'角色登入位置','S7-1':'換圖位置','S12-1':'角色位置','S6-2':'停止移動','S11-0':'戰鬥退場'}

def chinese(text):
    text=str(text)
    text=re.sub(r'\bHP\b','生命',text);text=re.sub(r'\bSP\b','魔力',text)
    for code,value in CODES.items():text=text.replace(code,value)
    text=re.sub(r'C20-8 direct door=([0-9]+)',r'傳送點直接觸發（出口 \1）',text)
    text=re.sub(r'\bS20-\d+\b','伺服器事件通知',text)
    for code,value in sorted(TEXT.items(),key=lambda x:-len(x[0])):text=text.replace(code,value)
    return text

def owned(unit,pid):return bool(pid and (unit.get('pid')==pid or unit.get('master_id')==pid))
def battle_local(state):return any(owned(u,state.get('player',{}).get('role_id')) for u in state.get('battle_units',{}).values())

def lines(event,state):
    if event.get('type')=='maintenance_status':return ['戰後修理／整理：'+event.get('status','')]
    if event.get('type')=='field_supply_status':return [('補給已確認：' if event.get('status')=='confirmed' else '補給已鎖定：')+event.get('reason','')]
    kind=event['type'];pid=state.get('player',{}).get('role_id');units=state.get('battle_units',{})
    if kind in ('unimplemented','sent') or kind.startswith('chat_'):return []
    if kind=='guild_roster':return [f"組織成員名稱已同步：{len(event['members'])} 位"]
    if kind in ('verification_result','login_result'):
        return [('帳號驗證' if kind=='verification_result' else '角色登入')+('成功' if event['result']==0 else f"未成功（原因 {event['result']}）")]
    if kind=='connection_closed':return ['連線已關閉']
    if kind=='command_rejected':return ['操作未送出：'+chinese(event['error'])]
    if not pid:return []
    if kind == 'tent_added' and event['tent']['owner_id'] == pid:return ['自家帳篷已在目前場景展開']
    if kind == 'tent_removed' and event['owner_id'] == pid:return ['自家帳篷已由伺服器收起']
    if kind == 'tent_limit':return ['展開帳篷失敗：本場景帳篷數已達上限']
    if kind == 'tent_entry_denied':return ['伺服器拒絕進入帳篷']
    if kind == 'tent_error':return ['帳篷伺服器錯誤：'+str(event['code'])]
    if kind.startswith('craft_'):
        names={'craft_snapshot':'家具製作排程已同步','craft_added':'已加入製作排程','craft_started':'開始製作','craft_paused':'暫停製作','craft_completed':'製作完成','craft_deleted':'製作排程已移除','craft_swapped':'製作順序回覆已收到','craft_human':'製作夥伴已同步'}
        return [event.get('reason') or names.get(kind,'製作資料已更新')]
    if kind in ('activity_self','activity_roles') and (kind=='activity_self' or pid in event.get('roles',[])):
        return [('開始' if event['active'] else '結束')+event['activity']]
    if kind in ('position_snapshot','walk'):
        if event['role_id']!=pid:return []
        point=f"座標 {event['x']}, {event['y']}"
        if kind=='position_snapshot':return [f"角色位置｜{map_label(event['scene'])}｜{point}"]
        return ['角色移動｜'+point]
    if kind=='movement_request':return [f"移動座標 {event['x']}, {event['y']}"]
    if kind=='attack_result':
        actions=[]
        for action in event['actions']:
            unit=units.get(f"{action['col']}:{action['row']}",{})
            if owned(unit,pid):actions.append(dict(action))
            else:
                targets=[t for t in action['targets'] if owned(units.get(f"{t['col']}:{t['row']}",{}),pid)]
                if targets:actions.append({**action,'targets':targets})
        for action in actions:action['skill_name']=skill_name(action['skill_id'])
        return [re.sub(r'\([0-9]+(?::[0-9]+)?\)','',line) for line in attack_lines({**event,'actions':actions},state)]
    if kind=='battle_start':
        return ['本機角色進入戰鬥'] if any(owned(u,pid) for u in event['units']) else []
    if kind=='battle_command_sent':
        if not owned(units.get(f"{event['col']}:{event['row']}",{}),pid):return []
        return [('已送出道具指令：'+item_name(event['item_id']) if 'item_id' in event else '已送出戰鬥指令：'+skill_name(event['skill_id']))+'｜等待結果']
    if kind=='fight_exit':return ['本機角色戰鬥退場，等待戰後事件'] if event['role_id']==pid else []
    if kind=='battle_unit_exit':
        unit=units.get(f"{event['col']}:{event['row']}",{})
        return [(unit.get('name') or '本機單位')+'已退出戰鬥'] if owned(unit,pid) else []
    if kind=='round_start':return [f"第 {event['round']} 回合開始"] if battle_local(state) else []
    if kind=='winner':return ['本場戰鬥已結束'] if battle_local(state) else []
    team=own_team(state);members=team['members'] if team else []
    if kind.startswith('team_') or kind=='social_rejected':
        if kind=='team_join' and not (event['role_id']==pid or event['leader_id']==pid or event['leader_id'] in members):return []
        if kind=='team_leave' and event['role_id']!=pid and event['role_id'] not in members:return []
        if kind=='team_list' and not any(pid in t['members'] for t in event['teams']):return []
        if kind=='team_new_leader' and not any(event.get(k) in members or event.get(k)==pid for k in ('leader_id','old_leader_id')):return []
        return ['組隊：'+event_text(event)]
    if kind=='attribute_set':
        if event['entity']!='self':return []
        if event['kind']==35:return [f"角色等級更新：{event['value']} 級"]
        return []
    if kind=='world_player':return ['已登入角色：'+event['player']['name']] if event['player']['role_id']==pid else []
    if kind=='shop_purchase_result':
        texts={0:'伺服器回報購買成功（尚須核對金幣／背包同步）',
               1:'伺服器拒絕購買：金幣不足',2:'伺服器拒絕購買：背包空間不足',
               3:'伺服器拒絕購買：數量超出限制',4:'伺服器回報購買失敗'}
        return [texts.get(event['result'],f"伺服器購買回覆：代碼 {event['result']}")]
    if kind=='sale_notice':
        return ['伺服器回報販售成功（需核對背包／金幣同步）' if event['result']==1
                else '伺服器回報販售失敗或狀態不明']
    if kind=='gold_snapshot':
        return ['角色金幣已由伺服器完成初始同步']
    if kind=='gold_delta':
        return ['角色金幣變更已由伺服器回覆']
    if kind=='gold_limit':
        return ['伺服器金幣上限通知；金額待重新同步']
    if kind=='bag_add':return [f"獲得道具：{item_name(event['item']['item_id'])} ×{event['item']['count']}"]
    if kind=='alchemy_result':return [f"煉金結果：{item_name(event['item_id'])} ×{event['count']}"]
    if kind=='alchemy_space_error':return ['煉金失敗：包包空間不足']
    if kind=='auto_battle_status':return ['自動戰鬥：'+ai_summary(event)]
    if kind=='roaming_status':return ['自動徘徊：'+roaming_summary(event)]
    if kind=='local_movement':return ['角色步行：'+chinese(event['reason'])]
    if kind=='field_storage_sent':return ['已送出儲存槽補給：'+event['resource'].upper()+f" {event['amount']}｜等待回覆"]
    if kind=='field_item_sent':return ['已送出補給指令：'+item_name(event['item_id'])+'｜等待回覆']
    known={'initial_data_complete':'登入資料已接收完成','player_combat_data':'角色能力資料已同步','player_equip_data':'角色裝備已同步','bag_snapshot':'包包資料已同步','companion_snapshot':'本機夥伴資料已同步','active_companion':'出戰夥伴已更新','event_end':'伺服器事件已結束','event_continue_permission':'伺服器允許接續事件','event_active':'伺服器事件處理中','movement_stop':'伺服器要求角色暫停移動','star_info':'二轉星脈經驗已更新'}
    if kind=='event_rejected':return ['伺服器拒絕操作：'+event['reason']]
    return [known[kind]] if kind in known else []
