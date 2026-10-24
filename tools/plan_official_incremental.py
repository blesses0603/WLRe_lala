"""Preview or explicitly download required official Bundle dependencies.

Example (requirements JSON must be outside a public Git working tree):
  python -m tools.plan_official_incremental --requirements /private/required.json
  python -m tools.plan_official_incremental --requirements /private/required.json \
      --download --max-mib 64 --max-files 32

Only the user explicitly chooses asset path/Bundle selectors. No implicit
full-package download, no game-file publishing, no runtime compatibility claim.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from wlre.services.official_incremental_sync import (
    IncrementalSyncError, build_update_plan, execute_update_plan,
    find_previous_verified_manifest,
)
from wlre.services.official_manifest_sync import (
    ManifestSyncError, PACKAGES, fetch_official_manifest, spec_from_snapshot,
)
from wlre.services.official_resource_sync import OfficialSyncError, observe_official_versions


MAX_REQUIREMENTS_BYTES = 64 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024


def _require_private_path(path):
    target = Path(path).expanduser().resolve()
    for folder in (target.parent, *target.parents):
        if (folder / '.git').exists():
            raise IncrementalSyncError('Private requirements/reports must be outside any Git worktree')
    return target


def load_private_requirements(path):
    path = _require_private_path(path)
    try:
        with path.open('rb') as stream:
            content = stream.read(MAX_REQUIREMENTS_BYTES + 1)
        if len(content) > MAX_REQUIREMENTS_BYTES:
            raise IncrementalSyncError('Requirement file exceeds 64 KiB')
        value = json.loads(content.decode('utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise IncrementalSyncError('Invalid private requirements JSON') from exc
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'packages'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['packages'], dict) or not value['packages']):
        raise IncrementalSyncError('Requirements must contain a nonempty packages object')
    for package, fields in value['packages'].items():
        if (package not in PACKAGES or not isinstance(fields, dict)
                or set(fields) != {'asset_paths', 'bundle_names'}):
            raise IncrementalSyncError('Requirement package/schema is invalid')
        for key in ('asset_paths', 'bundle_names'):
            values = fields[key]
            if (not isinstance(values, list) or len(values) > 512 or
                    any(not isinstance(item, str) or not item or len(item) > 1024 or
                        '\x00' in item or '*' in item or '?' in item for item in values)
                    or len(set(values)) != len(values)):
                raise IncrementalSyncError('Requirements must use unique exact selectors')
        if not fields['asset_paths'] and not fields['bundle_names']:
            raise IncrementalSyncError('Each package requires at least one explicit selector')
    return value['packages']


def plan_required_updates(requirements, *, observe=None, retrieve=None, previous_finder=None,
                          cache_root=None, bundle_root=None):
    observe = observe_official_versions if observe is None else observe
    retrieve = fetch_official_manifest if retrieve is None else retrieve
    previous_finder = (find_previous_verified_manifest if previous_finder is None
                       else previous_finder)
    snapshot = observe()
    plans = []
    for package in PACKAGES:
        if package not in requirements:
            continue
        spec = spec_from_snapshot(snapshot, package)
        current = retrieve(spec, cache_root=cache_root)
        previous = previous_finder(current, cache_root=cache_root)
        fields = requirements[package]
        plans.append(build_update_plan(
            current, previous=previous,
            asset_paths=fields['asset_paths'], bundle_names=fields['bundle_names'],
            cache_root=bundle_root))
    return plans


def execute_plans(plans, *, download=False, max_bytes=64 * 1024 * 1024,
                  max_files=32, bundle_root=None, opener=None):
    """Check the aggregate quota before processing the first package."""
    total_bytes = sum(plan.download_bytes for plan in plans)
    total_files = sum(plan.download_count for plan in plans)
    if download and (total_bytes > max_bytes or total_files > max_files):
        raise IncrementalSyncError('Combined Bundle plan exceeds byte/file quota')
    reports = []
    for plan in plans:
        reports.append(execute_update_plan(
            plan, cache_root=bundle_root, download=download,
            max_download_bytes=max_bytes, max_downloads=max_files,
            opener=opener))
    return reports


def private_report(plans, results, output):
    """Save detailed names only to an explicitly private destination."""
    target = _require_private_path(output)
    rows = []
    for plan, result in zip(plans, results):
        rows.append({
            'summary': result,
            'needed_bundles': [{
                'name': entry.spec.name,
                'bytes': entry.spec.file_size,
                'action': entry.action,
                'change': entry.change,
                'dependencies': list(entry.dependencies),
            } for entry in plan.entries],
        })
    content = (json.dumps({'schema_version': 1, 'packages': rows},
                          ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(content) > MAX_REPORT_BYTES:
        raise IncrementalSyncError('Private report exceeds 2 MiB')
    if not target.parent.is_dir():
        raise IncrementalSyncError('Private report directory must already exist')
    # Atomic create-if-absent: a failure cannot leave a partial final report.
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.bundle_plan_',
                                         suffix='.partial', delete=False) as stream:
            pending = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target)  # Fails safely if output already exists.
    except OSError as exc:
        raise IncrementalSyncError('Cannot create private update report') from exc
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='Preview/download only required official Bundles')
    parser.add_argument('--requirements', type=Path, required=True,
                        help='Private JSON with exact asset_paths and bundle_names')
    parser.add_argument('--download', action='store_true',
                        help='Explicitly download after aggregate quota preflight')
    parser.add_argument('--max-mib', type=int, default=64)
    parser.add_argument('--max-files', type=int, default=32)
    parser.add_argument('--report', type=Path, help='Write a private detailed Bundle list (new file only)')
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.max_mib <= 1024 or not 0 <= args.max_files <= 1024:
            raise IncrementalSyncError('Quota must be between 0 and the configured upper bound')
        requirements = load_private_requirements(args.requirements)
        plans = plan_required_updates(requirements)
        reports = execute_plans(plans, download=args.download,
                                max_bytes=args.max_mib * 1024 * 1024,
                                max_files=args.max_files)
        if args.report is not None:
            private_report(plans, reports, args.report)
    except (IncrementalSyncError, ManifestSyncError, OfficialSyncError, OSError) as exc:
        print(f'官方 Bundle 增量更新尚未完成：{exc}', file=sys.stderr)
        return 1
    print(json.dumps({'mode': 'download' if args.download else 'preview',
                      'packages': reports, 'assets_ready': False},
                     ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
