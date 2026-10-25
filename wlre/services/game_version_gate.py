"""Remote official game resource compatibility gate; bundled baseline.

Do not read the local Unity installation, LaLa binary or disk ManifestFiles.
"""
from wlre.services.official_version import (
    BASELINE, RESOURCE_MAP_URL, check_official_game_resources, check_official_versions,
)
from wlre.services.resource_compatibility import baseline_label


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
    all_same = (
        remote.get("status") == "same_resources" and
        all(packages.get(package, {}).get("comparison") == "same" for package in BASELINE)
    )
    # Fail closed: network errors, partial responses and unknown revisions
    # cannot become a login permit, even when the local 1275 cache is valid.
    blocked = package_changed or client_changed or not all_same
    support = baseline_label(BASELINE)
    if package_changed or client_changed:
        status = "blocked"
        if client_changed and not package_changed:
            message = (f"官方遊戲客戶端版本已有變更，LaLa 支援資源基準為 {support}；"
                       "禁止登入，請等待 LaLa 更新與相容性確認。")
        else:
            message = (f"官方遊戲資源版本與 LaLa 支援基準 {support} 不同；"
                       "禁止登入，請等待 LaLa 更新與相容性驗證。")
    elif all_same:
        status = "version_identifiers_match"
        message = (f"官方 MainPackage／DataPackage 版本識別值均符合 LaLa 支援基準 {support}；"
                   "遊戲協定相容性仍須另外驗證。")
    else:
        status = "unverified"
        message = (f"官方版本無法完整驗證（LaLa 支援基準 {support}），"
                   "可能是網路失敗或更新資料不足；禁止登入，請重新查詢官方版本。")
    # Official 1275 version identifiers are necessary, but not sufficient:
    # the matching, pinned 1275 data must be installed before live login.
    if (checker is None and sources is None
            and all(str(value) == '1275' for value in BASELINE.values())):
        from wlre.services.world.runtime_1275 import ready
        resources_ok, reason = ready()
        if not resources_ok:
            # A network outage/unknown revision must not bypass mandatory
            # 1275 asset validation and accidentally use bundled 1262 IDs.
            if blocked:
                # Preserve confirmed remote update/rejection as the primary
                # reason. Never rewrite a 1276 server change as local-only.
                message += ' 另外本機 1275 資料驗證未通過；禁止使用 1262 舊索引登入：' + reason
            else:
                blocked = True
                status = "blocked"
                message = ('LaLa 1275 缺少已校驗的 NPC／商店／製作／場景資料；'
                           '禁止使用 1262 舊索引登入。' + reason)
        elif all_same and not blocked:
            message += ' 已確認本機 1275 資源包完整；尚未等同正式伺服器協定驗收。'
    return {"status": status, "blocked": blocked, "message": message,
            "remote": remote, "baseline": dict(BASELINE),
            "baseline_label": support, "source": "official_remote_only"}
