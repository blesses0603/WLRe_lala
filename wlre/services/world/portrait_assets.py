"""Reviewed data-only portrait projection, NOT a partial Unity runtime loader.

Read three pinned bundles' raw serialized objects. Follow only each portrait's
texture/mask/shader PPtr. Unrelated Unity material-bundle dependencies are not
loaded or represented as satisfied. Every new source needs fresh review.
"""
import hashlib
import re
from pathlib import Path
from wlre.services.official_bundle_download import spec_from_manifest, _verified_file
from wlre.services.world.unity_textasset import _validate_unityfs_header
from wlre.services.world.portrait_render import PARTS, COLOR_PROFILE

VERSION = '1296_2026_11_04_13_36_07_72'
BUNDLES = {
    'mainpackage_material.bundle': '4940712f0a4aa16c71959fe3b315b2b85eef23144feb90a4b70db22046a1fc94',
    'mainpackage_texture_a.bundle': 'a7dc6325bc73f8e5083cde9143e60a87b393ce84719814d1349142893141d3ca',
    'mainpackage_unityshaders.bundle': '4e756561fa3d8b77f439b0b3e969a01f573b451ac9d14ac662d8c8bedf443a47',
}
COLOR_PROFILE_EVIDENCE = {
    'profile': COLOR_PROFILE,
    'reference': 'official mobile UI; not a claim about PC PlayerSettings',
    'apk_size': 103074197,
    'globalgamemanagers_bytes': 334292,
    'globalgamemanagers_sha256': 'ac933dbdb8407c4b0ca540c16356cc80675b8a262cc90095e7f1513c4f8ead31',
    'active_color_space': 0, 'color_gamuts': [0],
}
SHADER_BLOB = '95efa07a84d2cda0758e7d30893efec5c94899807cb3ec20bb8263b7a293d814'
SHADER_FILE = 'CAB-f0d25a36a0de0a1720bc340c0640a4e1'
SHADER_ID = -1215708881511709531
MATERIAL_FILE = 'CAB-66a0cb5c73552f6e34c71e0339b38329'
TEXTURE_FILE = 'CAB-62cd938e63ebf8b532f3064be45777c9'
PATTERN = re.compile(r'Assets/ResourcesBuild/Other/(Avatar2DMaterial/[0-9]{4}/PhotoAvatar_([0-9]{4})|Avatar2DNPCMaterial/([0-9]{4}(?:_[0-9]+)?)/PhotoAvatarNPC_([0-9]{4}(?:_[0-9]+)?))\.mat\Z')


def source_specs(manifest):
    if (manifest.spec.data_ver != '1.3.23' or manifest.spec.package != 'MainPackage'
            or manifest.spec.package_version != VERSION):
        raise ValueError('官方頭像來源版本尚未審核')
    specs = tuple(spec_from_manifest(data_ver='1.3.23', package='MainPackage',
                                    index=manifest.index, name=name) for name in BUNDLES)
    if len(specs) != 3 or sum(s.file_size for s in specs) != 24572057:
        raise ValueError('官方頭像來源大小或數量已改變')
    return specs


def _wanted(manifest):
    result = {}
    for asset in manifest.index['assets']:
        path = asset['path']
        if '/PhotoAvatar_' not in path and '/PhotoAvatarNPC_' not in path:
            continue
        match = PATTERN.fullmatch(path)
        if not match or asset['bundle_name'] != 'mainpackage_material.bundle':
            raise ValueError('未知頭像材質路徑')
        if match[2]:
            kind, icon = 'player', match[2]
            if path.split('/')[-2] != icon:
                raise ValueError('角色頭像路徑與編號不符')
        else:
            kind, icon = 'companion', match[4]
            if match[3] != icon:
                raise ValueError('夥伴頭像路徑與編號不符')
        if (kind, icon) in result:
            raise ValueError('重複頭像材質')
        result[kind, icon] = path
    if (len(result) != 778 or {i for k, i in result if k == 'player'}
            != {f'{i:04d}' for i in range(1, 16)}):
        raise ValueError('官方頭像清單不完整')
    return result


def _pointer(owner, pointer, objects, *, allow_null=False):
    fid, pid = pointer['m_FileID'], pointer['m_PathID']
    if pid == 0:
        if allow_null and fid == 0:
            return None
        raise ValueError('必要頭像引用缺少')
    if type(fid) is not int or not 0 <= fid <= len(owner.assets_file.externals):
        raise ValueError('頭像外部引用越界')
    file = owner.assets_file.name if fid == 0 else owner.assets_file.externals[fid - 1].name
    obj = objects.get((file, pid))
    if obj is None:
        raise ValueError('頭像引用不在已驗證資料投影內')
    return obj


def _texture(obj, expected_name=None):
    if obj.type.name != 'Texture2D':
        raise ValueError('頭像引用不是 Texture2D')
    data = obj.read()
    if (expected_name is not None and data.m_Name != expected_name
            or (data.m_Width, data.m_Height) != (256, 256)
            or data.m_TextureFormat not in (4, 10, 12) or data.m_ColorSpace != 1
            or data.m_MipCount != 1):
        raise ValueError('頭像貼圖格式尚未驗證')
    return data.image.convert('RGBA')


