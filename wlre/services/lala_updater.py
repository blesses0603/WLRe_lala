"""Safe GitHub Release discovery and verified download for WLRe_LaLa.

Never installs over the active process, never trusts a zip filename supplied by
an API response, and refuses archives without matching official SHA256SUMS.
A human chooses when to replace/relaunch a complete standalone application.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from wlre import __version__
from wlre.storage.paths import data_root

REPO = "blesses0603/WLRe_lala"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_SITE = f"https://github.com/{REPO}/releases"
MAX_API = 128 * 1024
MAX_HASHES = 64 * 1024
MAX_ARCHIVE = 1024 * 1024 * 1024  # a strict 1 GiB streaming ceiling
_TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


class UpdateError(ValueError):
    """A release was not available or did not pass source/integrity checks."""


def parsed_version(value):
    if not isinstance(value, str):
        raise UpdateError("版本字串無效")
    candidate = value if value.startswith("v") else "v" + value
    match = _TAG.fullmatch(candidate)
    if not match:
        raise UpdateError("LaLa 版本不符合 vX.Y.Z")
    return tuple(map(int, match.groups()))


def target_archive(tag, *, system=None, machine=None):
    if not _TAG.fullmatch(tag):
        raise UpdateError("發行標籤格式不正確")
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    if system == "Windows" and machine.lower() in {"amd64", "x86_64"}:
        return f"WLRe_LaLa_{tag}_windows_x64.zip"
    if system == "Darwin" and machine.lower() in {"arm64", "aarch64", "x86_64", "amd64"}:
        suffix = "arm64" if machine.lower() in {"arm64", "aarch64"} else "x64"
        return f"WLRe_LaLa_{tag}_macos_{suffix}.zip"
    raise UpdateError("此作業系統／架構沒有對應的已驗證安裝包")


def _request(url, *, accept, opener=None):
    if opener is None:
        opener = build_opener(_TrustedReleaseRedirect()).open
    return opener(Request(url, headers={
        "Accept": accept,
        "User-Agent": "WLRe-LaLa-Desktop-Updater/1",
        "Cache-Control": "no-cache",
    }), timeout=12)


def _asset_uri(uri, *, tag, filename):
    expected = f"https://github.com/{REPO}/releases/download/{tag}/{filename}"
    if uri != expected:
        raise UpdateError("Release 檔案網址與預期來源不符")
    return uri


class _TrustedReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        # GitHub release asset downloads redirect to GitHub-owned CDN services.
        permitted = {"github.com", "objects.githubusercontent.com",
                     "release-assets.githubusercontent.com"}
        if parsed.scheme != "https" or parsed.hostname not in permitted:
            raise UpdateError("下載被轉向不受信任的主機")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_small(url, limit, *, accept, opener=None):
    try:
        with _request(url, accept=accept, opener=opener) as stream:
            data = stream.read(limit + 1)
    except (OSError, ValueError) as exc:
        raise UpdateError("GitHub 發布資訊無法讀取") from exc
    if len(data) > limit:
        raise UpdateError("GitHub 回應超過大小限制")
    return data


def check_lala_release(*, current_version=__version__, opener=None,
                       system=None, machine=None):
    """Use published releases, not main's development version or an unmerged PR."""
    current = parsed_version(current_version)
    try:
        payload = json.loads(_read_small(API, MAX_API,
                                        accept="application/vnd.github+json",
                                        opener=opener))
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("GitHub Release 回應不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise UpdateError("Release 格式錯誤")
    tag = payload.get("tag_name")
    latest = parsed_version(tag)
    if payload.get("draft") or payload.get("prerelease"):
        raise UpdateError("不能使用草稿或預覽發行版本")
    available = latest > current
    info = {"status": "update_available" if available else "up_to_date",
            "current": current_version, "published": tag, "release_url": RELEASE_SITE}
    if not available:
        return info

    name = target_archive(tag, system=system, machine=machine)
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Release 沒有有效的下載檔案清單")
    indexed = {a["name"]: a for a in assets if isinstance(a, dict) and
               isinstance(a.get("name"), str)}
    if name not in indexed or "SHA256SUMS.txt" not in indexed:
        raise UpdateError("官方發布未提供對應平台安裝包與 SHA256SUMS.txt")
    for filename in (name, "SHA256SUMS.txt"):
        _asset_uri(indexed[filename].get("browser_download_url"), tag=tag, filename=filename)
    info.update({"archive_name": name, "archive_url": indexed[name]["browser_download_url"],
                 "checksum_url": indexed["SHA256SUMS.txt"]["browser_download_url"]})
    return info


def expected_checksum(data, filename):
    """Read the official generated sha256sum manifest; fail on ambiguous entries."""
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise UpdateError("發布的 SHA256SUMS 不是 ASCII") from exc
    hashes = []
    for line in lines:
        match = re.fullmatch(r"([0-9a-fA-F]{64})  \*?([^\r\n]+)", line)
        if match and match.group(2) == filename:
            hashes.append(match.group(1).lower())
    if len(hashes) != 1:
        raise UpdateError("找不到唯一對應的 ZIP SHA-256 校驗值")
    return hashes[0]


def download_verified_release(info, *, directory=None, opener=None):
    """Download to user data, verify SHA256, and atomically expose the ZIP.

    Does not extract, execute, or overwrite a running program. No account data.
    """
    if info.get("status") != "update_available":
        raise UpdateError("沒有經確認可下載的新版本")
    tag = info.get("published")
    name = target_archive(tag)
    if info.get("archive_name") != name:
        raise UpdateError("平台與下載檔案不一致")
    url = _asset_uri(info.get("archive_url"), tag=tag, filename=name)
    checksums = _asset_uri(info.get("checksum_url"), tag=tag, filename="SHA256SUMS.txt")
    digest = expected_checksum(_read_small(checksums, MAX_HASHES,
                                           accept="text/plain", opener=opener), name)
    destination = Path(directory) if directory is not None else data_root() / "updates" / tag
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / name
    temporary = destination / (name + ".partial")
    sha = hashlib.sha256()
    downloaded = 0
    try:
        with _request(url, accept="application/octet-stream", opener=opener) as stream, \
                temporary.open("wb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_ARCHIVE:
                    raise UpdateError("下載檔案超過安全容量上限")
                sha.update(chunk)
                output.write(chunk)
        if not downloaded or sha.hexdigest() != digest:
            raise UpdateError("下載完成但 SHA-256 與官方清單不一致")
        # ZIP CRC and intended package entry, without unsafe extraction.
        import zipfile
        with zipfile.ZipFile(temporary) as package:
            expected_file = ("WLRe_LaLa/WLRe_LaLa.exe" if name.endswith("_windows_x64.zip")
                             else "WLRe_LaLa.app/")
            names = package.namelist()
            # Forbid traversal, archive-based symlinks, and decompression bombs.
            if len(names) > 100000 or sum(x.file_size for x in package.infolist()) > 4 * MAX_ARCHIVE:
                raise UpdateError("安裝包解壓大小或項目數異常")
            if (not any(x == expected_file or
                        (expected_file.endswith("/") and x.startswith(expected_file))
                        for x in names) or
                    any(x.startswith("/") or x.startswith("\\") or "\\" in x or
                        ".." in x.split("/") for x in names) or
                    any(((x.external_attr >> 16) & 0o170000) == 0o120000
                        for x in package.infolist())):
                raise UpdateError("安裝包內容不符合預期結構")
            bad = package.testzip()
            if bad:
                raise UpdateError("安裝包 ZIP CRC 驗證失敗")
        os.replace(temporary, archive)
    except (OSError, ValueError, RuntimeError) as exc:
        raise UpdateError("LaLa 安裝包下載或驗證失敗") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return archive
