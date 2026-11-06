"""On-demand complete-bundle extraction, bounded to one reviewed model."""
import hashlib
from pathlib import Path
from wlre.services.world.navigation_database import REVIEWED_MODELS, import_cache, record_failure, database_path

MAX_BYTES=32*1024*1024
MAX_FILES=2


def sync_model(identity,model,*,root=None,fetch=None,manifest=None,observe=None):
    from wlre.storage.paths import data_root
    from wlre.services.official_manifest_sync import fetch_official_manifest, ManifestSpec
    from wlre.services.official_bundle_download import fetch_bundle, spec_from_manifest, _verified_file
    from wlre.services.official_resource_sync import observe_official_versions, validate_snapshot
    if type(model) is not int or model not in REVIEWED_MODELS:
        raise ValueError('Navigation model requires format review')
    from wlre.services.world.house_navigation import require_general_navigation
    require_general_navigation(model=model)
    root=Path(root) if root is not None else data_root()/'official_sync'
    database=database_path(root);version=identity.key
    observe=observe or observe_official_versions
    fetch=fetch or fetch_bundle
    expected={p.name:p.full_version for p in identity.packages}
    def check_version():
        current=validate_snapshot(observe())
        if current['data_ver']!=identity.data_ver or current['exe_version']!=identity.exe_version or current['packages']!=expected:
            raise ValueError('Official navigation version changed; refresh runtime')
    try:
        check_version()
        revision=next(p for p in identity.packages if p.name=='MainPackage')
        manifest=manifest or fetch_official_manifest(ManifestSpec(identity.data_ver,'MainPackage',revision.full_version),cache_root=root/'manifests')
        if (manifest.spec.data_ver!=identity.data_ver or manifest.spec.package_version!=revision.full_version
                or hashlib.sha256(manifest.cache_path.read_bytes()).hexdigest()!=revision.manifest_sha256):
            raise ValueError('Navigation manifest differs from active runtime')
        assets=[a for a in manifest.index['assets'] if a.get('address')==f'M{model:05d}' and a['path'].endswith(f'/M{model:05d}.unity')]
        if len(assets)!=1:raise ValueError('Navigation scene asset is not unique')
        name=assets[0]['bundle_name'];rows=[b for b in manifest.index['bundles'] if b['name']==name]
        if len(rows)!=1:raise ValueError('Navigation scene bundle is not unique')
        # Reviewed naming narrows a candidate only; exact CAB + path ID below
        # must resolve the serialized pointer before any bytes can be imported.
        dep=f'mainpackage_scene_{model:05d}_dependency.bundle'
        if dep not in rows[0]['dependencies']:raise ValueError('Navigation dependency not declared by manifest')
        specs=[spec_from_manifest(data_ver=identity.data_ver,package='MainPackage',index=manifest.index,name=n) for n in (name,dep)]
        if len(specs)>MAX_FILES or sum(s.file_size for s in specs)>MAX_BYTES:
            raise ValueError('Navigation download exceeds 32 MiB / 2 bundle budget')
        paths=[]
        for spec in specs:
            path=fetch(spec,cache_root=root/'bundles')
            if not _verified_file(path,spec):raise ValueError('Navigation bundle verification failed')
            paths.append(path)
        raw,pointer=extract_cache(paths,model)
        check_version()
        provenance={'identity':identity.as_dict(),'bundles':[dict(name=s.name,md5=s.file_hash,crc=s.file_crc,size=s.file_size) for s in specs], 'pointer':pointer}
        return import_cache(database,version,model,raw,provenance)
    except (OSError,ValueError,RuntimeError,ImportError) as error:
        record_failure(database,version,model,error)
        raise


def extract_cache(paths,model):
    import UnityPy
    candidates=[]
    for obj in UnityPy.load(str(paths[0])).objects:
        if obj.type.name!='MonoBehaviour':continue
        data=obj.read_typetree().get('data')
        if isinstance(data,dict) and 'file_cachedStartup' in data:candidates.append((obj,data))
    if len(candidates)!=1:raise ValueError('Navigation cache pointer is ambiguous')
    obj,data=candidates[0];ref=data['file_cachedStartup']
    if data.get('cacheStartup')!=1 or not 1<=ref['m_FileID']<=len(obj.assets_file.externals):
        raise ValueError('Unsupported navigation cache source')
    external=obj.assets_file.externals[ref['m_FileID']-1].path
    targets=[o for o in UnityPy.load(str(paths[1])).objects
             if o.type.name=='TextAsset' and o.path_id==ref['m_PathID'] and external.endswith('/'+o.assets_file.name)]
    if len(targets)!=1:raise ValueError('Navigation external CAB/path ID unresolved')
    tree=targets[0].read_typetree()
    if tree['m_Name']!=str(model):raise ValueError('Navigation TextAsset model mismatch')
    raw=tree['m_Script'];raw=raw.encode('utf-8','surrogateescape') if isinstance(raw,str) else bytes(raw)
    return raw,dict(external=external,path_id=ref['m_PathID'])
