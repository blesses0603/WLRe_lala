"""Package native app bundles with ditto to retain links, signatures and modes."""
import argparse
import hashlib
import subprocess
import sys
import zipfile

from tools.build.build_nuitka import ROOT
from tools.build.build_macos import bundle_executable, output_dir
from tools.build.release_nuitka import validate_tag


def package_release(tag, arch, root=ROOT):
    validate_tag(tag)
    if arch not in ('arm64', 'x64'):
        raise ValueError('macOS 架構必須為 arm64 或 x64')
    source = output_dir(root, arch) / 'WLRe_LaLa.app'
    executable = bundle_executable(source)
    destination = root / 'dist_nuitka/release'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f'WLRe_LaLa_{tag}_macos_{arch}.zip'
    temporary = archive.with_suffix('.zip.tmp')
    try:
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(source), str(temporary)], check=True)
        with zipfile.ZipFile(temporary) as bundle:
            bad = bundle.testzip()
            expected = source.name + '/' + executable.relative_to(source).as_posix()
            if bad or expected not in bundle.namelist():
                raise ValueError('macOS ZIP CRC／主程式檢查失敗：' + str(bad))
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    # Different artifact manifests must not overwrite each other on download.
    checksum = destination / f'SHA256SUMS_macos_{arch}.txt'
    checksum.write_text(f'{digest.hexdigest()}  {archive.name}\n', encoding='ascii')
    return archive, checksum


def main(argv=None):
    parser = argparse.ArgumentParser(description='封裝 macOS .app Release ZIP')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--arch', required=True, choices=('arm64', 'x64'))
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        parser.error('macOS ZIP 需在 macOS 使用 ditto 封裝')
    try:
        for item in package_release(args.tag, args.arch):
            print(item)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
