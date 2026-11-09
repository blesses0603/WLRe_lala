"""Owned UnityFS CAB/resS fixtures, checked with independent UnityPy/LZ4 readers."""
import base64,importlib.util,json,struct
from pathlib import Path
import UnityPy,lz4.block
spec=importlib.util.spec_from_file_location('owned',Path(__file__).parent.parent/'UnityTextAssets/generate_fixtures.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def make(resource,compression=3,name='CAB-owned.resS',flags=0,raw=None):
 raw=m.serialized() if raw is None else raw;data=raw+resource;chunks=[data[i:i+65536] for i in range(0,len(data),65536)]
 enc=lambda x:x if compression==0 else lz4.block.compress(x,store_size=False)
 parts=[enc(c) for c in chunks];info=bytes(16)+struct.pack('>i',len(chunks))
 for a,b in zip(chunks,parts):info+=struct.pack('>IIH',len(a),len(b),compression)
 info+=struct.pack('>iqqI',2,0,len(raw),4)+b'CAB-owned\0'+struct.pack('>qqI',len(raw),len(resource),flags)+name.encode()+b'\0'
 packed=enc(info);header=b'UnityFS\0'+struct.pack('>I',8)+b'5.x.x\0'+b'2021.3.45f2\0';length=(len(header)+20+15)//16*16
 header+=struct.pack('>qIII',length+len(packed)+sum(map(len,parts)),len(packed),len(info),64|compression)
 return m.align(header,16)+packed+b''.join(parts)
rows=[];payload=bytes(range(256))*4
for c in (0,2,3):
 b=make(payload,c);env=UnityPy.load(b);bundle=next(iter(env.files.values()));reader=bundle.files['CAB-owned.resS'];reader.Position=0;assert reader.read_bytes(len(payload))==payload
 rows.append({'compression':c,'bytes':base64.b64encode(b).decode()})
# Large compressed owned fixture verifies the opt-in 96 MiB bound without shipping large raw files.
large=make(bytes(64*1024*1024));over=make(bytes(96*1024*1024))
spec2=importlib.util.spec_from_file_location('pixels',Path(__file__).with_name('generate_pixels.py'));px=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(px)
pixelrows=[]
for row in px.rows[30:]:
 bodies=[];resource=b'prefix!'
 for item in row['objects']:
  cid=item['class'];body=base64.b64decode(item['bytes'])
  if cid==28:
   from UnityPy.helpers.TypeTreeHelper import read_typetree
   from UnityPy.streams import EndianBinaryReader
   d=read_typetree(px.roots[cid],EndianBinaryReader(body,endian='<'),byte_size=len(body))
   data=d['image data'];d['image data']=b'';d['m_StreamData']={'offset':len(resource),'size':len(data),'path':'archive:/CAB-owned/CAB-owned.resS'}
   resource+=data;body=px.encode(cid,d)
  bodies.append((cid,body))
 b=make(resource,raw=px.file(bodies));env=UnityPy.load(b);sprite=next(o for o in env.objects if o.type.name=='Sprite').read();image=sprite.image.convert('RGBA');assert image.tobytes()==base64.b64decode(row['pixels'])
 pixelrows.append({'bytes':base64.b64encode(b).decode(),'width':image.width,'height':image.height,'pixels':row['pixels']})
out={'pixels':pixelrows,'cases':rows,'large':base64.b64encode(large).decode(),'over':base64.b64encode(over).decode(),'unpaired':base64.b64encode(make(payload,name='CAB-other.resS')).decode(),'flags':base64.b64encode(make(payload,flags=1)).decode()}
Path(__file__).with_name('streams.json').write_text(json.dumps(out,indent=2)+'\n')
print('3 independent resource fixtures; owned size/flags/pairing boundary vectors')
