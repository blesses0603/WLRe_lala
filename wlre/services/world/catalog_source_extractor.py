"""Read only reviewed UnityFS TextAssets and derive LaLa adapter inputs.

An Eve TextAsset is binary. NPC/shop JSON is derived only through the
audited v115 scene record parser, then pinned by SourceContract SHA-256.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from wlre.services.world.official_catalog_pipeline import AssetBinding
from wlre.services.world.unity_textasset import extract_textasset, UnityTextAssetError
from wlre.services.world.eve_v115 import derive_eve_index


def extract_catalog_source(binding: AssetBinding, bundle_paths):
    """Verified Bundle cache -> TextAsset bytes -> optional Eve v115 index."""
    if not isinstance(binding, AssetBinding):
        raise UnityTextAssetError('Reviewed AssetBinding required')
    raw = extract_textasset(binding, bundle_paths)
    schema = binding.contract.schema_id
    name = PurePosixPath(binding.asset_path).name
    if schema == 'eve-npc-json-v1':
        if name != 'Eve.bytes' or binding.contract.source_name != 'EventData.NewNpc':
            raise UnityTextAssetError('NPC index is not bound to official Eve TextAsset')
        return derive_eve_index(raw, 'EventData.NewNpc')
    if schema == 'eve-interact-json-v1':
        if name != 'Eve.bytes' or binding.contract.source_name != 'EventData.NewInteract':
            raise UnityTextAssetError('Shop index is not bound to official Eve TextAsset')
        return derive_eve_index(raw, 'EventData.NewInteract')
    if schema == 'smith-new-33-v1' and name == 'SmithData_C.bytes':
        return raw
    if schema == 'stage-new-76-v1' and name == 'ScenesData_C.bytes':
        return raw
    raise UnityTextAssetError('Unreviewed TextAsset/source/schema combination')
