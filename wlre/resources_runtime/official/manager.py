"""明確範圍的官方資料更新協調；不啟用登入、傳送或其他遊戲指令。"""
import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from types import MappingProxyType

from wlre.core.primitives import check_cancelled, identifier
from wlre.resources_runtime.downloader import DownloadManager, FileIntegrity
from wlre.resources_runtime.official.adapters import adapter_for
from wlre.resources_runtime.official.compatibility import CompatibilityValidator
from wlre.resources_runtime.official.contracts import (
    ResourceStatus,
    validated_requirements,
)
from wlre.resources_runtime.official.gaps import ResourceGapAnalyzer
from wlre.resources_runtime.official.references import (
    audit_scene_references,
    reference_summary,
)
from wlre.resources_runtime.official.snapshots import SnapshotStore
from wlre.resources_runtime.official.source import ROOT
from wlre.resources_runtime.official.versions import VersionDetector
from wlre.resources_runtime.parsers.scenes import SceneTable
from wlre.resources_runtime.parsers.texts import TextTable
from wlre.resources_runtime.parsers.unity_textasset import (
    UnityTextAssetError,
    extract_exact_textasset,
)
from wlre.services.official_manifest_sync import (
    ManifestSpec,
    fetch_official_manifest,
    validate_manifest_bytes,
)


class ResourceRefreshError(ValueError):
    def __init__(self, code, *, findings=()):
        super().__init__(code)
        self.findings = findings


@dataclass(frozen=True)
class OfficialDataService:
    """整份快照的唯讀查詢；舊 view 在重新檢查或關閉時立即失效。"""
    snapshot_id: str
    scope: str
    versions: object
    validated_at: str
    _indexes: object = field(repr=False)
    _revoked: Event = field(repr=False, compare=False)
    _references: tuple = field(default=(), repr=False)

    def _check(self):
        if self._revoked.is_set():
            raise ResourceRefreshError('official_data_view_revoked')

    def records(self, index):
        self._check()
        return self._indexes[index]

    def get(self, index, record_id):
        if type(record_id) is not int:
            raise ValueError('integer_official_record_id_required')
        return next((row for row in self.records(index) if row['id'] == record_id), None)

    def scene_reference(self, scene_id):
        self._check()
        if type(scene_id) is not int:
            raise ValueError('integer_scene_id_required')
        return next((row for row in self._references if row.scene_id == scene_id), None)

    def reference_summary(self):
        self._check()
        return reference_summary(self._references)

    @property
    def protocol_approved(self):
        # 靜態資料解析成功永遠不等於遊戲封包相容性核准。
        return False


