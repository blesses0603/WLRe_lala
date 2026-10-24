"""Read-only SHA audit for the two Unity global resources across 1262/1275.

Identical global resources do NOT authenticate any A* graph, scene NavMesh,
dynamic obstacle, portal trigger, or live movement packet. User-supplied
binary resources stay local, and this tool only prints a compact report.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


class NavSourceAuditError(ValueError):
    pass


FILES = ('resources.assets', 'resources.resource')
OFFICIAL_MANIFEST_SHA256 = {
    'DataPackage': '8af6b9374d2e31e5bda4d82d2ec4be6b3a673e9188a522eb2c1b110e68c51dee',
    'MainPackage': '65da10fab29b8ce96247a18e611ee0ba3c5c3bc5cb71a42c4e177001a8c4ba49',
}


def _fingerprint(archive, member):
    sha = hashlib.sha256()
    size, signature = 0, b''
    with archive.open(member) as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            if not signature:
                signature = part[:4]
            size += len(part)
            sha.update(part)
    return {'size': size, 'sha256': sha.hexdigest(), 'signature': signature.hex()}


def audit(old_archive, new_archive):
    """Verify zip contents and both exact 1275 official manifest hashes."""
    try:
        with ZipFile(old_archive) as old, ZipFile(new_archive) as new:
            if old.testzip() is not None or new.testzip() is not None:
                raise NavSourceAuditError('來源 ZIP CRC 不符')
            for z, expected in (
                    (old, FILES),
                    (new, ('source_fingerprints.json',) +
                     tuple('source/' + name for name in FILES))):
                names = z.namelist()
                if any(names.count(name) != 1 for name in expected):
                    raise NavSourceAuditError('導航來源 ZIP 缺件或名稱重複')
            meta = json.loads(new.read('source_fingerprints.json'))
            if (meta.get('revision') != 1275 or
                    {k: v.get('sha256') for k, v in
                     meta.get('yoo_manifests', {}).items()} !=
                    OFFICIAL_MANIFEST_SHA256):
                raise NavSourceAuditError('1275 官方雙 Manifest 指紋不符')
            values = {}
            for name in FILES:
                a = _fingerprint(old, name)
                b = _fingerprint(new, 'source/' + name)
                expected = meta['unity_files'][name]
                if (b['size'] != expected.get('size') or
                        b['sha256'] != expected.get('sha256')):
                    raise NavSourceAuditError('1275 官方來源大小或 SHA 不符：' + name)
                values[name] = {
                    'size_1262': a['size'], 'size_1275': b['size'],
                    'sha256_1262': a['sha256'], 'sha256_1275': b['sha256'],
                    'identical': a['size'] == b['size'] and
                                 a['sha256'] == b['sha256'],
                    'signature_1275': b['signature'],
                }
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise NavSourceAuditError('1275 驗證清單結構無效') from exc
    all_identical = all(row['identical'] for row in values.values())
    return {
        'source_revision': 1275,
        'global_resource_files_identical': all_identical,
        'files': values,
        'resources_resource_is_fsb5': values['resources.resource']['signature_1275'] ==
                                      b'FSB5'.hex(),
        'astar_graphs_extracted': False,
        'navmesh_verified': False,
        'network_coordinates_verified': False,
        'auto_movement_authorized': False,
        'finding': ('兩份 Unity 全域資源完全相同，'
                    '但不是原始A*網格相同或可用1262導航的證據。'
                    if all_identical else
                    'Unity 全域資源存在差異，必須調查差異是否涉及導航。'),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description='1262與1275 Unity全域資源唯讀SHA比對')
    p.add_argument('baseline_1262', type=Path)
    p.add_argument('candidate_1275', type=Path)
    args = p.parse_args(argv)
    print(json.dumps(audit(args.baseline_1262, args.candidate_1275),
                     indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
