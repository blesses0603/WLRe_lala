"""Independent owned Shader writer fixtures; never official shader programs."""
from pathlib import Path
import base64,copy,hashlib,json,struct
import UnityPy
from UnityPy.helpers.Tpk import get_typetree_node,get_typetree
from UnityPy.helpers.UnityVersion import UnityVersion
from UnityPy.helpers.TypeTreeHelper import write_typetree,write_value,TypeTreeConfig
from UnityPy.streams import EndianBinaryWriter
assert UnityPy.__version__=='1.25.4'
v=UnityVersion.from_str('2021.3.45f2');tpk=get_typetree();root=get_typetree_node(48,v);raw=[]
def walk(i):
    n=tpk.NodeBuffer[i];raw.append(n)
    for c in n.SubNodes:walk(c)
walk(tpk.ClassInformation[48].getVersionedClass(v).ReleaseRootNode)
for i,(n,r) in enumerate(zip(root.traverse(),raw)):
    assert n.m_Type==tpk.StringBuffer[r.TypeName] and n.m_Name==tpk.StringBuffer[r.Name]
    n.m_TypeFlags=r.TypeFlags;n.m_RefTypeHash=0;n.m_Index=i

def values(n,populated=False):
    if n.m_Type=='string':return 'owned' if populated else ''
    if n.m_Children and n.m_Children[0].m_Type=='Array':return [values(n.m_Children[0].m_Children[1],True)] if populated else []
    if n.m_Type=='pair':return tuple(values(c,populated) for c in n.m_Children)
    if n.m_Children:return {c.m_Name:values(c,populated) for c in n.m_Children}
    return False if n.m_Type=='bool' else 0

def data(populated=False):
    d=values(root,populated);d['m_Name']='owned shader';d['m_ParsedForm']['m_Name']='UI_ProfilePhotoWithMask'
    prop_node=next(n for n in root.traverse() if n.m_Type=='SerializedProperty')
    prop=values(prop_node,populated);prop['m_Name']='_ColorMask1';prop['m_DefTexture']['m_DefaultName']='white'
    d['m_ParsedForm']['m_PropInfo']['m_Props']=[prop];d['compressedBlob']=list(b'owned synthetic shader blob, not official')
    return d

def encode(d):
    w=EndianBinaryWriter(endian='<');write_typetree(d,root,w);return w.bytes
p=lambda fmt,*values:struct.pack('<'+fmt,*values)
def align(b,n=4):return b+bytes((-len(b))%n)
w=EndianBinaryWriter(endian='<');root.dump_blob(w,22)
body=encode(data(True));meta=b'2021.3.45f2\0'+p('iBi',19,1,1)+p('iBh',48,0,-1)+bytes(16)+w.bytes+p('ii',0,1)
meta=align(meta)+p('qqIi',-1215708881511709531,0,len(body),0)+p('iii',0,0,0)+b'\0';offset=len(align(bytes(48)+meta,16))
file=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(body),offset,0)+meta
file=align(file,16)+body
asset=next(iter(UnityPy.load(file).files.values())).save()
read=next(iter(UnityPy.load(asset).objects)).read_typetree()
assert read['m_ParsedForm']['m_Name']=='UI_ProfilePhotoWithMask'
assert bytes(read['compressedBlob'])==bytes(data()['compressedBlob'])
cases=[]
def case(name,d,ok=True):cases.append({'name':name,'bytes':base64.b64encode(encode(d)).decode(),'read_ok':ok})
case('minimal',data());case('all-nested-arrays',data(True))
d=data();d['m_ParsedForm']['m_PropInfo']['m_Props'][0]['m_DefTexture']['m_DefaultName']='black';case('black-default',d)
d=data();d['m_ParsedForm']['m_Name']='unknown';case('unknown-name',d)
d=data();d['m_ParsedForm']['m_PropInfo']['m_Props']*=2;case('duplicate-property',d,False)
d=data();d['m_ParsedForm']['m_PropInfo']['m_Props'][0]['m_DefValue[0]']=float('nan');case('nonfinite-property',d,False)
d=data();d['m_Name']='x'*4097;case('oversized-name',d,False)
canonical=''.join(f'{n.m_Level}|{n.m_Type}|{n.m_Name}|{n.m_ByteSize}|{int(n.m_TypeFlags==1)}|{int(bool(n.m_MetaFlag & 0x4000))}\n' for n in root.traverse())
offsets={};w=EndianBinaryWriter(endian='<');minimal=data()
for child in root.m_Children:
    offsets[child.m_Name]=w.Position
    write_value(minimal[child.m_Name],child,w,TypeTreeConfig(True,None,False))
assert w.bytes==encode(minimal)
result={'offsets':offsets,'writer':'UnityPy 1.25.4 write_typetree + SerializedFile.save; all bytes synthetic',
 'tpk_sha256':hashlib.sha256((Path(UnityPy.__file__).parent/'resources/lzma.tpk').read_bytes()).hexdigest(),
 'shape_sha256':hashlib.sha256(canonical.encode()).hexdigest(),'nodes':len(raw),'asset':base64.b64encode(asset).decode(),
 'asset_sha256':hashlib.sha256(asset).hexdigest(),'blob_sha256':hashlib.sha256(bytes(data()['compressedBlob'])).hexdigest(),'cases':cases}
Path(__file__).with_name('shaders.json').write_text(json.dumps(result,indent=2)+'\n')
print(len(asset),len(body),len(cases),result['shape_sha256'])
