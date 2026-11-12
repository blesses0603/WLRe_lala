"""Owned structural fixtures, no game files/class database.
Run with UnityPy==1.25.4 on PYTHONPATH. Handwritten trees and bytes are first
parsed, rewritten by UnityPy's real SerializedFile writer, then independently
loaded as genuine UnityFS. Output is deterministic and contains invalid UTF-8.
"""
from pathlib import Path
import hashlib, json, struct
import UnityPy, lz4
assert lz4.__version__ == '4.4.5'
assert UnityPy.__version__ == '1.25.4'
OUT = Path(__file__).with_name('Fixtures')
PATH = 'Assets/ResourcesBuild/Data/Owned.bytes'
PAYLOAD = bytes.fromhex('0001fffe8041424300c3287f')
def p(fmt, *v): return struct.pack('<'+fmt, *v)
def align(b, n=4): return b+b'\0'*(-len(b)%n)
def string(s):
    b=s.encode() if isinstance(s,str) else s
    return align(p('i',len(b))+b)
def n(t,name,size=-1,children=(),array=0,aligned=0): return (t,name,size,list(children),array,aligned)
def st(name): return n('string',name,children=[n('Array','Array',children=[n('int','size',4),n('char','data',1)],array=1,aligned=1)])
def ptr(name): return n('PPtr<Object>',name,12,[n('int','m_FileID',4),n('SInt64','m_PathID',8)])
def info(name): return n('AssetInfo',name,20,[n('int','preloadIndex',4),n('int','preloadSize',4),ptr('asset')])
def arr(t,name,child,aligned=0): return n(t,name,children=[n('Array','Array',children=[n('int','size',4),child],array=1,aligned=aligned)])
TEXT=n('TextAsset','Base',children=[st('m_Name'),st('m_Script')])
BUNDLE=n('AssetBundle','Base',children=[st('m_Name'),arr('vector','m_PreloadTable',ptr('data'),1),
    arr('map','m_Container',n('pair','data',children=[st('first'),info('second')])),info('m_MainAsset'),
    n('unsigned int','m_RuntimeCompatibility',4),st('m_AssetBundleName'),arr('vector','m_Dependencies',st('data'),1),
    n('bool','m_IsStreamedSceneAssetBundle',1,aligned=1),n('int','m_ExplicitDataLayout',4),n('int','m_PathFlags',4),
    arr('map','m_SceneHashes',n('pair','data',children=[st('first'),st('second')]))])
def tree(root):
    nodes=[]; strings=bytearray(); offsets={}
    def offset(s):
        if s not in offsets: offsets[s]=len(strings); strings.extend(s.encode()+b'\0')
        return offsets[s]
    def visit(node,depth=0):
        t,name,size,children,array,aligned=node
        nodes.append(p('HBBIIiIIQ',1,depth,array,offset(t),offset(name),size,len(nodes),0x4000 if aligned else 0,0))
        for child in children: visit(child,depth+1)
    visit(root)
    return p('ii',len(nodes),len(strings))+b''.join(nodes)+strings

def serialized(*, entries=1, name="Owned", file_id=0, path_id=2, externals=(), script=PAYLOAD):
    # Minimal populated standard 2021 AssetBundle layout, all optional arrays empty.
    container=string('owned')+p('i',0)+p('i',entries)
    container+=(string(PATH)+p('iii q',0,0,file_id,path_id))*entries
    container+=p('iii q',0,0,0,0)+p('I',0)+string('owned')+p('i',0)+p('i',0)+p('ii',0,0)+p('i',0)
    text=string(name)+string(script)
    data=align(container,8)+align(text,8)
    meta=b'2021.3.45f2\0'+p('iB',19,1)+p('i',2)
    for cid,root in [(142,BUNDLE),(49,TEXT)]: meta+=p('iBh',cid,0,-1)+bytes(16)+tree(root)+p('i',0)
    meta+=p('i',2)
    # Metadata alignment uses absolute file position, header48 is aligned.
    meta=align(meta)+p('qqIi',1,0,len(container),0)
    meta=align(meta)+p('qqIi',2,len(align(container,8)),len(text),1)
    meta+=p('ii',0,len(externals))
    for external in externals: meta+=b'\0'+bytes(16)+p('i',0)+external.encode()+b'\0'
    meta+=p('i',0)+b'\0'
    offset=len(align(bytes(48)+meta,16))
    hdr=struct.pack('>IIIIB3sIqqq',0,0,22,0,0,bytes(3),len(meta),offset+len(data),offset,0)
    raw=align(hdr+meta,16)+data
    # Invoke independent real writer rather than retaining only a bespoke encoding.
    env=UnityPy.load(raw)
    file=next(iter(env.files.values()))
    saved=file.save()
    assert next(iter(UnityPy.load(saved).files.values())).save()==saved, 'Writer not stable'
    return saved

