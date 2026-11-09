"""Owned SpriteAtlas fixtures. Pinned UnityPy real writer; not official game data."""
from pathlib import Path
import base64,copy,hashlib,json,struct
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node,get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__=='1.25.4'
v=UnityVersion.from_str('2021.3.45f2'); cid=687078895; tpk=get_typetree(); root=get_typetree_node(cid,v); raw=[]
def walk(i):
 n=tpk.NodeBuffer[i];raw.append(n)
 for c in n.SubNodes:walk(c)
walk(tpk.ClassInformation[cid].getVersionedClass(v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):
 assert n.m_Type==tpk.StringBuffer[r.TypeName] and n.m_Name==tpk.StringBuffer[r.Name]
 n.m_TypeFlags=r.TypeFlags;n.m_RefTypeHash=0;n.m_Index=i

def defaults(n):
 if n.m_Type=='string':return ''
 if n.m_Children and n.m_Children[0].m_Type=='Array':return []
 if n.m_Type=='pair':return tuple(defaults(c) for c in n.m_Children)
 if n.m_Children:return {c.m_Name:defaults(c) for c in n.m_Children}
 return False if n.m_Type=='bool' else 0

def encode(d):
 w=EndianBinaryWriter(endian='<');write_typetree(d,root,w);return w.bytes
ptr=lambda f,p:{'m_FileID':f,'m_PathID':p}
data=defaults(root);data.update(m_Name='OwnedEmojiAtlas',m_PackedSprites=[ptr(0,2),ptr(1,-3)],m_PackedSpriteNamesToIndex=['Emoji_001_1','Emoji_002_1'],m_Tag='OwnedEmoji')
node=next(n for n in root.traverse() if n.m_Type=='SpriteAtlasData')
def entry(i):
 d=defaults(node);d.update(texture=ptr(1,100+i),textureRect={'x':float(i*4),'y':2.,'width':32.,'height':24.},textureRectOffset={'x':1.,'y':2.},atlasRectOffset={'x':3.,'y':4.},uvTransform={'x':5.,'y':6.,'z':7.,'w':8.},downscaleMultiplier=1.,settingsRaw=3)
 return (({f'data[{j}]':i*4+j for j in range(4)},-100-i),d)
data['m_RenderDataMap']=[entry(1),entry(2)]
p=lambda fmt,*x:struct.pack('<'+fmt,*x)
align=lambda b,n=4:b+bytes((-len(b))%n)
w=EndianBinaryWriter(endian='<');root.dump_blob(w,22);body=encode(data)
meta=b'2021.3.45f2\0'+p('iBi',19,1,1)+p('iBh',cid,0,-1)+bytes(16)+w.bytes+p('ii',0,1)
meta=align(meta)+p('qqIi',1,0,len(body),0)+p('ii',0,1)+b'\0'+bytes(16)+p('i',0)+b'CAB-owned-external\0'+p('i',0)+b'\0'
offset=len(align(bytes(48)+meta,16))
asset=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(body),offset,0)+meta
asset=next(iter(UnityPy.load(align(asset,16)+body).files.values())).save()
read=next(iter(UnityPy.load(asset).objects)).read_typetree()
assert read==data
assert next(iter(UnityPy.load(asset).files.values())).save()==asset
cases=[]
def case(name,change,ok=False):
 d=copy.deepcopy(data);change(d);cases.append({'name':name,'bytes':base64.b64encode(encode(d)).decode(),'ok':ok})
case('owned-two-entries',lambda d:None,True)
case('duplicate-sprite',lambda d:d['m_PackedSprites'].append(d['m_PackedSprites'][0]))
case('negative-file',lambda d:d['m_PackedSprites'][0].update(m_FileID=-1))
case('null-sprite',lambda d:d['m_PackedSprites'][0].update(m_PathID=0))
case('empty-sprites',lambda d:d.update(m_PackedSprites=[]))
case('duplicate-name',lambda d:d['m_PackedSpriteNamesToIndex'].append(d['m_PackedSpriteNamesToIndex'][0]))
case('duplicate-key',lambda d:d['m_RenderDataMap'].append(d['m_RenderDataMap'][0]))
case('missing-texture',lambda d:d['m_RenderDataMap'][0][1].update(texture=ptr(0,0)))
case('external-null-alpha',lambda d:d['m_RenderDataMap'][0][1].update(alphaTexture=ptr(1,0)))
case('nonfinite-rect',lambda d:d['m_RenderDataMap'][0][1]['textureRect'].update(x=float('nan')))
case('nonfinite-uv',lambda d:d['m_RenderDataMap'][0][1]['uvTransform'].update(w=float('inf')))
case('zero-downscale',lambda d:d['m_RenderDataMap'][0][1].update(downscaleMultiplier=0.))
case('empty-rect',lambda d:d['m_RenderDataMap'][0][1]['textureRect'].update(width=0.))
case('secondary-texture',lambda d:d['m_RenderDataMap'][0][1].update(secondaryTextures=[{'texture':ptr(0,4),'name':'extra'}]))
case('variant',lambda d:d.update(m_IsVariant=True))
case('separate-alpha-retained',lambda d:d['m_RenderDataMap'][0][1].update(alphaTexture=ptr(1,202)),True)
canonical=''.join(f'{n.m_Level}|{n.m_Type}|{n.m_Name}|{n.m_ByteSize}|{int(n.m_TypeFlags==1)}|{int(bool(n.m_MetaFlag&0x4000))}\n' for n in root.traverse())
out={'writer':'UnityPy 1.25.4 write_typetree + SerializedFile.save + read_typetree; owned data only','tpk_sha256':hashlib.sha256((Path(UnityPy.__file__).parent/'resources/lzma.tpk').read_bytes()).hexdigest(),'shape_sha256':hashlib.sha256(canonical.encode()).hexdigest(),'node_count':len(raw),'asset':base64.b64encode(asset).decode(),'cases':cases}
Path(__file__).with_name('atlases.json').write_text(json.dumps(out,indent=2)+'\n')
print(out['shape_sha256'],len(raw),len(cases))
