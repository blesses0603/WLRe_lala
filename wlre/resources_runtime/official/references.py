"""同次官方場景／文字／MainPackage 索引交叉核對；不猜缺少的模型。"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from wlre.resources_runtime.official.contracts import ResourceStatus
from wlre.services.official_manifest_sync import VerifiedManifest

_SCENE_PATH = re.compile(
    r'Assets/ResourcesBuild/Scenes/(?:BaseScenes|StageScenes)/M([0-9]{5})/M\1\.unity\Z')
_ADDRESS = re.compile(r'M([0-9]{5})\Z')


@dataclass(frozen=True)
class SceneReference:
    scene_id: int
    name_id: int
    name: str | None
    name_status: ResourceStatus
    name_code: str
    model_id: int
    model_manifest_status: ResourceStatus
    model_code: str
    model_asset_path: str | None = None
    model_bundle: str | None = None
    model_content_status: ResourceStatus = ResourceStatus.UNKNOWN

    @property
    def geometry_ready(self):
        return False  # 本階段沒有下載／解析場景幾何或官方網格。


def scene_display_name(value):
    if (type(value) is not str or not value.strip() or len(value) > 160
            or any(ord(char) < 32 for char in value)):
        return None
    return value.strip()


def _model_index(manifest):
    if (not isinstance(manifest, VerifiedManifest) or manifest.spec.package != 'MainPackage'
            or manifest.index['header']['package_name'] != 'MainPackage'
            or manifest.index['header']['package_version'] != manifest.spec.package_version):
        raise ValueError('verified_main_manifest_required')
    candidates = defaultdict(list)
    bundles = {row['name']: row for row in manifest.index['bundles']}
    for asset in manifest.index['assets']:
        address = _ADDRESS.fullmatch(asset['address'])
        path = _SCENE_PATH.fullmatch(asset['path'])
        # 僅識別兩個已觀測官方路徑族。相同 address 的異常路徑仍須保留為 INVALID。
        ids = set()
        if address:
            ids.add(int(address[1]))
        if path:
            ids.add(int(path[1]))
        for model_id in ids:
            candidates[model_id].append((asset, address, path))
    return candidates, bundles


def audit_scene_references(scenes, texts, main_manifest):
    candidates, bundles = _model_index(main_manifest)
    names = None if texts is None else {row['id']: row['text'] for row in texts.records}
    result = []
    for scene in scenes.records:
        name_id, model_id = scene['name_id'], scene['model_id']
        name = None
        if names is None:
            name_status, name_code = ResourceStatus.UNKNOWN, 'official_texts_not_requested'
        elif name_id <= 0 or name_id not in names:
            name_status, name_code = ResourceStatus.MISSING, 'scene_name_text_missing'
        else:
            name = scene_display_name(names[name_id])
            name_status = ResourceStatus.VALID if name is not None else ResourceStatus.INVALID
            name_code = 'scene_name_verified' if name is not None else 'scene_name_text_invalid'
        matches = candidates.get(model_id, ())
        model_path = model_bundle = None
        if not matches:
            model_status, model_code = ResourceStatus.MISSING, 'scene_model_manifest_missing'
        elif len(matches) != 1:
            model_status, model_code = ResourceStatus.INVALID, 'scene_model_identity_ambiguous'
        else:
            asset, address, path = matches[0]
            if not address or not path or int(address[1]) != model_id or int(path[1]) != model_id:
                model_status, model_code = ResourceStatus.INVALID, 'scene_model_identity_mismatch'
            elif asset['bundle_name'] not in bundles:
                model_status, model_code = ResourceStatus.INVALID, 'scene_model_bundle_missing'
            elif bundles[asset['bundle_name']]['encrypted']:
                model_status, model_code = ResourceStatus.UNSUPPORTED, 'scene_model_bundle_encrypted'
            else:
                model_status, model_code = ResourceStatus.VALID, 'scene_model_manifest_identity_only'
                model_path, model_bundle = asset['path'], asset['bundle_name']
        result.append(SceneReference(scene['id'], name_id, name, name_status, name_code,
                                     model_id, model_status, model_code, model_path, model_bundle))
    return tuple(result)


def reference_summary(references):
    return {
        'scene_count': len(references),
        'name_statuses': dict(Counter(row.name_status.value for row in references)),
        'model_manifest_statuses': dict(Counter(row.model_manifest_status.value for row in references)),
        'distinct_models': len({row.model_id for row in references}),
        'missing_distinct_models': len({row.model_id for row in references
                                        if row.model_manifest_status is ResourceStatus.MISSING}),
        'model_content_status': ResourceStatus.UNKNOWN.value,
        'geometry_ready': False,
    }
