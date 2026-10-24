"""Bridge four versioned candidate sources to the release-pinned 1275 runtime.

This does not install files, authorize packets or replace active_runtime.
Only the separately pinned official_resources_1275 archives can supply the
complete runtime (talks, texts, item catalog, doors and all game tables).
"""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from wlre.services.resource_compatibility import load_supported_resources
from wlre.services.world.auto_catalog import _ASSET_ROOT, _SOURCE_MAP, _trusted_cached_candidate
from wlre.services.world.catalog_adapters import FEATURES
from wlre.services.world.catalog_compatibility import (
    CompatibilityError, assess_candidate, read_compatibility_report,
)
from wlre.services.world.catalog_identity import OfficialCatalogIdentity, PackageRevision
from wlre.services.world.official_catalog_pipeline import AssetBinding, ResolvedAsset
from wlre.services.world.catalog_adapters import SourceContract
from wlre.storage.paths import data_root


class FormalBridgeError(ValueError):
    """Candidate differs from the independently release-pinned full runtime."""


def _identity_from_metadata(metadata):
    doc = metadata.get('official_identity')
    if (type(doc) is not dict or doc.get('schema_version') != 1
            or type(doc.get('packages')) is not list
            or len(doc['packages']) != 2
            or any(type(x) is not dict for x in doc['packages'])):
        raise FormalBridgeError('Candidate official identity is invalid')
    try:
        packages = tuple(PackageRevision(**p) for p in doc['packages'])
        identity = OfficialCatalogIdentity(doc['data_ver'], doc['exe_version'],
                                           packages)
    except (TypeError, KeyError, ValueError) as exc:
        raise FormalBridgeError('Candidate official revision is incomplete') from exc
    if identity.key != metadata.get('catalog_key') or identity.as_dict() != doc:
        raise FormalBridgeError('Candidate official digest identity mismatch')
    baseline = load_supported_resources()
    for pkg in identity.packages:
        source = baseline['packages'].get(pkg.name)
        if (source is None or source['revision'] != '1275'
                or pkg.full_version != source['manifest']):
            raise FormalBridgeError('Candidate is not the release-reviewed 1275 revision')
    if len({p.name for p in identity.packages}) != 2:
        raise FormalBridgeError('Candidate package names are not unique')
    return identity


def _binding_sources(identity):
    rev = next(p.full_version for p in identity.packages if p.name == 'DataPackage')
    return tuple(ResolvedAsset(
        AssetBinding(
            _ASSET_ROOT + _SOURCE_MAP[feature][0],
            SourceContract(feature, _SOURCE_MAP[feature][1],
                           _SOURCE_MAP[feature][2], '0' * 64,
                           'DataPackage', rev),
            tuple(_ASSET_ROOT + p for p in _SOURCE_MAP[feature][3])),
        'release-pinned-only')
        for feature in FEATURES)


def _canonical_npc(doc):
    if not isinstance(doc, dict) or type(doc.get('scenes')) is not dict:
        raise FormalBridgeError('Invalid candidate NPC scenes')
    return {str(k): rows for k, rows in doc['scenes'].items() if rows}


def _canonical_interacts(doc):
    if not isinstance(doc, dict) or type(doc.get('scenes')) is not dict:
        raise FormalBridgeError('Invalid candidate interact scenes')
    fields = ('index', 'form_kind', 'link_number')
    item_fields = ('id', 'text_id', 'database_kind', 'kind')
    result = {}
    for scene, rows in doc['scenes'].items():
        if not rows:
            continue
        # Derived shop ItemData previews are additional readonly information,
        # not fields in the canonical Eve interaction index.
        result[int(scene)] = {
            row['index']: {
                **{name: row[name] for name in fields},
                'items': [
                    {name: item[name] for name in item_fields}
                    for item in row['items']]
            } for row in rows
        }
    return result


