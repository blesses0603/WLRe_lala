"""Privately export verified 1275 Unity Sprite and SmallMap2D resources.

Requires optional 'UnityPy' plus Pillow locally. No proprietary game pixels
or Unity bundles are committed to GitHub; this runs only on user's archives.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from wlre.services.world.visuals_1275 import (
    RESOURCE_SOURCES, NEW_ICON_NAMES, VisualResourceError,
    verify_private_cache, sha256 as _sha)
def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def select_bundle(archives, selection, kind):
    """Read source bytes only after checking the user's 1275 selection pins."""
    bundle_name, pinned, _, _ = RESOURCE_SOURCES[kind]
    if (type(selection) is not dict or selection.get("target_revision") != 1275
            or type(selection.get("bundles")) is not list):
        raise VisualResourceError("1275 差異清單版本無效")
    matches = [row for row in selection["bundles"]
               if row.get("bundle_name") == bundle_name]
    if len(matches) != 1 or matches[0].get("sha256") != pinned:
        raise VisualResourceError("1275 影像來源清單 SHA-256 不符合已驗證指紋")
    record = matches[0]
    name = "source/" + record["path"]
    found = []
    for archive in archives:
        with ZipFile(archive) as z:
            if name in z.namelist():
                if z.namelist().count(name) != 1:
                    raise VisualResourceError("1275 來源 ZIP 有重複成員")
                raw = z.read(name)
                if (len(raw) != record["size"] or _sha(raw) != pinned):
                    raise VisualResourceError("1275 Bundle SHA-256／大小不符")
                found.append(raw)
    if len(found) != 1:
        raise VisualResourceError("1275 Bundle 必須恰好出現在一個 ZIP：" + bundle_name)
    return found[0]


def build(kind, archives, selection_file, output):
    if kind not in RESOURCE_SOURCES:
        raise VisualResourceError("不支援的1275資源類型")
    try:
        import UnityPy
        from PIL import Image
    except ImportError as exc:
        raise VisualResourceError("請先執行 py -m pip install UnityPy Pillow") from exc
    with open(selection_file, "r", encoding="utf-8") as f:
        selection = json.load(f)
    source = select_bundle(archives, selection, kind)
    bundle_name, expected, _, min_count = RESOURCE_SOURCES[kind]
    prefix = "s" if kind == "icons" else "SmallMap2D_"
    class_name = "Sprite" if kind == "icons" else "Texture2D"
    env = UnityPy.load(source)
    images = {}
    names = set()
    for obj in env.objects:
        if obj.type.name != class_name:
            continue
        try:
            # UnityPy's current API is parse_as_object(); old releases used read().
            parse = getattr(obj, 'parse_as_object', None)
            asset = parse() if callable(parse) else obj.read()
            name = asset.m_Name
            if not isinstance(name, str) or not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            if not suffix.isdecimal() or name in names:
                continue
            pic = asset.image
            if pic is None:
                continue
            if not isinstance(pic, Image.Image):
                raise VisualResourceError("解碼不是Pillow圖片：" + name)
            if not 1 <= pic.width <= 8192 or not 1 <= pic.height <= 8192:
                raise VisualResourceError("1275圖片尺寸超過預期：" + name)
            b = io.BytesIO()
            pic.convert("RGBA").save(b, format="PNG")
            images[name + ".png"] = b.getvalue()
            names.add(name)
        except (VisualResourceError, MemoryError):
            raise
        except Exception as exc:
            raise VisualResourceError("1275原始圖片解碼失敗：" + str(obj.path_id)) from exc
    if len(images) < min_count:
        raise VisualResourceError("1275圖片數量不足，拒絕部分安裝：" + str(len(images)))
    if kind == "icons" and not NEW_ICON_NAMES.issubset(names):
        raise VisualResourceError("1275缺少15個已確認的新Sprite")
    path = Path(output).resolve()
    if path.exists():
        raise FileExistsError("不覆寫既有1275圖像快取：" + str(path))
    if not path.parent.is_dir():
        raise FileNotFoundError("輸出資料夾不存在：" + str(path.parent))
    manifest = {
        "schema_version": 1, "resource_revision": 1275,
        "kind": kind, "source_bundle": bundle_name,
        "source_bundle_sha256": expected, "image_count": len(images),
        "images": {name: _sha(value) for name, value in sorted(images.items())},
    }
    if kind == "smallmaps":
        idx = [{"name":name.removesuffix(".png"),"entry":name}
               for name in sorted(images)]
    else:
        idx = None
    try:
        with ZipFile(path, "x", ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            if idx is not None:
                z.writestr("image_index.json", json.dumps(idx, ensure_ascii=False))
            for name, raw in sorted(images.items()):
                z.writestr(name, raw)
        verify_private_cache(path, kind)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {"kind": kind, "count":len(images), "output":str(path),
            "source_sha256":expected}


def main(argv=None):
    p = argparse.ArgumentParser(description="離線匯出已核對的1275物品圖示與小地圖PNG")
    p.add_argument("--kind", choices=("icons","smallmaps"), required=True)
    p.add_argument("--select", type=Path, required=True)
    p.add_argument("--archives", type=Path, nargs="+", required=True)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", type=Path,
                        help="離線輸出指定路徑（若檔案存在會拒絕覆寫）")
    target.add_argument("--install", action="store_true",
                        help="驗證後直接安裝到使用者的1275私人快取資料夾")
    args=p.parse_args(argv)
    if args.install:
        from wlre.services.world.runtime_1275 import resource_dir
        root = resource_dir()
        root.mkdir(parents=True, exist_ok=True)
        output = root / RESOURCE_SOURCES[args.kind][2]
    else:
        output = args.output
    print(json.dumps(build(args.kind, args.archives, args.select, output),
                     ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
