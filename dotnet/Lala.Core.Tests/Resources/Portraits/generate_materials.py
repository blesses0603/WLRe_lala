"""Owned Material fixtures using UnityPy 1.25.4's real writer and release TPK.
No official bytes or modified SHA pins. Run with the pinned reference on PYTHONPATH.
"""
from pathlib import Path
import base64, copy, hashlib, json, struct
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node, get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__ == '1.25.4'
v=UnityVersion.from_str('2021.3.45f2'); tpk=get_typetree(); root=get_typetree_node(21,v); raw=[]
def walk(i):
    node=tpk.NodeBuffer[i]; raw.append(node)
    for child in node.SubNodes: walk(child)
walk(tpk.ClassInformation[21].getVersionedClass(v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):
    assert n.m_Type==tpk.StringBuffer[r.TypeName] and n.m_Name==tpk.StringBuffer[r.Name]
    n.m_TypeFlags=r.TypeFlags; n.m_RefTypeHash=0; n.m_Index=i

def defaults(n):
    if n.m_Type=='string': return ''
    if n.m_Children and n.m_Children[0].m_Type=='Array': return []
    if n.m_Type=='pair': return tuple(defaults(c) for c in n.m_Children)
    if n.m_Children: return {c.m_Name:defaults(c) for c in n.m_Children}
    return False if n.m_Type=='bool' else 0

def encode(data):
    w=EndianBinaryWriter(endian='<'); write_typetree(data,root,w); return w.bytes
parts=['_1_0_c_Color','_1_1_HairColor','_1_2_SkinColor','_2_0_e_Color0','_2_1_e_Color1','_2_2_e_Color2','_3_0_e_Color3','_3_1_e_Color4','_4_2_a_Color','_3_2_s_Color','_4_0_w_Color0','_4_1_w_Color1','_5_0_p_Color','_13_EyeColor_']
data=defaults(root); data.update(m_Name='PhotoAvatarNPC_7214',m_Shader={'m_FileID':2,'m_PathID':-1215708881511709531},m_CustomRenderQueue=-1)
def env(fid,pid):return {'m_Texture':{'m_FileID':fid,'m_PathID':pid},'m_Scale':{'x':1.,'y':1.},'m_Offset':{'x':0.,'y':0.}}
data['m_SavedProperties'].update(m_TexEnvs=[('_ColorTextures',env(1,7213)),('_ColorMask1',env(0,0))],
 m_Floats=[('_UseShapeMask',0.),('_EdgeLength',0.),('_MaskClip',.06)],
 m_Colors=[(p,{'r':float(i%10),'g':4.,'b':6.,'a':1.}) for i,p in enumerate(parts)])
# Serialize a genuine SerializedFile22 with this embedded type tree, then round-trip with UnityPy.
p=lambda fmt,*values:struct.pack('<'+fmt,*values)
def align(b,n=4):return b+bytes((-len(b))%n)
w=EndianBinaryWriter(endian='<');root.dump_blob(w,22)
body=encode(data);meta=b'2021.3.45f2\0'+p('iBi',19,1,1)+p('iBh',21,0,-1)+bytes(16)+w.bytes+p('ii',0,1)
meta=align(meta)+p('qqIi',1,0,len(body),0)+p('ii',0,2)
for name in ('CAB-owned-texture','CAB-owned-shader'):meta+=b'\0'+bytes(16)+p('i',0)+name.encode()+b'\0'
meta+=p('i',0)+b'\0';offset=len(align(bytes(48)+meta,16))
file=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(body),offset,0)+meta
file=align(file,16)+body
asset=next(iter(UnityPy.load(file).files.values())).save()
obj=next(iter(UnityPy.load(asset).objects)); read=obj.read_typetree()
assert read['m_SavedProperties']['m_TexEnvs'][0][1]['m_Texture']['m_PathID']==7213
cases=[]
def case(name,mutate,read_ok=True,project_ok=False):
    d=copy.deepcopy(data);mutate(d);cases.append({'name':name,'bytes':base64.b64encode(encode(d)).decode(),'read_ok':read_ok,'project_ok':project_ok})
case('owned-default',lambda d:None,project_ok=True)
case('owned-local-mask',lambda d:d['m_SavedProperties']['m_TexEnvs'][1][1]['m_Texture'].update(m_FileID=0,m_PathID=99),project_ok=True)
case('keywords',lambda d:d.update(m_ValidKeywords=['UNKNOWN']))
case('invalid-keywords',lambda d:d.update(m_InvalidKeywords=['UNKNOWN']))
case('missing-shader',lambda d:d['m_Shader'].update(m_FileID=0,m_PathID=0))
case('bad-file-id',lambda d:d['m_Shader'].update(m_FileID=-1),False)
case('external-null',lambda d:d['m_Shader'].update(m_PathID=0),False)
case('missing-texture',lambda d:d['m_SavedProperties']['m_TexEnvs'].pop(0))
case('missing-mask',lambda d:d['m_SavedProperties']['m_TexEnvs'].pop())
case('transformed-uv',lambda d:d['m_SavedProperties']['m_TexEnvs'][0][1]['m_Scale'].update(x=2.))
case('missing-color',lambda d:d['m_SavedProperties']['m_Colors'].pop())
case('duplicate-color',lambda d:d['m_SavedProperties']['m_Colors'].append(d['m_SavedProperties']['m_Colors'][0]),False)
case('duplicate-float',lambda d:d['m_SavedProperties']['m_Floats'].append(('_MaskClip',.22)),False)
case('nonfinite-color',lambda d:d['m_SavedProperties']['m_Colors'][0][1].update(r=float('nan')),False)
case('unknown-clip',lambda d:d['m_SavedProperties']['m_Floats'].__setitem__(2,('_MaskClip',.3)))
case('shape-mask',lambda d:d['m_SavedProperties']['m_Floats'].__setitem__(0,('_UseShapeMask',1.)))
case('edge-length',lambda d:d['m_SavedProperties']['m_Floats'].__setitem__(1,('_EdgeLength',.1)))
case('texture-stacks',lambda d:d.update(m_BuildTextureStacks=[{'groupName':'owned','itemName':'owned'}]),False)
canonical=''.join(f'{n.m_Level}|{n.m_Type}|{n.m_Name}|{n.m_ByteSize}|{int(n.m_TypeFlags==1)}|{int(bool(n.m_MetaFlag & 0x4000))}\n' for n in root.traverse())
out={'writer':'UnityPy 1.25.4 write_typetree + SerializedFile.save; owned fixtures only',
 'tpk_sha256':hashlib.sha256((Path(UnityPy.__file__).parent/'resources/lzma.tpk').read_bytes()).hexdigest(),
 'shape_sha256':hashlib.sha256(canonical.encode()).hexdigest(),'node_count':len(raw),
 'asset':base64.b64encode(asset).decode(),'asset_sha256':hashlib.sha256(asset).hexdigest(),'cases':cases}
Path(__file__).with_name('materials.json').write_text(json.dumps(out,indent=2)+'\n')
print(len(cases),'cases',len(asset),'asset bytes',out['shape_sha256'])