def extract_portraits(manifest, bundle_root):
    """Return (zero-argument decode iterator factory, provenance with expected keys)."""
    specs = source_specs(manifest)
    wanted = _wanted(manifest)
    paths = []
    for spec in specs:
        path = spec.cache_path(bundle_root)
        if (not _verified_file(path, spec) or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != BUNDLES[spec.name]):
            raise ValueError('官方頭像來源指紋尚未審核或已損壞')
        _validate_unityfs_header(path, spec.file_size)
        paths.append(path)
    inputs = {'projection': 'portrait-1296-default-v1', 'version': VERSION,
              'source_sha256': dict(BUNDLES), 'color_profile': dict(COLOR_PROFILE_EVIDENCE), 'shader_blob_sha256': SHADER_BLOB,
              'expected': [list(k) for k in sorted(wanted)]}

    def decode():
        import UnityPy
        from PIL import Image
        # Deliberately separate raw bundle reads: never auto-resolve arbitrary
        # unselected Unity dependencies by loading the user's installation.
        environments = [UnityPy.load(str(path)) for path in paths]
        objects, containers = {}, {}
        for env in environments:
            for obj in env.objects:
                key = (obj.assets_file.name, obj.path_id)
                if key in objects:
                    raise ValueError('重複序列化物件識別')
                objects[key] = obj
            for path, ptr in env.container.items():
                containers.setdefault(path, []).append(ptr)
        shader = objects.get((SHADER_FILE, SHADER_ID))
        if shader is None or shader.type.name != 'Shader':
            raise ValueError('頭像 shader 引用缺少')
        shader_tree = shader.read_typetree()
        form = shader_tree['m_ParsedForm']
        props = {p['m_Name']: p for p in form['m_PropInfo']['m_Props']}
        if (form['m_Name'] != 'UI_ProfilePhotoWithMask'
                or hashlib.sha256(bytes(shader_tree['compressedBlob'])).hexdigest() != SHADER_BLOB
                or props['_ColorMask1']['m_DefTexture']['m_DefaultName'] != 'white'):
            raise ValueError('頭像 shader 或預設遮罩尚未審核')
        for (kind, icon), path in sorted(wanted.items()):
            candidates = containers.get(path, [])
            if len(candidates) != 1 or candidates[0].type.name != 'Material':
                raise ValueError('頭像材質精確路徑缺少或歧義')
            material = candidates[0].deref()
            if material.assets_file.name != MATERIAL_FILE:
                raise ValueError('頭像材質檔案識別不符')
            tree = material.read_typetree()
            if _pointer(material, tree['m_Shader'], objects) is not shader:
                raise ValueError('頭像 shader 不符')
            floats = dict(tree['m_SavedProperties']['m_Floats'])
            colors = dict(tree['m_SavedProperties']['m_Colors'])
            envs = dict(tree['m_SavedProperties']['m_TexEnvs'])
            if (tree['m_ValidKeywords'] or tree['m_InvalidKeywords']
                    or floats['_UseShapeMask'] != 0 or floats['_EdgeLength'] != 0
                    or floats['_MaskClip'] not in (0.05999999865889549, 0.2199999988079071)):
                raise ValueError('頭像材質變體尚未審核')
            for key in ('_ColorMask1', '_ColorTextures'):
                if (envs[key]['m_Scale'] != {'x': 1.0, 'y': 1.0}
                        or envs[key]['m_Offset'] != {'x': 0.0, 'y': 0.0}):
                    raise ValueError('頭像貼圖 UV 變換尚未審核')
            texture = _pointer(material, envs['_ColorTextures']['m_Texture'], objects)
            if texture.assets_file.name != TEXTURE_FILE:
                raise ValueError('頭像貼圖來源不符')
            # Official materials intentionally share some NPC textures (e.g.
            # 7214 references 7213). The PPtr, not the filename convention, wins.
            texture_name = texture.read().m_Name
            if not re.fullmatch(r'Avatar2D(?:NPC)?_[0-9]{4}(?:_[0-9]+)?', texture_name):
                raise ValueError('頭像貼圖名稱尚未審核')
            directory = 'Avatar2DNPC' if texture_name.startswith('Avatar2DNPC_') else 'Avatar2D'
            texture_path = f'Assets/ResourcesBuild/Texture/{directory}/{texture_name}.png'
            declared = containers.get(texture_path, [])
            if len(declared) != 1 or declared[0].deref() is not texture:
                raise ValueError('頭像貼圖引用與精確官方路徑不符')
            base = _texture(texture, texture_name)
            mask_obj = _pointer(material, envs['_ColorMask1']['m_Texture'], objects, allow_null=True)
            if mask_obj is not None and mask_obj.assets_file.name != MATERIAL_FILE:
                raise ValueError('頭像遮罩來源不符')
            mask = _texture(mask_obj) if mask_obj else Image.new('RGBA', (256, 256), 'white')
            metadata = {'shader': form['m_Name'], 'color_profile': COLOR_PROFILE, 'keywords': [], 'use_shape_mask': 0,
                        'mask_clip': floats['_MaskClip'], 'edge_length': floats['_EdgeLength'],
                        'colors': {p: [colors[p][c] for c in ('r', 'g', 'b')]
                                   for p in (*PARTS, '_13_EyeColor_')},
                        'material_asset': path, 'texture_name': texture_name,
                        'mask_source': 'shader_default_white' if mask_obj is None else 'verified_local_texture',
                        'shader_blob_sha256': SHADER_BLOB}
            yield kind, icon, base, mask, metadata
        # Detect a change during lazy decoding as well as before it.
        if any(not _verified_file(s.cache_path(bundle_root), s) for s in specs):
            raise ValueError('官方頭像來源在匯入中改變')
    return decode, inputs
