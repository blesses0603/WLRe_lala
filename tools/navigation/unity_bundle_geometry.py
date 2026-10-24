"""Extract private 1275 collision inputs directly from verified Unity bundles.

Uses scene instances only, not prefab definitions from dependency bundles.
Unknown collider meshes, terrain holes or height encodings reject the model;
other models can still be rebuilt and are listed separately in the report.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from zipfile import ZipFile
from tools.navigation.scan import ScanError,bake
from tools.resources.audit_1275_scene_collision import inspect
from tools.resources.extract_1275_recast_settings import extract,load_scene_selection


def multiply(a,b):return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
def identity():return [[int(i==j) for j in range(4)] for i in range(4)]
def point(matrix,p):return [sum(matrix[i][j]*p[j] for j in range(3))+matrix[i][3] for i in range(3)]
def determinant(m):
    return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
           -m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
           +m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))


def local_matrix(t):
    q=t.m_LocalRotation;p=t.m_LocalPosition;s=t.m_LocalScale
    x,y,z,w=q.x,q.y,q.z,q.w
    if not math.isclose(x*x+y*y+z*z+w*w,1,abs_tol=1e-4):raise ScanError('Non-unit Transform quaternion')
    m=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),p.x],
       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),p.y],
       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),p.z],[0,0,0,1]]
    for i in range(3):
        for j,scale in enumerate((s.x,s.y,s.z)):m[i][j]*=scale
    return m


def transform_of(go):
    for pair in go.m_Component:
        ptr=pair[1] if isinstance(pair,tuple) else pair.component
        reader=ptr.deref()
        if reader.type.name=='Transform':return reader.parse_as_object()
    raise ScanError('GameObject has no Transform')


def world_transform(t):
    matrix=identity();visited=set();active=True
    while t is not None:
        reader=t.object_reader;key=(reader.assets_file.name,reader.path_id)
        if key in visited or len(visited)>256:raise ScanError('Invalid Transform hierarchy')
        visited.add(key);active=active and bool(t.m_GameObject.deref_parse_as_object().m_IsActive)
        matrix=multiply(local_matrix(t),matrix)
        t=t.m_Father.deref_parse_as_object() if t.m_Father else None
    return matrix,active


def terrain_surface(heightmap,stride):
    r=heightmap.get('m_Resolution');heights=heightmap.get('m_Heights');limits=heightmap.get('m_MinMaxPatchHeights')
    if (type(r) is not int or not 2<=r<=4097 or type(heights) is not list or len(heights)!=r*r
            or not limits or heightmap.get('m_Holes') or heightmap.get('m_HolesLOD')):
        raise ScanError('Unsupported Terrain resolution/holes encoding')
    if any(type(v) is not int or not 0<=v<=32766 for v in heights):raise ScanError('Unknown Terrain height encoding')
    if (not math.isclose(min(heights)/32766,min(limits),abs_tol=1e-7)
            or not math.isclose(max(heights)/32766,max(limits),abs_tol=1e-7)):
        raise ScanError('Terrain height normalization disagrees with serialized patch bounds')
    if type(stride) is not int or stride<1:raise ScanError('Invalid terrain sample stride')
    samples=list(range(0,r-1,stride))+[r-1];scale=heightmap['m_Scale']
    vertices=[[x*scale['x'],heights[z*r+x]/32766*scale['y'],z*scale['z']] for z in samples for x in samples]
    n=len(samples);triangles=[]
    for z in range(n-1):
        for x in range(n-1):
            a=z*n+x;triangles.extend([[a,a+n,a+1],[a+1,a+n,a+n+1]])
    return vertices,triangles


def box_surface(box):
    e=[getattr(box.m_Size,k)/2 for k in ('x','y','z')];c=box.m_Center
    vertices=[[getattr(c,k)+sign[i]*e[i] for i,k in enumerate(('x','y','z'))]
        for sign in ((-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1),(-1,1,-1),(1,1,-1),(1,1,1),(-1,1,1))]
    flat=[0,1,2,0,2,3,4,6,5,4,7,6,0,4,5,0,5,1,1,5,6,1,6,2,2,6,7,2,7,3,3,7,4,3,4,0]
    return vertices,[flat[i:i+3] for i in range(0,len(flat),3)]


def extract_geometry(main,graph):
    from UnityPy.helpers.MeshHelper import MeshHandler
    vertices=[];triangles=[];included=[]
    for obj in main.get_objects():
        kind=obj.type.name
        if kind not in ('Terrain','BoxCollider','MeshCollider','SphereCollider','CapsuleCollider','TerrainCollider'):continue
        if kind=='TerrainCollider':continue # Terrain's own rasterize flag owns this surface.
        if kind=='Terrain' and not graph['rasterizeTerrain']:continue
        if kind!='Terrain' and not graph['rasterizeColliders']:continue
        asset=obj.parse_as_object();go=asset.m_GameObject.deref_parse_as_object()
        matrix,active=world_transform(transform_of(go))
        if not active or not asset.m_Enabled or getattr(asset,'m_IsTrigger',False):continue
        if not graph['mask']['value'] & (1<<go.m_Layer):continue
        if kind=='Terrain':
            if any(abs(matrix[i][j]-int(i==j))>1e-5 for i in range(3) for j in range(3)):
                raise ScanError('Rotated/scaled Terrain requires independent engine verification')
            data=asset.m_TerrainData.deref_parse_as_dict()
            points,faces=terrain_surface(data['m_Heightmap'],graph['terrainSampleSize'])
        elif kind=='BoxCollider':points,faces=box_surface(asset)
        elif kind=='MeshCollider':
            if asset.m_Convex:raise ScanError('Convex collider requires verified hull geometry')
            mesh=asset.m_Mesh.deref_parse_as_object()
            handler=MeshHandler(mesh);handler.process()
            points=handler.m_Vertices;faces=[list(t) for sub in handler.get_triangles() for t in sub]
            if not points or any(len(t)!=3 for t in faces):raise ScanError('Unsupported MeshCollider topology')
        else:raise ScanError('Unsupported collider: '+kind)
        base=len(vertices);vertices.extend(point(matrix,p) for p in points)
        reflected=determinant(matrix)<0
        triangles.extend([[base+t[0],base+t[2 if reflected else 1],base+t[1 if reflected else 2]] for t in faces])
        included.append({'kind':kind,'path_id':obj.path_id,'layer':go.m_Layer,'triangles':len(faces)})
    if not triangles:raise ScanError('No verified collider/terrain surface matched the Graph filters')
    return {'coordinate_space':'unity_world_y_up','vertices':vertices,'triangles':triangles,'included':included}


def candidate_settings(graph,cell_height):
    if any(graph['rotation'][a]!=0 for a in ('x','y','z')):raise ScanError('Rotated Recast bounds not implemented')
    center=graph['forcedBoundsCenter'];size=graph['forcedBoundsSize']
    return {'cell_size':graph['cellSize'],'cell_height':cell_height,'agent_height':graph['walkableHeight'],
        'agent_climb':graph['walkableClimb'],'agent_radius':graph['characterRadius'],'max_slope':graph['maxSlope'],
        'max_edge_length':graph['maxEdgeLength'],'max_simplification_error':graph['contourMaxError'],
        # These are explicit upstream candidate settings, NOT verified Astar conversions.
        'min_region_area':0,'merge_region_area':0,'detail_sample_distance':graph['cellSize']*6,
        'detail_sample_max_error':cell_height,'bounds_min':[center[a]-size[a]/2 for a in ('x','y','z')],
        'bounds_max':[center[a]+size[a]/2 for a in ('x','y','z')]}


BUILTIN_SHA256='026e6d1d96dc2e28c72ece25f2419469d649a95e25b6929bc5cfc95bca529f8e'


def read_builtin(path):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BUILTIN_SHA256:
        raise ScanError('Unity builtin resources SHA256 does not match the supplied, reviewed source')
    return raw


def rebuild(archive,selection,output,backend,cell_height,builtin_resources=None):
    import UnityPy
    class VerifiedEnvironment(UnityPy.Environment):
        def find_file(self,name,is_dependency=True):
            registered=self.get_cab(name)
            if registered is None:raise FileNotFoundError('Verified dependency not supplied: '+name)
            return registered
    root=Path(output)
    if root.exists():raise FileExistsError(root)
    builtin_raw=read_builtin(builtin_resources) if builtin_resources is not None else None
    report=inspect(archive,selection);graphs=extract(archive,selection)
    rows=load_scene_selection(archive,selection)['bundles']
    root.mkdir(parents=True);results=[]
    with ZipFile(archive) as z:
        for graph in graphs['scenes']:
            model=graph['model_id'];entry={'model_id':model,'can_send_packets':False}
            try:
                env=VerifiedEnvironment();main=None;builtin_evidence=None
                if builtin_raw is not None:
                    builtin=env.load_file(builtin_raw,name='unity default resources')
                    builtin_evidence={'sha256':BUILTIN_SHA256,'bytes':len(builtin_raw),
                                      'unity_version':builtin.unity_version}
                for row in rows:
                    if row['bundle_name'] in (f'mainpackage_scene_{model}.bundle',f'mainpackage_scene_{model}_dependency.bundle'):
                        bundle=env.load_file(z.read('source/'+row['path']),name=row['bundle_name'])
                        if row['bundle_name']==f'mainpackage_scene_{model}.bundle':main=bundle
                geometry=extract_geometry(main,graph['settings'])
                pair=report['scenes'][str(model)]
                geometry['source']={'model_id':str(model),'scene_bundle_sha256':pair['scene']['sha256'],
                    'dependency_bundle_sha256':pair['dependency']['sha256'],'graph_settings_sha256':graph['embedded_zip_sha256']}
                if builtin_evidence:geometry['source']['builtin_resources']=builtin_evidence
                config=candidate_settings(graph['settings'],cell_height)
                candidate=bake(geometry,config,backend)
                candidate['source_files_verified']=True
                candidate['conversion_notes']={'cell_height':'explicit upstream candidate override',
                    'region_areas':'candidate zero, not verified Astar minRegionSize conversion',
                    'dynamic_navmesh_cuts_applied':False,'terrain_stride':graph['settings']['terrainSampleSize']}
                for suffix,data in (('geometry',geometry),('candidate',candidate)):
                    (root/f'{model}_{suffix}.json').write_text(json.dumps(data,allow_nan=False),encoding='utf8')
                entry.update(status='candidate_built',input_triangles=len(geometry['triangles']),triangles=len(candidate['triangles']),included=geometry['included'])
            except (ValueError,OSError,KeyError,AttributeError,TypeError) as exc:
                entry.update(status='blocked',reason=f'{type(exc).__name__}: {exc}')
            results.append(entry)
    summary={'resource_revision':1275,'scenes':results,'built':sum(r['status']=='candidate_built' for r in results),
             'blocked':sum(r['status']=='blocked' for r in results),'settings_equivalence_verified':False,'can_send_packets':False}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    return summary


def main():
    p=argparse.ArgumentParser(description='Rebuild private offline candidate meshes from verified 1275 bundles')
    p.add_argument('--scenes-zip',required=True,type=Path);p.add_argument('--select',type=Path,help='可省略以使用ZIP內附的場景選取清單')
    p.add_argument('--output',required=True,type=Path);p.add_argument('--backend',required=True,type=Path)
    p.add_argument('--cell-height',required=True,type=float,help='Explicit candidate voxel height in metres; not an official Astar-equivalence claim')
    p.add_argument('--builtin-resources',type=Path,help='SHA-pinned unity default resources for built-in collider Mesh references')
    a=p.parse_args();print(json.dumps(rebuild(a.scenes_zip,a.select,a.output,a.backend,a.cell_height,a.builtin_resources),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
