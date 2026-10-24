"""1275 is the desktop game's active data baseline, not a 1262 fallback.

Game-derived resources stay outside public GitHub, in per-user application
storage. Official binaries are validated against pinned 1275 SHA-256 manifests
before any runtime records can be used. No network packets are sent here.
"""
from __future__ import annotations
import argparse
import os
from functools import lru_cache
from pathlib import Path
import shutil
import tempfile

from wlre.storage.paths import data_root
from wlre.services.resource_compatibility import load_supported_resources

FOLDER = 'official_resources_1275'
DATA_FILE = '1275_DataCatalog.zip'
EVE_FILE = '1275_EveNpcIndex.zip'


class Runtime1275Unavailable(ValueError):
    """1275 asset installation is absent, damaged, or not yet validated."""


def baseline_revision():
    document = load_supported_resources()
    packages = document['packages']
    versions = {packages[key]['revision'] for key in ('DataPackage', 'MainPackage')}
    if len(versions) != 1:
        raise Runtime1275Unavailable('MainPackage 與 DataPackage 基準必須一致')
    return versions.pop()


def resource_dir(base=None):
    return Path(base) if base is not None else data_root() / FOLDER


def _paths(base=None):
    root = resource_dir(base)
    return root / DATA_FILE, root / EVE_FILE


@lru_cache(maxsize=1)
def _default_runtime():
    """Prefer verified formal archives; use independently pinned Bundles otherwise.

    A damaged legacy ZIP is not proof that the official Bundle source is
    damaged. Each source is verified in full and is never mixed with the other.
    """
    from zipfile import BadZipFile
    from wlre.services.world.preview_1275 import load_preview
    from wlre.services.world.bundle_runtime_1275 import (
        BundleRuntimeUnavailable, load_verified_bundle_runtime)

    data, eve = _paths()
    legacy_present = data.exists() or eve.exists()
    if data.is_file() and eve.is_file():
        try:
            return load_preview(data, eve)
        except (OSError, ValueError, KeyError, EOFError, UnicodeError,
                BadZipFile):
            # Do not delete, overwrite, or silently trust broken ZIPs.
            # Independently verify the entire official Bundle source instead.
            pass

    try:
        return load_verified_bundle_runtime()
    except BundleRuntimeUnavailable as exc:
        # Bundle errors are already sanitized by the source verifier.
        prefix = ('舊 1275 ZIP 校驗失敗或只有部分安裝；'
                  if legacy_present else '')
        raise Runtime1275Unavailable(
            prefix + '1275 官方 Bundle 尚未完成完整核對：' + str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise Runtime1275Unavailable(
            '1275 官方 Bundle 來源校驗失敗，尚不可啟用正式資料') from exc

def active_runtime():
    """Use 1275 only, never silently return a 1262 NPC/item/recipe catalogue."""
    if baseline_revision() != '1275':
        raise Runtime1275Unavailable('此 LaLa 版本尚未選定 1275 資料基準')
    return _default_runtime()


def ready():
    try:
        # Full independently pinned ZIPs OR exact release-pinned official
        # Bundle bytes can supply runtime data. Candidate ZIP indexes alone
        # NEVER replace these sources.
        source = active_runtime()
        from wlre.services.world.formal_candidate_bridge import (
            FormalBridgeError, inspect_launcher_candidate)
        # A matching candidate is checked AGAIN against the full, release-
        # pinned source before any shared recipe dict is touched. A mismatch
        # must never partially change game state.
        bridge = inspect_launcher_candidate(source)
        from wlre.services.items.crafting import activate_1275_recipes
        activate_1275_recipes(source)
        if bridge['status'] == 'matches_formal_sources':
            return True, ('1275 正式資料完整驗證，且 Launcher 四類候選與正式來源一致；'
                          '遊戲協定仍須獨立驗收')
        return True, '1275 正式資料通過來源校驗，可供功能模組使用；遊戲協定仍須獨立驗收'
    except (Runtime1275Unavailable, OSError, ValueError) as exc:
        message = str(exc)
        if isinstance(exc, Runtime1275Unavailable):
            from wlre.services.world.resource_gap_diagnostics import (
                diagnose_resources, summarize)
            from wlre.services.world.launcher_catalog import read_launcher_status
            # A missing ZIP is not proof that the current official Bundle
            # runtime has failed because of ZIP installation. Keep the
            # actionable Bundle error whenever neither ZIP was installed.
            # All status messages remain informational, never authorization.
            try:
                data_zip, eve_zip = _paths()
                if data_zip.exists() or eve_zip.exists():
                    gaps = diagnose_resources()
                    if not gaps['formal_ready']:
                        # Retain the Bundle validation cause. The old ZIP
                        # diagnosis is supplementary, not an authorization
                        # decision or a replacement for the actual failure.
                        legacy = summarize(gaps)
                        if legacy not in message:
                            message += '｜舊 ZIP 診斷：' + legacy
                receipt = read_launcher_status()
                if receipt is not None and receipt.get('data_compatibility') == 'compatible':
                    message = 'Launcher 四類候選資料格式相容；' + message
            except Exception:
                # Diagnostics cannot undo the original runtime refusal.
                pass
        return False, message


def install(data_archive, eve_archive, *, base=None, check_only=True):
    """All-or-nothing install: verify both ZIPs before any writes.

    Refuses overwrites; does not modify the game directory or legacy indices.
    """
    from wlre.services.world.preview_1275 import load_preview
    data, eve = Path(data_archive), Path(eve_archive)
    verified = load_preview(data, eve)
    output = {'revision': verified.revision, 'items': len(verified.items),
              'recipes': len(verified.recipes), 'scenes': len(verified.scene_ids)}
    if check_only:
        return output
    root = resource_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    sources = ((data, root / DATA_FILE), (eve, root / EVE_FILE))
    if any(dest.exists() for _, dest in sources):
        raise FileExistsError('1275 資料已存在。請先備份並人工確認，安裝器不會覆寫')
    pending, created = [], []
    try:
        for src, dest in sources:
            with tempfile.NamedTemporaryFile(dir=root, prefix='.lala1275_', suffix='.tmp',
                                             delete=False) as handle:
                pending.append((Path(handle.name), dest))
                with src.open('rb') as stream:
                    shutil.copyfileobj(stream, handle, 1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
        # Protect against source files changing after the first verification,
        # or copy truncation. Validate the exact staged files before publishing
        # either destination; no partial active runtime is ever accepted.
        load_preview(pending[0][0], pending[1][0])
        for tmp, dest in pending:
            os.link(tmp, dest)
            created.append(dest)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for tmp, _ in pending:
            tmp.unlink(missing_ok=True)
    _default_runtime.cache_clear()
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description='安裝 1275 LaLa 正式資料基準（先校驗全部來源）')
    parser.add_argument('data_catalog', type=Path)
    parser.add_argument('eve_catalog', type=Path)
    parser.add_argument('--install', action='store_true', help='不加參數只檢查，不寫入')
    args = parser.parse_args(argv)
    report = install(args.data_catalog, args.eve_catalog, check_only=not args.install)
    print('1275 資料來源校驗通過：' + repr(report))
    print('已安裝到使用者資料夾' if args.install else '只驗證，沒有安裝')


if __name__ == '__main__':
    main()
