"""Bake offline candidate meshes using real Recast; never enable live movement."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from tools.navigation.build_recast import COMMIT


class ScanError(ValueError):pass


def _number(value,name,minimum=0):
    if type(value) not in (int,float) or not math.isfinite(value) or value<minimum:
        raise ScanError('Invalid '+name)
    return value


def validate(geometry,settings):
    if type(geometry) is not dict or geometry.get('coordinate_space')!='unity_world_y_up':
        raise ScanError('Geometry must explicitly use Unity world-space Y-up metres')
    vertices=geometry.get('vertices');triangles=geometry.get('triangles')
    if type(vertices) is not list or not 3<=len(vertices)<=2_000_000:
        raise ScanError('Invalid vertex count')
    if type(triangles) is not list or not 1<=len(triangles)<=4_000_000:
        raise ScanError('Invalid triangle count')
    for vertex in vertices:
        if type(vertex) is not list or len(vertex)!=3:raise ScanError('Invalid vertex')
        for value in vertex:
            if type(value) not in (int,float) or not math.isfinite(value):raise ScanError('Non-finite vertex')
    for tri in triangles:
        if (type(tri) is not list or len(tri)!=3
                or any(type(i) is not int or not 0<=i<len(vertices) for i in tri) or len(set(tri))!=3):
            raise ScanError('Invalid triangle')
    required=('cell_size','cell_height','agent_height','agent_climb','agent_radius','max_slope',
              'max_edge_length','max_simplification_error','min_region_area','merge_region_area',
              'detail_sample_distance','detail_sample_max_error','bounds_min','bounds_max')
    if type(settings) is not dict or set(settings)!=set(required):raise ScanError('All scan settings must be explicit')
    for name in required[:-2]:_number(settings[name],name)
    if (settings['cell_size']<=0 or settings['cell_height']<=0 or settings['agent_height']<=0
            or settings['max_slope']>=90):raise ScanError('Invalid voxel or agent dimensions')
    lower,upper=settings['bounds_min'],settings['bounds_max']
    for bound in (lower,upper):
        if type(bound) is not list or len(bound)!=3:raise ScanError('Invalid scan bounds')
        for v in bound:
            if type(v) not in (int,float) or not math.isfinite(v):raise ScanError('Invalid scan bounds')
    if any(upper[i]<=lower[i] for i in range(3)):raise ScanError('Empty scan bounds')
    if (math.ceil((upper[0]-lower[0])/settings['cell_size'])*
            math.ceil((upper[2]-lower[2])/settings['cell_size'])>16_000_000):
        raise ScanError('Grid cell budget exceeded; verified tiling is required')
    if (upper[1]-lower[1])/settings['cell_height']>=8191:raise ScanError('Vertical span overflow')
    if math.ceil(settings['agent_height']/settings['cell_height'])<3:raise ScanError('Agent must span at least three height cells')
    if (settings['agent_radius']/settings['cell_size']>32768
            or settings['agent_climb']/settings['cell_height']>8191
            or settings['max_edge_length']/settings['cell_size']>32768
            or max(settings['min_region_area'],settings['merge_region_area'])>16_000_000):
        raise ScanError('Scan parameters exceed Recast limits')
    return vertices,triangles


def bake(geometry,settings,backend,*,timeout=120):
    vertices,triangles=validate(geometry,settings)
    header=[len(vertices),len(triangles),settings['cell_size'],settings['cell_height'],
        settings['agent_height'],settings['agent_climb'],settings['agent_radius'],settings['max_slope'],
        int(settings['max_edge_length']/settings['cell_size']),settings['max_simplification_error'],
        settings['min_region_area'],settings['merge_region_area'],settings['detail_sample_distance'],
        settings['detail_sample_max_error']]
    payload='\n'.join(' '.join(map(str,row)) for row in
        [header,*vertices,*triangles,settings['bounds_min'],settings['bounds_max']])+'\n'
    executable=Path(backend).resolve(strict=True)
    run=subprocess.run([str(executable)],input=payload,text=True,capture_output=True,timeout=timeout)
    if run.returncode:raise ScanError('Recast scan failed: '+run.stderr.strip())
    result=json.loads(run.stdout)
    # Validate actual output independently of a successful process exit.
    if result.get('triangles'):
        validate({'coordinate_space':'unity_world_y_up',**result},settings)
    elif result!={'vertices':[],'triangles':[]}:raise ScanError('Malformed empty Recast output')
    return {
        'schema_version':1,'resource_revision':1275,'kind':'offline_recast_candidate',
        'backend':'Recast 1.6.0','backend_commit':COMMIT,
        'backend_binary_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'input_sha256':hashlib.sha256(json.dumps(geometry,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'settings':settings,'coordinate_space':'unity_world_y_up',
        'source':geometry.get('source',{}),'vertices':result['vertices'],'triangles':result['triangles'],
        'recast_scan_performed':True,'settings_equivalence_verified':False,
        'source_geometry_verified':False,'live_movement_verified':False,'can_send_packets':False,
    }


def verify_sources(geometry,scenes_archive,selection_file):
    """Match export provenance to SHA-verified real scene/configuration archives.

    This verifies source files, not Unity export fidelity or official scan equivalence.
    """
    from tools.resources.extract_1275_recast_settings import extract
    from tools.resources.audit_1275_scene_collision import inspect
    report=inspect(scenes_archive,selection_file)
    settings=extract(scenes_archive,selection_file)
    source=geometry.get('source',{})
    model=str(source.get('model_id',''))
    pair=report['scenes'].get(model)
    graph=next((row for row in settings['scenes'] if str(row['model_id'])==model),None)
    if (not pair or not graph or source.get('scene_bundle_sha256')!=pair['scene']['sha256']
            or source.get('dependency_bundle_sha256')!=pair['dependency']['sha256']
            or source.get('graph_settings_sha256')!=graph['embedded_zip_sha256']):
        raise ScanError('Export provenance does not match the verified 1275 scene and graph')
    return {'model_id':int(model),'scene_bundle_sha256':pair['scene']['sha256'],
            'dependency_bundle_sha256':pair['dependency']['sha256'],
            'embedded_graph_zip_sha256':graph['embedded_zip_sha256'],
            'source_files_verified':True,'geometry_export_verified':False}


def to_offline_mesh(candidate):
    """Adapt world metres to the existing offline Int3 mesh reader only."""
    from wlre.services.world.navigation import Mesh
    vertices=[];indices={};remap=[]
    for point in candidate['vertices']:
        key=tuple(round(v*1000) for v in point)
        if key not in indices:indices[key]=len(vertices);vertices.append(list(key))
        remap.append(indices[key])
    triangles=[[remap[i] for i in tri] for tri in candidate['triangles']]
    return Mesh({'tiles':[{'vertices_b_int3':vertices,'triangles':triangles}]})


def main():
    p=argparse.ArgumentParser(description='Scan world-space geometry into an offline candidate mesh')
    p.add_argument('--geometry',type=Path,required=True);p.add_argument('--settings',type=Path,required=True)
    p.add_argument('--backend',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--scenes-zip',type=Path);p.add_argument('--select',type=Path)
    args=p.parse_args()
    if bool(args.scenes_zip)!=bool(args.select):p.error('--scenes-zip and --select must be supplied together')
    if args.output.exists():raise FileExistsError(args.output)
    geometry=json.loads(args.geometry.read_text())
    evidence=verify_sources(geometry,args.scenes_zip,args.select) if args.scenes_zip else None
    result=bake(geometry,json.loads(args.settings.read_text()),args.backend)
    if evidence:result['source_verification']=evidence
    with args.output.open('x',encoding='utf8') as out:json.dump(result,out,allow_nan=False)
    print(json.dumps({'triangles':len(result['triangles']),'can_send_packets':False}))

if __name__=='__main__':main()
