"""Read-only, fail-closed official YooAsset version comparison.

The 1262 IL2CPP metadata contains the public CDN *root*, not verified .version
paths. Never interpret a missing/unreachable endpoint as a compatible client.
"""
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASELINE = {"MainPackage": "1262", "DataPackage": "1262"}
OFFICIAL_HOST = "wlreupload.chinesegamer.net"
OFFICIAL_PATH_PREFIX = "/wln/TW/"
MAX_RESPONSE_BYTES = 4096
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class VersionSourceError(ValueError):
    """The official version source could not be trusted or read."""


def validate_source(url):
    """Reject non-official endpoints and embedded credentials before networking."""
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise VersionSourceError("來源網址無效")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != OFFICIAL_HOST
            or parsed.port is not None or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or not parsed.path.startswith(OFFICIAL_PATH_PREFIX)
            or not parsed.path.endswith((".version", ".txt", ".json"))):
        raise VersionSourceError("僅允許官方 HTTPS CDN 下的版本紀錄網址")
    return url


def parse_version(body):
    """Handle YooAsset text version and explicit JSON version fields only."""
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
            raise VersionSourceError("版本 JSON 格式無效")
        text = record.get("packageVersion", record.get("PackageVersion", record.get("version")))
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        raise VersionSourceError("版本內容不符合預期，拒絕推測")
    return text


class _SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_version(url, *, timeout=5, opener=None):
    validate_source(url)
    if opener is None:
        opener = build_opener(_SameHostRedirect()).open
    try:
        with opener(Request(url, headers={"Accept": "text/plain, application/json", "User-Agent": "WLRe-LaLa-VersionCheck/1"}), timeout=timeout) as response:
            # urllib may follow redirects: validate final URL, too.
            validate_source(response.geturl())
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise VersionSourceError("無法取得官方版本紀錄") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise VersionSourceError("版本回應過大")
    return parse_version(body)


def _game_resource_number(version):
    """Handle numbered YooAsset package names such as 1275_2026_10_21_18_29_38_49.

    Timestamps distinguish manifests within one game revision; LaLa's current
    compatibility baseline only records the numbered game resource revision.
    """
    match = re.fullmatch(r"(\\d+)(?:_20\\d{2}(?:_\\d{2}){6})?", version)
    return int(match.group(1)) if match else None


def compare_versions(local, remote):
    if local == remote:
        return "same"
    old_version, new_version = _game_resource_number(local), _game_resource_number(remote)
    if old_version is not None and new_version is not None:
        return ("same" if new_version == old_version else
                "newer" if new_version > old_version else "older")
    return "different"  # Non-numeric YooAsset versions are opaque identifiers.


def check_official_versions(sources=None, *, fetcher=fetch_version):
    """Returns evidence, not a claim of protocol compatibility or official approval.

    No source configured = unverified; a partially reachable source is also
    unverified, even when one package is unchanged.
    """
    sources = sources or {}
    results = {}
    for package, baseline in BASELINE.items():
        url = sources.get(package)
        if not url:
            results[package] = {"baseline": baseline, "remote": None,
                                "comparison": "unverified", "reason": "尚未確認官方版本紀錄網址"}
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
    return {"status": status, "packages": results,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol_compatibility": "unverified", "read_only": True}
