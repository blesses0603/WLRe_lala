"""Read-only official game resource checks against the observed PC endpoints.

Fiddler evidence (2026-10-22):
  GET https://wlreftp.chinesegamer.net/WLN/TW/ResourcePath_PC.dat
  GET https://wlreftp.chinesegamer.net/WLN/TW/{DataVer}/ResourcesPC/AssetBundle/{Package}.version
Both .version responses were 27-byte YooAsset revision identifiers, 1275.
No local game installation or login credentials are needed.
"""
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASELINE = {"MainPackage": "1262", "DataPackage": "1262"}
# Exact versions from the two user-provided 1262 YooAsset manifest filename pairs.
# No copyrighted Unity asset binaries are bundled into the application.
BASELINE_MANIFEST = {
    "MainPackage": "1262_2026_10_14_15_02_22_47",
    "DataPackage": "1262_2026_10_14_15_00_34_84",
}
# This is the official GAME executable identity from the Fiddler DataVer map,
# not the LaLa program version, and never read from the user's installed game.
SUPPORTED_OFFICIAL_EXE_VERSION = "1.3.0"
OFFICIAL_HOST = "wlreftp.chinesegamer.net"
ROOT = "https://wlreftp.chinesegamer.net/WLN/TW"
RESOURCE_MAP_URL = ROOT + "/ResourcePath_PC.dat"
MAX_RESPONSE_BYTES = 16 * 1024
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_DATA_VER = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\Z")
_SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_RESOURCE_FILE = re.compile(
    r"/WLN/TW/[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}/ResourcesPC/AssetBundle/"
    r"(?:MainPackage|DataPackage)\.version\Z"
)


class VersionSourceError(ValueError):
    """Official game version data is missing, invalid or untrusted."""


