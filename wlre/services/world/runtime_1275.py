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
    from wlre.services.world.preview_1275 import load_preview
    data, eve = _paths()
    if not data.is_file() or not eve.is_file():
        raise Runtime1275Unavailable(
            '缺少已驗證的 1275 LaLa 資源。請先安裝 1275_DataCatalog.zip 與 1275_EveNpcIndex.zip。')
    try:
        return load_preview(data, eve)
    except (OSError, ValueError, KeyError, EOFError, UnicodeError) as exc:
        raise Runtime1275Unavailable('1275 資源驗證失敗，已停止使用新版資料') from exc


def active_runtime():
    """Use 1275 only, never silently return a 1262 NPC/item/recipe catalogue."""
    if baseline_revision() != '1275':
        raise Runtime1275Unavailable('此 LaLa 版本尚未選定 1275 資料基準')
    return _default_runtime()


def ready():
    try:
        source = active_runtime()
        # All crafting views share this dictionary object; swap only after
        # full 1275 ZIP validation, before allowing the login screen.
        from wlre.services.items.crafting import activate_1275_recipes
        activate_1275_recipes(source)
        return True, '1275 NPC／商店／製作／場景索引通過來源校驗'
    except (Runtime1275Unavailable, OSError, ValueError) as exc:
        return False, str(exc)


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
                with src.open('rb') as stream:
                    shutil.copyfileobj(stream, handle, 1024 * 1024)
                pending.append((Path(handle.name), dest))
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
