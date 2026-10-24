"""Incrementally rebuild a PRIVATE, never-authorized 1275 raw-resource inventory.

Includes every supported DataPackage TextAsset and all separately PINNED
members already present in existing full formal archives. New raw members
come only from Manifest-derived, size+MD5+CRC-verified official Bundles.
Missing raw assets are retried on later Launcher runs within a per-run quota.

The output is NOT the release-pinned 1275_DataCatalog.zip / EveNpcIndex.zip.
It can never authorize login or overwrite an installed formal archive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from wlre.services.official_bundle_download import (
    _verified_file, fetch_bundle, spec_from_manifest,
)
from wlre.services.official_manifest_sync import VerifiedManifest
from wlre.services.world.catalog_adapters import MAX_SOURCE_BYTES, SourceContract
from wlre.services.world.official_catalog_pipeline import AssetBinding
from wlre.services.world.unity_textasset import extract_textasset
from wlre.storage.paths import data_root

SCHEMA = 1
MAX_ASSETS = 256
MAX_RESULT_BYTES = 128 * 1024 * 1024
MAX_EXISTING_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_PER_LAUNCH_DOWNLOADS = 4
MAX_PER_LAUNCH_BYTES = 16 * 1024 * 1024
_NAME = re.compile(r'[A-Za-z0-9_]+\.bytes\Z')
_PREFIX = 'Assets/ResourcesBuild/Data/'
_FILE = 'verified_raw_inventory.zip'


class ResourceRebuildError(ValueError):
    """Untrusted or incomplete resource source; never activate as formal data."""


def _roots(candidate_root=None, formal_base=None):
    candidate = (Path(candidate_root) if candidate_root is not None
                 else data_root() / 'official_sync' / 'derived_catalogs')
    formal = Path(formal_base) if formal_base is not None else data_root()
    return candidate, formal


def _checked_existing(formal_base):
    """Reuse ONLY members matching release-pinned manifests/fixed hashes.

    A partially corrupted ZIP may still contain its authentic, pinned
    manifest and individually intact entries. Never accept an invented local
    manifest or any unvalidated index.
    """
    from wlre.services.world.runtime_1275 import DATA_FILE, EVE_FILE, FOLDER
    from wlre.services.world.game_data_1275 import read_manifest
    from wlre.services.world.npc_1275_eve import FILES, verify_file
    candidates = (
        Path(formal_base) / FOLDER,
        Path(formal_base) / 'official_sync' / 'reviewed_full_1275',
    )
    trusted, reference = {}, None
    for root in candidates:
        data = root / DATA_FILE
        if data.is_file() and not data.is_symlink() and data.stat().st_size <= MAX_EXISTING_ARCHIVE_BYTES:
            try:
                with ZipFile(data) as archive:
                    if len(archive.infolist()) > 168:
                        continue
                    if len(set(archive.namelist())) != len(archive.infolist()):
                        continue
                    manifest = read_manifest(archive)
                    if reference is None:
                        reference = manifest
                    for name, expected in manifest['files'].items():
                        if name in trusted:
                            continue
                        try:
                            entry = archive.getinfo(name)
                            if entry.is_dir() or entry.file_size != expected['bytes']:
                                continue
                            body = archive.read(name)
                            if hashlib.sha256(body).hexdigest() != expected['sha256']:
                                continue
                            trusted[name] = body
                        except (BadZipFile, KeyError, OSError, ValueError, RuntimeError):
                            continue
            except (BadZipFile, KeyError, OSError, ValueError, RuntimeError):
                pass
        eve = root / EVE_FILE
        if eve.is_file() and not eve.is_symlink() and eve.stat().st_size <= MAX_EXISTING_ARCHIVE_BYTES:
            try:
                with ZipFile(eve) as archive:
                    names = archive.namelist()
                    if len(names) != len(set(names)) or len(names) > 3:
                        continue
                    for name in FILES:
                        if name in trusted:
                            continue
                        try:
                            raw = archive.read(name)
                            verify_file(name, raw)
                            trusted[name] = raw
                        except (BadZipFile, KeyError, OSError, ValueError, RuntimeError):
                            continue
            except (BadZipFile, OSError, ValueError, RuntimeError):
                pass
    return trusted, reference


def _manifest_assets(verified):
    if not isinstance(verified, VerifiedManifest):
        raise ResourceRebuildError('Verified official DataPackage Manifest required')
    index = verified.index
    if (index.get('header', {}).get('package_name') != 'DataPackage'
            or index['header'].get('package_version') != verified.spec.package_version):
        raise ResourceRebuildError('DataPackage Manifest identity mismatch')
    selected = {}
    for row in index.get('assets', []):
        path = row.get('path')
        if not isinstance(path, str) or not path.startswith(_PREFIX):
            continue
        filename = path[len(_PREFIX):]
        if not _NAME.fullmatch(filename):
            continue
        name = row.get('bundle_name')
        if not isinstance(name, str) or path in selected:
            raise ResourceRebuildError('Duplicate or invalid official asset binding')
        selected[path] = name
    if not 1 <= len(selected) <= MAX_ASSETS:
        raise ResourceRebuildError('Unexpected DataPackage raw asset count')
    return selected


def _load_previous(path, *, catalog_key):
    """Optional read-only acceleration, not independent SHA authorization."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_RESULT_BYTES:
        return {}
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if (len(names) != len(set(names)) or len(names) > MAX_ASSETS + 8
                    or 'inventory.json' not in names):
                return {}
            meta = json.loads(archive.read('inventory.json'))
            if (meta.get('schema_version') != SCHEMA
                    or meta.get('catalog_key') != catalog_key
                    or type(meta.get('entries')) is not dict):
                return {}
            found = {}
            for name, row in meta['entries'].items():
                if (name not in names or type(row) is not dict
                        or type(row.get('sha256')) is not str
                        or type(row.get('size')) is not int
                        or row['size'] > MAX_SOURCE_BYTES or row['size'] < 1):
                    continue
                body = archive.read(name)
                if len(body) == row['size'] and hashlib.sha256(body).hexdigest() == row['sha256']:
                    found[name] = (body, row)
            return found
    except (OSError, BadZipFile, KeyError, ValueError, TypeError, RuntimeError):
        return {}




