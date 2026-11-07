"""Read AstarPath profiles from verified cached official scene bundles only.

Never downloads or dereferences external files automatically. This records scene
serialization, not subsequent native/runtime overrides or movement authority.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import zlib


def profile(tree):
    if not isinstance(tree,dict):raise ValueError('Require scene object fields')
    result={}
    for key in ('heuristic','heuristicScale','maxNearestNodeDistance','fullGetNearestSearch','scanOnStartup','m_Enabled'):
        if key not in tree:raise ValueError('Missing scene profile field '+key)
        value=tree[key]
        if key in ('fullGetNearestSearch','scanOnStartup','m_Enabled'):
            if type(value) not in (bool,int) or value not in (0,1):raise ValueError('Invalid scene flag '+key)
            value=bool(value)
        elif key=='heuristic':
            if type(value) is not int or not 0<=value<=3:raise ValueError('Unreviewed heuristic enum')
        elif type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100000:raise ValueError('Invalid scene numeric field '+key)
        result[key]=value
    data=tree.get('data')
    if not isinstance(data,dict):raise ValueError('Missing scene AstarData')
    cache=data.get('cacheStartup')
    if type(cache) not in (bool,int) or cache not in (0,1):raise ValueError('Invalid scene cacheStartup')
    result['cacheStartup']=bool(cache)
    return result


def inspect(manifest_root,bundle_root):
    from wlre.services.official_manifest_sync import ManifestSpec,read_verified_cached_manifest
    from wlre.services.official_bundle_download import spec_from_manifest
    from wlre.services.world.navigation_database import REVIEWED_MODELS
    manifest=read_verified_cached_manifest(ManifestSpec('1.3.23','MainPackage','1296_2026_11_04_13_36_07_72'),cache_root=Path(manifest_root))
    import UnityPy
    rows=[];total=0
    for model in REVIEWED_MODELS:
        if model in (10000,10004,10005):continue
        spec=spec_from_manifest(data_ver=manifest.spec.data_ver,package=manifest.spec.package,index=manifest.index,name=f'mainpackage_scene_{model}.bundle')
        if spec.file_size>1024*1024:raise ValueError('Scene exceeds research bound')
        total+=spec.file_size
        if total>20*1024*1024:raise ValueError('Scene aggregate bound')
        path=spec.cache_path(Path(bundle_root))
        with path.open('rb') as stream:raw=stream.read(1024*1024+1)
        if len(raw)!=spec.file_size or hashlib.md5(raw,usedforsecurity=False).hexdigest()!=spec.file_hash.lower() or (zlib.crc32(raw)&0xffffffff).to_bytes(4,'little').hex()!=spec.file_crc.lower():raise ValueError('Unverified cached scene '+str(model))
        env=UnityPy.load(raw);objects={};scripts={}
        for obj in env.objects:
            key=(obj.assets_file.name,obj.path_id)
            if key in objects:raise ValueError('Ambiguous scene object identity')
            objects[key]=obj
            if obj.type.name=='MonoScript':scripts[key]=obj.read_typetree()
        matches=[]
        for obj in objects.values():
            if obj.type.name!='MonoBehaviour':continue
            tree=obj.read_typetree();ref=tree.get('m_Script',{});fid=ref.get('m_FileID');pid=ref.get('m_PathID')
            if type(fid) is not int or fid<0 or fid>len(obj.assets_file.externals):raise ValueError('Invalid scene script reference')
            file=obj.assets_file.name if fid==0 else obj.assets_file.externals[fid-1].path.rsplit('/',1)[-1]
            script=scripts.get((file,pid))
            # Only resolve objects contained in these verified bytes.
            if script is None:
                if 'heuristic' in tree:raise ValueError('Unresolved possible AstarPath script')
                continue
            if script.get('m_ClassName')!='AstarPath':continue
            if script.get('m_AssemblyName')!='AstarPathfindingProject.dll' or script.get('m_Namespace')!='':raise ValueError('Unexpected AstarPath script identity')
            go=tree.get('m_GameObject',{})
            if go.get('m_FileID')!=0:raise ValueError('External AstarPath owner')
            owner=objects.get((obj.assets_file.name,go.get('m_PathID')))
            if owner is None or owner.type.name!='GameObject':raise ValueError('Missing AstarPath owner')
            owner_tree=owner.read_typetree()
            matches.append(dict(object_id=obj.path_id,asset_file=obj.assets_file.name,script=script['m_ClassName'],script_file=file,script_id=pid,owner_id=owner.path_id,owner_name=owner_tree.get('m_Name'),owner_active=owner_tree.get('m_IsActive'),settings=profile(tree)))
        if len(matches)!=1:raise ValueError('Require exactly one verified AstarPath per scene')
        rows.append(dict(model=model,bundle_name=spec.name,bytes=len(raw),manifest_md5=spec.file_hash,manifest_crc=spec.file_crc,sha256=hashlib.sha256(raw).hexdigest(),astar=matches[0]))
    return dict(resource_platform='ResourcesPC',manifest_sha256=hashlib.sha256(manifest.cache_path.read_bytes()).hexdigest(),data_version=manifest.spec.data_ver,package_version=manifest.spec.package_version,unitypy_version=UnityPy.__version__,scenes=rows,total_bytes=total,can_send_packets=False,scope=__doc__)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--manifest-root',required=True);parser.add_argument('--bundle-root',required=True);args=parser.parse_args()
    print(json.dumps(inspect(args.manifest_root,args.bundle_root),sort_keys=True))


if __name__=='__main__':main()
