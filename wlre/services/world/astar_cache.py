"""Strict decoding of reviewed official A* 4.3.60 caches.

This is a research decoder, not a navigation activation or movement authority.
"""
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import zipfile

REVIEWED_CACHES=frozenset({
    'a728cd68b449c76d89585bcb2f8c29a7bdd146e5da18d9ad01f6647565e689e6',
    'ab622995a92f4bc8f6914c716fda0a82bc2bbfc52a3b6636e616c30d25485889',
    '5fb34818dba90dd16c133f2504fd4e3a6da1351eb90262bab538da87b8de61cb',
    '721540e7699eaa738ef8bf899bf2deb9b808fc11cf05c2678efbbf82b003337d',
    '13c46904d5c16e3418f4c2dd7a7ab24621323b8eccad677900c3031c9c3edc3f',
    '4899fcbe081b3f8924219ef26b4ae490afc007c38d85fb9b1b96d7a7dd38f1b9',
    '2bc5d749067948ad630697f71da34d9a79164ca7f8783625a1341b14be3bc455',
    '493c40032453791d503112d95dfc5ab87a5aa9674ba5be50b60122b7abe8b552',
    '713401e696f3befe979e17db6e0182bbcd20822e02cae187dfa83feabc5b10e1',
    'bd4581bbc2c1661123cd16e46303f0d9e8da63afea47330a50e38fce0b128828',
    'd95005692c09067a3ca6e5d32759d4ed002baec095535a4f7bc592f141a8ae90',

    '5ce014b21935647aceaeb697cde52110c1509ced3212388972c5f7e0132e004e',
    '998e421e3ec0fe29cd9c5fe215f0336d20a9afb7a6a480d28c135bede226d06f',
    'aac34ed3b1d41360d48a116a301d60aa523d7df79e986a762e8fc5d71b874ff9',

    '3703387b6fee3cc4e4654ba682366277ec13bc2e90baf8f115c8c31a4785acab',
    '3203818b7256474b28539346256fb08a7e866939e9af8ae5aa0ef1c740526ab0',
    '8260bebfbefe5818ae705595d58f6f2ec3b85a415f778d5312bd5bdda7ddcb8d',
    '9fafab7be0d03215611949d69fbfeecf0ca4bb280f812f2bedda462d6067d227',
    '5ff98ac860fd1f161a9bc5134555fe207afb03a3f3961eb178d2aa35b8ef1384',
    '6e915dac61f477eaa0f2e07bce729d730e1875bad882c80e940fe9d8b1ed5b78',
})
MEMBERS=frozenset(('graph0.json','graph_references.binary','graph0_extra.binary',
                  'graph0_references.binary','node_link2.binary','meta.json'))
MAX_BYTES=8*1024*1024
MAX_ELEMENTS=100000


class Reader:
    def __init__(self,raw):self.raw=raw;self.pos=0
    def take(self,n):
        if n<0 or self.pos+n>len(self.raw):raise ValueError('Truncated A* geometry')
        value=self.raw[self.pos:self.pos+n];self.pos+=n;return value
    def i32(self):return struct.unpack('<i',self.take(4))[0]
    def count(self):
        value=self.i32()
        if not 0<=value<=MAX_ELEMENTS:raise ValueError('Unreviewed A* array size')
        return value
    def vertices(self):return [list(struct.unpack('<3i',self.take(12))) for _ in range(self.count())]


