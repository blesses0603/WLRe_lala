"""Owned 1024 Texture2D stream fixtures; independent UnityPy 1.25.4 pixel oracle."""
from pathlib import Path
import base64,hashlib,json,struct
import UnityPy,lz4.block
from UnityPy.helpers.Tpk import get_typetree_node,get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__=='1.25.4'
# Reuse only declarations; do not execute existing fixture-generation loops.
path=Path(__file__).parent.parent/'UnityTextAssets/generate_fixtures.py'
ns={'__file__':str(path)};exec(path.read_text().split('def serialized(')[0],ns)
p,align,string,tree,BUNDLE=(ns[k] for k in ('p','align','string','tree','BUNDLE'))
v=UnityVersion.from_str('2021.3.45f2');tpk=get_typetree();root=get_typetree_node(28,v);raw=[]
def walk(i):
 n=tpk.NodeBuffer[i];raw.append(n)
 for c in n.SubNodes:walk(c)
walk(tpk.ClassInformation[28].getVersionedClass(v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):
 n.m_TypeFlags=r.TypeFlags;n.m_RefTypeHash=0;n.m_Index=i

def defaults(n):
 if n.m_Type=='string':return ''
 if n.m_Type=='TypelessData':return b''
 if n.m_Children and n.m_Children[0].m_Type=='Array':return []
 if n.m_Type=='pair':return tuple(defaults(c) for c in n.m_Children)
 if n.m_Children:return {c.m_Name:defaults(c) for c in n.m_Children}
 return False if n.m_Type=='bool' else 0
ASSET='Assets/ResourcesBuild/Texture/SmallMap2D/SmallMap2D_10001.png'
def make(fmt,width=1024,color=1,models=1):
 size=width*1024*4 if fmt==4 else ((width+3)//4)*256*(8 if fmt==10 else 16)
 payload=bytes((i*37+17)%256 for i in range(size))
 d=defaults(root);d.update(m_Name='SmallMap2D_10001',m_Width=width,m_Height=1024,m_CompleteImageSize=size,m_TextureFormat=fmt,m_MipCount=1,m_ImageCount=1,m_TextureDimension=2,m_ColorSpace=color)
 d['m_StreamData']={'offset':7,'size':size,'path':'archive:/CAB-owned/CAB-owned.resS'}
 w=EndianBinaryWriter(endian='<');write_typetree(d,root,w);texture=w.bytes
 container=string('owned')+p('i',0)+p('i',models)+b''.join(string(ASSET.replace('10001',str(10001+i)))+p('iiiq',0,0,0,2) for i in range(models))+p('iiiq',0,0,0,0)+p('I',0)+string('owned')+p('i',0)+p('i',0)+p('ii',0,0)+p('i',0)
 tw=EndianBinaryWriter(endian='<');root.dump_blob(tw,22)
 meta=b'2021.3.45f2\0'+p('iBi',19,1,2)
 for cid,tr in ((142,tree(BUNDLE)),(28,tw.bytes)):meta+=p('iBh',cid,0,-1)+bytes(16)+tr+p('i',0)
 data=align(container,8)+texture;meta+=p('i',2)
 for i,offset,length,typ in ((1,0,len(container),0),(2,len(align(container,8)),len(texture),1)):meta=align(meta)+p('qqIi',i,offset,length,typ)
 meta+=p('iii',0,0,0)+b'\0';offset=len(align(bytes(48)+meta,16))
 serial=align(struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(data),offset,0)+meta,16)+data
 serial=next(iter(UnityPy.load(serial).files.values())).save()
 resource=b'prefix!'+payload;expanded=serial+resource;chunks=[expanded[i:i+65536] for i in range(0,len(expanded),65536)];parts=[lz4.block.compress(x,store_size=False) for x in chunks]
 info=bytes(16)+struct.pack('>i',len(parts))
 for a,b in zip(chunks,parts):info+=struct.pack('>IIH',len(a),len(b),3)
 info+=struct.pack('>iqqI',2,0,len(serial),4)+b'CAB-owned\0'+struct.pack('>qqI',len(serial),len(resource),0)+b'CAB-owned.resS\0'
 packed=lz4.block.compress(info,store_size=False);header=b'UnityFS\0'+struct.pack('>I',8)+b'5.x.x\0'+b'2021.3.45f2\0';length=(len(header)+20+15)//16*16
 header+=struct.pack('>qIII',length+len(packed)+sum(map(len,parts)),len(packed),len(info),67)
 bundle=align(header,16)+packed+b''.join(parts);env=UnityPy.load(bundle);image=env.container[ASSET].read().image.convert('RGBA')
 assert image.size==(width,1024)
 return {'models':models,'format':fmt,'width':width,'color':color,'bytes':base64.b64encode(bundle).decode(),'pixels':hashlib.sha256(image.tobytes()).hexdigest()}
rows=[make(f) for f in (4,10,12)]+[make(4,1023),make(4,color=0),make(10,models=2)]
Path(__file__).with_name('smallmaps.json').write_text(json.dumps({'oracle':'UnityPy 1.25.4 Texture2D.image, owned repeating pixels','cases':rows},indent=2)+'\n')
print('6 owned smallmap bundles with independent complete RGBA hashes')
