"""Verify current official daily-task schemas and SQLite bindings; never log in."""
import argparse
import json
from pathlib import Path
from functools import lru_cache


def main(argv=None):
    parser=argparse.ArgumentParser(description='核對官方每日／每週任務資料與 SQLite 載入')
    parser.add_argument('--online',action='store_true',help='允許下載當次官方驗證 Bundle，不登入遊戲')
    parser.add_argument('--cache-dir',type=Path)
    args=parser.parse_args(argv)
    if not args.online:parser.error('需要 --online 才會連線下載官方資源')
    from wlre.services.world.dynamic_bundle_runtime import prepare_dynamic_runtime
    runtime=prepare_dynamic_runtime(sync=True,sync_root=args.cache_dir)
    catalog=runtime.daily_tasks
    if not catalog:
        # Repeat the failed optional load with its specific schema error exposed
        # to this explicit diagnostic, never to regular gameplay logs.
        from wlre.storage.paths import data_root
        from wlre.services.official_resource_sync import observe_official_versions,validate_snapshot
        from wlre.services.official_manifest_sync import fetch_official_manifest,spec_from_snapshot,PACKAGES
        from wlre.services.world.catalog_identity import identity_from_verified_manifests
        from wlre.services.world.daily_task_catalog import load_verified_catalog
        from wlre.services.world.unity_textasset import _loader
        root=args.cache_dir or data_root()/'official_sync'
        snapshot=validate_snapshot(observe_official_versions())
        manifests={p:fetch_official_manifest(spec_from_snapshot(snapshot,p),cache_root=root/'manifests') for p in PACKAGES}
        identity=identity_from_verified_manifests(snapshot,manifests)
        if identity!=runtime.catalog_identity:raise ValueError('官方資源已變動，拒絕混用')
        catalog=load_verified_catalog(manifests['DataPackage'],root/'bundles',lru_cache(maxsize=3)(_loader),
                                      root,identity,runtime.texts,runtime.items)
    print(json.dumps(dict(status='verified',catalog_key=runtime.catalog_identity.key,
        packages={p.name:p.full_version for p in runtime.catalog_identity.packages},
        task_count=len(catalog['tasks']),reward_count=len(catalog['rewards']),
        cycles=sorted({r['cycle'] for r in catalog['tasks']}),
        unsupported_conditions=sorted({r['condition_kind'] for r in catalog['tasks'] if not r['goal']}),
        sources=catalog['sources'],game_server_tested=False),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
