"""Remote official game resource compatibility gate; baseline 1262.

Do not read the local Unity installation, LaLa binary or disk ManifestFiles.
"""
from wlre.services.official_version import (
    BASELINE, RESOURCE_MAP_URL, check_official_game_resources, check_official_versions,
)


def configured_sources(environ=None):
    """The public verified root; per-package paths are resolved dynamically."""
    return {"ResourcePath_PC.dat": RESOURCE_MAP_URL}


def run_prelogin_check(sources=None, *, checker=None):
    """Check official source and block upon a confirmed incompatible revision.

    Explicit sources/checker are reserved for offline regression tests/CLI.
    Normal GUI startup always performs the ResourcePath_PC.dat lookup.
    """
    if checker is not None:
        remote = checker(sources or {})
    elif sources is not None:
        remote = check_official_versions(sources)
    else:
        remote = check_official_game_resources()
    packages = remote.get("packages", {})
    package_changed = (
        remote.get("status") == "resources_changed" or
        any(item.get("comparison") in ("newer", "older", "different")
            for item in packages.values())
    )
    client_changed = bool(remote.get("newer_official_client"))
    blocked = package_changed or client_changed
    all_same = (
        remote.get("status") == "same_resources" and
        all(packages.get(package, {}).get("comparison") == "same" for package in BASELINE)
    )
    if blocked:
        status = "blocked"
        if client_changed and not package_changed:
            message = "官方遊戲客戶端版本已有變更，請等待 LaLa 更新與相容性確認；禁止登入。"
        else:
            message = "官方遊戲資源版本已與 LaLa 支援的 1262 不同，禁止登入；請等待 LaLa 更新與相容性驗證。"
    elif all_same:
        status = "version_identifiers_match"
        message = ("官方 MainPackage／DataPackage 版本識別值均符合 1262；"
                   "遊戲協定相容性仍須另外驗證。")
    else:
        status = "unverified"
        message = "官方版本無法完整驗證，可能是網路失敗或更新資料不足；不代表已同步官方最新版本。"
    return {"status": status, "blocked": blocked, "message": message,
            "remote": remote, "baseline": dict(BASELINE), "source": "official_remote_only"}
