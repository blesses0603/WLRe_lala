"""Verified private 1275 PNG resource caches, independent of dev tools.

The archives live under user data storage, never in the public GitHub repo.
They can be generated from the user's SHA-pinned 1275 UnityFS bundles.
"""
import hashlib
import io
import re
import json
from zipfile import ZipFile

RESOURCE_SOURCES = {
    "icons": ("mainpackage_assets_resourcesbuild_sprite_sprite_item.bundle",
              "a5f043d6f72e874ecc7cfc5c22935a9c5bfa4defc1d775738db7a58fc28e9375",
              "item_icons_1275.zip", 4000),
    "smallmaps": ("mainpackage_texture_s.bundle",
                  "ffcc3897f8eb9a8ee85485eaf2760ad9f25853bc17ca3d74d28c4cf1f1eecea9",
                  "smallmaps_1275.zip", 500),
}
NEW_ICON_NAMES = {*(f"s{i}" for i in range(4253, 4267)), "s9937"}


class VisualResourceError(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _verify_private_cache(path, kind):
    """Full SHA-256 verification of every PNG before trusting versioned art."""
    if kind not in RESOURCE_SOURCES:
        raise VisualResourceError("未知圖像快取種類")
    source, pinned, _, lower = RESOURCE_SOURCES[kind]
    with ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise VisualResourceError("圖片ZIP有重複檔案")
        if "manifest.json" not in names:
            raise VisualResourceError("沒有1275圖像指紋")
        manifest = json.loads(z.read("manifest.json"))
        if not isinstance(manifest,dict):raise VisualResourceError("1275圖像Manifest必須是物件")
        hashes = manifest.get("images")
        if (manifest.get("schema_version") != 1
                or manifest.get("resource_revision") != 1275
                or manifest.get("kind") != kind
                or manifest.get("source_bundle") != source
                or manifest.get("source_bundle_sha256") != pinned
                or not isinstance(hashes, dict) or len(hashes) < lower
                or manifest.get("image_count") != len(hashes)):
            raise VisualResourceError("圖像來源不是已驗證的1275快取")
        extras = {"manifest.json"} | ({"image_index.json"} if kind == "smallmaps" else set())
        if set(names) != set(hashes) | extras:
            raise VisualResourceError("1275圖像檔案有缺漏或未知額外成員")
        pattern = r"s[0-9]+\.png" if kind == "icons" else r"SmallMap2D_[0-9]+\.png"
        for name, digest in hashes.items():
            if (not isinstance(name, str) or "/" in name or "\\" in name
                    or not re.fullmatch(pattern,name) or type(digest) is not str
                    or sha256(z.read(name)) != digest):
                raise VisualResourceError("1275圖片SHA-256不符：" + str(name))
            from PIL import Image
            with Image.open(io.BytesIO(z.read(name))) as image:
                if image.format != 'PNG' or not 1 <= image.width <= 8192 or not 1 <= image.height <= 8192:
                    raise VisualResourceError('1275圖片格式或尺寸無效：'+name)
                image.verify()
            # verify() checks the PNG structure; load() also validates compressed pixels.
            with Image.open(io.BytesIO(z.read(name))) as image:image.load()
        if kind == "icons" and not {x+".png" for x in NEW_ICON_NAMES}.issubset(hashes):
            raise VisualResourceError("新版物品圖示遺漏")
        if kind == "smallmaps":
            index = json.loads(z.read("image_index.json"))
            if (type(index) is not list or len(index) != len(hashes)
                    or any(not isinstance(v,dict) or not isinstance(v.get('name'),str)
                           or v.get('entry') != v['name']+'.png'
                           or not re.fullmatch(r'SmallMap2D_[0-9]+',v['name']) for v in index)
                    or {v.get("entry") for v in index} != set(hashes)
                    or len({int(v['name'].rsplit('_',1)[1]) for v in index}) != len(index)):
                raise VisualResourceError("1275小地圖索引無效")
        return manifest


def verify_private_cache(path, kind):
    """Validate provenance, schema and every decoded PNG; report one public error type."""
    from zipfile import BadZipFile
    from PIL import Image
    try:
        return _verify_private_cache(path,kind)
    except VisualResourceError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BadZipFile,
            Image.DecompressionBombError) as exc:
        raise VisualResourceError('1275圖像快取無效：'+str(exc)) from exc
