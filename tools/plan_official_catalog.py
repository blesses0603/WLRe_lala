"""Preview or explicitly download ONLY reviewed LaLa catalog AssetPaths.

Example:
  python -m tools.plan_official_catalog --bindings private_bindings.json
  python -m tools.plan_official_catalog --bindings private_bindings.json --download

This command does not extract UnityFS/TextAssets or enable game features.
The source bindings JSON must live OUTSIDE a Git worktree. The expected
SHA-256 of a derived source must be independently reviewed for that revision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tools.plan_official_incremental import _require_private_path
from wlre.services.official_incremental_sync import IncrementalSyncError
from wlre.services.official_manifest_sync import ManifestSyncError
from wlre.services.official_resource_sync import OfficialSyncError
from wlre.services.world.catalog_adapters import (
    FEATURES, CatalogAdapterError, SourceContract,
)
from wlre.services.world.official_catalog_pipeline import (
    AssetBinding, OfficialCatalogPipelineError,
    plan_current_catalog, run_catalog_pipeline,
)

MAX_BINDINGS_BYTES = 64 * 1024


def load_bindings(path):
    source = _require_private_path(path)
    try:
        with source.open('rb') as stream:
            data = stream.read(MAX_BINDINGS_BYTES + 1)
        if not 0 < len(data) <= MAX_BINDINGS_BYTES:
            raise OfficialCatalogPipelineError('Bindings file is empty or too large')
        config = json.loads(data.decode('utf-8'))
        if (type(config) is not dict
                or set(config) != {'schema_version', 'sources'}
                or config['schema_version'] != 1
                or type(config['sources']) is not list
                or len(config['sources']) != len(FEATURES)):
            raise OfficialCatalogPipelineError('Expected four release-reviewed source bindings')
        result = []
        for item in config['sources']:
            if (type(item) is not dict or set(item) != {
                    'feature', 'asset_path', 'source_name', 'schema_id',
                    'expected_sha256', 'package', 'package_version'}):
                raise OfficialCatalogPipelineError('Unexpected source binding fields')
            contract = SourceContract(
                item['feature'], item['source_name'], item['schema_id'],
                item['expected_sha256'], item['package'], item['package_version'])
            result.append(AssetBinding(item['asset_path'], contract))
        if {r.contract.feature for r in result} != set(FEATURES):
            raise OfficialCatalogPipelineError('Missing or duplicate feature binding')
        return tuple(result)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise OfficialCatalogPipelineError('Invalid private source bindings') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings', type=Path, required=True,
                        help='Private, release-reviewed exact AssetPath/Schema/SHA JSON')
    parser.add_argument('--download', action='store_true',
                        help='Explicitly download verified required Bundles; never parse UnityFS')
    parser.add_argument('--max-mib', type=int, default=64)
    parser.add_argument('--max-files', type=int, default=32)
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.max_mib <= 1024 or not 0 <= args.max_files <= 1024:
            raise OfficialCatalogPipelineError('Invalid download quota')
        bindings = load_bindings(args.bindings)
        plan = plan_current_catalog(bindings)
        result, parsed = run_catalog_pipeline(
            plan, download=args.download, max_download_bytes=args.max_mib*1024*1024,
            max_downloads=args.max_files)
        if parsed:
            raise OfficialCatalogPipelineError('CLI unexpectedly produced game catalog')
    except (CatalogAdapterError, IncrementalSyncError, ManifestSyncError,
            OfficialSyncError, OfficialCatalogPipelineError, OSError) as exc:
        print(f'通用資源流程停止（安全拒絕）：{exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print('Bundle 定位／校驗階段；UnityFS 解包及正式功能啟用仍未實裝。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