def decode_geometry(raw):
    r=Reader(raw);grid=[r.i32(),r.i32()]
    if grid!=[1,1]:raise ValueError('Only reviewed single-tile graphs are supported')
    x,z,width,depth=(r.i32() for _ in range(4))
    if (x,z,width,depth)!=(0,0,1,1):raise ValueError('Unreviewed tile layout')
    count=r.count()
    if count%3:raise ValueError('Invalid triangle index count')
    triangles=[list(struct.unpack('<3i',r.take(12))) for _ in range(count//3)]
    a,b=r.vertices(),r.vertices()
    if not a or len(a)!=len(b):raise ValueError('Vertex arrays do not correspond')
    nodes=r.count()
    if nodes!=len(triangles):raise ValueError('Triangle and node counts differ')
    metadata=[]
    for triangle in triangles:
        penalty,flags=struct.unpack('<2I',r.take(8));indices=list(struct.unpack('<3i',r.take(12)))
        if indices!=triangle or any(not 0<=i<len(b) for i in indices):raise ValueError('Invalid node vertex references')
        metadata.append([penalty,flags])
    if r.pos!=len(raw):raise ValueError('Unconsumed A* geometry bytes')
    return {'tile_grid':grid,'tiles':[dict(x=x,z=z,width=width,depth=depth,
        vertices_a_int3=a,vertices_b_int3=b,triangles=triangles,node_metadata=metadata)],'bytes_consumed':r.pos}


def review_cache(raw):
    if type(raw) is not bytes or len(raw)>MAX_BYTES or hashlib.sha256(raw).hexdigest() not in REVIEWED_CACHES:
        raise ValueError('A* cache fingerprint has not been reviewed')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            info=archive.infolist()
            if len(info)!=len(MEMBERS) or {r.filename for r in info}!=MEMBERS:
                raise ValueError('Unknown or duplicate A* archive member')
            if sum(r.file_size for r in info)>MAX_BYTES:raise ValueError('A* archive exceeds review quota')
            parts={r.filename:archive.read(r) for r in info}
    except (zipfile.BadZipFile,RuntimeError) as error:raise ValueError('Invalid A* archive') from error
    # A* emits a bare dotted System.Version token. Recognize this exact syntax;
    # preserve original bytes, rather than treating arbitrary malformed JSON as repairable.
    meta_text=parts['meta.json'].decode('utf-8')
    match=re.search(r'"version"\s*:\s*4\.3\.60(?=\s*,)',meta_text)
    if not match:raise ValueError('Unreviewed A* serializer version')
    meta=json.loads(meta_text[:match.start()]+ '"version":"4.3.60"'+meta_text[match.end():])
    settings=json.loads(parts['graph0.json'])
    if meta.get('graphs')!=1 or meta.get('typeNames')!=['Pathfinding.RecastGraph']:
        raise ValueError('Unreviewed graph type')
    if meta.get('guids')!=[settings.get('guid',{}).get('value')]:raise ValueError('Graph GUID mismatch')
    if settings.get('rotation')!={'x':0,'y':0,'z':0}:raise ValueError('Rotated graphs need separate review')
    if parts['node_link2.binary']!=bytes(4):raise ValueError('Off-mesh links need separate review')
    mesh=decode_geometry(parts['graph0_extra.binary'])
    origin=[(settings['forcedBoundsCenter'][k]-settings['forcedBoundsSize'][k]/2)*1000 for k in ('x','y','z')]
    max_error=max(abs(a[i]-b[i]-origin[i]) for tile in mesh['tiles']
                  for a,b in zip(tile['vertices_a_int3'],tile['vertices_b_int3']) for i in range(3))
    if max_error>0.501:raise ValueError('Graph-space/world-space transform mismatch')
    connections=decode_connections(parts,mesh)
    return dict(mesh=mesh,connections=connections,origin=origin,origin_max_error=max_error,serializer_version='4.3.60',
                member_sha256={k:hashlib.sha256(v).hexdigest() for k,v in parts.items()},
                references_interpreted=True,live_movement_verified=False,can_send_packets=False)


def decode_connections(parts, mesh):
    """Native MeshNode reader: Int32 reference, UInt32 cost, Byte shape edge."""
    triangles=mesh['tiles'][0]['triangles']
    r=Reader(parts['graph_references.binary']);maximum=r.count()
    ids=[r.i32() for _ in triangles]
    if len(set(ids))!=len(ids) or any(not 0<=i<=maximum for i in ids) or r.pos!=len(r.raw):
        raise ValueError('Invalid graph node reference map')
    index={node:i for i,node in enumerate(ids)}
    r=Reader(parts['graph0_references.binary']);connections=[]
    for source,triangle in enumerate(triangles):
        count=r.count()
        if count>3:raise ValueError('Unreviewed non-triangle connections')
        rows=[];targets=set()
        for _ in range(count):
            ref,cost,edge=struct.unpack('<iIB',r.take(9))
            if ref not in index or edge>2:raise ValueError('Invalid connection reference')
            target=index[ref]
            if target==source or target in targets:raise ValueError('Duplicate or self connection')
            targets.add(target)
            shared=set(triangle)&set(triangles[target])
            if len(shared)!=2 or shared!={triangle[edge],triangle[(edge+1)%3]}:
                raise ValueError('Connection does not cross its declared triangle edge')
            rows.append([target,cost,edge])
        connections.append(rows)
    if r.pos!=len(r.raw):raise ValueError('Unconsumed connection bytes')
    return connections