def _exact_reviewed_manifest(formal_base):
    """Recover only the release-pinned manifest bytes from existing archives."""
    from wlre.services.world.runtime_1275 import DATA_FILE, FOLDER
    from wlre.services.world.game_data_1275 import read_manifest
    for root in (Path(formal_base) / FOLDER,
                 Path(formal_base) / 'official_sync' / 'reviewed_full_1275'):
        path = root / DATA_FILE
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_EXISTING_ARCHIVE_BYTES:
            continue
        try:
            with ZipFile(path) as z:
                read_manifest(z)  # Includes the release-pinned manifest SHA-256
                return z.read('manifest.json')
        except (OSError, ValueError, KeyError, BadZipFile, RuntimeError):
            pass
    return None


def _build_full_reviewed_if_pinned(identity, formal_base, payloads, pinned_files):
    """Assemble only when 163+2 original members match independent pinned SHA.

    This can complete a PARTIAL, formerly installed DataCatalog using verified
    Bundle data plus existing pinned indexes. No self-signed or unknown
    candidate is ever installed as official; activation remains a separate gate.
    """
    from wlre.services.world.runtime_1275 import DATA_FILE, EVE_FILE
    from wlre.services.world.game_data_1275 import verify_archive
    from wlre.services.world.npc_1275_eve import FILES, read_verified_zip
    if not pinned_files or not all(name in payloads for name in pinned_files):
        return 'awaiting_pinned_catalog_members'
    if not all(name in payloads for name in FILES):
        return 'awaiting_pinned_eve_indices'
    manifest_bytes = _exact_reviewed_manifest(formal_base)
    if manifest_bytes is None:
        return 'awaiting_release_pinned_manifest'
    root = Path(formal_base) / 'official_sync' / 'reviewed_full_1275'
    target_data, target_eve = root / DATA_FILE, root / EVE_FILE
    if target_data.exists() or target_eve.exists():
        # Never overwrite an existing formal reviewed ZIP, even if damaged.
        return 'reviewed_archives_already_present'
    root.mkdir(parents=True, exist_ok=True)
    pending, created = [], []
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.data_',
                                         suffix='.partial', delete=False) as handle:
            first = Path(handle.name)
            pending.append(first)
            with ZipFile(handle, 'w', ZIP_DEFLATED) as z:
                z.writestr('manifest.json', manifest_bytes)
                z.writestr('使用說明.txt', 'LaLa 本機逐檔校驗的 1275 資源。')
                for member in sorted(pinned_files):
                    z.writestr(member, payloads[member])
            handle.flush()
            os.fsync(handle.fileno())
        with tempfile.NamedTemporaryFile(dir=root, prefix='.eve_',
                                         suffix='.partial', delete=False) as handle:
            second = Path(handle.name)
            pending.append(second)
            with ZipFile(handle, 'w', ZIP_DEFLATED) as z:
                z.writestr('README.txt', 'LaLa 本機校驗的 1275 Eve 索引。')
                for member in sorted(FILES):
                    z.writestr(member, payloads[member])
            handle.flush()
            os.fsync(handle.fileno())
        # Verify full release-pinned manifest + ALL inner file SHA-256s,
        # and both static Eve compressed SHA-256s + contents, before linking.
        verify_archive(first)
        read_verified_zip(second)
        for staged, target in ((first, target_data), (second, target_eve)):
            os.link(staged, target)
            created.append(target)
    except FileExistsError:
        for path in created:
            path.unlink(missing_ok=True)
        return 'reviewed_archives_already_present'
    except (OSError, ValueError, KeyError, BadZipFile, RuntimeError):
        for path in created:
            path.unlink(missing_ok=True)
        return 'reviewed_archive_verification_failed'
    finally:
        for path in pending:
            path.unlink(missing_ok=True)
    return 'reviewed_archives_constructed'

