"""Owned class28/213 fixtures, UnityPy 1.25.4 TPK release schema + real writer.
Not official game data; schema source recorded with package hash. No runtime TPK dependency.
"""
from pathlib import Path
import importlib.util, json, struct, hashlib
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node, get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree, write_value, TypeTreeConfig
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__ == '1.25.4'
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('owned',HERE.parent/'UnityTextAssets'/'generate_fixtures.py')
old=importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
p,align,string=old.p,old.align,old.string
ASSET='Assets/ResourcesBuild/Sprite/Sprite_Item/s1000.png'
nodes={cid:get_typetree_node(cid,UnityVersion.from_str('2021.3.45f2')) for cid in (28,213)}
def defaults(node):
    if node.m_Type=='string': return ''
    if node.m_Type=='TypelessData': return b''
    if node.m_Children and node.m_Children[0].m_Type=='Array': return []
    if node.m_Type=='pair': return tuple(defaults(n) for n in node.m_Children)
    if node.m_Children: return {n.m_Name:defaults(n) for n in node.m_Children}
    return False if node.m_Type=='bool' else 0
# UnityPy get_typetree_node omits TPK TypeFlags; retain the original flags directly.
tpk=get_typetree()
for cid,root in nodes.items():
    cls=tpk.ClassInformation[cid].getVersionedClass(UnityVersion.from_str('2021.3.45f2'))
    raw_nodes=[]
    def walk(index):
        node=tpk.NodeBuffer[index]; raw_nodes.append(node)
        for child in node.SubNodes: walk(child)
    walk(cls.ReleaseRootNode)
    assert len(raw_nodes)==len(list(root.traverse()))
    for i,(n,original) in enumerate(zip(root.traverse(),raw_nodes)):
        assert n.m_Type==tpk.StringBuffer[original.TypeName] and n.m_Name==tpk.StringBuffer[original.Name]
        n.m_TypeFlags=original.TypeFlags
        n.m_RefTypeHash=0
        n.m_Index=i

def blob(root):
    w=EndianBinaryWriter(endian='<'); root.dump_blob(w,22); return w.bytes

def body(cid,values):
    w=EndianBinaryWriter(endian='<'); write_typetree(values,nodes[cid],w); return w.bytes
texture=defaults(nodes[28]); texture.update(m_Name='s1000',m_Width=4,m_Height=3,m_CompleteImageSize=48,
    m_TextureFormat=4,m_MipCount=1,m_ImageCount=1,m_TextureDimension=2)
texture['image data']=bytes((i*37+11)%256 for i in range(48))
sprite=defaults(nodes[213]); sprite.update(m_Name='s1000',m_PixelsToUnits=100)
sprite['m_Rect'].update(x=0,y=0,width=2,height=3)
sprite['m_RD']['texture'].update(m_FileID=0,m_PathID=3)
sprite['m_RD']['textureRect'].update(x=1,y=0,width=2,height=3)
sprite['m_RD'].update(settingsRaw=2,downscaleMultiplier=1)
def make(sprite=sprite,texture=texture,entries=((0,2),(0,3))):
    container=string('owned')+p('i',0)+p('i',len(entries))
    for fileid,pathid in entries: container+=string(ASSET)+p('iiiq',0,0,fileid,pathid)
    container+=p('iiiq',0,0,0,0)+p('I',0)+string('owned')+p('i',0)+p('i',0)+p('ii',0,0)+p('i',0)
    bodies=[container,body(213,sprite),body(28,texture)]
    meta=b'2021.3.45f2\0'+p('iB',19,1)+p('i',3)
    for cid,tree in [(142,old.tree(old.BUNDLE)),(213,blob(nodes[213])),(28,blob(nodes[28]))]:
        meta+=p('iBh',cid,0,-1)+bytes(16)+tree+p('i',0)
    meta+=p('i',3); data=b''
    for i,b in enumerate(bodies):
        data=align(data,8); meta=align(meta)+p('qqIi',i+1,len(data),len(b),i); data+=b
    meta+=p('iii',0,0,0)+b'\0'; offset=len(align(bytes(48)+meta,16))
    raw=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(data),offset,0)+meta
    raw=align(raw,16)+data
    file=next(iter(UnityPy.load(raw).files.values())); saved=file.save()
    assert next(iter(UnityPy.load(saved).files.values())).save()==saved
    return saved
