"""受控場景定義快照驗證；只輸出來源收據，不發布原始遊戲資料。"""
import argparse
import json
import math
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from wlre.core.application import Application, LifecycleError
from wlre.resources_runtime.official.contracts import (
    SCENE_DEFINITIONS,
    TEXT_DEFINITIONS,
)
from wlre.resources_runtime.official.manager import ResourceRefreshError
from wlre.resources_runtime.official.module import OfficialResourceModule
from wlre.storage.atomic import write_json


def private_cache(path):
    """由 Git 確認真正工作樹；雲端掛載的空 .git 標記不是有效 Repository。"""
    path = path.expanduser().resolve()
    project = Path(__file__).resolve().parents[1]
    if path.is_relative_to(project):
        raise ValueError('private_cache_inside_source_tree')
    existing = next(parent for parent in (path, *path.parents) if parent.is_dir())
    result = subprocess.run(['git', '-C', str(existing), 'rev-parse', '--is-inside-work-tree'],
                            capture_output=True, timeout=5, check=False)
    if result.returncode == 0:
        raise ValueError('private_cache_inside_git_tree')
    # 無法識別 Git 錯誤時不自行放行，例如權限問題或安全目錄限制。
    if b'not a git repository' not in result.stderr.lower():
        raise ValueError('private_cache_git_status_unknown')
    return path


@contextmanager
def managed_snapshot(cache_root, exe_version, *, scope, requirements, timeout=120, opener=None):
    """命令列也使用正式生命週期／事件 pump；查詢僅在 context 內有效。"""
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 300):
        raise ValueError('invalid_snapshot_deadline')
    module = OfficialResourceModule(cache_root, opener=opener)
    application = Application((module,))
    try:
        application.initialize()
        application.start()
        module.api.refresh(exe_version, scope=scope, requirements=requirements)
        deadline = time.monotonic() + timeout
        wait = Event()
        while True:
            status = module.api.poll()
            application.pump()
            if status.phase == 'current':
                break
            if status.phase not in ('refreshing', 'cancel_requested'):
                raise ResourceRefreshError(status.code)
            if time.monotonic() >= deadline:
                raise TimeoutError('official_snapshot_deadline_exceeded')
            wait.wait(0.02)
        yield module.api.current(), module.api.diagnose(scope)['document']
    finally:
        application.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe-version', required=True, help='明確指定客戶端 ExeVer，不猜預設版號')
    parser.add_argument('--cache-root', required=True, type=Path, help='Git 工作樹以外的私人快取')
    parser.add_argument('--report', required=True, type=Path, help='只含來源、大小與筆數的 JSON 收據')
    parser.add_argument('--scene-references', action='store_true',
                        help='同次核對官方文字名稱及 MainPackage 模型索引；不驗收幾何')
    parser.add_argument('--timeout-seconds', type=float, default=120,
                        help='整批等待截止，預設 120 秒、上限 300 秒')
    args = parser.parse_args(argv)
    try:
        cache_root = private_cache(args.cache_root)
        scope = 'scene_references' if args.scene_references else 'scene_definitions'
        requirements = ((SCENE_DEFINITIONS, TEXT_DEFINITIONS) if args.scene_references
                        else (SCENE_DEFINITIONS,))
        with managed_snapshot(cache_root, args.exe_version, scope=scope, requirements=requirements,
                              timeout=args.timeout_seconds) as (service, receipt):
            report = {
                'schema_version': 1, 'validated_at': service.validated_at,
                'snapshot_id': service.snapshot_id, 'source_url': receipt['source_url'],
                'lala_version': service.versions.lala_version,
                'observed_exe_version': service.versions.observed_exe_version,
                'data_version': service.versions.data_version,
                'data_package_version': service.versions.data_package_version,
                'main_package_version': service.versions.main_package_version,
                'manifest_receipts': receipt['manifests'],
                'bundle_receipts': receipt['bundles'],
                'source_receipts': receipt['sources'],
                'record_count': len(service.records('scene_definitions')),
                'acceptance_scope': ('scene_reference_audit_only' if args.scene_references
                                     else 'scene_definitions_only'),
                'references': service.reference_summary(),
                'protocol_approved': service.protocol_approved,
                'live_game_e2e': 'not_executed',
                'legacy_consumers_migrated': False,
                'offline_current_view_allowed': False,
            }
        # 成功退出 context 表示背景工作與查詢租約已清理，才發布驗證報告。
        write_json(args.report, report)
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled', 'code': 'official_snapshot_check_cancelled'}))
        return 130
    except (OSError, ValueError, LifecycleError):
        print(json.dumps({'status': 'failed', 'code': 'official_snapshot_check_failed'}))
        return 2
    print(json.dumps({'status': 'validated_requested_scope', 'record_count': report['record_count'],
                      'protocol_approved': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
