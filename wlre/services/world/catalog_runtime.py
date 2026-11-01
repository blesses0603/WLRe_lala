"""Official-only version-pair Catalog verification.

No candidate data or downloaded approval may authorize gameplay.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from wlre.services.world.catalog_adapters import (
    FEATURES, SourceContract, ParsedCatalog, CatalogAdapterError, parse_selected,
)

PACKAGES = frozenset(("DataPackage", "MainPackage"))


@dataclass(frozen=True)
class CatalogRuntimeDecision:
    catalog_key: str | None
    status: str
    reason: str
    verified_features: tuple[str, ...] = ()
    assets_ready: bool = False
    can_send_packets: bool = False


def official_package_versions(remote: dict) -> dict[str, str]:
    """Read the exact two official package versions; reject incomplete identity."""
    if type(remote) is not dict or remote.get("newer_official_client") is not False:
        raise CatalogAdapterError("Official client identity is not verified")
    packages = remote.get("packages")
    if type(packages) is not dict or set(packages) != PACKAGES:
        raise CatalogAdapterError("Missing or unexpected official package")
    result = {}
    for name in PACKAGES:
        row = packages[name]
        if (type(row) is not dict or type(row.get("remote")) is not str
                or not row["remote"] or len(row["remote"]) > 100):
            raise CatalogAdapterError("Invalid official package revision")
        result[name] = row["remote"]
    if any(type(remote.get(k)) is not str or not remote[k]
           for k in ("resource_path", "official_exe_version")):
        raise CatalogAdapterError("Missing official client identifiers")
    return result


def official_catalog_key(remote: dict) -> str:
    """Stable official version identity, never a gameplay approval token."""
    versions = official_package_versions(remote)
    identity = {
        "data_ver": remote["resource_path"],
        "exe_version": remote["official_exe_version"],
        "packages": {name: versions[name] for name in sorted(PACKAGES)},
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def select_catalog_runtime(remote, *, package_versions=None):
    """Identify official sources without granting runtime or packet access."""
    try:
        versions = official_package_versions(remote)
        if (package_versions is not None
                and (type(package_versions) is not dict or package_versions != versions)):
            return CatalogRuntimeDecision(None, "blocked", "official_package_pair_mismatch")
        return CatalogRuntimeDecision(
            official_catalog_key(remote), "verification_required",
            "source_validation_required",
        )
    except (CatalogAdapterError, TypeError, ValueError):
        return CatalogRuntimeDecision(None, "blocked", "invalid_official_identity")


def validate_official_catalog(remote, *, contracts: Mapping[str, SourceContract],
                              source_payloads: Mapping[str, bytes]) -> dict[str, ParsedCatalog]:
    """Validate all four trusted sources before returning any parsed records.

    Source contracts must come from trusted application policy, not downloaded
    metadata, SQLite rows or a remote approval. Protocol remains unauthorized.
    """
    versions = official_package_versions(remote)
    if (not isinstance(contracts, Mapping) or set(contracts) != set(FEATURES)
            or not isinstance(source_payloads, Mapping)):
        raise CatalogAdapterError("Complete official source contracts and payloads required")
    for feature in FEATURES:
        contract = contracts[feature]
        if (type(contract) is not SourceContract or contract.feature != feature
                or contract.package_version != versions.get(contract.package)):
            raise CatalogAdapterError("Unverified official source contract or package pair")
    return parse_selected(
        catalog_key=official_catalog_key(remote),
        package_versions=versions,
        contracts=contracts,
        source_payloads=source_payloads,
    )
