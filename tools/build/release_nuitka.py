"""Validate a release tag and package a verified standalone Nuitka build."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from wlre import __version__
from tools.build.build_nuitka import ROOT


def validate_tag(tag, version=__version__):
    if tag != 'v' + version:
        raise ValueError(f'版本標籤必須與 wlre.__version__ 相符：預期 v{version}，收到 {tag!r}')
    return tag


def package_release(tag, root=ROOT):
    validate_tag(tag)
    source = root / 'dist_nuitka/standalone/WLRE_Client.dist'
    executable = source / 'WLRE_Client.exe'
    if not executable.is_file() or executable.stat().st_size == 0:
        raise ValueError('找不到完整的 standalone EXE；請先完成 Nuitka 打包及資源自檢')
    destination = root / 'dist_nuitka/release'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f'WLRE_LaLa_{tag}_windows_x64.zip'
    temporary = archive.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for item in sorted(source.rglob('*')):
                if item.is_symlink():
                    raise ValueError(f'發行內容不接受符號連結：{item}')
                if item.is_file():
                    bundle.write(item, 'WLRE_Client/' + item.relative_to(source).as_posix())
        # Reopen after close: a truncated archive must never be published.
        with zipfile.ZipFile(temporary) as bundle:
            bad = bundle.testzip()
            if bad:
                raise ValueError(f'ZIP CRC 檢查失敗：{bad}')
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    checksum = destination / 'SHA256SUMS.txt'
    checksum.write_text(f'{digest.hexdigest()}  {archive.name}\n', encoding='ascii')
    return archive, checksum


def main(argv=None):
    parser = argparse.ArgumentParser(description='驗證版本並封裝 Nuitka Release ZIP')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--check-tag', action='store_true', help='只檢查版本標籤，不封裝')
    args = parser.parse_args(argv)
    try:
        validate_tag(args.tag)
        if not args.check_tag:
            for item in package_release(args.tag):
                print(item)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
