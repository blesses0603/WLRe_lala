"""Bundled, release-reviewed LaLa resource compatibility declaration.

The *official server* supplies the observed revisions. This local JSON
declares only what this particular LaLa build was tested against; network
downloads must never edit or replace it.
"""
import json
import re
from pathlib import Path

from wlre.paths import RESOURCE_ROOT

FILENAME = "lala_supported_resources.json"
PACKAGES = ("DataPackage", "MainPackage")
MAX_CONFIG_SIZE = 4096
_GAME_VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}\Z")
_REVISION = re.compile(r"[1-9][0-9]{0,5}\Z")
_MANIFEST = re.compile(r"([1-9][0-9]{0,5})_20[0-9]{2}(?:_[0-9]{2}){6}\Z")


class ResourceBaselineError(ValueError):
    """Shipped compatibility data is missing or not trustworthy."""


def load_supported_resources(path=None):
    """Load the *bundled* compatibility file; validate before any comparison.

    The optional path is for offline unit tests. No environment variable,
    user game installation or official network response supplies this file.
    """
    filename = Path(path) if path is not None else RESOURCE_ROOT / FILENAME
    try:
        raw = filename.read_bytes()
    except OSError as exc:
        raise ResourceBaselineError("LaLa 內建相容性基準檔缺失或無法讀取") from exc
    if len(raw) > MAX_CONFIG_SIZE:
        raise ResourceBaselineError("LaLa 內建相容性基準資料過大")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ResourceBaselineError("LaLa 內建相容性基準不是有效 JSON") from exc
    if (not isinstance(document, dict) or
            set(document) != {"schema_version", "official_game_exe_version", "packages"} or
            type(document["schema_version"]) is not int or
            document["schema_version"] != 1 or
            not isinstance(document["official_game_exe_version"], str) or
            not _GAME_VERSION.fullmatch(document["official_game_exe_version"])):
        raise ResourceBaselineError("LaLa 內建相容性基準版本或結構不正確")
    packages = document["packages"]
    if not isinstance(packages, dict) or set(packages) != set(PACKAGES):
        raise ResourceBaselineError("LaLa 內建相容性資源包清單不完整")
    for name in PACKAGES:
        entry = packages[name]
        if (not isinstance(entry, dict) or set(entry) != {"revision", "manifest"} or
                not isinstance(entry["revision"], str) or
                not _REVISION.fullmatch(entry["revision"]) or
                not isinstance(entry["manifest"], str)):
            raise ResourceBaselineError("LaLa " + name + " 支援基準格式不正確")
        manifest = _MANIFEST.fullmatch(entry["manifest"])
        if manifest is None or manifest.group(1) != entry["revision"]:
            raise ResourceBaselineError("LaLa " + name + " 完整 Manifest 與版本號不一致")
    return document


def baseline_maps(document):
    """Derive both comparison views from ONE validated JSON declaration."""
    return (
        {name: document["packages"][name]["revision"] for name in PACKAGES},
        {name: document["packages"][name]["manifest"] for name in PACKAGES},
    )


def baseline_label(revisions):
    """Display one common revision, or both numbers if packages differ."""
    if not isinstance(revisions, dict) or set(revisions) != set(PACKAGES):
        raise ResourceBaselineError("LaLa 支援基準不完整，無法顯示")
    if all(revisions[name] == revisions[PACKAGES[0]] for name in PACKAGES):
        return revisions[PACKAGES[0]]
    return "／".join(name + " " + revisions[name] for name in PACKAGES)
