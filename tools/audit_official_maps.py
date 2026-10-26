"""Audit pinned official minimap assets; optionally fetch and decode exact Bundles.

Private outputs only. A manifest ID match is not a pixel or projection match.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED

from wlre.services.world.bundle_runtime_1275 import _PINNED_MANIFEST_SHA256
from tools.resources.lala_manifest_full_index import parse_manifest


def map_assets(index):
    rows = {}
    for asset in index['assets']:
        match = re.fullmatch(r'Assets/ResourcesBuild/Texture/SmallMap2D/SmallMap2D_(\d+)\.png', asset['path'])
        if not match: continue
        model = int(match[1])
        if model in rows: raise ValueError('Duplicate official minimap ID')
        rows[model] = asset
    if not rows: raise ValueError('No exact SmallMap2D assets in the verified index')
    return rows


def audit(index, local_archive, decoded=None):
    from PIL import Image
    assets = map_assets(index)
    bundles = {row['name']: row for row in index['bundles']}
    models = sorted({int(match[1]) for name in bundles
        if (match := re.fullmatch(r'mainpackage_scene_(\d+)\.bundle', name))})
    rows, local_ids = [], set()
    with ZipFile(local_archive) as z:
        entries = z.namelist()
        if len(entries) != len(set(entries)): raise ValueError('Duplicate local image entries')
        local = {}
        for item in json.loads(z.read('image_index.json')):
            match = re.fullmatch(r'SmallMap2D_(\d+)', item['name'])
            if not match: raise ValueError('Unknown local image identity')
            model = int(match[1])
            if model in local: raise ValueError('Duplicate local minimap ID')
            local[model] = item
        for model, asset in sorted(assets.items()):
            item = local.get(model)
            entry = item.get('entry', item['name'] + '.png') if item else None
            present = entry in entries if entry else False
            result = {'model_id': model, 'asset_path': asset['path'], 'local_present': present,
                      'bundle_hash': bundles[asset['bundle_name']]['file_hash'],
                      'pixels_compared': False, 'pixel_changed': None}
            old = None
            if present:
                raw = z.read(entry)
                if item.get('encoded_sha256') and hashlib.sha256(raw).hexdigest() != item['encoded_sha256']:
                    raise ValueError('Local image checksum mismatch')
                with Image.open(io.BytesIO(raw)) as im:
                    if im.size != (1024, 1024): raise ValueError('Unreviewed local minimap dimensions')
                    old = hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest()
                local_ids.add(model)
            if decoded is not None:
                image = decoded(model, asset)
                if image.size != (1024, 1024): raise ValueError('Unreviewed official minimap dimensions')
                digest = hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()
                result.update(pixels_compared=present, pixel_changed=(old != digest) if present else None,
                              official_rgba_sha256=digest)
            rows.append(result)
    return {'resource_revision': 1275, 'official_map_count': len(assets),
            'local_matching_ids': len(local_ids), 'missing_ids': sorted(set(assets) - local_ids),
            'scene_model_count': len(models),
            'official_models_without_minimap_asset': sorted(set(models) - set(assets)),
            'pixel_comparison_complete': decoded is not None,
            'current_online_version_observed': False, 'maps': rows, 'can_send_packets': False,
            'note': 'Scene model IDs are not logical scene IDs. No image is fabricated for models without an official asset.'}


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--manifest', type=Path, help='Pinned 1275 MainPackage .bytes for offline ID audit')
    group.add_argument('--online', action='store_true', help='Observe official versions, verify and fetch needed map Bundles')
    parser.add_argument('--local', type=Path, default=Path('wlre/resources/smallmaps.zip'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists(): raise FileExistsError(args.output_dir)
    envs = None
    snapshot = None
    if args.online:
        from wlre.services.official_resource_sync import observe_official_versions
        from wlre.services.official_manifest_sync import fetch_official_manifest, spec_from_snapshot
        from wlre.services.official_incremental_sync import build_update_plan, execute_update_plan
        from wlre.services.resource_compatibility import load_supported_resources
        snapshot = observe_official_versions()
        baseline = load_supported_resources()
        if any(snapshot['packages'][p] != baseline['packages'][p]['manifest'] for p in ('MainPackage','DataPackage')):
            raise ValueError('Unreviewed official version; map activation refused')
        verified = fetch_official_manifest(spec_from_snapshot(snapshot, 'MainPackage'))
        raw = verified.cache_path.read_bytes()
    else:
        raw = args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _PINNED_MANIFEST_SHA256['MainPackage']:
        raise ValueError('Official MainPackage is not the reviewed 1275 source')
    index = parse_manifest(raw)
    if args.online:
        plan = build_update_plan(verified, asset_paths=tuple(row['path'] for row in map_assets(index).values()))
        execute_update_plan(plan, download=True, max_download_bytes=64*1024*1024)
        finish = observe_official_versions()
        if any(finish[k] != snapshot[k] for k in ('packages','data_ver','exe_version')):
            raise ValueError('Official version changed during download; refusing export')
        import UnityPy
        envs = {entry.spec.name: UnityPy.load(str(entry.spec.cache_path())) for entry in plan.entries}
    args.output_dir.mkdir(parents=True)
    archive = None
    try:
        if envs is not None: archive = ZipFile(args.output_dir/'official_smallmaps_1275.zip','x',ZIP_DEFLATED)
        image_index = []
        def decoded(model, asset):
            from wlre.services.world.unity_textasset import _find_exact_container_object
            obj = _find_exact_container_object(envs[asset['bundle_name']].container, asset['path'])
            if obj is None or obj.type.name not in ('Texture2D','Sprite'):
                raise ValueError('Official map path does not resolve uniquely to a supported image')
            data = obj.read()
            if data.m_Name != 'SmallMap2D_'+str(model): raise ValueError('Official image identity mismatch')
            image = data.image.convert('RGBA')
            if image.size != (1024,1024): raise ValueError('Unreviewed official image dimensions')
            buffer = io.BytesIO();image.save(buffer,format='PNG');blob = buffer.getvalue()
            entry = 'SmallMap2D_'+str(model)+'.png'
            archive.writestr(entry,blob)
            image_index.append({'name':'SmallMap2D_'+str(model),'entry':entry,'width':1024,'height':1024,
                                'encoded_sha256':hashlib.sha256(blob).hexdigest()})
            return image
        report = audit(index,args.local,decoded if envs is not None else None)
        report['current_online_version_observed'] = snapshot is not None
        if archive:
            archive.writestr('image_index.json',json.dumps(image_index))
            archive.writestr('provenance.json',json.dumps({'manifest_sha256':hashlib.sha256(raw).hexdigest(),
                'role':'offline_image_comparison_only','coordinate_mapping_verified':False,'can_send_packets':False}))
        (args.output_dir/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:report[k] for k in ('official_map_count','local_matching_ids','missing_ids','pixel_comparison_complete')},ensure_ascii=False))
    except Exception:
        if archive:
            archive.close();(args.output_dir/'official_smallmaps_1275.zip').unlink(missing_ok=True)
        raise
    finally:
        if archive: archive.close()


if __name__ == '__main__': main()
