"""Read-only official PC YooAsset version discovery.

Evidence: official game's Fiddler HTTPS GETs for ResourcePath_PC.dat and
MainPackage.version / DataPackage.version on wlreftp.chinesegamer.net.
Never read local game files or infer a remote version from the LaLa app version.
"""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASELINE = {"MainPackage": "1262", "DataPackage": "1262"}
OFFICIAL_HOST = "wlreftp.chinesegamer.net"
ROOT = f"https://{OFFICIAL_HOST}/WLN/TW/"
RESOURCE_PATH_URL = ROOT + "ResourcePath_PC.dat"
SUPPORTED_EXE_VERSION = "1.3.0"  # Official game ExeVer, NOT WLRe_LaLa.__version__.
MAX_RESPONSE_BYTES = 4096
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_PATH_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
_PACKAGE_PATH = re.compile(
    r"/WLN/TW/(?P<data_ver>\d+\.\d+\.\d+)/ResourcesPC/AssetBundle/"
    r"(?P<package>MainPackage|DataPackage)\.version\Z"
)


class VersionSourceError(ValueError):
    """Untrusted URL, unusable format or unavailable remote resource."""


def validate_source(url, *, permit_cache_parameter=False):
    """Only the exact observed CDN endpoints, never arbitrary hosts/paths."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise VersionSourceError("官方來源網址無效")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise VersionSourceError("官方來源網址格式不正確") from exc
    if (parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST or
            port is not None or parsed.username is not None or
            parsed.password is not None or parsed.fragment or
            parsed.path != "/WLN/TW/ResourcePath_PC.dat" and
            not _PACKAGE_PATH.fullmatch(parsed.path)):
        raise VersionSourceError("僅允許已實際觀測的官方 HTTPS PC 版本端點")
    if parsed.path != "/WLN/TW/ResourcePath_PC.dat":
        version = _PACKAGE_PATH.fullmatch(parsed.path).group("data_ver")
        if not _PATH_VERSION.fullmatch(version):
            raise VersionSourceError("資源路徑版本格式不正確")
    if parsed.query:
        if not permit_cache_parameter:
            raise VersionSourceError("不允許手動附加查詢參數")
        qs = parse_qs(parsed.query)
        if set(qs) != {"_ts"} or len(qs["_ts"]) != 1 or not qs["_ts"][0].isdigit():
            raise VersionSourceError("不允許非快取控制的查詢參數")
    return url


class _OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source(newurl, permit_cache_parameter=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official_bytes(url, *, timeout=5, opener=None, nonce=None):
    """GET only, bounded response and no-store request; validate final URL."""
    validate_source(url)
    nonce = str(time.time_ns()) if nonce is None else str(nonce)
    if not nonce.isdigit():
        raise VersionSourceError("快取控制值無效")
    requested_url = url + "?_ts=" + nonce
    if opener is None:
        opener = build_opener(_OfficialRedirect()).open
    request = Request(requested_url, headers={
        "Accept": "text/plain, application/json",
        "Cache-Control": "no-cache, no-store",
        "Pragma": "no-cache",
        "User-Agent": "WLRe-LaLa-VersionCheck/1",
    })
    try:
        with opener(request, timeout=timeout) as response:
            final_url = response.geturl()
            validate_source(final_url, permit_cache_parameter=True)
            if final_url.split("?", 1)[0] != url:
                raise VersionSourceError("版本查詢出現非預期轉址")
            if hasattr(response, "status") and response.status != 200:
                raise VersionSourceError("官方版本查詢未回傳 HTTP 200")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, ValueError, TypeError) as exc:
        raise VersionSourceError("官方 HTTPS 版本檔無法取得") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise VersionSourceError("官方版本檔超過大小限制")
    return raw


def parse_version(body):
    try:
        text = body.decode("utf-8-sig").strip()
    except (UnicodeError, AttributeError) as exc:
        raise VersionSourceError("版本內容不是 UTF-8") from exc
    if text.startswith("{"):
        try:
            record = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise VersionSourceError("版本 JSON 無法解析") from exc
        if not isinstance(record, dict):
            raise VersionSourceError("版本 JSON 必須是物件")
        text = record.get("packageVersion", record.get("PackageVersion", record.get("version")))
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        raise VersionSourceError("版本內容格式錯誤")
    return text


def parse_resource_path(body, *, exe_version=SUPPORTED_EXE_VERSION):
    """Parse the observed [{ExeVer,DataVer},...] official PC mapping.

    Choose the highest *advertised* official ExeVer to avoid silently staying
    in an old directory when a new client version appears.
    """
    try:
        records = json.loads(body.decode("utf-8-sig"))
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise VersionSourceError("ResourcePath_PC.dat 不是有效 JSON") from exc
    if not isinstance(records, list) or not 1 <= len(records) <= 64:
        raise VersionSourceError("官方資源路徑清單不完整")
    known = {}
    for entry in records:
        if not isinstance(entry, dict) or set(entry) != {"ExeVer", "DataVer"}:
            raise VersionSourceError("資源路徑資料欄位不正確")
        exe_ver, data_ver = entry["ExeVer"], entry["DataVer"]
        if (not isinstance(exe_ver, str) or not _PATH_VERSION.fullmatch(exe_ver)
                or not isinstance(data_ver, str) or not _PATH_VERSION.fullmatch(data_ver)
                or exe_ver in known):
            raise VersionSourceError("資源路徑版本無效或有重複")
        known[exe_ver] = data_ver
    if exe_version not in known:
        raise VersionSourceError("官方資源路徑清單缺少 LaLa 對應遊戲版本")
    latest_exe = max(known, key=lambda v: tuple(map(int, v.split("."))))
    return {"resource_path_version": known[latest_exe],
            "latest_exe_version": latest_exe,
            "supported_exe_version": exe_version,
            "supported_resource_path_version": known[exe_version],
            "client_path_changed": known[exe_version] != known[latest_exe]}


def package_sources(resource_path_version):
    if not isinstance(resource_path_version, str) or not _PATH_VERSION.fullmatch(resource_path_version):
        raise VersionSourceError("官方資源路徑版本無效")
    root = ROOT + resource_path_version + "/ResourcesPC/AssetBundle/"
    urls = {package: root + package + ".version" for package in BASELINE}
    for url in urls.values():
        validate_source(url)
    return urls


def fetch_version(url, *, timeout=5, opener=None):
    return parse_version(fetch_official_bytes(url, timeout=timeout, opener=opener))


def _game_resource_number(version):
    match = re.fullmatch(r"(\d+)(?:_20\d{2}(?:_\d{2}){6})?", version)
    return int(match.group(1)) if match else None


def compare_versions(local, remote):
    if local == remote:
        return "same"
    left, right = _game_resource_number(local), _game_resource_number(remote)
    if left is not None and right is not None:
        return "same" if right == left else "newer" if right > left else "older"
    return "different"


def check_official_versions(sources=None, *, fetcher=fetch_version):
    sources = sources or {}
    results = {}
    for package, baseline in BASELINE.items():
        url = sources.get(package)
        if not url:
            results[package] = {"baseline": baseline, "remote": None,
                                "comparison": "unverified", "reason": "未取得正式版本網址"}
            continue
        try:
            remote = fetcher(url)
            results[package] = {"baseline": baseline, "remote": remote,
                                "comparison": compare_versions(baseline, remote)}
        except (VersionSourceError, OSError, ValueError):
            results[package] = {"baseline": baseline, "remote": None,
                                "comparison": "unverified", "reason": "官方版本來源無法驗證"}
    states = {v["comparison"] for v in results.values()}
    status = ("unverified" if "unverified" in states else
              "same_resources" if states == {"same"} else "resources_changed")
    return {
        "status": status, "packages": results,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocol_compatibility": "unverified", "read_only": True,
    }


def check_official_pc_versions(*, path_fetcher=fetch_official_bytes,
                               version_fetcher=fetch_version):
    """Official 3-stage lookup; only accepts resource path from official JSON."""
    checked = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        mapping = parse_resource_path(path_fetcher(RESOURCE_PATH_URL))
        sources = package_sources(mapping["resource_path_version"])
    except (VersionSourceError, OSError, ValueError) as exc:
        return {"status": "unverified",
                "packages": {name: {"baseline": baseline, "remote": None,
                                    "comparison": "unverified", "reason": "官方資源路徑無法驗證"}
                             for name, baseline in BASELINE.items()},
                "reason": "ResourcePath_PC.dat 無法確認",
                "resource_path": None, "checked_at_utc": checked,
                "protocol_compatibility": "unverified", "read_only": True}
    result = check_official_versions(sources, fetcher=version_fetcher)
    result["resource_path"] = mapping
    result["source"] = "official_pc_three_stage"
    # A newly advertised path is already a resource-path update, even when
    # individual package requests fail; never report the old path as current.
    if mapping["client_path_changed"]:
        result["status"] = "resources_changed"
        result["reason"] = "官方最新遊戲版本改用其他資源路徑"
    return result
