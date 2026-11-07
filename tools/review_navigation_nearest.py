"""Bounded native NavmeshBase.GetNearest graph-level integration probe.

Synthetic one-graph state, up to 2x2 tiles/512 triangles (isolated opt-in 1024) and initialized vtables.
Center preparation explicitly models modf; optional outer AstarPath calls. Not a live map,
Android-device acceptance, or movement authority.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle,validate_inputs
from tools.review_navigation_bbtree import oracle as tree_oracle


def validate_query(vertices,faces,point,origin,*,capacity=512):
    if type(capacity) is not int or capacity not in (512,1024):raise ValueError('Invalid nearest capacity')
    if not isinstance(faces,list) or not 1<=len(faces)<=capacity:raise ValueError(f'Require 1..{capacity} triangles')
    for face in faces:validate_inputs(vertices,face)
    for vector in (point,origin):
        if len(vector)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>1000 for x in vector):
            raise ValueError('Require bounded finite query/translation')
    if any(abs(x)>1000000 for vertex in vertices for x in vertex):raise ValueError('Vertex limit for nearest probe')
    for face in faces:
        a,b,c=[vertices[i] for i in face]
        u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        if not any(cross):raise ValueError('Degenerate triangle')


def oracle(path,*,_state=None,_search_state=False,_outer_instruction_limit=200000,capacity=512,_shared_large_prepare=False):
    if type(capacity) is not int or capacity not in (512,1024) or (capacity!=512 and _search_state and not _shared_large_prepare):
        raise ValueError('Extended nearest requires isolated state')
    if type(_shared_large_prepare) is not bool:raise ValueError('Invalid shared Prepare selector')
    if _shared_large_prepare and (not _search_state or capacity!=1024 or _outer_instruction_limit not in (200000,1000000)):
        raise ValueError('Invalid shared large Prepare layout')
    if type(_outer_instruction_limit) is not int or _outer_instruction_limit not in ((200000,400000,1000000) if capacity==1024 and (not _search_state or _shared_large_prepare) else (200000,400000)):
        raise ValueError('Unreviewed diagnostic instruction budget')
    if _search_state and _outer_instruction_limit!=200000 and not (_shared_large_prepare and _outer_instruction_limit==1000000):
        raise ValueError('Extended diagnostic budget is not for path pipelines')
    # Optional native dependencies are loaded after the vertex factory checks hash.
    state={}
    node_base=0x6242000 if _shared_large_prepare else 0x6090000 if _search_state else 0x6080000
    load=vertex_oracle(path,modeled_center=True,_state=state,_path_magnitude=_search_state);u=state['vm'];data=state['data']
    from unicorn.arm64_const import UC_ARM64_REG_S0,UC_ARM64_REG_X8
    ranges=((0x2843ff8,0x28440d4),(0x1a7a794,0x1a7abb0),(0x1a76cb8,0x1a76d34),(0x2e9b100,0x2e9b144),(0x2a903a4,0x2a903f4),(0x2a8ff50,0x2a8ff68),(0x2a8ff80,0x2a90030),(0x2d83808,0x2d83814),(0x2d93f7c,0x2d93f88),(0x27a375c,0x27a3c0c),(0x27a1618,0x27a16b8),(0x22d23f0,0x22d2454),(0x30c9944,0x30c999c),(0x28383b8,0x28383e0),(0x2d86f88,0x2d86f90),(0x2843af0,0x2843bc8),(0x2843cb0,0x2843d94),(0x28440d4,0x28442f4),(0x24c3e70,0x24c3e80),(0x2832dd8,0x2832f18),(0x2a98e20,0x2a99050),(0x2d83820,0x2d83848),(0x20d12c4,0x20d133c),(0x20d14bc,0x20d1534),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x379a000,0x4c4f000,0x4940000,0x494b000,0x4c68000,0x4c54000,0x4c50000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['pages'].update(pages);state['ranges'].extend(ranges)
    def q(a,v):u.mem_write(a,struct.pack('<Q',v))
    def w(a,v):u.mem_write(a,struct.pack('<I',v))
    for a in (0x4c5a461,0x4c5a462,0x4c5aae8,0x4c5aa8c,0x4c4ff5d):u.mem_write(a,b'\x01')
    for a in (0x4940360,0x494b558):q(a,0x6010000)
    u.mem_write(0x379addc,data(0x379addc,4))
    q(0x6021258,0x27a3844);q(0x60213b8,0x28383b8);q(0x60213c8,0x28383cc)
    w(0x60200e0,1);w(0x60200e4,1);w(0x6020154,10);w(0x6020158,10);u.mem_write(0x6020138,struct.pack('<f',1.0))
    q(0x6020118,0x6041000);u.mem_write(0x6041012,b'\x01')
    q(0x6000000,0x6040000);q(0x6040218,0x2832dd8)
    q(0x6024040,0x6042000);q(0x6042010,0x6043000);q(0x6042018,0x6044000);w(0x6042020,1)
    w(0x6043018,1);w(0x6044018,4)
    q(0x6047188,0x2a8ff80);q(0x6047178,0x2a8ff50);q(0x6048000,0x6047000)
    q(0x6021248,0x27a375c)
    q(0x6049020,0x604a000);q(0x604a040,0x604b000);w(0x604b018,1);q(0x604b020,0x6020000)
    u.mem_write(0x4c54e25,b'\x01');u.mem_write(0x4c5039f,b'\x01')
    u.mem_write(0x604801c,b'\x01\x01')
    build=tree_oracle(path,capacity=capacity)
    def query(vertices,faces,point,origin=(0,0,0),matrix=False,walkable=None,*,outer=False,full_search=False,graph_mask=1,max_distance=None,tile_shape=(1,1),face_tiles=None,cell_size=1.0,tile_cells=(10,10),node_flags=None,tag_mask=None):
     validate_query(vertices,faces,point,origin,capacity=capacity)
     if len(tile_shape)!=2 or any(type(x) is not int or not 1<=x<=2 for x in tile_shape):raise ValueError('Require at most 2x2 tiles')
     if type(cell_size) not in (int,float) or not math.isfinite(cell_size) or not 0<cell_size<=100:raise ValueError('Invalid cell size')
     if len(tile_cells)!=2 or any(type(x) is not int or not 1<=x<=100000 for x in tile_cells):raise ValueError('Invalid tile cell dimensions')
     w(0x6020154,tile_cells[0]);w(0x6020158,tile_cells[1]);u.mem_write(0x6020138,struct.pack('<f',cell_size))
     tile_count=tile_shape[0]*tile_shape[1]
     face_tiles=[0]*len(faces) if face_tiles is None else face_tiles
     if len(face_tiles)!=len(faces) or any(type(x) is not int or not 0<=x<tile_count for x in face_tiles):raise ValueError('Invalid tile ownership')
     w(0x6023018,1);q(0x6023020,0x6024000)
     if type(graph_mask) is not int or not 0<=graph_mask<=0xffffffff:raise ValueError('Invalid graph mask')
     if max_distance is not None and (type(max_distance) not in (int,float) or not math.isfinite(max_distance) or not 0<=max_distance<=1000):raise ValueError('Invalid distance limit')
     if walkable is not None and (len(walkable)!=len(faces) or any(type(x) is not bool for x in walkable)):raise ValueError('Invalid walkability')
     if node_flags is not None and (walkable is not None or len(node_flags)!=len(faces) or any(type(f) is not int or not 0<=f<0x1000000 for f in node_flags)):raise ValueError('Invalid single-graph node flags')
     if tag_mask is not None and (type(tag_mask) is not int or not 0<=tag_mask<=0xffffffff):raise ValueError('Invalid tag mask')
     u.mem_write(0x604801f,bytes([tag_mask is not None]));w(0x6048020,tag_mask or 0)
     rects=[];centers=[]
     for i,face in enumerate(faces):
      result=load(vertices,face);rects.append(result['bounds']);centers.append(result['center'])
      node=node_base+i*0x100
      u.mem_write(node,bytes(0x100));q(node,0x6040000);w(node+0x14,node_flags[i] if node_flags is not None else int(walkable[i]) if walkable is not None else 1)
      u.mem_write(node+0x1c,struct.pack('<3i',*result['center']));u.mem_write(node+0x30,struct.pack('<3i',*(j|(face_tiles[i]<<12) for j in face)))
     w(0x60200e0,tile_shape[0]);w(0x60200e4,tile_shape[1]);w(0x6023018,tile_count)
     for tile_index in range(tile_count):
      members=[i for i,t in enumerate(face_tiles) if t==tile_index]
      tile_record=0x6050000+tile_index*0x100
      q(0x6023020+tile_index*8,tile_record if members else 0)
      if not members:continue
      tree=build([rects[i] for i in members],[centers[i] for i in members])
      tree_record=0x6100000+tile_index*0x20000;boxes=tree_record+0x1000;refs=tree_record+0x10000
      q(tile_record+0x18,0x6030000);q(tile_record+0x40,tree_record)
      q(tree_record+0x10,boxes);q(tree_record+0x18,refs);w(tree_record+0x20,len(tree['boxes']))
      w(boxes+0x18,len(tree['boxes']));w(refs+0x18,len(tree['leaf_references']))
      u.mem_write(boxes+0x20,b''.join(struct.pack('<7i',*box) for box in tree['boxes']))
      for i,ref in enumerate(tree['leaf_references']):q(refs+0x20+i*8,0 if ref is None else node_base+members[ref]*0x100)
     u.mem_write(0x6041012,bytes([not matrix]));u.mem_write(0x60410a0,struct.pack('<3f',*origin))
     inverse=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,-origin[0],-origin[1],-origin[2],1.]
     u.mem_write(0x6041054,struct.pack('<16f',*inverse))
     def position():
      for i,v in enumerate(point):u.reg_write(UC_ARM64_REG_S0+i,struct.unpack('<I',struct.pack('<f',v))[0])
     position();tile=struct.unpack('<2i',state['execute'](0x27a1618,(0x6020000,0))[:8])
     position();u.reg_write(UC_ARM64_REG_X8,0x6045000);u.mem_write(0x6045000,bytes(0x30))
     if outer:
      w(0x6048010,graph_mask)
      u.mem_write(0x6049049,bytes([bool(full_search)]));u.mem_write(0x6048024,bytes([max_distance is not None]))
      u.mem_write(0x6049044,struct.pack('<f',max_distance or 0))
      state['execute'](0x1a7a794,(0x6049000,0x6048000,0),instruction_limit=_outer_instruction_limit)
     else:
      state['execute'](0x27a375c if walkable is None else 0x27a3844,(0x6020000,0 if walkable is None else 0x6048000,0),instruction_limit=200000)
     node=struct.unpack('<Q',u.mem_read(0x6045000,8))[0]
     if node and (not node_base<=node<node_base+len(faces)*0x100 or (node-node_base)%0x100):raise ValueError('Invalid nearest node')
     result=dict(node=None if not node else (node-node_base)//0x100,
                 point=list(struct.unpack('<3f',u.mem_read(0x6045008 if outer else 0x6045010,12))) if node else None,tile=list(tile))
     if result['point'] and not all(math.isfinite(x) for x in result['point']):raise ValueError('Nonfinite nearest output')
     return result
    if _shared_large_prepare:state['large_prepare_layout']=True
    if _state is not None:_state.update(state)
    return query


def reference_triangle(vertices,point):
    """Independent double-precision plane projection plus bounded edge candidates."""
    a,b,c=vertices
    sub=lambda x,y:[u-v for u,v in zip(x,y)]
    dot=lambda x,y:sum(u*v for u,v in zip(x,y))
    ab=sub(b,a);ac=sub(c,a)
    normal=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
    scale=dot(sub(point,a),normal)/dot(normal,normal)
    projection=[p-scale*n for p,n in zip(point,normal)]
    ap=sub(projection,a);aa=dot(ab,ab);cc=dot(ac,ac);cross=dot(ab,ac);det=aa*cc-cross*cross
    v=(dot(ap,ab)*cc-dot(ap,ac)*cross)/det
    w=(dot(ap,ac)*aa-dot(ap,ab)*cross)/det
    candidates=[]
    if v>=0 and w>=0 and v+w<=1:candidates.append(projection)
    for x,y in ((a,b),(b,c),(c,a)):
        edge=sub(y,x);t=max(0.,min(1.,dot(sub(point,x),edge)/dot(edge,edge)))
        candidates.append([start+t*step for start,step in zip(x,edge)])
    return min(candidates,key=lambda x:dot(sub(point,x),sub(point,x)))


def vectors(path):
    call=oracle(path);rows=[]
    flat=[[0,0,0],[10000,0,0],[0,0,10000]]
    slope=[[0,0,0],[10000,4000,0],[0,8000,10000]]
    stacked=flat+[[x,y+5000,z] for x,y,z in flat]
    four=[ [x,y+5000*level,z] for level in range(4) for x,y,z in flat ]
    meshes=((flat,[[0,1,2]]),(slope,[[0,1,2]]),(stacked,[[0,1,2],[3,4,5]]),(four,[[i*3,i*3+1,i*3+2] for i in range(4)]))
    points=((2,3,2),(15,1,15),(-1,0,1),(0,0,0),(4,6,3),(-10.1,2,0),(10,2,2),(2,2.5,2))
    for vertices,faces in meshes:
        for origin in ((0,0,0),(32,4,-16)):
            shifted=[[x+int(origin[k]*1000) for k,x in enumerate(v)] for v in vertices]
            for matrix in (False,True):
                for local in points:
                    point=[x+y for x,y in zip(local,origin)]
                    for walkable in (None,[False]*len(faces),[i==len(faces)-1 for i in range(len(faces))]):
                        output=call(shifted,faces,point,origin,matrix,walkable)
                        candidates=[]
                        for i,face in enumerate(faces):
                            if walkable is not None and not walkable[i]:continue
                            closest=reference_triangle([[x/1000 for x in shifted[j]] for j in face],point)
                            distance=sum((a-b)**2 for a,b in zip(point,closest));candidates.append((distance,i,closest))
                        tile=[int((point[k]-origin[k])/10) for k in (0,2)]
                        if output['tile']!=tile:raise ValueError('Native tile-coordinate mismatch')
                        if not candidates:
                            if output['node'] is not None:raise ValueError('Excluded triangle was selected')
                        else:
                            distance,index,closest=min(candidates)
                            if output['node']!=index or max(abs(a-b) for a,b in zip(output['point'],closest))>0.0002:
                                raise ValueError('Native graph nearest comparison failed '+str((output,index,closest)))
                        rows.append(dict(vertices=shifted,faces=faces,point=point,origin=origin,matrix=matrix,walkable=walkable,native_output=output))
    return dict(cases=rows,can_send_packets=False,modeled_modf=True,
                scope='Native NavmeshBase.GetNearest/GetNearestForce on synthetic single-tile leaf trees; not outer AstarPath, real-map or device acceptance')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--libil2cpp',required=True);args=parser.parse_args()
    try:print(json.dumps(vectors(args.libil2cpp),sort_keys=True))
    except (OSError,ValueError,ImportError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
