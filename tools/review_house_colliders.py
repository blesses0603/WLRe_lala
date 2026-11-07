"""Extract reviewed furniture/pillar boxes in prefab-local coordinates only.

No world placement, Recast rescan or movement approval is inferred.
"""
import hashlib
import itertools
import json
import math
from pathlib import Path

BUNDLE_SHA='6f5646b1f3a5449e603c019225137129c55741c01ff0e8f47fcabec769581b9b'
MAX_BYTES=48*1024*1024
ASSETS=('Assets/ResourcesBuild/Model/House/Furniture/Furniture_9515.prefab',
        'Assets/ResourcesBuild/Model/House/Pillar/Pillar_9194.prefab')
IDENTITY=((1,0,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1))


def multiply(a,b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)) for i in range(4))


def transform_matrix(tree):
    p=tree['m_LocalPosition'];q=tree['m_LocalRotation'];s=tree['m_LocalScale']
    values=[float(d[k]) for d,keys in ((p,'xyz'),(q,'xyzw'),(s,'xyz')) for k in keys]
    if any(not math.isfinite(v) or abs(v)>100000 for v in values):raise ValueError('Invalid prefab transform')
    if abs(sum(float(q[k])**2 for k in 'xyzw')-1)>1e-4:raise ValueError('Unreviewed non-unit quaternion')
    if any(float(s[k])==0 for k in 'xyz'):raise ValueError('Degenerate collider scale')
    x,y,z,w=(float(q[k]) for k in 'xyzw')
    rotation=((1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w),
              (2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w),
              (2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y))
    return tuple(tuple(rotation[i][j]*float(s['xyz'[j]]) for j in range(3))+(float(p['xyz'[i]]),) for i in range(3))+((0,0,0,1),)


def box_corners(matrix,center,size):
    if any(not math.isfinite(float(d[k])) for d in (center,size) for k in 'xyz') or any(float(size[k])<=0 for k in 'xyz'):
        raise ValueError('Invalid BoxCollider dimensions')
    result=[]
    for signs in itertools.product((-1,1),repeat=3):
        point=[float(center[k])+signs[i]*float(size[k])/2 for i,k in enumerate('xyz')]+[1]
        result.append([sum(matrix[i][j]*point[j] for j in range(4)) for i in range(3)])
    return result


def inspect_bundle(path):
    import UnityPy
    path=Path(path)
    if path.stat().st_size>MAX_BYTES or hashlib.sha256(path.read_bytes()).hexdigest()!=BUNDLE_SHA:
        raise ValueError('House bundle fingerprint has not been reviewed')
    env=UnityPy.load(str(path));result={}
    for asset in ASSETS:
        ptr=env.container[asset]
        if ptr.file_id!=0:raise ValueError('External prefab root')
        objects=ptr.assetsfile.objects
        def read(ref,kind=None):
            if ref['m_FileID']!=0:raise ValueError('Unresolved external collider hierarchy')
            obj=objects[ref['m_PathID']]
            if kind and obj.type.name!=kind:raise ValueError('Unexpected collider hierarchy type')
            return obj,obj.read_typetree()
        root=objects[ptr.path_id].read_typetree();transforms=[]
        for entry in root['m_Component']:
            obj,tree=read(entry['component'])
            if obj.type.name=='Transform':transforms.append((obj,tree))
        if len(transforms)!=1:raise ValueError('Ambiguous prefab root transform')
        visited=set();boxes=[]
        def visit(obj,tree,matrix,names,active,is_root=False):
            if obj.path_id in visited or len(visited)>=256:raise ValueError('Collider hierarchy cycle/quota')
            visited.add(obj.path_id)
            _,go=read(tree['m_GameObject'],'GameObject');names=names+[go['m_Name']]
            active=active and bool(go['m_IsActive'])
            matrix=matrix if is_root else multiply(matrix,transform_matrix(tree))
            for entry in go['m_Component']:
                component,data=read(entry['component'])
                if component.type.name in ('Animation','Animator','MeshCollider','SphereCollider','CapsuleCollider'):
                    raise ValueError('Animated or non-box collider needs separate review')
                if component.type.name=='BoxCollider':
                    if data['m_IsTrigger']:raise ValueError('Trigger collider needs separate review')
                    boxes.append(dict(path='/'.join(names),branch=next((n for n in names[1:] if n in ('L','R')),None),
                        enabled=bool(data['m_Enabled']),active_in_prefab=active,layer=go['m_Layer'],
                        corners_prefab_local=box_corners(matrix,data['m_Center'],data['m_Size'])))
            for child in tree['m_Children']:
                obj2,tree2=read(child,'Transform');visit(obj2,tree2,matrix,names,active)
        obj,tree=transforms[0];visit(obj,tree,IDENTITY,[],True,True)
        if not boxes:raise ValueError('Reviewed prefab has no box colliders')
        result[asset]=dict(boxes=boxes,root_transform=transform_matrix(tree),coordinate_space='prefab_root_local',
                           runtime_recast_override='solid_unwalkable_surface',world_placement_verified=False,
                           dynamic_scan_verified=False,can_send_packets=False)
    return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();target=args.output.resolve()
    if any((p/'.git').exists() for p in target.parents):parser.error('Decoded official geometry must stay outside Git')
    result=inspect_bundle(args.bundle)
    with target.open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps({path:len(row['boxes']) for path,row in result.items()}))


if __name__=='__main__':main()
