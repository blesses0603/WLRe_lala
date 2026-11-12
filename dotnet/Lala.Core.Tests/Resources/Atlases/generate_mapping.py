"""Actual Python EmojiData parser with an explicit owned-fixture hash seam only."""
from pathlib import Path
import base64,hashlib,json,struct,importlib.util
from unittest.mock import patch
from wlre.services.world.emoji_database import parse_entries,KNOWN_SHA256
cases=[]
def case(name,rows):
 raw=struct.pack('<I',len(rows))+b''.join(struct.pack('<BBBIB',*r) for r in rows)
 with patch('wlre.services.world.emoji_database.KNOWN_SHA256',hashlib.sha256(raw).hexdigest()):
  try:expected=parse_entries(raw)
  except ValueError:expected=None
 cases.append(dict(name=name,raw=base64.b64encode(raw).decode(),expected=expected))
case('row-not-id',[(17,9,7,100,0),(3,0,2,200,1),(17,255,7,4294967295,0)])
case('single',[(255,255,255,1,1)])
case('max-count',[(1,0,1,1,i%2) for i in range(255)])
case('empty',[])
case('too-many',[(1,0,1,1,0)]*256)
for label,index in [('zero-id',0),('zero-icon',2),('zero-text',3)]:
 row=[1,0,1,1,0];row[index]=0;case(label,[row])
case('bad-hidden',[(1,0,1,1,2)])
spec=importlib.util.spec_from_file_location('owned_text',Path(__file__).parent.parent/'UnityTextAssets/generate_fixtures.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
helper.PATH='Assets/ResourcesBuild/Data/EmojiData_C.bytes'
bundle=helper.bundle(helper.serialized(name='EmojiData_C',script=base64.b64decode(cases[0]['raw'])))
out={'bundle':base64.b64encode(bundle).decode(),'oracle':'Actual Python emoji_database.parse_entries; owned digest seam only, C# production must reject all fixtures','production_pin':KNOWN_SHA256,'cases':cases}
Path(__file__).with_name('mapping.json').write_text(json.dumps(out,indent=2)+'\n')
print(len(cases),'Python mapping cases')
