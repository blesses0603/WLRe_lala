"""Offline verification of privately supplied YooAsset Manifest and Bundle files.

ZIP .hash consistency is not independent proof of live official authenticity.
No CDN access, game network commands, source activation or data uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import zlib

from tools.resources.lala_manifest_full_index import parse_manifest
from wlre.services.official_bundle_download import _verified_file, spec_from_manifest
from wlre.services.official_manifest_sync import MAX_MANIFEST_BYTES
from wlre.services.world.auto_catalog import _ASSET_ROOT, _SOURCE_MAP
from wlre.services.world.catalog_adapters import FEATURES, SourceContract, parse_feature
from wlre.services.world.official_catalog_pipeline import AssetBinding


class OfflineVerificationError(ValueError):
    """A local archive, Bundle fingerprint or TextAsset format failed validation."""


def inspect_manifest_zip(path, package):
    if package not in ('DataPackage', 'MainPackage'):
        raise OfflineVerificationError('Invalid Package')
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if (len(members) != 2 or any(m.is_dir() for m in members)
                    or len({m.filename for m in members}) != 2
                    or any('/' in m.filename or '\\' in m.filename for m in members)):
                raise OfflineVerificationError('Manifest ZIP must contain two flat entries')
            names = [m.filename for m in members]
            matching = [n for n in names if n.startswith(package + '_') and n.endswith('.bytes')]
            if len(matching) != 1:
                raise OfflineVerificationError('Package Manifest filename mismatch')
            name = matching[0]
            hash_name = name[:-6] + '.hash'
            if hash_name not in names:
                raise OfflineVerificationError('Package Manifest hash is absent')
            m = archive.getinfo(name)
            if not 0 < m.file_size <= MAX_MANIFEST_BYTES or archive.getinfo(hash_name).file_size != 8:
                raise OfflineVerificationError('Manifest ZIP entry exceeds size limits')
            raw = archive.read(name)
            hash_text = archive.read(hash_name).decode('ascii').lower()
    except (OSError, zipfile.BadZipFile, RuntimeError, UnicodeError) as exc:
        raise OfflineVerificationError('Cannot read local Manifest archive') from exc
    computed = (zlib.crc32(raw) & 0xffffffff).to_bytes(4, 'little').hex()
    if hash_text != computed:
        raise OfflineVerificationError('Manifest CRC32 mismatch')
    try:
        index = parse_manifest(raw)
    except (ValueError, KeyError, TypeError) as exc:
        raise OfflineVerificationError('YooAsset 2.2.5 parse failed') from exc
    revision = name[len(package)+1:-6]
    h = index['header']
    if (h['package_name'] != package or h['package_version'] != revision
            or h['file_version'] != '2.2.5' or h['output_name_style'] != 1):
        raise OfflineVerificationError('Package header/revision mismatch')
    return ({
        'package': package, 'revision': revision,
        'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest_crc32_le': hash_text,
        'asset_count': index['asset_count'],
        'bundle_count': index['bundle_count'],
    }, index)


def required_bundle_set(index, data_ver):
    assets = {a['path']: a['bundle_name'] for a in index['assets']}
    lookup = {b['name']: b for b in index['bundles']}
    selected, roots = {}, set()
    for feature in FEATURES:
        asset, _, _, related = _SOURCE_MAP[feature]
        names = set()
        for name in (asset, *related):
            full = _ASSET_ROOT + name
            if full not in assets:
                raise OfflineVerificationError('Required exact AssetPath missing: ' + full)
            names.add(assets[full])
        selected[feature] = names
        roots.update(names)

    selected_all, visiting, specs = set(), set(), {}
    def visit(name):
        if name in visiting:
            raise OfflineVerificationError('Cyclic Bundle dependencies')
        if name in selected_all:
            return
        row = lookup.get(name)
        if row is None:
            raise OfflineVerificationError('Missing Bundle dependency')
        visiting.add(name)
        for dep in row['dependencies']:
            visit(dep)
        visiting.remove(name)
        selected_all.add(name)
        specs[name] = spec_from_manifest(
            data_ver=data_ver, package='DataPackage', index=index, name=name)

    for name in roots:
        visit(name)
    for feature, names in selected.items():
        result = set()
        def collect(name):
            if name in result:
                return
            result.add(name)
            for dep in lookup[name]['dependencies']:
                collect(dep)
        for name in names:
            collect(name)
        selected[feature] = tuple(sorted(result))
    return specs, selected


def scan_game_yoo_bundle_cache(yoo_root, specs, *, max_candidates=40000):
    """Find known official Bundle *contents* in YooAsset hashed __data files.

    The game stores Bundle bytes at hashed paths, not necessarily under their
    original .bundle names. Search only DataPackage/BundleFiles and inspect
    candidates with exact Manifest sizes before MD5/CRC checks.
    Read-only; never rename/delete the game's files or follow symlinks.
    """
    root = Path(yoo_root) / 'DataPackage' / 'BundleFiles'
    if not root.is_dir() or root.is_symlink():
        raise OfflineVerificationError('Game YooAsset DataPackage/BundleFiles unavailable')
    needed = {}
    for name, spec in specs.items():
        needed.setdefault(spec.file_size, []).append((name, spec))
    located = {}
    for count, path in enumerate(root.rglob('__data'), start=1):
        if count > max_candidates:
            raise OfflineVerificationError('Too many hashed Bundle candidates')
        if (path.is_symlink() or not path.is_file()
                or any(part.is_symlink() for part in path.parents
                       if part != root and root in part.parents)):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        for name, spec in needed.get(size, ()):
            if name not in located and _verified_file(path, spec):
                located[name] = path
        if len(located) == len(specs):
            break
    return located


def verify_local(data_zip, main_zip, *, data_ver, bundle_dir=None,
                 bundle_cache_root=None, game_yoo=None,
                 decode=False, extractor=None):
    """Validate archives, then optionally verify and decode all real Bundles."""
    if sum(x is not None for x in
           (bundle_dir, bundle_cache_root, game_yoo)) > 1:
        raise OfflineVerificationError('Choose exactly one Bundle storage root')
    if decode and all(x is None for x in (bundle_dir, bundle_cache_root, game_yoo)):
        raise OfflineVerificationError('Decode needs verified local Bundle paths')
    data, index = inspect_manifest_zip(data_zip, 'DataPackage')
    main, _ = inspect_manifest_zip(main_zip, 'MainPackage')
    specs, selected = required_bundle_set(index, data_ver)
    scanned = (scan_game_yoo_bundle_cache(game_yoo, specs)
               if game_yoo is not None else {})
    bundles, paths = {}, {}
    for name, spec in sorted(specs.items()):
        path = (scanned.get(name) if game_yoo is not None else
                spec.cache_path(bundle_cache_root) if bundle_cache_root is not None
                else Path(bundle_dir) / name if bundle_dir is not None else None)
        exists = path is not None and path.is_file()
        ok = bool(exists and _verified_file(path, spec))
        bundles[name] = {
            'size': spec.file_size, 'md5': spec.file_hash,
            'crc32_le': spec.file_crc,
            'status': ('verified' if ok else
                       'invalid_checksum' if exists else 'missing'),
        }
        if ok:
            paths[name] = path
    report = {
        'source': 'user_supplied_local_archives',
        'live_official_authentication': False,
        'packages': [data, main],
        'required_bundle_count': len(specs),
        'required_bundle_bytes': sum(b.file_size for b in specs.values()),
        'bundles': bundles,
        'features': {key: list(names) for key, names in selected.items()},
        'decoded': False, 'approved': False,
        'assets_ready': False, 'can_send_packets': False,
    }
    if not decode:
        return report
    if len(paths) != len(specs):
        raise OfflineVerificationError('Bundle missing or MD5/CRC mismatch; decode refused')
    if extractor is None:
        from wlre.services.world.catalog_source_extractor import extract_catalog_source
        extractor = extract_catalog_source
    if not callable(extractor):
        raise OfflineVerificationError('Invalid TextAsset extractor')
    key = hashlib.sha256((data['manifest_sha256'] + ':' +
                          main['manifest_sha256']).encode('ascii')).hexdigest()
    summary = {}
    for feature in FEATURES:
        asset, name, schema, related = _SOURCE_MAP[feature]
        revision = data['revision']
        binding = AssetBinding(
            _ASSET_ROOT + asset,
            SourceContract(feature, name, schema, '0' * 64,
                           'DataPackage', revision),
            tuple(_ASSET_ROOT + n for n in related))
        try:
            raw = extractor(binding, tuple(paths[n] for n in selected[feature]))
            if type(raw) is not bytes:
                raise OfflineVerificationError('TextAsset extractor returned non-bytes')
            contract = SourceContract(
                feature, name, schema, hashlib.sha256(raw).hexdigest(),
                'DataPackage', revision)
            parsed = parse_feature(
                catalog_key=key, package_versions={'DataPackage': revision},
                contract=contract, raw=raw)
        except Exception as exc:
            raise OfflineVerificationError(
                'Unrecognized ' + feature + ' format; no Catalog activated') from exc
        summary[feature] = {
            'schema_id': parsed.schema_id, 'record_count': parsed.record_count,
            'source_sha256': parsed.source_sha256,
        }
    report['decoded'] = True
    report['decoded_features'] = summary
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-zip', type=Path, required=True)
    ap.add_argument('--main-zip', type=Path, required=True)
    ap.add_argument('--data-ver', required=True)
    origin = ap.add_mutually_exclusive_group()
    origin.add_argument('--bundle-dir', type=Path)
    origin.add_argument('--bundle-cache-root', type=Path)
    origin.add_argument('--game-yoo', type=Path,
                        help='Game install ..._Data/yoo (hashed __data scan, read-only)')
    ap.add_argument('--decode', action='store_true')
    args = ap.parse_args(argv)
    try:
        report = verify_local(args.data_zip, args.main_zip,
                              data_ver=args.data_ver,
                              bundle_dir=args.bundle_dir,
                              bundle_cache_root=args.bundle_cache_root,
                              game_yoo=args.game_yoo, decode=args.decode)
    except (ValueError, OSError) as exc:
        print('LaLa 離線驗證拒絕：' + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
