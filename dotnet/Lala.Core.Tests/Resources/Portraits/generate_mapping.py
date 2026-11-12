"""Owned fixtures from real Python selection/parser; no network or production pin changes."""
import base64,json,struct,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from wlre.services.world.portrait_mapping import CHARACTERS,parse_npc_portraits
from wlre.services.world.character_portraits import select_portrait

def row(ident,icon,kind,palettes):
    f=bytearray(203);struct.pack_into('<H',f,1,ident);f[5]=kind;struct.pack_into('<H',f,6,icon);struct.pack_into('<4I',f,8,*palettes)
    return b'\0\0\0\0'+f
raw=struct.pack('<I',3)+row(7000,7000,0,[444444444,123456789,0,999999999])+row(7001,71,2,[1,2,3,4])+row(7002,0,0,[0]*4)
# Explicit synthetic reference seam only. C# production must reject this same raw input.
with patch('wlre.services.world.portrait_mapping.NPC_SHA256',hashlib.sha256(raw).hexdigest()):
    npcs=parse_npc_portraits(raw)
catalog=SimpleNamespace(characters=CHARACTERS,npcs=npcs)
cases=[]
for sex in range(6):
 for head in range(10):
    state={'player':{'role_id':1,'sex':sex,'head':head,'palette1':123456789,'palette5':987654321}}
    cases.append({'sex':sex,'head':head,'expected':select_portrait(state,'player',catalog)})
result={'raw':base64.b64encode(raw).decode(),'npcs':npcs,'players':cases,'source':'actual Python parser (owned digest seam) and select_portrait; no official acceptance'}
Path(__file__).with_name('mapping.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
