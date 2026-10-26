"""舊 AssetBinding API 的相容入口；UnityFS 解析僅由共用資源層實作。"""
from wlre.resources_runtime.parsers.unity_textasset import (  # noqa: F401
    MAX_BLOCK_INFO_BYTES,
    MAX_BUNDLE_BYTES,
    MAX_CONTAINER_ENTRIES,
    MAX_INPUT_BUNDLES,
    MAX_SOURCE_BYTES,
    MAX_TOTAL_INPUT_BYTES,
    UnityTextAssetError,
    _find_exact_container_object,
    _loader,
    _payload,
    _validate_unityfs_header,
    extract_exact_textasset,
)
from wlre.services.world.official_catalog_pipeline import AssetBinding


def extract_textasset(binding, bundle_paths, *, loader=None):
    if not isinstance(binding, AssetBinding):
        raise UnityTextAssetError('Expected a reviewed binding and bounded Bundle paths')
    return extract_exact_textasset(binding.asset_path, bundle_paths,
                                   loader=_loader if loader is None else loader)