def bundle(raw,version=8,compression=0,multi=False):
    # compression2/3 use the independent lz4 package's raw block writer.
    from lz4.block import compress
    encode=lambda x: x if compression==0 else compress(x,store_size=False)
    chunks=[raw[i:i+1024] for i in range(0,len(raw),1024)] if multi else [raw]
    packed_chunks=[encode(chunk) for chunk in chunks]
    data=b''.join(packed_chunks)
    info=bytes(16)+struct.pack('>i',len(chunks))
    for plain,packed_chunk in zip(chunks,packed_chunks): info+=struct.pack('>IIH',len(plain),len(packed_chunk),compression)
    info+=struct.pack('>iqqI',1,0,len(raw),4)+b'CAB-owned\0'
    packed=encode(info)
    hdr=b'UnityFS\0'+struct.pack('>I',version)+b'5.x.x\0' + b'2021.3.45f2\0'
    length=len(hdr)+20
    if version>=7: length=(length+15)//16*16
    padding=(-length-len(packed))%16 if compression==3 else 0
    hdr+=struct.pack('>qIII',length+len(packed)+padding+len(data),len(packed),len(info),0x40|compression|(0x200 if compression==3 else 0))
    if version>=7: hdr=align(hdr,16)
    return hdr+packed+bytes(padding)+data

def verify(data):
    env=UnityPy.load(data)
    pairs=list(env.container.items())
    assert len(pairs)==1 and pairs[0][0]==PATH
    obj=pairs[0][1].deref_parse_as_object()
    assert obj.m_Name=='Owned'
    assert obj.m_Script.encode('utf-8','surrogateescape')==PAYLOAD
    bundle_file=next(iter(env.files.values()))
    file=next(iter(bundle_file.files.values()))
    assert file.header.version==22 and file._enable_type_tree
    return {'unity_version':file.unity_version,'serialized_version':file.header.version,'classes':[t.class_id for t in file.types], 'nodes':[len(list(t.node.traverse())) for t in file.types]}

def main():
    OUT.mkdir(exist_ok=True); hashes={}
    raw=serialized(); (OUT/'owned.assets').write_bytes(raw)
    for version,compression in [(6,0),(7,0),(8,0),(8,2),(8,3)]:
        name=f'owned-v{version}-c{compression}.bundle'; data=bundle(raw,version,compression)
        observed=verify(data); (OUT/name).write_bytes(data)
        hashes[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),**observed}
    data=bundle(raw,compression=3,multi=True); name='owned-multiblock.bundle'; (OUT/name).write_bytes(data)
    hashes[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),**verify(data)}
    hashes['owned.assets']={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    # Independent writer-generated structural variants, never patched game data.
    variants={'duplicate':dict(entries=2), 'external':dict(file_id=1,externals=('archive:/CAB-owned/CAB-owned',)),
              'target':dict(entries=0), 'unused-empty':dict(entries=0,script=b''), 'bad-name':dict(name='Wrong'), 'filename-name':dict(name='Owned.bytes'),
              'wrong-class':dict(path_id=1), 'empty-script':dict(script=b'')}
    for name,kwargs in variants.items():
        data=serialized(**kwargs); (OUT/(name+'.assets')).write_bytes(data)
        hashes[name+'.assets']={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    # Small independent offset recipe for malformed-field tests.
    import io
    def i32(b,pos): return struct.unpack_from('<i',b,pos)[0]
    pos=48+len(b'2021.3.45f2\0')+4
    layout={'type_enabled':pos,'type_count':pos+1,'first_class':pos+5,'first_tree_count':pos+28,'first_tree_strings':pos+32,'first_node':pos+36}
    pos+=5
    for _ in range(i32(raw,layout['type_count'])):
        pos+=23; count=i32(raw,pos); size=i32(raw,pos+4); pos+=8+count*32+size
        deps=i32(raw,pos); pos+=4+deps*4
    layout['object_count']=pos; pos=(pos+4+3)//4*4
    layout['first_object']=pos; layout['second_object']=pos+24
    layout['script_count']=pos+48; layout['external_count']=pos+52; layout['reference_count']=pos+56
    data_start=struct.unpack_from('>q',raw,32)[0]
    container=data_start+struct.unpack_from('<q',raw,pos+8)[0]
    text=data_start+struct.unpack_from('<q',raw,pos+32)[0]
    layout['container']=container; layout['preload_count']=container+len(string('owned')); layout['container_count']=layout['preload_count']+4
    layout['container_path_length']=layout['container_count']+4
    layout['container_file_id']=layout['container_path_length']+len(string(PATH))+8
    layout['container_path_id']=layout['container_file_id']+4
    layout['text']=text; layout['script_length']=text+len(string('Owned'))
    (OUT/'layout.json').write_text(json.dumps(layout,indent=2)+'\n')
    # Legal common-table suffix offset, independently accepted by UnityPy.
    from UnityPy.helpers.Tpk import get_common_strings
    common=get_common_strings(); suffix=next(k for k,v in common.items() if v=='unsigned int')+9
    altered=bytearray(raw); struct.pack_into('<I',altered,layout['first_node']+3*32+4,0x80000000|suffix)
    env=UnityPy.load(bytes(altered)); text=next(o for o in env.objects if o.type.name=='TextAsset').read()
    assert text.m_Script.encode('utf-8','surrogateescape')==PAYLOAD
    name='suffix.assets'; (OUT/name).write_bytes(altered)
    hashes[name]={'sha256':hashlib.sha256(altered).hexdigest(),'bytes':len(altered)}

    (OUT/'evidence.json').write_text(json.dumps({'writer':'UnityPy 1.25.4 SerializedFile.save','compression_writer':'lz4 4.4.5 raw block','payload_hex':PAYLOAD.hex(),'path':PATH,'files':hashes},indent=2)+'\n')
    print(json.dumps(hashes,indent=2))
if __name__=='__main__': main()
