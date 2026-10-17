"""Lua-derived normal attacks and readable server-reported effects.

Never derive absolute HP from attack deltas; S51/11 snapshots own HP.
"""
from wlre.paths import RESOURCE_ROOT
import json
from wlre.network.wire import ProtocolError

DATA=json.loads(RESOURCE_ROOT.joinpath('normal_attack_data.json').read_text(encoding='utf8'))
NORMALS={10001:'空手普攻',10002:'刃技普攻',10003:'棒技普攻',10004:'魔杖／法器普攻',10005:'槍技普攻',
         10007:'銃普攻',10018:'人型夥伴銃普攻',10019:'弓普攻',10020:'人型夥伴弓普攻',
         10026:'火箭筒普攻',10027:'人型夥伴火箭筒普攻',10010:'怪物貼地普攻',10023:'怪物跳躍普攻',10029:'怪物貼地魔法普攻',10030:'怪物跳躍魔法普攻'}
BROKEN={10062,11098,12069,13064,15051,14063,17066,18062,19055,20039,21120,22125,23105,24090,25044}

def normal_skill(unit, player_id):
    equips=unit.get('equips',[])
    if len(equips)<3:raise ProtocolError('缺少手部裝備資料，尚無法自動判斷普攻')
    item=equips[2]['item_id']
    weapon=0 if item==0 or item in BROKEN else DATA['items'].get(str(item))
    if weapon is None:raise ProtocolError(f'未知武器 {item}，尚無法自動判斷普攻')
    npc=None
    if unit.get('pid')==player_id:
        body=1 if unit.get('change_body_id',0) else 0
    elif unit.get('master_id')==player_id:
        npc=DATA['npcs'].get(str(unit['pid']))
        if not npc or npc['kind'] not in (0,1):raise ProtocolError('夥伴類型尚無法判定，尚無法自動判斷普攻')
        body=npc['bodyType'] if item==0 and npc['kind']==0 else 1
    else:raise ProtocolError('操作單位不屬於本機角色')
    if npc and npc['kind']==1:
        magic=bool(item and weapon in (5,10))
        if npc['normalAttackKind']==0:return 10030 if magic else 10023
        if npc['normalAttackKind'] in (1,2):return 10029 if magic else 10010
        raise ProtocolError('未知怪物普攻類型，尚無法自動判斷普攻')
    if weapon==0:return 10001
    if weapon in (1,2,6,8):return 10002
    if weapon in (7,9):return 10003
    if weapon in (5,10):return 10004
    if weapon==3:return 10005
    if body not in (0,1):raise ProtocolError('未知身體類型，尚無法自動判斷普攻')
    if weapon==4:return 10019 if body==0 else 10020
    if weapon==11:
        return (10026 if body==0 else 10027) if item in (20037,20038,20040) else (10007 if body==0 else 10018)
    raise ProtocolError('此裝備無已確認的普攻')

def unit_label(state,col,row):
    slot=f'{col}:{row}'
    unit=state.get('battle_units',{}).get(slot,{})
    return f"{unit.get('name') or '未知單位'}({slot})"

def effect_text(value):
    kind,amount,sign=value['kind'],value['value'],value['sign']
    if kind==0 and amount==0:return None
    attr={25:'HP',26:'SP'}.get(kind,value.get('attribute') or f'屬性{kind}')
    if kind in (25,26):
        if sign==0:return f'{attr} 回復 {amount}'
        if sign==1:return f'{attr} 傷害 {amount}'
        if sign==2:return f'{attr} 爆擊傷害 {amount}'
        if sign==3:return f'{attr} 無視護盾傷害 {amount}'
    return f'{attr}={amount}（sign {sign}）'

def attack_lines(event,state):
    lines=[]
    for action in event['actions']:
        actor=unit_label(state,action['col'],action['row'])
        skill=action['skill_id'];name={**NORMALS,60021:'防禦',60041:'逃跑',10008:'捕捉'}.get(skill,action.get('skill_name') or '技能')
        for target in action['targets']:
            effects=[text for v in target['attributes'] if (text:=effect_text(v))]
            result='、'.join(effects) or '無有效屬性變化'
            lines.append(f"{actor} → {unit_label(state,target['col'],target['row'])}｜{name}({skill})｜{result}")
    return lines