def validate_source(url):
    """Restrict requests to two observed types of public official URL."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise VersionSourceError("網址格式無效")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise VersionSourceError("網址格式無效") from exc
    if (parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST or
            port is not None or parsed.username is not None or
            parsed.password is not None or parsed.fragment or
            (parsed.query and not re.fullmatch(r"[0-9]{1,20}", parsed.query))):
        raise VersionSourceError("非官方 HTTPS 版本來源")
    if parsed.path != "/WLN/TW/ResourcePath_PC.dat" and not _RESOURCE_FILE.fullmatch(parsed.path):
        raise VersionSourceError("非已確認的官方資源版本路徑")
    # Reject any percent-encoding or backslash, including encoded traversal.
    if "%" in parsed.path or "\\" in parsed.path:
        raise VersionSourceError("版本路徑包含非法字元")
    return url


class _ApprovedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source(newurl)
        # Do not follow a redirect to a different asset/file or subdomain.
        if urlsplit(req.full_url).path != urlsplit(newurl).path:
            raise VersionSourceError("官方版本來源轉址到其他檔案")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _request_problem(exc):
    """Public-safe failure category; never put remote headers, URLs or tokens in UI."""
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}（官方 CDN 拒絕或找不到檔案）"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "連線逾時"
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)):
        return "TLS 憑證驗證失敗"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, (ssl.SSLError, ssl.CertificateError)):
            return "TLS 憑證驗證失敗"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "連線逾時"
        if isinstance(reason, socket.gaierror):
            return "DNS 無法解析官方網域"
        if isinstance(reason, ConnectionRefusedError):
            return "官方伺服器拒絕連線"
        return "HTTPS 連線失敗"
    if isinstance(exc, socket.gaierror):
        return "DNS 無法解析官方網域"
    if isinstance(exc, VersionSourceError):
        return str(exc)
    return "無法取得回應"


def fetch_bytes(url, *, timeout=12, opener=None):
    """GET with a cache-busting numeric query and a strict payload cap."""
    validate_source(url)
    target = (url if "?" in url else
              url + "?" + str(int(time.time() * 1000)))
    validate_source(target)
    if opener is None:
        opener = build_opener(_ApprovedRedirect()).open
    headers = {
        "Accept": "text/plain, application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "WLRe-LaLa-VersionCheck/1",
    }

    def read_one(request_url):
        validate_source(request_url)
        with opener(Request(request_url, headers=headers), timeout=timeout) as response:
            returned = response.geturl()
            validate_source(returned)
            if urlsplit(returned).path != urlsplit(url).path:
                raise VersionSourceError("回應網址與預期不一致")
            if getattr(response, "status", 200) != 200:
                raise VersionSourceError("官方回應不是 HTTP 200")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise VersionSourceError("官方版本回應超過安全上限")
            return body

    try:
        return read_one(target)
    except HTTPError as exc:
        # Some CDNs reject an unfamiliar cache-busting query. Retry exactly
        # once with the observed canonical HTTPS path; never change host or TLS.
        if exc.code not in (400, 403, 404) or "?" in url:
            raise VersionSourceError(_request_problem(exc)) from exc
        try:
            return read_one(url)
        except (OSError, ValueError) as retry_exc:
            raise VersionSourceError(_request_problem(retry_exc)) from retry_exc
    except (OSError, ValueError) as exc:
        raise VersionSourceError(_request_problem(exc)) from exc


def parse_version(body):
    try:
        value = body.decode("utf-8-sig").strip()
    except (AttributeError, UnicodeError) as exc:
        raise VersionSourceError("版本內容不是 UTF-8") from exc
    if value.startswith("{"):
        try:
            record = json.loads(value)
            value = record.get("packageVersion", record.get("PackageVersion", record.get("version")))
        except (ValueError, TypeError, AttributeError) as exc:
            raise VersionSourceError("版本 JSON 不正確") from exc
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise VersionSourceError("版本內容格式不正確")
    return value


def fetch_version(url, *, timeout=5, opener=None):
    return parse_version(fetch_bytes(url, timeout=timeout, opener=opener))


def _numeric_game_revision(version):
    match = re.fullmatch(r"([0-9]+)(?:_20[0-9]{2}(?:_[0-9]{2}){6})?", version)
    return int(match.group(1)) if match else None


def compare_versions(local, remote):
    if local == remote:
        return "same"
    a, b = _numeric_game_revision(local), _numeric_game_revision(remote)
    if a is not None and b is not None:
        return "same" if a == b else "newer" if b > a else "older"
    return "different"


def parse_resource_path(body, exe_version=SUPPORTED_OFFICIAL_EXE_VERSION):
    """Parse official PC ExeVer->DataVer JSON; no best-guess version fallback."""
    try:
        rows = json.loads(body.decode("utf-8-sig"))
    except (ValueError, UnicodeError, AttributeError) as exc:
        raise VersionSourceError("ResourcePath_PC.dat 不是有效 JSON") from exc
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise VersionSourceError("資源路徑對照表格式不符")
    matched = []
    newer_exe = []
    for item in rows:
        if (not isinstance(item, dict) or
                not isinstance(item.get("ExeVer"), str) or
                not isinstance(item.get("DataVer"), str) or
                not _SEMVER.fullmatch(item["ExeVer"]) or
                not _DATA_VER.fullmatch(item["DataVer"])):
            raise VersionSourceError("對照表內有不合法的版本資料")
        if item["ExeVer"] == exe_version:
            matched.append(item["DataVer"])
        if tuple(map(int, item["ExeVer"].split("."))) > tuple(map(int, exe_version.split("."))):
            newer_exe.append(item["ExeVer"])
    if len(matched) != 1:
        raise VersionSourceError("官方找不到唯一對應的遊戲程式版本")
    # A newly published official PC executable may change DataVer. Check the
    # newest public mapping and block the unsupported executable separately;
    # never keep fetching the old 1.3.21 path as if it were the latest.
    latest = max(rows, key=lambda item: tuple(map(int, item["ExeVer"].split("."))))
    latest_version = tuple(map(int, latest["ExeVer"].split(".")))
    supported_version = tuple(map(int, exe_version.split(".")))
    actual_path_version = latest["DataVer"] if latest_version > supported_version else matched[0]
    return {"exe_version": exe_version, "data_version": actual_path_version,
            "supported_data_version": matched[0],
            "selected_exe_version": latest["ExeVer"] if latest_version > supported_version else exe_version,
            "newer_exe_versions": sorted(set(newer_exe), key=lambda x: tuple(map(int, x.split("."))))}


def official_package_urls(data_version):
    if not isinstance(data_version, str) or not _DATA_VER.fullmatch(data_version):
        raise VersionSourceError("官方資源目錄版號格式不正確")
    return {
        package: ROOT + "/" + data_version + "/ResourcesPC/AssetBundle/" + package + ".version"
        for package in BASELINE
    }


def check_official_versions(sources=None, *, fetcher=fetch_version,
                            strict_manifest=False):
    sources = sources or {}
    results = {}
    for package, baseline in BASELINE.items():
        url = sources.get(package)
        if not url:
            results[package] = {"baseline": baseline, "remote": None,
                                "comparison": "unverified", "reason": "無官方版本網址"}
            continue
        try:
            remote = fetcher(url)
            comparison = compare_versions(baseline, remote)
            if strict_manifest:
                # The full YooAsset manifest identity changes on republish even
                # when the numeric resource revision is held at 1262.
                if remote == BASELINE_MANIFEST[package]:
                    comparison = "same"
                elif remote == baseline:
                    comparison = "unverified"  # A bare integer cannot verify identity.
                elif comparison == "same":
                    comparison = "different"
            results[package] = {"baseline": baseline,
                                "baseline_manifest": BASELINE_MANIFEST[package],
                                "remote": remote, "comparison": comparison}
        except (VersionSourceError, OSError, ValueError) as exc:
            results[package] = {"baseline": baseline, "remote": None,
                                "comparison": "unverified",
                                "reason": _request_problem(exc)}
    states = {v["comparison"] for v in results.values()}
    status = ("unverified" if "unverified" in states else
              "same_resources" if states == {"same"} else "resources_changed")
    return {"status": status, "packages": results,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol_compatibility": "unverified", "read_only": True}


def check_official_game_resources(*, fetcher=fetch_bytes, exe_version=SUPPORTED_OFFICIAL_EXE_VERSION):
    """Sequential remote lookup. No local game/LaLa files are consulted."""
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        path = parse_resource_path(fetcher(RESOURCE_MAP_URL), exe_version=exe_version)
    except (VersionSourceError, OSError, ValueError) as exc:
        return {"status": "unverified", "packages": {
            p: {"baseline": b, "remote": None, "comparison": "unverified"}
            for p, b in BASELINE.items()}, "resource_path": None,
            "newer_official_client": False, "failed_stage": "ResourcePath_PC.dat",
            "reason": _request_problem(exc),
            "checked_at_utc": checked_at,
            "protocol_compatibility": "unverified", "read_only": True}
    urls = official_package_urls(path["data_version"])
    result = check_official_versions(urls, fetcher=lambda url: parse_version(fetcher(url)),
                                     strict_manifest=True)
    result["resource_path"] = path["data_version"]
    result["failed_stage"] = next(
        (pkg + ".version" for pkg in BASELINE
         if result["packages"][pkg]["comparison"] == "unverified"), None)
    result["official_exe_version"] = exe_version
    result["newer_official_client"] = bool(path["newer_exe_versions"])
    result["newer_official_exe_versions"] = path["newer_exe_versions"]
    # A newer official executable is a separate compatibility-warning signal,
    # not evidence that a particular YooAsset package changed.
    return result
