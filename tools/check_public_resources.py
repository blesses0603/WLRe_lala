"""Reject newly committed official-game resources in the public source tree.

This is a *change guard*, not a claim that older commits are clean. Existing
assets require a separate local-resource migration and Git history cleanup.

Usage: python -m tools.check_public_resources --base <git-sha> [--head HEAD]
"""

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


ARCHIVE_SUFFIXES = ('.zip', '.rar', '.7z', '.unity3d', '.bundle', '.assets',
                    '.ress', '.resource', '.bytes')
ART_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.tga', '.dds', '.psd', '.ico')
GENERATED_NAMES = ('npc_', 'item_', 'map_', 'smallmap', 'navigation',
                   'stage_', 'portal', 'crafting_catalog', 'combat_catalog',
                   'alchemy_catalog', 'expedition_catalog', 'normal_attack',
                   'graph_origin', 'instance_catalog', 'emoji_catalog')
GIT_REF = re.compile(r'^(?:[0-9a-f]{7,40}|HEAD)$', re.IGNORECASE)


def prohibited_reason(filename, size=None):
    """Return a reason if a new/modified path needs to stay out of public Git."""
    path = filename.replace('\\', '/')
    parts = PurePosixPath(path).parts
    lower = path.lower()
    name = parts[-1].lower() if parts else ''

    if any(part.lower() in ('bundlefiles', 'manifestfiles', 'tempfiles')
           or part.lower().endswith('_data') for part in parts):
        return '官方 YooAsset／Unity 原始資料目錄'
    if name == '__data' or any(part == '1275_差異' for part in parts):
        return '官方 Bundle／版本差異原始資料'
    if name.startswith(('resourcepath_pc', 'resourcepath_android',
                        'datapackage_', 'mainpackage_')):
        return '官方 Manifest／Package 原始檔'
    if name.endswith(ARCHIVE_SUFFIXES) or name.endswith('.json.gz'):
        return '二進位封包／壓縮遊戲資源不得公開提交'
    if lower.startswith('wlre/resources/'):
        if name.endswith(ART_SUFFIXES):
            return '資源目錄中的圖片須移至使用者本機安裝'
        if name.endswith('.json') and name.startswith(GENERATED_NAMES):
            return '遊戲衍生目錄／索引資料須移至本機'
    if lower.startswith('docs/button-assets/') and not name.endswith('.md'):
        return '官方按鈕貼圖及預覽素材'
    if name.endswith(('.json', '.html', '.txt', '.csv')) and size is not None and size > 1024 * 1024:
        return '大型資料表／匯出資料須人工確認來源及授權'
    return None


def changed_paths(base, head='HEAD', *, directory=None):
    """Only inspect changes; do not reject pre-existing files in the base."""
    if not GIT_REF.fullmatch(base) or not GIT_REF.fullmatch(head):
        raise ValueError('Only Git commit SHAs or HEAD are accepted')
    result = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMRT', '-z',
         base, head, '--'], cwd=directory, capture_output=True, check=True)
    return [name.decode('utf-8') for name in result.stdout.split(b'\0') if name]


def violations(base, head='HEAD', *, directory=None):
    root = Path(directory or Path.cwd())
    found = []
    for name in changed_paths(base, head, directory=root):
        path = root / name
        size = path.stat().st_size if path.is_file() else None
        reason = prohibited_reason(name, size)
        if reason:
            found.append((name, reason))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description='Public LaLa resource upload guard')
    parser.add_argument('--base', required=True, help='previous/base Git commit SHA')
    parser.add_argument('--head', default='HEAD', help='target commit SHA, default HEAD')
    args = parser.parse_args(argv)
    problems = violations(args.base, args.head)
    if problems:
        print('BLOCKED: these resources must not enter the public repository:')
        for path, reason in problems:
            print(f'  {path}: {reason}')
        print('Use the verified local-resource installer; never use git add -f.')
        return 1
    print('PASS: no newly added/modified prohibited game resource paths')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
