"""Synthetic deterministic parity vectors. Run from repo root; never reads accounts."""
import json, random, sys
from pathlib import Path
root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
from wlre.services.expedition.teams import condition_met, success_details, choose_members
rng = random.Random(47131)
cases = []
for i in range(400):
    roles, npcs = [], {}
    for index in rng.sample(range(1, 35), rng.randrange(0, 10)):
        roles.append(dict(index=index, npc_id=index+100, faith=rng.randrange(0,101), stats={k:rng.randrange(0,180) for k in ('level','potential','str','con','int','wis','agi')}))
        roles[-1]['stats']['degree'] = rng.randrange(0,4)
        if rng.random() < .8: npcs[str(index+100)] = {k: rng.choice([None,0,1,2,3,4]) for k in ('element','kind','original')}
    def cond(kind=None):
        kind = rng.randrange(0,17) if kind is None else kind
        return [kind, rng.randrange(0,5) if kind in (0,1,2,3,4,12,13,14,15,16) else rng.randrange(0,750), rng.randrange(0,5)]
    join = cond(i % 17)
    recs = [dict(condition=cond(), bonus=rng.choice([0,50,100,200,400])) for _ in range(rng.randrange(0,5))]
    quest = dict(condition=join, recommendations=recs, success_rate=rng.choice([0,100,500,900,1000,1200]),faith_cost=rng.randrange(0,101))
    threshold = rng.randrange(0,101)
    cases.append(dict(roles=roles,npcs=npcs,quest=quest,threshold=threshold,met=condition_met(join,roles,npcs),
        success=success_details(quest,roles,npcs),selected=[r['index'] for r in choose_members(quest,roles,threshold,npcs)]))
payload = json.dumps(cases,ensure_ascii=False,separators=(',',':'))
Path(__file__).with_name('PythonExpeditionVectors.cs').write_text('namespace Lala.Core.Tests.Expedition;\ninternal static class PythonExpeditionVectors { internal const string Json = """\n'+payload+'\n"""; }\n')
