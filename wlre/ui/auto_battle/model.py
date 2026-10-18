"""Validated AutoPlay draft and server-confirmed action catalogue."""
import copy
from functools import lru_cache
from wlre.services.battle.auto_battle import validate, ACTION_IDS
from wlre.services.battle.battle_commands import ACTIONS, owned_units
from wlre.services.items.combat_resources import CAT, skill_rows, field_context

NAMES={0:'略過此格',**{sid:ACTIONS[mode] for sid,mode in ACTION_IDS.items()}}
TARGETS={1:'最低HP',2:'屬性優先',3:'最高HP'}
NOTICES={1:'同方任一單位',2:'本機角色',3:'出戰夥伴'}
COMPARES={1:'大於',2:'小於'}
GROUPS=(('bDeadAction','deadAction','同方陣亡',1),('bEnemyHPAction','enemyHpAction','敵HP條件',1),
        ('bLowHpAction','lowHpAction','低HP條件',1),('bLowSpAction','lowSpAction','低SP條件',1),
        ('bRoundAction','roundAction','指定回合',3),('bRepeatAction','repeatAction','循環行動',5),
        ('bOrderAction','orderAction','順序行動',2))

def action_label(row):
    sid=row['id']
    if sid in NAMES:return NAMES[sid]
    source=CAT['items'] if row['kind']==2 else CAT['skills']
    return f"{source.get(str(sid),{}).get('name','未知')} ({sid})"


def confirmed_skill_entries(state,who):
    """Only this profile's confirmed skills; never search the full catalogue."""
    if state.get('battle',{}).get('active'):
        actors=owned_units(state,False)
    else:
        context,_=field_context(state)
        actors=list(context['battle_units'].values())
    pid=state.get('player',{}).get('role_id');known={}
    if not pid:return []
    for actor in actors:
        if (actor['pid']==pid)!=(who=='player'):continue
        for skill in skill_rows(state,actor):
            source='裝備附帶' if skill['source']=='目前裝備附帶' else '已學'
            known.setdefault(skill['id'],[]).append(f"{actor.get('name','夥伴')} {source} Lv{skill['level']}")
    return [(sid,f"{CAT['skills'].get(str(sid),{}).get('name',f'技能{sid}')} ({sid})｜"+'／'.join(labels))
            for sid,labels in sorted(known.items())]

def confirmed_action_label(row,state,who):
    if row['kind']==1 and row['id'] not in NAMES:
        if row['id'] not in dict(confirmed_skill_entries(state,who)):
            return '特技未學會或尚未同步，請重新選擇'
    return action_label(row)

@lru_cache(maxsize=1)
def supply_catalogue():
    return tuple((int(sid),value['name']) for sid,value in CAT['items'].items() if value['kind'] in (23,32))

def action_entries(state,who,item):
    special=(0,-2,-3) if item else (0,-1,10001,60021,60041,10008)
    entries=[(sid,NAMES[sid]) for sid in special]
    if item:
        counts={}
        for value in state.get('inventory',{}).get('items',{}).values():
            counts[value['item_id']]=counts.get(value['item_id'],0)+value['count']
        data=[(sid,f"{name} ({sid})｜持有 {counts.get(sid,0)}") for sid,name in supply_catalogue()]
        data.sort(key=lambda row:(row[0] not in counts,row[0]))
    else:data=[entry for entry in confirmed_skill_entries(state,who) if entry[0] not in special]
    return entries+data

class RuleDraft:
    """A detached draft: cancel/import/export never silently applies settings."""
    def __init__(self,value):self.value=validate(value)
    def rows(self,who):
        p=self.value['profiles'][who]
        for flag,key,label,count in GROUPS:
            for i in range(count):
                yield key,i,label,p[flag],p[key][i] if count>1 else p[key]
    def set_action(self,who,key,index,row):
        value=copy.deepcopy(self.value);profile=value['profiles'][who]
        if isinstance(profile[key],list):profile[key][index]=copy.deepcopy(row)
        else:profile[key]=copy.deepcopy(row)
        self.value=validate(value)
    def swap(self,who,key,index,direction):
        values=self.value['profiles'][who][key];other=index+direction
        if not isinstance(values,list) or not 0<=other<len(values):return False
        values[index],values[other]=values[other],values[index];return True

MISC_RULE_KEYS=('lowHpAction','lowSpAction','enemyHpAction','deadAction')
