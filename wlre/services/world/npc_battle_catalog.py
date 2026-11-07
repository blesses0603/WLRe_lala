"""Known-source NPC battle quotes, rebuilt from official bytes into SQLite.

The sole reviewed raw fingerprint is byte-identical across 1262/1275/1296.
All 94 records were independently compared with the previously reviewed index
and re-encoded byte-for-byte. This is NOT an unknown-format Lua decoder.
"""
import hashlib
import struct
from pathlib import Path
from wlre.services.parser_diagnostics import diagnosed, checkpoint

TABLES = ('NpcTalkData_C',)
KNOWN_SHA256 = '9de2f789e7f194148959457e7a1fc4744bf3378d62fdaff54ce51efe28499bb8'


@diagnosed('npc-battle-talk-known-v1')
def parse_known_battle_talk(raw):
    checkpoint(offset=0, field='source_fingerprint')
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != KNOWN_SHA256:
        raise ValueError('NpcTalkData 來源指紋未經審核；拒絕推測新格式')
    if len(raw) < 4:
        raise ValueError('NpcTalkData 缺少筆數')
    count = struct.unpack_from('<I', raw)[0]
    if not 0 < count <= 20000 or len(raw) != 4 + count * 10:
        raise ValueError('NpcTalkData 筆數或長度不符')
    groups = {}
    for group, text_id, kind, parameter, duration in struct.iter_unpack('<HIBHB', raw[4:]):
        rows = groups.setdefault(group, [])
        if not group or not text_id or len(rows) >= 255:
            raise ValueError('NpcTalkData 群組或文字 ID 無效')
        rows.append(dict(text_id=text_id, kind=kind, parameter=parameter, duration=duration))
    return groups


def build_catalog(raw, text_raw):
    from wlre.services.expedition.data import parse_text_data
    groups = parse_known_battle_talk(raw)
    texts = parse_text_data(text_raw)
    if any(row['text_id'] not in texts for rows in groups.values() for row in rows):
        raise ValueError('戰鬥台詞缺少同版 TextData 文字')
    return groups


def load_verified_catalog(manifest, bundle_root, loader, root, identity, core_sources):
    from wlre.services.official_incremental_sync import build_update_plan
    from wlre.services.official_bundle_download import _verified_file
    from wlre.services.world.catalog_adapters import SourceContract
    from wlre.services.world.official_catalog_pipeline import AssetBinding
    from wlre.services.world.unity_textasset import extract_textasset
    from wlre.storage.normalized_resources import load_parsed
    asset = 'Assets/ResourcesBuild/Data/NpcTalkData_C.bytes'
    plan = build_update_plan(manifest, asset_paths=(asset,), cache_root=bundle_root)
    if not plan.entries or any(row.action != 'cached' for row in plan.entries):
        raise ValueError('官方戰鬥台詞尚未快取')
    paths = tuple(row.spec.cache_path(bundle_root) for row in plan.entries)
    if any(not _verified_file(path, row.spec) for path, row in zip(paths, plan.entries)):
        raise ValueError('戰鬥台詞 Bundle 校驗失敗')
    binding = AssetBinding(asset, SourceContract('scenes', 'NpcTalkData_C', 'stage-new-76-v1',
        '0' * 64, 'DataPackage', manifest.spec.package_version))
    raw = extract_textasset(binding, paths, loader=loader)
    text_raw = core_sources['TextData_C']
    return load_parsed(Path(root) / 'derived_catalogs' / 'resource_inventory.sqlite3',
        identity.key, 'npc-battle-talk', 'npc-battle-talk-known-v1',
        {'NpcTalkData_C': raw, 'TextData_C': text_raw},
        lambda: build_catalog(raw, text_raw))
