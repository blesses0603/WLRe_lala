"""Whole Texture2D RGBA evidence from UnityPy 1.25.4, no Sprite identities."""
from pathlib import Path
import base64,hashlib,json,struct
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node,get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree,write_value,TypeTreeConfig
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__=='1.25.4'
v=UnityVersion.from_str('2021.3.45f2');root=get_typetree_node(28,v);tpk=get_typetree();raw=[]
def walk(i):
 n=tpk.NodeBuffer[i];raw.append(n)
 for c in n.SubNodes:walk(c)
walk(tpk.ClassInformation[28].getVersionedClass(v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):n.m_TypeFlags=r.TypeFlags;n.m_RefTypeHash=0;n.m_Index=i

def defaults(n):
 if n.m_Type=='string':return ''
 if n.m_Type=='TypelessData':return b''
 if n.m_Children and n.m_Children[0].m_Type=='Array':return []
 if n.m_Children:return {c.m_Name:defaults(c) for c in n.m_Children}
 return False if n.m_Type=='bool' else 0

def make(width,height,fmt,seed):
 length=width*height*4 if fmt==4 else ((width+3)//4)*((height+3)//4)*(8 if fmt==10 else 16)
 payload=bytes((i*37+seed*19+11)%256 for i in range(length))
 d=defaults(root);d.update(m_Name='Avatar2DNPC_7213',m_Width=width,m_Height=height,m_CompleteImageSize=length,m_TextureFormat=fmt,m_MipCount=1,m_ImageCount=1,m_TextureDimension=2,m_ColorSpace=1)
 d['image data']=payload
 w=EndianBinaryWriter(endian='<');write_typetree(d,root,w);body=w.bytes
 p=lambda fmt,*a:struct.pack('<'+fmt,*a)
 def align(b,n=4):return b+bytes((-len(b))%n)
 w=EndianBinaryWriter(endian='<');root.dump_blob(w,22)
 meta=b'2021.3.45f2\0'+p('iBi',19,1,1)+p('iBh',28,0,-1)+bytes(16)+w.bytes+p('ii',0,1)
 meta=align(meta)+p('qqIi',7213,0,len(body),0)+p('iii',0,0,0)+b'\0';offset=len(align(bytes(48)+meta,16))
 asset=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(body),offset,0)+meta
 asset=align(asset,16)+body
 obj=next(iter(UnityPy.load(asset).objects));pixels=obj.read().image.convert('RGBA').tobytes()
 return d,body,hashlib.sha256(pixels).hexdigest()
rows=[]
for w,h in ((4,3),(5,7),(256,256),(1024,1024)):
 for fmt in (4,10,12):
  seed=fmt+w%13;d,b,sha=make(w,h,fmt,seed);rows.append(dict(width=w,height=h,format=fmt,seed=seed,sha256=sha))
d,body,sha=make(256,256,10,7);offsets={};w=EndianBinaryWriter(endian='<')
for child in root.m_Children:
 offsets[child.m_Name]=w.Position;write_value(d[child.m_Name],child,w,TypeTreeConfig(True,None,False))
assert w.bytes==body
out={'writer':'UnityPy 1.25.4 Texture2D.image on owned SerializedFile22', 'vectors':rows,'texture':base64.b64encode(body).decode(),'texture_sha256':sha,'offsets':offsets}
Path(__file__).with_name('textures.json').write_text(json.dumps(out,indent=2)+'\n')
print(len(rows),'whole texture vectors; raw fixture',len(body),'bytes')
