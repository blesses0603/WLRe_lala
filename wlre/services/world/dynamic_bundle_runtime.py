"""Version-pair-aware, read-only runtime catalog metadata for current official assets.

The live official version pair is authoritative; historical 1275 constants are
not used. Parsed record counts are sourced from verified TextAssets stored by
the official catalog pipeline, never inferred from a Manifest asset count.
This does not grant gameplay or network protocol approval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from wlre.services.world.catalog_adapters import FEATURES
from wlre.services.world.catalog_runtime import official_catalog_key, official_package_versions
from wlre.services.world.official_catalog_store import active_official_catalog

_HEX = re.compile(r'[0-9a-f]{64}\Z')


class DynamicRuntimeUnavailable(ValueError):
    """Official runtime metadata is absent, stale, or incomplete."""


@dataclass(frozen=True)
class DynamicRuntime:
    catalog_key: str
    package_versions: dict[str, str]
    record_counts: dict[str, int]
    source_sha256: dict[str, str]
    assets_ready: bool = False
    can_send_packets: bool = False


def load_dynamic_runtime_metadata(remote, *, db_path):
    """Select only the exact official version pair from the verified SQLite cache.

    The record_count columns were checked against parsed payloads by the
    catalog pipeline before transactional storage. This function does not
    treat editable local SQLite metadata as a trust anchor for gameplay.
    """
    try:
        versions = official_package_versions(remote)
        key = official_catalog_key(remote)
    except (ValueError, KeyError, TypeError) as exc:
        raise DynamicRuntimeUnavailable('Official version pair unavailable') from exc
    catalog = active_official_catalog(db_path)
    if not catalog or catalog['catalog_key'] != key:
        raise DynamicRuntimeUnavailable('Verified current-version catalog unavailable')
    sources = catalog['sources']
    if set(sources) != set(FEATURES):
        raise DynamicRuntimeUnavailable('Official source set incomplete')
    counts, digests = {}, {}
    for feature in FEATURES:
        row = sources[feature]
        count, digest = row['record_count'], row['sha256']
        if (type(count) is not int or not 0 <= count <= 20000
                or type(digest) is not str or not _HEX.fullmatch(digest)):
            raise DynamicRuntimeUnavailable('Official source metadata invalid')
        counts[feature] = count
        digests[feature] = digest
    return DynamicRuntime(key, versions, counts, digests)


def load_parsed_dynamic_runtime(remote, *, parsed):
    """Accept complete independently parsed current-version records, not counts."""
    from wlre.services.world.catalog_adapters import FEATURES, ParsedCatalog
    try:
        key = official_catalog_key(remote)
        versions = official_package_versions(remote)
        if type(parsed) is not dict or set(parsed) != set(FEATURES):
            raise DynamicRuntimeUnavailable('Incomplete parsed source set')
        for feature in FEATURES:
            item = parsed[feature]
            if (type(item) is not ParsedCatalog or item.feature != feature
                    or item.catalog_key != key or item.assets_ready is not False
                    or item.can_send_packets is not False):
                raise DynamicRuntimeUnavailable('Unverified runtime source')
        return {
            'catalog_key': key,
            'package_versions': versions,
            'records': {f: parsed[f].records for f in FEATURES},
            'record_counts': {f: parsed[f].record_count for f in FEATURES},
            'assets_ready': False,
            'can_send_packets': False,
        }
    except (ValueError, TypeError, KeyError) as exc:
        raise DynamicRuntimeUnavailable('Dynamic runtime unavailable') from exc