def inspect_formal_bridge(runtime, *, root=None, candidate_key=None):
    """Cross-check candidate and pinned full runtime before safe hand-off.

    Called only AFTER runtime_1275.active_runtime has independently validated
    both official 1275 ZIPs. Candidate absence preserves legacy behavior;
    recognized but damaged/mismatching candidates fail closed.
    """
    if candidate_key is None:
        return {'status': 'not_requested', 'protocol_compatibility': 'unverified'}
    if (type(candidate_key) is not str or len(candidate_key) != 64
            or any(c not in '0123456789abcdef' for c in candidate_key)):
        raise FormalBridgeError('Invalid Launcher candidate key')
    candidate_root = (Path(root) if root is not None else
                      data_root() / 'official_sync' / 'derived_catalogs')
    path = candidate_root / candidate_key / 'candidate.zip'
    meta = _trusted_cached_candidate(path, candidate_key)
    if meta is None:
        raise FormalBridgeError('Candidate ZIP is missing or damaged')
    identity = _identity_from_metadata(meta)
    receipt = read_compatibility_report(identity, candidate_root=candidate_root)
    if receipt is None:
        raise FormalBridgeError('Compatibility report missing, stale or tampered')
    with ZipFile(path) as z:
        raws = {feature: z.read(feature + '.source') for feature in FEATURES}
    sources = _binding_sources(identity)
    try:
        result = assess_candidate(
            identity, sources, raw_by_feature=raws, metadata=meta)
    except CompatibilityError as exc:
        raise FormalBridgeError('Candidate is not schema compatible') from exc
    if receipt['features'] != result['features']:
        raise FormalBridgeError('Candidate report differs from freshly parsed sources')
    if getattr(runtime, 'revision', None) != 1275:
        raise FormalBridgeError('Complete formally pinned 1275 runtime required')

    npc = json.loads(raws['npc'].decode('utf-8'))
    shops = json.loads(raws['shops'].decode('utf-8'))
    if _canonical_npc(npc) != {
            str(k): rows for k, rows in runtime.npc_index.scenes.items() if rows}:
        raise FormalBridgeError('NPC candidate differs from pinned formal Eve source')
    if _canonical_interacts(shops) != {
            int(k): rows for k, rows in runtime.interact_index.scenes.items() if rows}:
        raise FormalBridgeError('Shop interaction candidate differs from pinned formal Eve')
    from wlre.services.world.preview_1275 import parse_smith_1275
    from wlre.services.instance_catalog import parse_stages
    if parse_smith_1275(raws['crafting']) != runtime.recipes:
        raise FormalBridgeError('Crafting candidate differs from pinned formal recipes')
    if frozenset(parse_stages(raws['scenes'])) != runtime.scene_ids:
        raise FormalBridgeError('Scene candidate differs from pinned formal scene table')
    return {
        'status': 'matches_formal_sources', 'candidate_key': identity.key,
        'data_compatibility': 'compatible',
        'protocol_compatibility': 'unverified',
        'approved': False, 'assets_ready': False, 'can_send_packets': False,
        'checked_features': list(FEATURES),
    }


def inspect_launcher_candidate(runtime, *, root=None):
    """Use only the current Launcher receipt; no user-edited key is trusted."""
    from wlre.services.world.launcher_catalog import read_launcher_status
    receipt = read_launcher_status(root=root)
    if (receipt is None or receipt.get('status') != 'review_required'
            or receipt.get('data_compatibility') != 'compatible'):
        return {'status': 'not_requested', 'protocol_compatibility': 'unverified'}
    return inspect_formal_bridge(runtime, candidate_key=receipt['catalog_key'])


def promote_reviewed_archives(candidate_key, *, candidate_root=None,
                              reviewed_root=None, install_root=None,
                              check_only=False):
    """Safe Launcher handoff when COMPLETE pinned ZIPs were supplied locally.

    Four derived candidate sources alone never satisfy this requirement.
    A pair of independently pinned original ZIPs must exist in the private
    reviewed_full_1275 input directory (never download generated candidates
    to that directory). No existing formal source may be overwritten.
    """
    from wlre.services.world import runtime_1275
    from wlre.services.world.preview_1275 import load_preview
    root = (Path(reviewed_root) if reviewed_root is not None else
            data_root() / 'official_sync' / 'reviewed_full_1275')
    data_path, eve_path = root / runtime_1275.DATA_FILE, root / runtime_1275.EVE_FILE
    target_data, target_eve = runtime_1275._paths(install_root)
    installed = (target_data.exists(), target_eve.exists())
    if all(installed):
        formal = load_preview(target_data, target_eve)
        inspect_formal_bridge(
            formal, candidate_key=candidate_key, root=candidate_root)
        return {'status': 'already_verified', 'installed': True,
                'protocol_compatibility': 'unverified'}
    if any(installed):
        raise FormalBridgeError('Partial formal 1275 installation requires manual review')
    if not data_path.is_file() or not eve_path.is_file():
        return {'status': 'awaiting_complete_reviewed_archives',
                'installed': False, 'protocol_compatibility': 'unverified'}
    # The formal reader validates ALL 163 pinned tables/indexes and BOTH
    # independently reviewed Eve index sources before any filesystem writes.
    formal = load_preview(data_path, eve_path)
    inspect_formal_bridge(formal, candidate_key=candidate_key, root=candidate_root)
    if check_only:
        return {'status': 'ready_for_install', 'installed': False,
                'protocol_compatibility': 'unverified'}
    # Pre-existing source files cannot be replaced. runtime_1275.install
    # commits the two pinned ZIPs with rollback on partial copy/link failure.
    runtime_1275.install(data_path, eve_path, base=install_root, check_only=False)
    installed_formal = load_preview(target_data, target_eve)
    inspect_formal_bridge(
        installed_formal, candidate_key=candidate_key, root=candidate_root)
    return {'status': 'installed_and_verified', 'installed': True,
            'protocol_compatibility': 'unverified'}
