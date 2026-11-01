"""Version-neutral, read-only Catalog runtime selection.

A Launcher candidate is never an approved gameplay runtime. This module
separates official identity matching from independently reviewed activation.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from wlre.services.world.catalog_adapters import FEATURES

_KEY = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class CatalogRuntimeDecision:
    catalog_key: str | None
    status: str
    reason: str
    verified_features: tuple[str, ...] = ()
    assets_ready: bool = False
    can_send_packets: bool = False


def select_catalog_runtime(remote, candidate, *, reviewed_keys=()):
    """Select only independently reviewed catalog identities.

    `reviewed_keys` must come from a trusted, release-bundled review policy,
    never from a downloaded candidate, a local receipt or a server response.
    This function is informational; it never authorizes network traffic.
    """
    if not isinstance(remote, dict) or not isinstance(candidate, dict):
        return CatalogRuntimeDecision(None, "blocked", "missing_identity")
    key = candidate.get("catalog_key")
    identity = candidate.get("official_identity")
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return CatalogRuntimeDecision(None, "blocked", "invalid_catalog_key")
    if not isinstance(identity, dict):
        return CatalogRuntimeDecision(key, "blocked", "missing_official_identity")
    from wlre.services.game_version_gate import compare_database_identity
    if compare_database_identity(remote, identity) != "same":
        return CatalogRuntimeDecision(key, "blocked", "official_identity_mismatch")
    if (candidate.get("approved") is not False
            or candidate.get("assets_ready") is not False
            or candidate.get("can_send_packets") is not False
            or candidate.get("status") != "review_required"):
        return CatalogRuntimeDecision(key, "blocked", "untrusted_candidate_state")
    features = candidate.get("features")
    if not isinstance(features, dict) or set(features) != set(FEATURES):
        return CatalogRuntimeDecision(key, "blocked", "incomplete_features")
    if any(not isinstance(features[name], dict) or
           not isinstance(features[name].get("sha256"), str) or
           not _KEY.fullmatch(features[name]["sha256"]) for name in FEATURES):
        return CatalogRuntimeDecision(key, "blocked", "invalid_feature_receipt")
    if key not in reviewed_keys:
        return CatalogRuntimeDecision(key, "review_required",
                                      "release_review_missing", tuple(FEATURES))
    # A release review permits subsequent independently validated loading,
    # not automatic activation or protocol approval.
    return CatalogRuntimeDecision(key, "reviewed_source",
                                  "runtime_validation_required", tuple(FEATURES))
