"""Audit actual 1275 Recast scanner input classes from SHA-pinned scene Bundles.

Counts candidates for Terrain, TerrainData, colliders and Mesh in both the
scene and its dependency Bundle. This is NOT a NavMesh builder: Unity Layer,
transform, collider enabled state, Terrain height samples and Recast voxel
rasterization must be verified before any triangle can be walkable.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
from zipfile import ZipFile

from tools.resources.extract_1275_recast_settings import (
    Recast1275Error, _sha, unity_nodes, serialized_objects, load_scene_selection, scene_models)


# Official Unity built-in class IDs. Class 198 is ParticleSystem; class 156
# is TerrainData and class 218 is Terrain.
CLASS_IDS = {
    1: 'GameObject', 4: 'Transform', 23: 'MeshRenderer',
    33: 'MeshFilter', 43: 'Mesh', 64: 'MeshCollider',
    65: 'BoxCollider', 114: 'MonoBehaviour', 135: 'SphereCollider',
    136: 'CapsuleCollider', 156: 'TerrainData', 198: 'ParticleSystem',
    218: 'Terrain',
}
COLLIDER_TYPES = (64, 65, 135, 136)


def class_inventory(raw):
    """Use the same bounded object reader as AstarPath configuration extraction."""
    return Counter(cid for _,cid,_ in serialized_objects(raw))


def inspect(scenes_zip, selection_file=None):
    selection = load_scene_selection(scenes_zip,selection_file)
    if (selection.get('target_revision') != 1275
            or not isinstance(selection.get('bundles'), list)):
        raise Recast1275Error('官方1275差異選取清單無效')
    rows = [row for row in selection['bundles']
            if row.get('group') == 'scenes']
    expected=scene_models(selection)
    if len(rows)!=2*len(expected):raise Recast1275Error('1275場景主檔與相依Bundle不完整')
    records = {}
    aggregate = Counter()
    with ZipFile(scenes_zip) as z:
        if z.testzip() is not None:
            raise Recast1275Error('1275 場景來源 ZIP CRC 錯誤')
        for row in rows:
            name = row.get('bundle_name')
            if not isinstance(name, str) or not name.startswith('mainpackage_scene_'):
                raise Recast1275Error('1275 場景 Bundle 名稱無效')
            part = name.removeprefix('mainpackage_scene_').removesuffix('.bundle')
            suffix = '_dependency'
            dependent = part.endswith(suffix)
            try:
                scene_id = int(part[:-len(suffix)] if dependent else part)
            except ValueError as exc:
                raise Recast1275Error('1275 場景模型 ID 無效') from exc
            member = 'source/' + row['path']
            if z.namelist().count(member) != 1:
                raise Recast1275Error('1275 場景 ZIP 缺件或重複成員')
            original = z.read(member)
            if len(original) != row['size'] or _sha(original) != row['sha256']:
                raise Recast1275Error('1275 場景 SHA-256/大小不符：'+name)
            counter = Counter()
            for inner_name, blob in unity_nodes(original):
                # Raw binary texture stream, not a SerializedFile.
                if inner_name.endswith(('.resS', '.resource')):
                    continue
                counter.update(class_inventory(blob))
            kind = 'dependency' if dependent else 'scene'
            pairs = records.setdefault(scene_id, {})
            if kind in pairs:
                raise Recast1275Error('1275 場景 Bundle 重複')
            pairs[kind] = {
                'sha256': row['sha256'], 'object_count': sum(counter.values()),
                'classes': {CLASS_IDS.get(k, str(k)): counter[k]
                            for k in sorted(counter)},
            }
            aggregate.update(counter)
    if set(records) != expected or any(set(row) != {'scene', 'dependency'}
                                 for row in records.values()):
        raise Recast1275Error('1275 場景主檔／相依 Bundle 缺件')
    report = {
        'resource_revision': 1275, 'scene_count': len(records),
        'bundle_count': len(rows),
        'unity_object_count': sum(aggregate.values()),
        'class_totals': {CLASS_IDS.get(k, str(k)): aggregate[k]
                         for k in sorted(aggregate)},
        'scenes': {str(k): records[k] for k in sorted(records)},
        'terrain_or_collider_inputs_found': bool(
            aggregate[156] or aggregate[218] or
            any(aggregate[x] for x in COLLIDER_TYPES)),
        'recast_voxelization_performed': False,
        'rasterizer_layers_verified': False,
        'collider_transforms_verified': False,
        'walkable_triangle_mesh_built': False,
        'can_send_packets': False,
        'warning': ('Unity資源類別存在僅代表掃描輸入候選；必須核對地形、'
                    '碰撞器Layer與Transform、Recast voxel/agent參數、'
                    '障礙物與結果節點才能啟用1275自動移動。'),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='唯讀盤點1275場景Mesh/Terrain/Collider來源，不啟動導航')
    parser.add_argument('--scenes-zip', type=Path, required=True)
    parser.add_argument('--select', type=Path, help='可省略以讀取ZIP內附場景清單')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError('不覆寫1275已存在的碰撞器稽核報告')
    doc = inspect(args.scenes_zip, args.select)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                           encoding='utf8')
    print(json.dumps({
        'scenes': doc['scene_count'], 'bundles': doc['bundle_count'],
        'objects': doc['unity_object_count'],
        'walkable_triangle_mesh_built': False,
        'can_send_packets': False,
        'path': str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
