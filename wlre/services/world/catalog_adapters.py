"""Version-agnostic, offline and read-only source-format adapters.

This layer consumes *already extracted* and independently verified table/index
bytes. It DOES NOT extract UnityFS bundles, download content, activate runtime
catalogs, or authorize any game-network command. Callers must supply a
release-reviewed exact SHA-256 and schema for each source at every revision.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import struct
from typing import Mapping

FEATURES = ('npc', 'shops', 'crafting', 'scenes')
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 20000
_HEX64 = re.compile(r'[a-f0-9]{64}\Z')
_SCHEMAS = {
    'npc': ('eve-npc-json-v1',),
    'shops': ('eve-interact-json-v1',),
    'crafting': ('smith-new-33-v1',),
    'scenes': ('stage-new-76-v1',),
}


class CatalogAdapterError(ValueError):
    """Source, provenance or explicitly selected format is unsupported."""


@dataclass(frozen=True)
class SourceContract:
    feature: str
    source_name: str
    schema_id: str
    expected_sha256: str
    package: str
    package_version: str

    def __post_init__(self):
        if (self.feature not in FEATURES or self.schema_id not in _SCHEMAS[self.feature]
                or not isinstance(self.source_name, str) or not self.source_name
                or len(self.source_name) > 120 or '/' in self.source_name
                or '\\' in self.source_name or self.source_name in ('.', '..')
                or not isinstance(self.expected_sha256, str)
                or not _HEX64.fullmatch(self.expected_sha256)
                or self.package not in ('DataPackage', 'MainPackage')
                or not isinstance(self.package_version, str) or not self.package_version
                or len(self.package_version) > 100):
            raise CatalogAdapterError('Unknown feature/schema or invalid reviewed source contract')


@dataclass(frozen=True)
class ParsedCatalog:
    catalog_key: str
    feature: str
    source_name: str
    schema_id: str
    source_sha256: str
    record_count: int
    records: object
    can_send_packets: bool = False
    assets_ready: bool = False


def _json_scenes(raw: bytes, *, source: str, required_fields: tuple[str, ...]):
    try:
        doc = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise CatalogAdapterError('Invalid UTF-8/JSON index') from exc
    if (type(doc) is not dict or doc.get('schema_version') != 1
            or doc.get('source') != source or type(doc.get('scenes')) is not dict
            or type(doc.get('record_count')) is not int):
        raise CatalogAdapterError('Derived index schema/source mismatch')
    scenes, total = {}, 0
    for key, rows in doc['scenes'].items():
        if (type(key) is not str or not key.isdecimal() or str(int(key)) != key
                or not 0 <= int(key) <= 65535
                or type(rows) is not list or len(rows) > 4096):
            raise CatalogAdapterError('Invalid scene ID or list')
        parsed, indices = [], set()
        for row in rows:
            if (type(row) is not dict or any(type(row.get(f)) is not int for f in required_fields)
                    or not 0 <= row['index'] <= 65535 or row['index'] in indices):
                raise CatalogAdapterError('Invalid/duplicate event index')
            indices.add(row['index'])
            if source == 'EventData.NewNpc':
                if (not 1 <= row['npc_id'] <= 0xffffffff
                        or not 0 <= row['x'] <= 0xffffffff
                        or not 0 <= row['y'] <= 0xffffffff):
                    raise CatalogAdapterError('Invalid NPC source field')
            else:
                if (row['form_kind'] not in (1, 2, 3)
                        or type(row.get('items')) is not list
                        or len(row['items']) > 255):
                    raise CatalogAdapterError('Invalid shop interaction type')
                for item in row['items']:
                    if (type(item) is not dict
                            or any(type(item.get(k)) is not int for k in
                                   ('id', 'text_id', 'database_kind', 'kind'))
                            or not 0 <= item['id'] <= 255
                            or not 0 <= item['text_id'] <= 65535
                            or not 0 <= item['database_kind'] <= 255
                            or not 0 <= item['kind'] <= 255):
                        raise CatalogAdapterError('Invalid interaction item')
            parsed.append(row)
        scenes[key] = parsed
        total += len(parsed)
        if total > MAX_ROWS:
            raise CatalogAdapterError('Index exceeds maximum record count')
    if total != doc['record_count']:
        raise CatalogAdapterError('Index record count mismatch')
    return scenes, total


def _binary_table(raw: bytes, record_size: int):
    if len(raw) < 4:
        raise CatalogAdapterError('Truncated binary table header')
    count = struct.unpack_from('<i', raw)[0]
    if not 0 <= count <= MAX_ROWS or len(raw) != 4 + count * record_size:
        raise CatalogAdapterError('Unknown binary record layout or truncated table')
    return count


def _decode(contract: SourceContract, raw: bytes):
    schema = contract.schema_id
    if schema == 'eve-npc-json-v1':
        return _json_scenes(raw, source='EventData.NewNpc',
                            required_fields=('index', 'npc_id', 'x', 'y'))
    if schema == 'eve-interact-json-v1':
        return _json_scenes(raw, source='EventData.NewInteract',
                            required_fields=('index', 'form_kind'))
    if schema == 'smith-new-33-v1':
        count = _binary_table(raw, 33)
        from wlre.services.world.preview_1275 import parse_smith_1275
        result = parse_smith_1275(raw)
        if type(result) is not dict or len(result) != count:
            raise CatalogAdapterError('Smith parser count mismatch')
        return result, count
    if schema == 'stage-new-76-v1':
        count = _binary_table(raw, 76)
        from wlre.services.instance_catalog import parse_stages
        result = parse_stages(raw)
        if type(result) is not dict or len(result) != count:
            raise CatalogAdapterError('Stage parser count mismatch')
        return result, count
    raise CatalogAdapterError('Unreviewed schema adapter')


def parse_feature(*, catalog_key: str, package_versions: Mapping[str, str],
                  contract: SourceContract, raw: bytes) -> ParsedCatalog:
    """Fail closed on any unreviewed format/version/digest; never enable gameplay."""
    if not isinstance(catalog_key, str) or not _HEX64.fullmatch(catalog_key):
        raise CatalogAdapterError('A verified versioned Catalog key is required')
    if (not isinstance(contract, SourceContract)
            or not isinstance(package_versions, Mapping)
            or package_versions.get(contract.package) != contract.package_version):
        raise CatalogAdapterError('Catalog/package source revision mismatch')
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise CatalogAdapterError('Missing or oversized source payload')
    digest = hashlib.sha256(raw).hexdigest()
    if digest != contract.expected_sha256:
        raise CatalogAdapterError('Unreviewed or corrupted source SHA-256')
    try:
        records, count = _decode(contract, raw)
    except CatalogAdapterError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, UnicodeError, struct.error) as exc:
        raise CatalogAdapterError('Source parser failed; adapter requires review') from exc
    return ParsedCatalog(catalog_key, contract.feature, contract.source_name,
                         contract.schema_id, digest, count, records)


def parse_selected(*, catalog_key: str, package_versions: Mapping[str, str],
                   contracts: Mapping[str, SourceContract],
                   source_payloads: Mapping[str, bytes]) -> dict[str, ParsedCatalog]:
    """Validate ALL four features before returning; no partial activation."""
    if (not isinstance(contracts, Mapping) or set(contracts) != set(FEATURES)
            or not isinstance(source_payloads, Mapping)):
        raise CatalogAdapterError('All four independently reviewed feature contracts are required')
    parsed = {}
    for feature in FEATURES:
        contract = contracts[feature]
        if not isinstance(contract, SourceContract) or contract.feature != feature:
            raise CatalogAdapterError('Feature/source contract mismatch')
        if contract.source_name not in source_payloads:
            raise CatalogAdapterError('Missing required feature source')
        parsed[feature] = parse_feature(
            catalog_key=catalog_key, package_versions=package_versions,
            contract=contract, raw=source_payloads[contract.source_name])
    return parsed