class OfficialResourceManager:
    """順序下載明確需求；一批全部通過後才提交，沒有自動離線退回。"""

    def __init__(self, cache_root, *, opener=None):
        self._root = Path(cache_root).resolve()
        self._store = SnapshotStore(self._root / 'snapshots')
        self._transport = DownloadManager(opener=opener)
        self._opener = opener
        self._closed = Event()
        self._refresh_lock = Lock()
        self._publication_lock = Lock()
        self._lease = Event()

    def __enter__(self):
        check_cancelled(self._closed)
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        with self._publication_lock:
            self._closed.set()
            self._lease.set()
            self._transport.close()

    def revoke_views(self):
        """停止或重新排程時立即撤銷查詢；不永久關閉傳輸。"""
        with self._publication_lock:
            self._lease.set()

    def diagnose(self, scope):
        return self._store.diagnose(scope)

    def refresh(self, exe_version, *, scope, requirements, cancel_event=None, progress=None):
        identifier(scope)
        validated_requirements(requirements)
        if not self._refresh_lock.acquire(blocking=False):
            raise ResourceRefreshError('official_refresh_already_running')
        try:
            self._lease.set()
            cancellation = _Cancellation(self._closed, cancel_event)
            check_cancelled(cancellation)
            previous = self._store.current_id(scope)
            return self._refresh(exe_version, scope, requirements, previous,
                                 cancellation, progress)
        except (InterruptedError, ResourceRefreshError):
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            # 外部資料／I/O 的原始例外不可把憑證或回應文字帶入 UI／Log。
            raise ResourceRefreshError('official_resource_refresh_failed') from None
        finally:
            self._refresh_lock.release()

    def _refresh(self, exe_version, scope, requirements, previous, cancellation, progress):
        detector = VersionDetector(fetcher=lambda url: self._transport.read(
            url, limit=256 * 1024, cancel_event=cancellation))
        versions = detector.observe(exe_version, cancel_event=cancellation)
        manifests = {}
        for package, version in (('DataPackage', versions.data_package_version),
                                 ('MainPackage', versions.main_package_version)):
            check_cancelled(cancellation)
            spec = ManifestSpec(versions.data_version, package, version)
            manifests[package] = fetch_official_manifest(
                spec, cache_root=self._root / 'manifests', opener=self._opener,
                timeout=5, cancel_event=cancellation)
        gap_report = ResourceGapAnalyzer().analyze(
            requirements, manifests, bundle_cache=self._root / 'bundles')
        if not gap_report.complete:
            raise ResourceRefreshError('official_resource_gaps', findings=gap_report.findings)
        entries = {(row.spec.package, row.spec.name): row
                   for plan in gap_report.plans for row in plan.entries}
        paths, bundle_receipts = {}, []
        for key, row in entries.items():
            check_cancelled(cancellation)
            spec = row.spec
            path = self._transport.download(
                spec.url, FileIntegrity(spec.file_size, spec.file_hash, spec.file_crc),
                spec.cache_path(self._root / 'bundles'), cancel_event=cancellation,
                progress=progress)
            paths[key] = path
            bundle_receipts.append({**asdict(spec), 'source_url': spec.url,
                                    'integrity': 'size_md5_crc32_verified'})
        indexes, source_receipts, findings, tables = {}, [], [], []
        for requirement, plan in zip(requirements, gap_report.plans, strict=True):
            check_cancelled(cancellation)
            selected = tuple(paths[(row.spec.package, row.spec.name)] for row in plan.entries)
            for row, path in zip(plan.entries, selected, strict=True):
                spec = row.spec
                if not self._transport.verify_file(
                        path, FileIntegrity(spec.file_size, spec.file_hash, spec.file_crc),
                        cancel_event=cancellation):
                    raise ResourceRefreshError('official_bundle_cache_changed', findings=(
                        requirement.finding(ResourceStatus.INVALID, 'bundle_integrity_failed',
                                             field='size_md5_crc32'),))
            # 每個需求只讀自己的完整相依閉包，避免其他資產的同名 container 污染。
            try:
                raw = extract_exact_textasset(requirement.asset_path, selected)
            except UnityTextAssetError:
                raise ResourceRefreshError('official_resource_extract_failed', findings=(
                    requirement.finding(ResourceStatus.INVALID, 'unity_textasset_invalid',
                                         field='container_asset_path_or_payload'),)) from None
            check_cancelled(cancellation)
            result = CompatibilityValidator().validate(requirement, raw)
            findings.append(result.finding)
            if result.table is None:
                raise ResourceRefreshError('official_resource_incompatible', findings=tuple(findings))
            source_sha = self._store.put(raw)
            indexes[requirement.index] = result.table.records
            tables.append(result.table)
            source_receipts.append({
                **asdict(requirement), 'sha256': source_sha, 'size': len(raw),
                **adapter_for(requirement).receipt(result.table),
            })
        scene_table = next((table for table in tables if isinstance(table, SceneTable)), None)
        text_table = next((table for table in tables if isinstance(table, TextTable)), None)
        references = (() if scene_table is None else
                      audit_scene_references(scene_table, text_table, manifests['MainPackage']))
        # 驗證與下載可能跨過官方更新；版本映射及兩套 hash 全部再核對。
        after = detector.observe(exe_version, cancel_event=cancellation)
        if _version_identity(after) != _version_identity(versions):
            raise ResourceRefreshError('official_versions_changed_during_refresh')
        manifest_receipts = []
        for package, manifest in manifests.items():
            current_hash = self._transport.read(manifest.spec.url('hash'), limit=8,
                                                cancel_event=cancellation)
            if current_hash.lower() != manifest.hash_text.encode('ascii'):
                raise ResourceRefreshError('official_manifest_changed_during_refresh')
            # 保留被完整解析的原始 Manifest，快照不引用會被下一次更新覆寫的路徑。
            with manifest.cache_path.open('rb') as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
            # 快取可能被另一程序覆寫；重新核對完整性與身分。
            if validate_manifest_bytes(raw, manifest.spec, expected_crc32_le=manifest.hash_text) != manifest.index:
                raise ResourceRefreshError('official_manifest_cache_changed')
            manifest_receipts.append({
                **asdict(manifest.spec), 'manifest_name': package + '.bytes',
                'source_url': manifest.spec.url('bytes'), 'size': len(raw),
                'sha256': self._store.put(raw), 'crc32_le': manifest.hash_text,
                'parser_id': 'yooasset-2.2.5', 'parser_version': 1,
                'integrity': 'crc32_verified_https_source',
            })
        checked_at = datetime.now(UTC).isoformat(timespec='seconds')
        document = {
            'schema_version': 1, 'scope': scope, 'source_url': ROOT,
            'observed_at': versions.observed_at, 'download_completed_at': checked_at,
            'validated_at': checked_at, 'lala_version': versions.lala_version,
            'requested_exe_version': versions.requested_exe_version,
            'observed_exe_version': versions.observed_exe_version,
            'data_version': versions.data_version,
            'data_package_version': versions.data_package_version,
            'main_package_version': versions.main_package_version,
            'resource_map_sha256': hashlib.sha256(versions.resource_map_raw).hexdigest(),
            'resource_map_blob': self._store.put(versions.resource_map_raw),
            'manifests': manifest_receipts, 'bundles': bundle_receipts, 'sources': source_receipts,
            'references': reference_summary(references),
            'acceptance': 'validated_requested_scope', 'protocol_approved': False,
            'previous_snapshot': previous,
        }
        with self._publication_lock:
            check_cancelled(cancellation)
            snapshot_id = self._store.commit(scope, document, expected_current=previous)
            self._lease = Event()
            return OfficialDataService(snapshot_id, scope, versions, checked_at,
                                       MappingProxyType(indexes), self._lease, references)


def _version_identity(versions):
    return (versions.requested_exe_version, versions.observed_exe_version,
            versions.data_version, versions.data_package_version,
            versions.main_package_version, versions.resource_map_sha256)


class _Cancellation:
    def __init__(self, closed, requested):
        self.closed, self.requested = closed, requested

    def is_set(self):
        return self.closed.is_set() or (self.requested is not None and self.requested.is_set())

    def wait(self, timeout):
        # 下載器的退避有界；關閉可立即喚醒，外部取消最遲於退避結束再檢查。
        self.closed.wait(timeout)
        return self.is_set()
