"""Synthetic offline oracle using actual maintenance helpers and tick's selection prefix.
Intercept repair_packet before packet creation or reservation installation. No network.
"""
import base64, copy, gzip, json, os, sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
os.environ['WLRE_DISABLE_AUTO_CATALOG']='1'
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from wlre.services.items import maintenance as m, post_battle_maintenance as p

def base():
    return dict(items={'10':dict(kind=25,special=130,fit_type=0,restrict=0),
                       '11':dict(kind=25,special=130,fit_type=0,restrict=16),
                       '20':dict(kind=1,special=0,fit_type=1,restrict=144)},
                player={'equips':[dict(item_id=20,damage=200)]}, companions={},active=9,
                inventory=dict(ready=True,reliable=True,items={'9':dict(item_id=10,count=2,damage=0),
                               '2':dict(item_id=10,count=3,damage=0),'1':dict(item_id=11,count=1,damage=0)}),
                threshold=50,repair_items=[10,11])
cases=[]
def add(name, change=lambda x:None):
    x=base();change(x);cases.append((name,x))
add('base')
for d in [None,0,1,199,200,249,250,251]:
    add('damage-'+str(d),lambda x,d=d:x['player']['equips'][0].update(damage=d))
for threshold in [0,1,49,50,249]:add('threshold-'+str(threshold),lambda x,t=threshold:x.update(threshold=t))
for field in ['locked','available_time','limited_time']:
    add('target-'+field,lambda x,f=field:x['player']['equips'][0].update({f:1}))
    add('supply-'+field,lambda x,f=field:[v.update({f:1}) for v in x['inventory']['items'].values()])
for fit in [0,1,2,3,4,5,6,7]:add('fit-'+str(fit),lambda x,f=fit:x['items']['20'].update(fit_type=f))
add('special',lambda x:x['items']['20'].update(special=1))
add('unreviewed',lambda x:x['items']['20'].clear())
add('missing-catalog',lambda x:x['items'].pop('20'))
for sid in sorted(p.BROKEN|{0,25746}):
    def mutate(x,sid=sid):
        x['items'][str(sid)]=x['items']['20'].copy();x['player']['equips'][0]['item_id']=sid
    add('excluded-id-'+str(sid),mutate)
add('unknown-damage',lambda x:x['player']['equips'][0].pop('damage'))
add('sparse-empty',lambda x:x['player'].clear())
add('all-active-order',lambda x:x.update(companions={'7':dict(index=7,npc_id=9,equips=[dict(item_id=20,damage=220)]),
    '3':dict(index=3,npc_id=8,equips=[dict(item_id=20,damage=240)]),
    '2':dict(index=2,npc_id=9,equips=[dict(item_id=20,damage=230)])}))
add('unknown-active',lambda x:x.update(active=None,companions={'1':dict(index=1,npc_id=0,equips=[dict(item_id=20,damage=200)])}))
add('zero-active',lambda x:x.update(active=0,companions={'1':dict(index=1,npc_id=0,equips=[dict(item_id=20,damage=200)])}))
for field in ['ready','reliable']:add('not-'+field,lambda x,f=field:x['inventory'].update({f:False}))
for n in [-1,1,2,3,99]:add('reserved-'+str(n),lambda x,n=n:x['inventory'].update(reserved={'2':n}))
for field in ['alchemy_slots','expedition_slots','maintenance_slots']:
    add(field,lambda x,f=field:x['inventory'].update({f:['2']}))
for exclusive,uncertain in [(False,False),(True,False),(False,True)]:
    add('hold-'+str((exclusive,uncertain)),lambda x,e=exclusive,u=uncertain:x['inventory'].update(holds={'battle':[dict(index='2',exclusive=e,uncertain=u)]}))
for count in [0,-1,260]:add('count-'+str(count),lambda x,n=count:x['inventory']['items']['2'].update(count=n))
for d in [249,250,251]:add('supply-damage-'+str(d),lambda x,d=d:x['inventory']['items']['2'].update(damage=d))
add('preference',lambda x:x.update(repair_items=[11,10]))
add('no-selected',lambda x:x.update(repair_items=[0,0]))
add('duplicate',lambda x:x.update(repair_items=[10,10]))
add('no-stock',lambda x:x['inventory']['items'].clear())
add('unknown-stock',lambda x:x['inventory']['items']['2'].update(item_id=999))
add('no-target',lambda x:x['player']['equips'].clear())
class Selected(Exception):pass
def capture(target,index,item_id):raise Selected(index)
out=[]
for name,x in cases:
    inv=x['inventory']; state=NS(knowledge={'player':x['player'],'companions':x['companions'],'active_npc_id':x['active']},inventory=inv,
        editing=lambda *a:nullcontext(),maintenance={},battle_count=1,player={'role_id':1})
    settings={'maintenance':dict(repair_enabled=True,cleanup_enabled=False,repair_below=x['threshold'],repair_items=x['repair_items'])}
    logic=NS(auto_battle=NS(enabled=True,settings=settings),world_acknowledged=True,movement=NS(stop=lambda *a:None))
    cat={'items':x['items']}
    with patch.object(m,'CAT',cat),patch.object(p,'CAT',cat),patch.object(p,'coordination_reason',lambda *a:None),patch.object(p,'repair_packet',capture):
        expected=dict(targets=list(p.repair_targets(state,x['threshold'])),stock=m.backpack_stock(inv,True),
            all_stock=m.backpack_stock(inv),slots={k:p.PostBattleMaintenance.slot_available(inv,k) for k in inv['items']},
            repair={k:m.is_repair(int(k)) for k in x['items']},cleanup={k:m.cleanup_action(int(k)) for k in x['items']},selected=None)
        worker=p.PostBattleMaintenance()
        try:worker.tick(state,logic,0);worker.tick(state,logic,1)
        except Selected as selected:expected['selected']=selected.args[0]
        assert not inv.get('holds',{}).get('maintenance')
    out.append(dict(name=name,input=x,expected=expected))
encoded=base64.b64encode(gzip.compress(json.dumps(out,separators=(',',':')).encode(),mtime=0)).decode()
code='''// Generated by generate_maintenance_vectors.py; actual Python helpers, synthetic data only.
using System.IO.Compression;
using System.Text.Json;
namespace Lala.Core.Tests.Inventory;
public static class MaintenancePythonVectors
{
    public static IEnumerable<object[]> Cases()
    {
        using var stream = new GZipStream(new MemoryStream(Convert.FromBase64String("'''+encoded+'''")), CompressionMode.Decompress);
        using var data = JsonDocument.Parse(stream);
        foreach (var row in data.RootElement.EnumerateArray())
            yield return new object[] { row.GetProperty("name").GetString()!, row.GetRawText() };
    }
}
'''
Path(__file__).with_name('MaintenancePythonVectors.cs').write_text(code)
print(len(out),'vectors')
