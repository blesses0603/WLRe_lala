"""Pre-login, read-only game resource version gate (1262 baseline).

Local file names prove *observed installed manifest candidates*, not a remote
official latest version. Remote checks only run when official URLs are supplied.
"""
import os
import re
import sys
from pathlib import Path
from wlre.services.official_version import BASELINE, check_official_versions

_PATTERN = re.compile(
    r"^(MainPackage|DataPackage)_(\d{3,})_(20\d{2}(?:_\d{2}){6})\.(bytes|hash)$",
    re.IGNORECASE,
)
_PACKAGES = tuple(BASELINE)


def find_yoo_root(selected=None, *, strict=False):
    """Search explicit, saved and bounded local installation candidates only."""
    candidates = []
    if selected:
        candidates.append(Path(selected))
    if strict and not selected:
        return None
    env = os.getenv("WLRE_GAME_YOO_ROOT")
    if not strict:
        if env:
            candidates.append(Path(env))
        for base in (Path(sys.executable).resolve().parent, Path.cwd()):
            candidates.extend((base, base.parent, base.parent.parent))
        # A previously reported installation layout; no filesystem-wide crawl.
        candidates.append(Path("D:/Program Files/D/wlre"))
    seen = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
            if key in seen:
                continue
            seen.add(key)
            paths = [candidate, candidate / "yoo"]
            if candidate.is_dir() and not (candidate / "MainPackage").is_dir():
                paths.extend(p / "yoo" for p in candidate.glob("*_Data") if p.is_dir())
            for root in paths:
                if all((root / package / "ManifestFiles").is_dir() for package in _PACKAGES):
                    return root
        except (OSError, ValueError):
            continue
    return None


def scan_local_manifests(selected=None):
    """Inspect paired manifest filenames only; do not read or mutate game assets."""
    root = find_yoo_root(selected)
    result = {"status": "unverified", "root": str(root) if root else None,
              "packages": {}, "baseline": dict(BASELINE)}
    if root is None:
        result["reason"] = "尚未找到官方遊戲的 YooAsset ManifestFiles 資料夾"
        return result
    changed = False
    complete = True
    for package, baseline in BASELINE.items():
        folder = root / package / "ManifestFiles"
        pairs = {}
        try:
            for path in folder.iterdir():
                if not path.is_file() or path.is_symlink():
                    continue
                match = _PATTERN.fullmatch(path.name)
                if match is None or match.group(1).lower() != package.lower():
                    continue
                version, timestamp, suffix = match.group(2), match.group(3), match.group(4).lower()
                pairs.setdefault((int(version), timestamp), set()).add(suffix)
        except OSError:
            complete = False
            result["packages"][package] = {"status": "unverified", "reason": "無法讀取 ManifestFiles"}
            continue
        valid = sorted((v, t) for (v, t), ext in pairs.items() if {"bytes", "hash"} <= ext)
        if not valid:
            complete = False
            result["packages"][package] = {"status": "unverified", "reason": "找不到完整的 bytes/hash 配對"}
            continue
        version, timestamp = valid[-1]
        observed = str(version)
        state = "same" if observed == baseline else "changed"
        changed |= state == "changed"
        result["packages"][package] = {
            "status": state, "version": observed,
            "manifest_id": f"{package}_{observed}_{timestamp}",
            "baseline": baseline,
        }
    # Confirmed divergence blocks even if other package manifests are absent.
    result["status"] = ("changed" if changed else "same_local" if complete else "unverified")
    if not changed and not complete:
        result["reason"] = "本機資源紀錄不完整"
    return result


def run_prelogin_check(selected=None, sources=None):
    """Fail-closed on *observed change*, not on offline/unconfigured endpoints.

    Unverified never means synced. The login UI must prominently warn that
    online compatibility remains unverified if no official URL was confirmed.
    """
    local = scan_local_manifests(selected)
    if sources is None:
        sources = {
            "MainPackage": os.getenv("WLRE_OFFICIAL_MAIN_VERSION_URL"),
            "DataPackage": os.getenv("WLRE_OFFICIAL_DATA_VERSION_URL"),
        }
    remote = check_official_versions(sources)
    # A confirmed changed package is sufficient to block, even if the other
    # endpoint is unavailable; partial unverified must not suppress evidence.
    remote_changed = any(item.get("comparison") in ("newer", "older", "different")
                         for item in remote.get("packages", {}).values())
    blocked = local["status"] == "changed" or remote_changed
    if blocked:
        message = "偵測到遊戲資源版本異動（LaLa 基準 1262），禁止登入；請等待 LaLa 更新與相容性驗證。"
        status = "blocked"
    elif local["status"] == "same_local" and remote["status"] == "same_resources":
        status = "version_identifiers_match"
        message = "1262 資源版本識別值一致；遊戲協定相容性仍未經驗證。"
    else:
        status = "unverified"
        detail = local.get("reason") or "尚無經確認的官方即時版本查詢來源"
        message = f"版本無法完整驗證（{detail}），目前未觀測到版本異動；不代表已同步官方最新版。"
    return {"blocked": blocked, "status": status, "message": message,
            "local": local, "remote": remote, "baseline": dict(BASELINE)}
