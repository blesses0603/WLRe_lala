"""Read-only coverage inventory; availability is not movement authorization."""
import argparse
from collections import Counter
import hashlib
import json
from wlre.services.world.house_navigation import HOUSE_MODELS,HOUSE_TEMPLATES,HOUSE_MIN,HOUSE_MAX
from wlre.services.world.navigation_database import REVIEWED_MODELS
from wlre.services.world.navigation_sync import MAX_BYTES, REVIEWED_DEPENDENCY_MODELS


def inventory(stages,index):
    models={};excluded=[]
    for scene,row in stages.items():
        scene=int(scene);model=row['model_id']
        if scene in HOUSE_TEMPLATES.values() or HOUSE_MIN<=scene<=HOUSE_MAX or model in HOUSE_MODELS:
            excluded.append(scene);continue
        models.setdefault(model,[]).append(scene)
    rows=[]
    for model,scenes in sorted(models.items()):
        assets=[a for a in index['assets'] if a.get('address')==f'M{model:05d}' and a['path'].endswith(f'/M{model:05d}.unity')]
        result=dict(model=model,stage_ids=sorted(scenes),reviewed_cache=model in REVIEWED_MODELS,can_send_packets=False)
        if len(assets)!=1:result['status']='missing_or_ambiguous_scene_asset'
        else:
            root=assets[0]['bundle_name'];dependency_model=REVIEWED_DEPENDENCY_MODELS.get(model,model)
            dep=f'mainpackage_scene_{dependency_model:05d}_dependency.bundle'
            roots=[b for b in index['bundles'] if b['name']==root]
            deps=[b for b in index['bundles'] if b['name']==dep]
            if len(roots)!=1 or len(deps)!=1:result['status']='missing_or_ambiguous_bundle'
            elif dep not in roots[0]['dependencies']:result['status']='candidate_dependency_not_declared'
            else:
                result['bundle_bytes']=roots[0]['file_size']+deps[0]['file_size']
                result['status']='within_download_budget' if result['bundle_bytes']<=MAX_BYTES else 'exceeds_download_budget'
        rows.append(result)
    return dict(models=rows,model_count=len(rows),stage_count=sum(len(r['stage_ids']) for r in rows),
                excluded_house_stages=sorted(excluded),statuses=dict(Counter(r['status'] for r in rows)),
                reviewed_models=sum(r['reviewed_cache'] for r in rows),can_send_packets=False,
                note='Manifest candidates only: exact cache pointer, format, version and path parity still require validation.')


def audit(runtime,manifest):
    identity=runtime.catalog_identity
    revision=next(p for p in identity.packages if p.name=='MainPackage')
    if (manifest.spec.data_ver!=identity.data_ver or manifest.spec.package!='MainPackage'
            or manifest.spec.package_version!=revision.full_version
            or hashlib.sha256(manifest.cache_path.read_bytes()).hexdigest()!=revision.manifest_sha256):
        raise ValueError('Coverage manifest does not match current runtime')
    result=inventory(runtime.stages,manifest.index)
    result['catalog_key']=identity.key
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args()
    from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime
    from wlre.services.official_manifest_sync import ManifestSpec,read_verified_cached_manifest
    from wlre.storage.paths import data_root
    runtime=prepare_dynamic_runtime(sync=False);identity=runtime.catalog_identity
    revision=next(p for p in identity.packages if p.name=='MainPackage')
    manifest=read_verified_cached_manifest(ManifestSpec(identity.data_ver,'MainPackage',revision.full_version),cache_root=data_root()/'official_sync'/'manifests')
    if manifest is None:parser.exit(1,'Verified current manifest is unavailable.\n')
    print(json.dumps(audit(runtime,manifest),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
