"""Synthetic oracle vectors for activity.py; run from any cwd, reads no accounts."""
import json, random, struct, sys
from pathlib import Path
from types import SimpleNamespace
root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
from wlre.core.activity import decode_activity, apply_activity
rng = random.Random(7741)
names = {'釣魚':'Fishing','採集':'Gathering','跳舞':'Dancing','馬桶製作':'ToiletCrafting','鍛鍊':'Training','夥伴鍛鍊':'CompanionTraining'}
cases=[]
for i in range(200):
    key = rng.choice([(23,122),(23,123),(23,138),(23,137),(7,4),(62,67),(62,84)])
    pid = rng.choice([None, 7, 8])
    role = rng.choice([7,8,0,4294967295])
    payload=b''
    if key in [(23,122),(23,123)]: payload=struct.pack('<IB',role,rng.randrange(256))
    elif key==(23,138): payload=b''.join(struct.pack('<I',rng.choice([7,8,9])) for _ in range(rng.randrange(6)))
    elif key==(23,137): payload=struct.pack('<I',role)
    elif key==(7,4):
        mode=rng.choice([0,1,3]); payload=bytes([mode])
        if mode==0:
            roles=rng.choices([7,8,9],k=rng.randrange(6));payload+=struct.pack('<I',len(roles))+b''.join(struct.pack('<I',r) for r in roles)
        else: payload+=struct.pack('<I',role)
    elif key==(62,84):payload=bytes([rng.randrange(3)])
    event=decode_activity(SimpleNamespace(main=key[0],sub=key[1],payload=payload))
    initial=rng.sample(list(names),rng.randrange(7))
    state=SimpleNamespace(player={'role_id':pid},activities=dict.fromkeys(initial,True))
    apply_activity(state,event)
    cases.append(dict(main=key[0],sub=key[1],hex=payload.hex(),pid=pid,initial=[names[n] for n in initial],expected=sorted(names[n] for n in state.activities)))
Path(__file__).with_name('PythonActivityVectors.cs').write_text('namespace Lala.Core.Tests.Activities;\ninternal static class PythonActivityVectors { internal const string Json = """\n'+json.dumps(cases,separators=(',',':'))+'\n"""; }\n')
