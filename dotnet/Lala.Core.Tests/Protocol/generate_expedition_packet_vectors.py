"""Synthetic packet parity for the original S31 decoder; no live captures."""
import json,random,struct,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from wlre.network.expedition import decode_expedition
rng=random.Random(3197)
cases=[]
for n in range(160):
 sub=[6,3,24,5,26,12,27,35,13,15,16,17,18,19,20,25,21][n%17]
 raw=lambda size: bytes(rng.randrange(256) for _ in range(size))
 if sub==6:
  count=rng.randrange(5);payload=bytes([20,count])+raw(count*32)
 elif sub in (3,24):payload=raw(32)
 elif sub in (5,26,20,25):payload=raw(1)
 elif sub==12:payload=raw(2)
 elif sub in (27,17):payload=raw(3)
 elif sub==35:payload=raw(6)
 elif sub==13:payload=raw(210+100+140+5+27)
 elif sub==15:payload=raw(rng.randrange(30))
 elif sub==16:payload=raw(6+9*rng.randrange(5))
 elif sub==18:payload=raw(21)
 elif sub==19:payload=raw(151)
 elif sub==21:payload=raw(5)
 event=decode_expedition(SimpleNamespace(main=31,sub=sub,payload=payload))
 cases.append(dict(sub=sub,hex=payload.hex(),expected=event))
Path(__file__).with_name('PythonExpeditionPacketVectors.cs').write_text('namespace Lala.Core.Tests.Protocol;\ninternal static class PythonExpeditionPacketVectors { internal const string Json = """\n'+json.dumps(cases,separators=(',',':'))+'\n"""; }\n')
