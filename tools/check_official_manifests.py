"""Verify both official PC YooAsset Manifests and report counts, not asset paths.

This is an explicit command. It only downloads the two manifests to private
per-user cache and never queues game Bundles or bypasses the version gate.
"""

import argparse
import json
import sys

from wlre.services.official_manifest_sync import (
    ManifestSyncError, PACKAGES, fetch_official_manifest, spec_from_snapshot,
)
from wlre.services.official_resource_sync import OfficialSyncError, observe_official_versions


def inspect_current_manifests(*, observe=None, retrieve=None, packages=PACKAGES):
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    snapshot = observe()
    result = {
        'data_ver': snapshot['data_ver'],
        'exe_version': snapshot['exe_version'],
        'packages': {},
        'assets_ready': False,
        'note': 'Metadata verified; game runtime compatibility and Bundle installation are not validated',
    }
    for package in packages:
        spec = spec_from_snapshot(snapshot, package)
        manifest = retrieve(spec)
        result['packages'][package] = {
            'package_version': spec.package_version,
            'hash': manifest.hash_text,
            'asset_count': len(manifest.index['assets']),
            'bundle_count': len(manifest.index['bundles']),
            'downloaded': manifest.downloaded,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify official PC YooAsset Manifest indexes')
    parser.add_argument('--package', choices=PACKAGES,
                        help='Only inspect one package; default is both')
    options = parser.parse_args(argv)
    try:
        packages = (options.package,) if options.package else PACKAGES
        summary = inspect_current_manifests(packages=packages)
    except (ManifestSyncError, OfficialSyncError, OSError, KeyError) as exc:
        print(f'官方 Manifest 尚不可用：{exc}', file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