def rebuild_raw_resources(identity, data_manifest, *,
                          bundle_root=None, candidate_root=None, formal_base=None,
                          fetcher=None, extractor=None, progress=None,
                          max_downloads=MAX_PER_LAUNCH_DOWNLOADS,
                          max_download_bytes=MAX_PER_LAUNCH_BYTES):
    """Incrementally rebuild both already-present and missing raw assets.

    A retained extracted asset must still have its source Bundle verified
    under THIS official revision. Truly pinned formal members can instead
    be reused after checking their independent release SHA-256.
    """
    from wlre.services.world.catalog_identity import OfficialCatalogIdentity
    if (not isinstance(identity, OfficialCatalogIdentity)
            or not isinstance(data_manifest, VerifiedManifest)
            or data_manifest.spec.package_version not in {
                p.full_version for p in identity.packages if p.name == 'DataPackage'}
            or not callable(getattr(identity, 'private_catalog_dir', None))):
        raise ResourceRebuildError('Rebuild identity not bound to verified official revision')
    if (type(max_downloads) is not int or not 0 <= max_downloads <= 32
            or type(max_download_bytes) is not int
            or not 0 <= max_download_bytes <= 64 * 1024 * 1024):
        raise ResourceRebuildError('Invalid per-launch download quota')
    if progress is not None and not callable(progress):
        raise ResourceRebuildError('Invalid progress callback')
    if fetcher is not None and not callable(fetcher):
        raise ResourceRebuildError('Invalid Bundle fetcher')
    if extractor is not None and not callable(extractor):
        raise ResourceRebuildError('Invalid text asset extractor')
    fetcher = fetch_bundle if fetcher is None else fetcher
    extractor = extract_textasset if extractor is None else extractor

    candidate_root, formal_base = _roots(candidate_root, formal_base)
    selected = _manifest_assets(data_manifest)
    specs = {}
    for name in sorted(set(selected.values())):
        specs[name] = spec_from_manifest(
            data_ver=identity.data_ver, package='DataPackage',
            index=data_manifest.index, name=name)
    staging = identity.private_catalog_dir(candidate_root)
    dest = staging / _FILE
    # Release-pinned 1275 files must NEVER be mixed into another official
    # revision even if some filename happens to match.
    from wlre.services.resource_compatibility import load_supported_resources
    supported = load_supported_resources()
    identical_release = all(
        supported['packages'].get(p.name, {}).get('manifest') == p.full_version
        for p in identity.packages)
    trusted, pinned = (_checked_existing(formal_base)
                       if identical_release else ({}, None))
    previous = _load_previous(dest, catalog_key=identity.key)
    pinned_files = pinned.get('files', {}) if pinned is not None else {}

    # All selected raw assets, including previously verified ones, are
    # reflected in the output. The incomplete inventory stays private.
    payloads, entries = {}, {}
    missing, reused, extracted, downloaded = [], 0, 0, 0
    spent = 0
    attempted = set()
    total_bytes = 0
    for asset_path, name in sorted(selected.items()):
        filename = PurePosixPath(asset_path).name
        member = f'tables/{name}/{filename}'
        # The reviewed, independently pinned SHA is stronger than an
        # existing candidate's own SHA. Reuse it without re-downloading.
        if member in trusted:
            body = trusted[member]
            source = 'existing_pinned'
            reused += 1
        else:
            spec = specs[name]
            path = spec.cache_path(bundle_root)
            if not _verified_file(path, spec):
                if (name not in attempted and
                        downloaded < max_downloads and
                        spent + spec.file_size <= max_download_bytes):
                    attempted.add(name)
                    try:
                        fetcher(spec, cache_root=bundle_root)
                        if _verified_file(path, spec):
                            downloaded += 1
                            spent += spec.file_size
                    except (OSError, ValueError, RuntimeError):
                        pass
            if not _verified_file(path, spec):
                missing.append(asset_path)
                continue
            prior = previous.get(member)
            if (prior is not None and
                    prior[1].get('bundle_md5') == spec.file_hash.lower()):
                # Only a self-consistent candidate copy; official Bundle
                # is independently reverified above before reuse.
                body, _ = prior
                source = 'cached_candidate'
                reused += 1
            else:
                binding = AssetBinding(asset_path, SourceContract(
                    'scenes', filename.removesuffix('.bytes'), 'stage-new-76-v1',
                    '0' * 64, 'DataPackage', data_manifest.spec.package_version))
                try:
                    body = extractor(binding, (path,))
                    if type(body) is not bytes or not 0 < len(body) <= MAX_SOURCE_BYTES:
                        raise ResourceRebuildError('Invalid TextAsset payload')
                except (OSError, ValueError, RuntimeError):
                    missing.append(asset_path)
                    continue
                source = 'verified_bundle'
                extracted += 1
        if member in pinned_files:
            spec = pinned_files[member]
            if (len(body) != spec['bytes']
                    or hashlib.sha256(body).hexdigest() != spec['sha256']):
                missing.append(asset_path)
                continue
        total_bytes += len(body)
        if total_bytes > MAX_RESULT_BYTES:
            raise ResourceRebuildError('Rebuilt raw resources exceed byte quota')
        payloads[member] = body
        entries[member] = {
            'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'source': source, 'bundle_md5': specs[name].file_hash.lower(),
        }
        if progress is not None:
            progress('raw_resource_item', {
                'completed': len(entries), 'total': len(selected),
                'source': source,
            })
    # Include all independently pinned, previously present indexes, even if
    # some raw tables still cannot be extracted. Never infer these from 1262.
    for member, body in sorted(trusted.items()):
        if member in entries or not (
                member.startswith('indexes/') or member in (
                    'npc_event_index_1275.json.gz', 'npc_interact_1275.json.gz')):
            continue
        total_bytes += len(body)
        if total_bytes > MAX_RESULT_BYTES:
            raise ResourceRebuildError('Indexed resources exceed byte quota')
        payloads[member] = body
        entries[member] = {
            'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'source': 'existing_pinned', 'bundle_md5': None,
        }
        reused += 1

    missing_formal = (
        sorted(set(pinned_files) - set(entries)) if pinned_files else
        ['尚無固定 SHA 的完整 1275 DataCatalog manifest；不能正式封裝']
    )
    if identical_release:
        for member in ('npc_event_index_1275.json.gz', 'npc_interact_1275.json.gz'):
            if member not in entries:
                missing_formal.append(member)
    formal_construction = (
        _build_full_reviewed_if_pinned(identity, formal_base, payloads, pinned_files)
        if identical_release else 'not_release_pinned')
    report = {
        'schema_version': SCHEMA, 'catalog_key': identity.key,
        'official_manifest_sha256': next(
            p.manifest_sha256 for p in identity.packages if p.name == 'DataPackage'),
        'asset_total': len(selected), 'asset_collected': len(selected) - len(missing),
        'existing_or_cached_reused': reused, 'newly_extracted': extracted,
        'new_bundle_downloads': downloaded, 'missing_asset_paths': missing,
        'missing_formal_members': sorted(set(missing_formal)),
        'formal_construction': formal_construction,
        'entries': entries, 'complete_raw_assets': not missing,
        'formal_approved': False, 'assets_ready': False,
        'can_send_packets': False, 'protocol_compatibility': 'unverified',
    }
    staging.mkdir(parents=True, exist_ok=True)
    pending = None
    lock = staging / '.rebuild.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise ResourceRebuildError('Raw resource rebuild is already in progress')
    try:
        with tempfile.NamedTemporaryFile(
                dir=staging, prefix='.raw_rebuild_', suffix='.partial',
                delete=False) as fd:
            pending = Path(fd.name)
            with ZipFile(fd, 'w', compression=ZIP_DEFLATED) as archive:
                for member, body in sorted(payloads.items()):
                    archive.writestr(member, body)
                archive.writestr(
                    'inventory.json', json.dumps(
                        report, sort_keys=True, ensure_ascii=True,
                        separators=(',', ':')).encode('utf-8'))
            fd.flush()
            os.fsync(fd.fileno())
        if len(_load_previous(pending, catalog_key=identity.key)) != len(entries):
            raise ResourceRebuildError('Staged raw archive failed readback')
        os.replace(pending, dest)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
    return {key: report[key] for key in (
        'asset_total', 'asset_collected', 'existing_or_cached_reused',
        'newly_extracted', 'new_bundle_downloads', 'missing_asset_paths',
        'missing_formal_members', 'formal_construction',
        'complete_raw_assets', 'formal_approved',
        'assets_ready', 'can_send_packets', 'protocol_compatibility')}
