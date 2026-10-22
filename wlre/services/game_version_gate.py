"""Check the *official remote* YooAsset versions before allowing LaLa login.

The LaLa-supported baseline is 1262. Local installation versions, LaLa app
version, cached manifests and game install paths are NEVER consulted.
An official endpoint must first be independently verified and explicitly
configured; otherwise the result is unverified, not a fabricated match.
"""
import os

from wlre.services.official_version import (
    BASELINE, check_official_versions, check_official_pc_versions,
)


def configured_sources(environ=None):
    """Only trusted version URLs supplied by deployment/user configuration."""
    env = os.environ if environ is None else environ
    return {
        "MainPackage": env.get("WLRE_OFFICIAL_MAIN_VERSION_URL") or None,
        "DataPackage": env.get("WLRE_OFFICIAL_DATA_VERSION_URL") or None,
    }


def run_prelogin_check(sources=None, *, checker=check_official_versions,
                       discovery_checker=check_official_pc_versions):
    """Compare remote resource versions with LaLa's 1262 compatibility baseline.

    Explicit observed differences block login, even when the other endpoint
    cannot be checked. Missing/failed endpoints are UNKNOWN, never synced.
    No game credentials or files are accessed.
    """
    if sources is None:
        # Automatic three-stage discovery (no setup, no local game files).
        remote = discovery_checker()
    else:
        # Explicit URLs retained for diagnostics/tests only.
        remote = checker(sources)
    packages = remote.get("packages", {})
    confirmed_change = (
        remote.get("status") == "resources_changed" or
        any(info.get("comparison") in {"newer", "older", "different"}
            for info in packages.values())
    )
    all_same = (remote.get("status") == "same_resources" and
                all(packages.get(package, {}).get("comparison") == "same"
                    for package in BASELINE))
    if confirmed_change:
        status = "blocked"
        message = (
            "官方伺服器資源版本已與 LaLa 支援的 1262 不同，"
            "禁止登入；請等待 LaLa 更新與相容性驗證。"
        )
    elif all_same:
        status = "version_identifiers_match"
        message = (
            "官方 MainPackage／DataPackage 版本識別值均符合 1262；"
            "遊戲協定是否相容仍須另外驗證。"
        )
    else:
        status = "unverified"
        message = (
            "官方遊戲資源版本無法驗證：官方版本設定或資源查詢失敗。"
            "此結果不代表已同步最新版。"
        )
    return {
        "status": status,
        "blocked": confirmed_change,
        "message": message,
        "remote": remote,
        "baseline": dict(BASELINE),
        "source": "official_remote_only",
    }
