"""動態觀測官方版本；不比較固定遊戲版號、不啟用候選資料。"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from wlre import __version__
from wlre.core.primitives import check_cancelled
from wlre.resources_runtime.official.source import ROOT, package_url
from wlre.services.official_version import (
    fetch_bytes,
    parse_resource_path,
    parse_version,
)


class VersionObservationError(ValueError):
    pass


@dataclass(frozen=True)
class OfficialVersions:
    requested_exe_version: str
    observed_exe_version: str
    data_version: str
    data_package_version: str
    main_package_version: str
    resource_map_sha256: str
    resource_map_raw: bytes = field(repr=False)
    source_url: str
    observed_at: str
    lala_version: str = __version__


class VersionDetector:
    """兩次有界觀測必須一致；版本正好在更新時拒絕回傳混合觀測。"""

    def __init__(self, *, fetcher=None):
        self._fetcher = fetcher

    def _read(self, url, cancel_event):
        check_cancelled(cancel_event)
        result = (self._fetcher(url) if self._fetcher is not None
                  else fetch_bytes(url, cache_bust=False))
        check_cancelled(cancel_event)
        return result

    def _observe(self, exe_version, cancel_event):
        raw = self._read(ROOT + '/ResourcePath_PC.dat', cancel_event)
        path = parse_resource_path(raw, exe_version=exe_version)
        data_version = path['data_version']
        data = parse_version(self._read(package_url(data_version, 'DataPackage', 'version'), cancel_event))
        main = parse_version(self._read(package_url(data_version, 'MainPackage', 'version'), cancel_event))
        return (path['selected_exe_version'], data_version, data, main,
                hashlib.sha256(raw).hexdigest(), raw)

    def observe(self, exe_version, *, cancel_event=None):
        # 不取預設 ExeVer 或猜最大的 Package 版本；必須提供明確客戶端身分。
        if not isinstance(exe_version, str) or not re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,4}){2}', exe_version):
            raise VersionObservationError('official_exe_version_required')
        first = self._observe(exe_version, cancel_event)
        second = self._observe(exe_version, cancel_event)
        if first != second:
            raise VersionObservationError('official_versions_changed_during_observation')
        return OfficialVersions(exe_version, *first, ROOT,
                                datetime.now(UTC).isoformat(timespec='seconds'))
