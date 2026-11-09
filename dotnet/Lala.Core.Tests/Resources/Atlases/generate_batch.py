"""Owned mapping and images through the real Python emoji build_catalog."""
import base64,hashlib,json,struct,sys
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
from wlre.services.world import emoji_database as emoji
raw=struct.pack('<I',3)+b''.join(struct.pack('<BBBIB',*r) for r in [(1,255,1,100,0),(2,0,2,200,1),(1,0,1,300,0)])
images={f'Emoji_{i:03}_1':Image.frombytes('RGBA',(3,5),bytes((n*37+i)%256 for n in range(60))) for i in (1,2)}
with patch.object(emoji,'KNOWN_SHA256',hashlib.sha256(raw).hexdigest()):catalog=emoji.build_catalog(raw,lambda:list(images.items())+[('unused',Image.new('RGBA',(1,1)))])
out={'raw':base64.b64encode(raw).decode(),'images':{k:{'width':v.width,'height':v.height,'pixels':base64.b64encode(v.tobytes()).decode()} for k,v in images.items()},'tokens':{k:{'frame':catalog['entries'][k]['sprite']+'_1','show':catalog['entries'][k]['show_in_list'],'pixels':v['pixels']} for k,v in catalog['images'].items()}}
Path(__file__).with_name('batch.json').write_text(json.dumps(out,indent=2)+'\n');print('Python build_catalog owned token/image oracle')
