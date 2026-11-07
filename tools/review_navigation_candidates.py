"""Offline format inspection of verified scene Bundles; never activates candidates.

Use a trusted official Manifest SHA-256 and already downloaded complete Bundles.
Output is review evidence, not a database import or movement authorization.
"""
import argparse
import hashlib
import json
from pathlib import Path
from wlre.services.official_bundle_download import spec_from_manifest, _verified_file
from wlre.services.world.astar_cache import inspect_cache_format
from wlre.services.world.navigation_sync import extract_cache, MAX_BYTES, REVIEWED_DEPENDENCY_MODELS
from wlre.services.world.house_navigation import require_general_navigation
from tools.resources.lala_manifest_full_index import parse_manifest


def inspect_model(index, data_ver, model, bundle_dir):
    require_general_navigation(model=model)
    assets=[a for a in index['assets'] if a.get('address')==f'M{model:05d}' and a['path'].endswith(f'/M{model:05d}.unity')]
    if len(assets)!=1:raise ValueError('Scene asset is not unique')
    name=assets[0]['bundle_name'];dependency_model=REVIEWED_DEPENDENCY_MODELS.get(model,model)
    dep=f'mainpackage_scene_{dependency_model:05d}_dependency.bundle'
    roots=[b for b in index['bundles'] if b['name']==name]
    if len(roots)!=1 or dep not in roots[0]['dependencies']:raise ValueError('Dependency is not declared')
    specs=[spec_from_manifest(data_ver=data_ver,package='MainPackage',index=index,name=n) for n in (name,dep)]
    if sum(s.file_size for s in specs)>MAX_BYTES:raise ValueError('Candidate exceeds bundle budget')
    paths=[Path(bundle_dir)/s.name for s in specs]
    if not all(_verified_file(p,s) for p,s in zip(paths,specs)):raise ValueError('Missing or corrupt Bundle')
    raw,pointer=extract_cache(paths,model)
    result=inspect_cache_format(raw)
    return dict(model=model,status='format_inspected_not_activated',sha256=hashlib.sha256(raw).hexdigest(),
                pointer=pointer,cache_bytes=len(raw),triangles=len(result['mesh']['tiles'][0]['triangles']),
                serializer_version=result['serializer_version'],can_send_packets=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--data-version',required=True)
    p.add_argument('--bundle-dir',required=True,type=Path)
    p.add_argument('--models',required=True,help='Comma-separated numeric model IDs')
    args=p.parse_args();raw=args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.manifest_sha256:p.error('Manifest SHA-256 mismatch')
    index=parse_manifest(raw)
    if index['header']['package_name']!='MainPackage':p.error('Expected MainPackage')
    rows=[]
    for model in sorted(set(int(v) for v in args.models.split(','))):
        try:rows.append(inspect_model(index,args.data_version,model,args.bundle_dir))
        except (OSError,ValueError,RuntimeError,ImportError) as error:
            rows.append(dict(model=model,status='blocked',reason=str(error),can_send_packets=False))
    print(json.dumps(dict(manifest_sha256=args.manifest_sha256,models=rows,can_send_packets=False),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
