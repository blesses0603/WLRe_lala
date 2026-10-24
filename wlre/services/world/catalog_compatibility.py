"""Read-only, version-bound, four-feature compatibility assessment.

Data Schema passing does NOT imply protocol compatibility, login readiness,
packet authorization, or approved game resources. Never used by the login gate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from wlre.services.world.catalog_adapters import (
    CatalogAdapterError, FEATURES, MAX_ROWS, MAX_SOURCE_BYTES,
    SourceContract, parse_feature,
)

REPORT_SCHEMA = 1
MAX_REPORT_BYTES = 8192
EXPECTED_SCHEMAS = {
    'npc': ('eve-npc-json-v1', 'EventData.NewNpc'),
    'shops': ('eve-interact-json-v1', 'EventData.NewInteract'),
    'crafting': ('smith-new-33-v1', 'SmithData_C'),
    'scenes': ('stage-new-76-v1', 'ScenesData_C'),
}
_HEX = set('0123456789abcdef')


class CompatibilityError(ValueError):
    """Candidate identity, feature schema or source digest failed validation."""


def _digest(value):
    return (type(value) is str and len(value) == 64
            and all(char in _HEX for char in value))


def _expected(identity, sources):
    if (not _digest(getattr(identity, 'key', None))
            or not callable(getattr(identity, 'as_dict', None))
            or not isinstance(sources, tuple) or len(sources) != len(FEATURES)):
        raise CompatibilityError('Invalid Catalog identity or feature set')
    official = identity.as_dict()
    packages = official.get('packages', []) if type(official) is dict else []
    if (type(packages) is not list or len(packages) != 2
            or any(type(p) is not dict for p in packages)
            or {p.get('name') for p in packages} != {'MainPackage', 'DataPackage'}):
        raise CompatibilityError('Missing independently identified official Packages')
    versions = {p['name']: p['full_version'] for p in packages}
    bindings = {}
    for resolved in sources:
        binding = getattr(resolved, 'binding', None)
        contract = getattr(binding, 'contract', None)
        if contract is None:
            raise CompatibilityError('Missing reviewed feature source contract')
        feature = contract.feature
        if (feature not in EXPECTED_SCHEMAS or feature in bindings
                or (contract.schema_id, contract.source_name) != EXPECTED_SCHEMAS[feature]
                or contract.package != 'DataPackage'
                or contract.package_version != versions['DataPackage']):
            raise CompatibilityError('Unexpected feature/source/schema binding')
        bindings[feature] = binding
    if set(bindings) != set(FEATURES):
        raise CompatibilityError('Missing required feature binding')
    return official, versions, bindings


def assess_candidate(identity, sources, *, raw_by_feature, metadata):
    """Independently decode all four sources and compare exact reviewed bindings.

    The caller must verify official Manifest and Bundle integrity first.
    A newly computed SHA proves internal consistency, not server protocol
    compatibility or independent release approval.
    """
    official, versions, bindings = _expected(identity, sources)
    if (type(metadata) is not dict or
            metadata.get('catalog_key') != identity.key or
            metadata.get('official_identity') != official or
            metadata.get('status') != 'review_required' or
            metadata.get('approved') is not False or
            metadata.get('assets_ready') is not False or
            metadata.get('can_send_packets') is not False or
            type(metadata.get('features')) is not dict or
            set(metadata['features']) != set(FEATURES) or
            type(raw_by_feature) is not dict or
            set(raw_by_feature) != set(FEATURES)):
        raise CompatibilityError('Candidate identity or source set does not match official revision')
    results = {}
    for feature in FEATURES:
        binding = bindings[feature]
        desc = metadata['features'][feature]
        raw = raw_by_feature[feature]
        expected = binding.contract
        if (type(desc) is not dict or type(raw) is not bytes
                or not 0 < len(raw) <= MAX_SOURCE_BYTES
                or desc.get('bytes') != len(raw)
                or type(desc.get('record_count')) is not int
                or not 0 <= desc['record_count'] <= MAX_ROWS
                or desc.get('package') != expected.package
                or desc.get('package_version') != expected.package_version
                or desc.get('schema_id') != expected.schema_id
                or desc.get('source_name') != expected.source_name
                or desc.get('asset_path') != binding.asset_path
                or desc.get('related_asset_paths') != list(binding.related_asset_paths)
                or not _digest(desc.get('sha256'))
                or desc['sha256'] != hashlib.sha256(raw).hexdigest()):
            raise CompatibilityError(f'{feature} candidate metadata mismatch')
        contract = SourceContract(
            feature, expected.source_name, expected.schema_id, desc['sha256'],
            expected.package, expected.package_version)
        try:
            parsed = parse_feature(
                catalog_key=identity.key, package_versions=versions,
                contract=contract, raw=raw)
        except (CatalogAdapterError, ValueError, TypeError) as exc:
            raise CompatibilityError(f'{feature} source schema incompatible') from exc
        if parsed.record_count != desc['record_count']:
            raise CompatibilityError(f'{feature} candidate record count mismatch')
        results[feature] = {
            'status': 'compatible', 'schema_id': contract.schema_id,
            'record_count': parsed.record_count, 'source_sha256': desc['sha256'],
        }
    return {
        'schema_version': REPORT_SCHEMA,
        'catalog_key': identity.key, 'official_identity': official,
        'data_compatibility': 'compatible',
        'protocol_compatibility': 'unverified',
        'requires_protocol_review': True,
        'features': results,
        'approved': False, 'assets_ready': False, 'can_send_packets': False,
    }


def _report_path(identity, candidate_root=None):
    return identity.private_catalog_dir(candidate_root) / 'compatibility_report.json'


def write_compatibility_report(identity, report, *, candidate_root=None):
    """Save display-only report atomically after verified candidate creation."""
    if (type(report) is not dict
            or report.get('catalog_key') != identity.key
            or report.get('data_compatibility') != 'compatible'
            or report.get('protocol_compatibility') != 'unverified'
            or report.get('approved') is not False
            or report.get('assets_ready') is not False
            or report.get('can_send_packets') is not False):
        raise CompatibilityError('Cannot publish an unsafe compatibility result')
    target = _report_path(identity, candidate_root)
    payload = (json.dumps(report, ensure_ascii=True, sort_keys=True,
                          separators=(',', ':')) + '\n').encode('utf-8')
    if not 0 < len(payload) <= MAX_REPORT_BYTES:
        raise CompatibilityError('Compatibility report exceeds limit')
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix='.compat_', suffix='.partial',
                delete=False) as fd:
            pending = Path(fd.name)
            fd.write(payload)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(pending, target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return target


def read_compatibility_report(identity, *, candidate_root=None):
    """Read display-only report. Never treat it as a gameplay authorization."""
    try:
        path = _report_path(identity, candidate_root)
        with path.open('rb') as fd:
            raw = fd.read(MAX_REPORT_BYTES + 1)
        if not 0 < len(raw) <= MAX_REPORT_BYTES:
            return None
        report = json.loads(raw)
        if (type(report) is not dict
                or set(report) != {
                    'schema_version', 'catalog_key', 'official_identity',
                    'data_compatibility', 'protocol_compatibility',
                    'requires_protocol_review', 'features', 'approved',
                    'assets_ready', 'can_send_packets'}
                or report['schema_version'] != REPORT_SCHEMA
                or report['catalog_key'] != identity.key
                or report['official_identity'] != identity.as_dict()
                or report['data_compatibility'] != 'compatible'
                or report['protocol_compatibility'] != 'unverified'
                or report['requires_protocol_review'] is not True
                or report['approved'] is not False
                or report['assets_ready'] is not False
                or report['can_send_packets'] is not False
                or type(report['features']) is not dict
                or set(report['features']) != set(FEATURES)):
            return None
        for feature, desc in report['features'].items():
            if (type(desc) is not dict or
                    set(desc) != {'status', 'schema_id', 'record_count', 'source_sha256'}
                    or desc['status'] != 'compatible'
                    or desc['schema_id'] != EXPECTED_SCHEMAS[feature][0]
                    or type(desc['record_count']) is not int
                    or not 0 <= desc['record_count'] <= MAX_ROWS
                    or not _digest(desc['source_sha256'])):
                return None
        return report
    except (OSError, ValueError, TypeError, KeyError):
        return None
