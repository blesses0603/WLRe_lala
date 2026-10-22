"""Safe WLRe_LaLa desktop Release discovery and verified ZIP staging.

Never execute, unpack into the app, or overwrite running binaries. Explicit
user action is required to stage a newer public GitHub Release.
"""
import hashlib
import json
import os
import platform
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from wlre import __version__
from wlre.storage.paths import data_root

RELEASE_API = "https://api.github.com/repos/blesses0603/WLRe_lala/releases/latest"
RELEASE_PAGE = "https://github.com/blesses0603/WLRe_lala/releases/latest"
_REPO_RELEASE = re.compile(
    r"https://github\.com/blesses0603/WLRe_lala/releases/download/"
    r"(v[0-9]+\.[0-9]+\.[0-9]+)/"
    r"(WLRe_LaLa_v[0-9]+\.[0-9]+\.[0-9]+_(?:windows_x64|macos_arm64|macos_x64)\.zip|SHA256SUMS\.txt)\Z"
)
_VERSION = re.compile(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)\Z")
_MAX_META = 256 * 1024
_MAX_CHECKSUM = 64 * 1024
_MAX_ARCHIVE = 800 * 1024 * 1024


class UpdateError(ValueError):
    pass


def version_key(version):
    matched = _VERSION.fullmatch(version)
    if not matched:
        raise UpdateError("無法解析 LaLa 發布版本號")
    return tuple(map(int, matched.groups()))


def release_asset_name(tag, os_name=None, machine=None):
    os_name = sys.platform if os_name is None else os_name
    machine = platform.machine().lower() if machine is None else machine.lower()
    if os_name == "win32" and machine in ("amd64", "x86_64"):
        target = "windows_x64"
    elif os_name == "darwin" and machine in ("arm64", "aarch64"):
        target = "macos_arm64"
    elif os_name == "darwin" and machine in ("x86_64", "amd64"):
        target = "macos_x64"
    else:
        raise UpdateError("目前沒有這個系統架構的自動更新包")
    version_key(tag)
    return f"WLRe_LaLa_{tag}_{target}.zip"


