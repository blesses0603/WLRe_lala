"""Bounded native NavmeshBase.GetNearest graph-level integration probe.

Synthetic single tile, at most four triangles and initialized transform/vtables.
Center preparation explicitly models modf. Not AstarPath.GetNearest, a live map,
Android-device acceptance, or movement authority.
"""
import argparse
import json
import math
import struct
from tools.review_navigation_vertices import oracle as vertex_oracle,validate_inputs
from tools.review_navigation_bbtree import oracle as tree_oracle


def validate_query(vertices,faces,point,origin):
    if not isinstance(faces,list) or not 1<=len(faces)<=4:raise ValueError('Require 1..4 triangles')
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


def oracle(path):
    # Optional native dependencies are loaded after the vertex factory checks hash.
    state={}
    load=vertex_oracle(path,modeled_center=True,_state=state);u=state['vm'];data=state['data']
    from unicorn.arm64_const import UC_ARM64_REG_S0,UC_ARM64_REG_X8
    ranges=((0x2a8ff80,0x2a90030),(0x2d83808,0x2d83814),(0x2d93f7c,0x2d93f88),(0x27a375c,0x27a3c0c),(0x27a1618,0x27a16b8),(0x22d23f0,0x22d2454),(0x30c9944,0x30c999c),(0x28383b8,0x28383e0),(0x2d86f88,0x2d86f90),(0x2843af0,0x2843bc8),(0x2843cb0,0x2843d94),(0x28440d4,0x28442f4),(0x24c3e70,0x24c3e80),(0x2832dd8,0x2832f18),(0x2a98e20,0x2a99050),(0x2d83820,0x2d83848),(0x20d12c4,0x20d133c),(0x20d14bc,0x20d1534),(0xe00550,0xe00554),(0xe81860,0xe81864),(0xec1130,0xec1178))
    pages={p for a,b in ranges for p in range(a&~4095,((b+4095)//4096)*4096,4096)}|{0x379a000,0x4c4f000,0x4940000,0x494b000,0x4c68000}
    for p in pages-state['pages']:u.mem_map(p,4096)
    for a,b in ranges:u.mem_write(a,data(a,b-a))
    state['ranges'].extend(ranges)
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
    q(0x6047188,0x2a8ff80);q(0x6048000,0x6047000)
    u.mem_write(0x604801c,b'\x01\x01')
    build=tree_oracle(path)
    def query(vertices,faces,point,origin=(0,0,0),matrix=False,walkable=None):
     validate_query(vertices,faces,point,origin)
     if walkable is not None and (len(walkable)!=len(faces) or any(type(x) is not bool for x in walkable)):raise ValueError('Invalid walkability')
     rects=[];centers=[]
     for i,face in enumerate(faces):
      result=load(vertices,face);rects.append(result['bounds']);centers.append(result['center'])
      node=0x6046000+i*0x100
      u.mem_write(node,bytes(0x100));q(node,0x6040000);w(node+0x14,int(walkable[i]) if walkable is not None else 1)
      u.mem_write(node+0x1c,struct.pack('<3i',*result['center']));u.mem_write(node+0x30,struct.pack('<3i',*face))
     tree=build(rects,centers)
     if len(tree['boxes'])!=1:raise ValueError('Unreviewed internal tree branch')
     u.mem_write(0x6043020,struct.pack('<7i',*tree['boxes'][0]))
     for i,ref in enumerate(tree['leaf_references']):q(0x6044020+i*8,0 if ref is None else 0x6046000+ref*0x100)
     u.mem_write(0x6041012,bytes([not matrix]));u.mem_write(0x60410a0,struct.pack('<3f',*origin))
     inverse=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,-origin[0],-origin[1],-origin[2],1.]
     u.mem_write(0x6041054,struct.pack('<16f',*inverse))
     def position():
      for i,v in enumerate(point):u.reg_write(UC_ARM64_REG_S0+i,struct.unpack('<I',struct.pack('<f',v))[0])
     position();tile=struct.unpack('<2i',state['execute'](0x27a1618,(0x6020000,0))[:8])
     position();u.reg_write(UC_ARM64_REG_X8,0x6045000);u.mem_write(0x6045000,bytes(0x30))
     state['execute'](0x27a375c if walkable is None else 0x27a3844,(0x6020000,0 if walkable is None else 0x6048000,0))
     node=struct.unpack('<Q',u.mem_read(0x6045000,8))[0]
     if node and (not 0x6046000<=node<0x6046000+len(faces)*0x100 or (node-0x6046000)%0x100):raise ValueError('Invalid nearest node')
     result=dict(node=None if not node else (node-0x6046000)//0x100,
                 point=list(struct.unpack('<3f',u.mem_read(0x6045010,12))) if node else None,tile=list(tile))
     if result['point'] and not all(math.isfinite(x) for x in result['point']):raise ValueError('Nonfinite nearest output')
     return result
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
