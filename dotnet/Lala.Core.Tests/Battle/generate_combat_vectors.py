"""Synthetic Python combat parity vectors. No live data or server actions."""
from pathlib import Path
import json
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from wlre.services.battle import combat

def cs(value):
    if value is None:return 'null'
    if isinstance(value,str):return json.dumps(value,ensure_ascii=False)
    return str(value)
lines=['// Generated from retained Python combat.py using synthetic catalog snapshots.',
'namespace Lala.Core.Tests.Battle;', 'public static class PythonCombatVectors', '{',
'    public static IEnumerable<object?[]> NormalCases()', '    {']
count=0
def add(name, item, weapon, pid=123, master=None, change=0, npc_kind=None, body=0, attack=0, equip_count=3):
    global count
    unit={'pid':pid,'master_id':master,'change_body_id':change,'equips':[{'item_id':0},{'item_id':0},{'item_id':item}][:equip_count]}
    data={'items':{} if weapon is None else {str(item):weapon}, 'npcs':{} if npc_kind is None else {str(pid):{'kind':npc_kind,'bodyType':body,'normalAttackKind':attack}}}
    with patch.object(combat.DATA,'snapshot',return_value=data):
        try: expected=combat.normal_skill(unit,123); error=None
        except Exception as ex: expected=None; error=str(ex)
    vals=[cs(name),str(item),cs(weapon),f'{pid}u', 'null' if master is None else f'{master}u',f'{change}u',cs(npc_kind),str(body),str(attack),str(equip_count),cs(expected),cs(error)]
    lines.append('        yield return new object?[] { '+', '.join(vals)+' };')
    count+=1
for weapon in range(14):
    for change in [0,99]:add(f'player-kind{weapon}-body{change}',50000+weapon,weapon,change=change)
    add(f'human-kind{weapon}',50000+weapon,weapon,pid=456,master=123,npc_kind=0)
    for normal in range(4):
        add(f'monster-kind{weapon}-normal{normal}',50000+weapon,weapon,pid=456,master=123,npc_kind=1,attack=normal)
for item in [0,*sorted(combat.BROKEN),20037,20038,20040]:
    for pid,master,npc in [(123,None,None),(456,123,0),(456,123,1)]:
        add(f'special-{item}-{pid}-{npc}',item,None if item in combat.BROKEN or item==0 else 11,pid=pid,master=master,npc_kind=npc)
add('unknown-weapon',54321,None)
add('missing-equipment',0,None,equip_count=2)
add('foreign-unit',0,None,pid=456,master=999)
add('missing-npc',0,None,pid=456,master=123)
add('unknown-npc-kind',0,None,pid=456,master=123,npc_kind=9)
lines+=['    }','    public static IEnumerable<object?[]> EffectCases()','    {']
for kind in [0,25,26,999]:
    for amount in [0,42,-7,2147483647]:
        for sign in [0,1,2,3,4,-1]:
            for attribute in [None,'自訂屬性','']:
                result=combat.effect_text({'kind':kind,'value':amount,'sign':sign,'attribute':attribute})
                lines.append('        yield return new object?[] { '+', '.join([str(kind),f'{amount}L',str(sign),cs(attribute),cs(result)])+' };')
lines+=['    }','}']
Path(__file__).with_name('PythonCombatVectors.cs').write_text('\n'.join(lines)+'\n')
print(f'{count} normal attack vectors; 288 effect vectors')