def _read_https(url, limit, *, timeout=10, opener=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise UpdateError("更新來源不是安全 HTTPS")
    if url != RELEASE_API and not _REPO_RELEASE.fullmatch(url):
        raise UpdateError("非官方 GitHub Release 下載路徑")
    requester = opener or urllib.request.urlopen
    request = urllib.request.Request(url, headers={
        "User-Agent": "WLRe-LaLa-UpdateChecker/1",
        "Accept": "application/vnd.github+json" if url == RELEASE_API else "application/octet-stream",
    })
    try:
        with requester(request, timeout=timeout) as response:
            # GitHub asset downloads may redirect to a temporary HTTPS assets host.
            final = urlsplit(response.geturl())
            if final.scheme != "https" or (
                final.hostname not in ("api.github.com", "github.com",
                                       "release-assets.githubusercontent.com",
                                       "objects.githubusercontent.com")
            ):
                raise UpdateError("更新內容轉址到未核准主機")
            if getattr(response, "status", 200) != 200:
                raise UpdateError("GitHub 更新伺服器未回應 200")
            content = response.read(limit + 1)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        raise UpdateError("無法取得 GitHub Release 資訊") from exc
    if len(content) > limit:
        raise UpdateError("更新回應超過大小限制")
    return content


def parse_latest_release(body, current=__version__):
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise UpdateError("Release JSON 格式無效") from exc
    if not isinstance(obj, dict) or obj.get("draft") or obj.get("prerelease"):
        raise UpdateError("找不到可供更新的正式 Release")
    tag = obj.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise UpdateError("Release 版本格式無效")
    version_key(current)
    page = obj.get("html_url")
    if page != f"https://github.com/blesses0603/WLRe_lala/releases/tag/{tag}":
        raise UpdateError("Release 頁面來源無法驗證")
    assets = obj.get("assets")
    if not isinstance(assets, list) or len(assets) > 50:
        raise UpdateError("Release 資產清單無效")
    vetted = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        name, url, size = item.get("name"), item.get("browser_download_url"), item.get("size")
        if not isinstance(name, str) or not isinstance(url, str) or not isinstance(size, int) or size < 1:
            continue
        match = _REPO_RELEASE.fullmatch(url)
        if match and match.group(1) == tag and match.group(2) == name:
            vetted[name] = {"url": url, "size": size}
    status = ("available" if version_key(tag) > version_key(current) else
              "current" if version_key(tag) == version_key(current) else "development_ahead")
    return {"status": status, "local_version": current, "latest_version": tag[1:],
            "tag": tag, "page": page, "assets": vetted}


def check_lala_release(*, getter=_read_https, current=__version__):
    try:
        return parse_latest_release(getter(RELEASE_API, _MAX_META), current=current)
    except (UpdateError, OSError, ValueError):
        return {"status": "unverified", "local_version": current,
                "latest_version": None, "page": RELEASE_PAGE, "assets": {}}


def _expected_sha256(text, name):
    try:
        lines = text.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise UpdateError("校驗碼清單格式不正確") from exc
    hashes = {}
    for line in lines:
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?([^\r\n/\\]+)", line.strip())
        if match:
            hashes[match.group(2)] = match.group(1).lower()
    if name not in hashes:
        raise UpdateError("Release 缺少此平台 ZIP 的 SHA-256 校驗碼")
    return hashes[name]


def _safe_archive_layout(path, os_name):
    """Archive is checked but NOT extracted or executed here."""
    try:
        with zipfile.ZipFile(path) as archive:
            records = archive.infolist()
            if not 1 <= len(records) <= 50000:
                raise UpdateError("發行 ZIP 檔案列表不合理")
            if sum(x.file_size for x in records) > 4 * 1024 * 1024 * 1024:
                raise UpdateError("發行 ZIP 解壓後容量超過安全限制")
            names = [x.filename for x in records]
            if any(
                x.startswith("/") or "\\" in x or
                any(part in ("", ".", "..") for part in x.rstrip("/").split("/"))
                for x in names
            ):
                raise UpdateError("ZIP 含有不安全的路徑")
            if os_name == "win32" and "WLRe_LaLa/WLRe_LaLa.exe" not in names:
                raise UpdateError("Windows 更新包缺少主程式")
            if os_name == "darwin" and not any(
                    p.startswith("WLRe_LaLa.app/Contents/MacOS/") for p in names):
                raise UpdateError("macOS 更新包缺少應用程式")
            if archive.testzip() is not None:
                raise UpdateError("ZIP CRC 檢查未通過")
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError("ZIP 檔案損毀") from exc


def stage_release_update(release, *, dest=None, getter=_read_https,
                         os_name=None, machine=None):
    """Explicitly download and verify next version, never install it silently."""
    if release.get("status") != "available":
        raise UpdateError("目前沒有比 LaLa 更高版本的正式 Release")
    tag = release["tag"]
    os_name = sys.platform if os_name is None else os_name
    file_name = release_asset_name(tag, os_name, machine)
    assets = release["assets"]
    chosen, checksums = assets.get(file_name), assets.get("SHA256SUMS.txt")
    if not chosen or not checksums:
        raise UpdateError("正式版缺少平台 ZIP 或 SHA256SUMS.txt，禁止自動下載")
    if not 0 < chosen["size"] <= _MAX_ARCHIVE or checksums["size"] > _MAX_CHECKSUM:
        raise UpdateError("Release 檔案大小異常")
    expected = _expected_sha256(
        getter(checksums["url"], _MAX_CHECKSUM), file_name)
    folder = Path(dest) if dest is not None else data_root() / "updates" / tag
    folder.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".WLRe_update_", suffix=".part",
                                         dir=folder, delete=False) as stream:
            tmp_path = Path(stream.name)
            content = getter(chosen["url"], chosen["size"])
            if len(content) != chosen["size"]:
                raise UpdateError("更新包實際長度與 GitHub 釋出資訊不符")
            stream.write(content)
        digest = hashlib.file_digest(tmp_path.open("rb"), "sha256").hexdigest()
        if digest != expected:
            raise UpdateError("更新 ZIP SHA-256 不符，拒絕安裝")
        _safe_archive_layout(tmp_path, os_name)
        target = folder / file_name
        os.replace(tmp_path, target)
        tmp_path = None
        return target
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
