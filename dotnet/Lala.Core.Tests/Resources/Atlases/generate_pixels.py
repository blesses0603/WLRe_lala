"""Owned complete atlas/Sprite/Texture files, decoded by real UnityPy SpriteHelper."""
from pathlib import Path
import base64,hashlib,json,struct
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node,get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree,write_value,TypeTreeConfig
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__=='1.25.4'
v=UnityVersion.from_str('2021.3.45f2');tpk=get_typetree();classes=[687078895,213,28];roots={}
for cid in classes:
 root=get_typetree_node(cid,v);raw=[]
 def walk(i):
  n=tpk.NodeBuffer[i];raw.append(n)
  for c in n.SubNodes:walk(c)
 walk(tpk.ClassInformation[cid].getVersionedClass(v).ReleaseRootNode)
 for i,(n,r) in enumerate(zip(root.traverse(),raw)):
  assert n.m_Type==tpk.StringBuffer[r.TypeName] and n.m_Name==tpk.StringBuffer[r.Name]
  n.m_TypeFlags=r.TypeFlags;n.m_RefTypeHash=0;n.m_Index=i
 roots[cid]=root

def defaults(n):
 if n.m_Type=='string':return ''
 if n.m_Type=='TypelessData':return b''
 if n.m_Children and n.m_Children[0].m_Type=='Array':return []
 if n.m_Type=='pair':return tuple(defaults(c) for c in n.m_Children)
 if n.m_Children:return {c.m_Name:defaults(c) for c in n.m_Children}
 return False if n.m_Type=='bool' else 0
p=lambda fmt,*a:struct.pack('<'+fmt,*a)
align=lambda b,n=4:b+bytes((-len(b))%n)
ptr=lambda i:{'m_FileID':0,'m_PathID':i}
key=({f'data[{j}]':j+11 for j in range(4)},-902)
def encode(cid,d):
 w=EndianBinaryWriter(endian='<');write_typetree(d,roots[cid],w);return w.bytes

def file(bodies):
 meta=b'2021.3.45f2\0'+p('iBi',19,1,3)
 for cid in classes:
  w=EndianBinaryWriter(endian='<');roots[cid].dump_blob(w,22)
  meta+=p('iBh',cid,0,-1)+bytes(16)+w.bytes+p('i',0)
 meta+=p('i',len(bodies));data=b''
 for index,(cid,b) in enumerate(bodies,1):
  data=align(data,8);meta=align(meta)+p('qqIi',index,len(data),len(b),classes.index(cid));data+=b
 meta+=p('iii',0,0,0)+b'\0';offset=len(align(bytes(48)+meta,16))
 result=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(data),offset,0)+meta
 return next(iter(UnityPy.load(align(result,16)+data).files.values())).save()

def texture(fmt,seed):
 d=defaults(roots[28]);size=9*7*4 if fmt==4 else 3*2*(8 if fmt==10 else 16)
 d.update(m_Name='OwnedTexture',m_Width=9,m_Height=7,m_CompleteImageSize=size,m_TextureFormat=fmt,m_MipCount=1,m_ImageCount=1,m_TextureDimension=2,m_ColorSpace=1)
 d['image data']=bytes((i*37+seed)%256 for i in range(size));return d
rows=[];base=None;offsets={}
for extended in (False,True):
 for fmt in (4,10,12):
  for rotation in range(5):
   for alpha in (False,True):
    atlas=defaults(roots[687078895]);atlas.update(m_Name='OwnedAtlas',m_PackedSprites=[ptr(2)],m_PackedSpriteNamesToIndex=['Emoji_001_1'],m_Tag='Owned')
    entry=defaults(next(n for n in roots[687078895].traverse() if n.m_Type=='SpriteAtlasData'))
    entry.update(texture=ptr(3),alphaTexture=ptr(4 if alpha else 0),textureRect={'x':2.,'y':1.,'width':3.,'height':5.},downscaleMultiplier=1.,settingsRaw=3+(rotation<<2)+(64 if extended else 0))
    atlas['m_RenderDataMap']=[(key,entry)]
    sprite=defaults(roots[213]);sprite.update(m_Name='Emoji_001_1',m_PixelsToUnits=100.,m_RenderDataKey=key,m_SpriteAtlas=ptr(1),m_AtlasTags=['Owned'])
    sprite['m_Rect'].update(width=5. if rotation==4 else 3.,height=3. if rotation==4 else 5.)
    if extended:
     sprite['m_Rect']['width']+=7;sprite['m_Rect']['height']+=9
     sprite['m_PhysicsShape']=[[{'x':-1.,'y':0.},{'x':2.,'y':3.},{'x':0.,'y':1.}]]
    bodies=[(687078895,encode(687078895,atlas)),(213,encode(213,sprite)),(28,encode(28,texture(fmt,17)))]
    if alpha:bodies.append((28,encode(28,texture(4,91))))
    asset=file(bodies);env=UnityPy.load(asset);obj=next(o for o in env.objects if o.path_id==2)
    image=obj.read().image.convert('RGBA');pixels=image.tobytes()
    assert image.size==((5,3) if rotation==4 else (3,5))
    if base is None:
     base=asset
     for cid,values in ((687078895,atlas),(213,sprite)):
      writer=EndianBinaryWriter(endian='<');fields={}
      for node in roots[cid].m_Children:
       fields[node.m_Name]=writer.Position;write_value(values[node.m_Name],node,writer,TypeTreeConfig(True,None,False))
      assert writer.bytes==encode(cid,values)
      offsets[str(cid)]=fields
    rows.append({'format':fmt,'rotation':rotation,'alpha':alpha,'objects':[{'class':c,'bytes':base64.b64encode(b).decode()} for c,b in bodies], 'width':image.width,'height':image.height,'pixels':base64.b64encode(pixels).decode(),'sha256':hashlib.sha256(pixels).hexdigest()})
out={'oracle':'UnityPy 1.25.4 real SerializedFile Sprite.image / SpriteHelper, non-square owned texture crop', 'asset':base64.b64encode(base).decode(),'offsets':offsets,'cases':rows}
Path(__file__).with_name('pixels.json').write_text(json.dumps(out,indent=2)+'\n')
print(len(rows),'independent atlas pixel cases')