out=HERE/'SerializedFixtures'; out.mkdir(exist_ok=True)
raw=make(); (out/'owned.assets').write_bytes(raw)
bundle=old.bundle(raw); (out/'owned.bundle').write_bytes(bundle)
for name,entries in [('sprite-only.assets',((0,2),)),('texture-only.assets',((0,3),)),('reversed.assets',((0,3),(0,2)))]:
    (out/name).write_bytes(make(entries=entries))
env=UnityPy.load(bundle); sprite_obj=next(o for o in env.objects if o.type.name=='Sprite').read()
assert sprite_obj.m_RD.texture.path_id==3
pixels=sprite_obj.image.convert('RGBA').tobytes()
shapes={}
for cid,root in nodes.items():
    canonical=''.join(f'{n.m_Level}|{n.m_Type}|{n.m_Name}|{n.m_ByteSize}|{int(n.m_TypeFlags==1)}|{int(bool(n.m_MetaFlag & 0x4000))}\n' for n in root.traverse())
    shapes[str(cid)]={'nodes':len(list(root.traverse())),'sha256':hashlib.sha256(canonical.encode()).hexdigest()}
evidence={'writer':'UnityPy 1.25.4 SerializedFile.save + Texture2DConverter/SpriteHelper', 'schema':'UnityPy 1.25.4 bundled TPK 2021.3.45f2 release',
    'tpk_sha256':hashlib.sha256((Path(UnityPy.__file__).parent/'resources'/'lzma.tpk').read_bytes()).hexdigest(),
    'shapes':shapes,'asset_path':ASSET,'pixels_hex':pixels.hex(),'pixel_sha256':hashlib.sha256(pixels).hexdigest(),
    'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted([*out.glob('*.assets'),out/'owned.bundle'])}}
(out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps(evidence,indent=2))

# Mutation locations come from the independent writer, not hand-counted object offsets.
def field_layout(cid, values):
    w=EndianBinaryWriter(endian='<'); offsets={}
    for child in nodes[cid].m_Children:
        offsets[child.m_Name]=w.Position
        write_value(values[child.m_Name],child,w,TypeTreeConfig(True,None,False))
    assert w.bytes == body(cid,values)
    return offsets
objects={o.path_id:o for o in UnityPy.load(raw).objects}
t,s=field_layout(28,texture),field_layout(213,sprite)
starts={str(i):objects[i].byte_start for i in (1,2,3)}
container=starts['1']; second=container+20+len(string(ASSET))+20
layout={
 'texture-width':starts['3']+t['m_Width'], 'texture-complete':starts['3']+t['m_CompleteImageSize'],
 'texture-format':starts['3']+t['m_TextureFormat'], 'texture-mips':starts['3']+t['m_MipCount'],
 'sprite-external':starts['2']+s['m_RD'], 'sprite-missing':starts['2']+s['m_RD']+4,
 'sprite-wrong-class':starts['2']+s['m_RD']+4, 'sprite-name':starts['2']+4,
 'pair-duplicate':second+len(string(ASSET))+12, 'pair-external':second+len(string(ASSET))+8,
 'pair-missing':second+len(string(ASSET))+12,
}
assert struct.unpack_from('<i',raw,layout['texture-width'])[0]==4
assert struct.unpack_from('<q',raw,layout['sprite-missing'])[0]==3
assert struct.unpack_from('<q',raw,layout['pair-duplicate'])[0]==3
(out/'layout.json').write_text(json.dumps(layout,indent=2)+'\n')
