"""Read verified UnityFS TextAssets and derive LaLa adapter inputs.

An Eve TextAsset is binary. NPC/shop JSON is derived only through the
reviewed v115 parser. An explicit ItemData_C dependency can enrich shop offers
with offline *base* item values, never an authorized transaction price.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from wlre.services.world.official_catalog_pipeline import AssetBinding
from wlre.services.world.unity_textasset import extract_textasset, UnityTextAssetError
from wlre.services.world.eve_v115 import derive_eve_index
from wlre.services.world.itemdata_v1 import parse_itemdata, ItemDataDecodeError


def _shop_index(binding, bundle_paths, raw):
    document = derive_eve_index(raw, 'EventData.NewInteract')
    if not binding.related_asset_paths:
        return document
    extras = binding.related_asset_paths
    if (len(extras) != 1 or
            extras[0] != 'Assets/ResourcesBuild/Data/ItemData_C.bytes'):
        raise UnityTextAssetError('Shop requires the exact reviewed ItemData_C AssetPath')
    related_binding = AssetBinding(extras[0], binding.contract)
    item_raw = extract_textasset(related_binding, bundle_paths)
    items = parse_itemdata(item_raw)
    doc = json.loads(document.decode('utf-8'))
    for rows in doc['scenes'].values():
        for interact in rows:
            if interact['form_kind'] not in (2, 3):
                continue
            for offer in interact['items']:
                if offer['kind'] == 3:
                    if offer['database_kind'] != 2:
                        raise ItemDataDecodeError('Shop item references unknown database')
                    info = items.get(offer['text_id'])
                    if info is None:
                        raise ItemDataDecodeError('Referenced shop ItemData ID is missing')
                    offer['item_data'] = info
                    offer['buy_enabled'] = False
    doc['itemdata_sha256'] = hashlib.sha256(item_raw).hexdigest()
    doc['itemdata_count'] = len(items)
    doc['itemdata_verified'] = True
    # This fully derived output is individually pinned by SourceContract.
    return json.dumps(doc, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def extract_catalog_source(binding: AssetBinding, bundle_paths):
    """Verified Bundle cache -> TextAsset -> optional Eve/ItemData derived JSON."""
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
        return _shop_index(binding, bundle_paths, raw)
    if schema == 'smith-new-33-v1' and name == 'SmithData_C.bytes':
        return raw
    if schema == 'stage-new-76-v1' and name == 'ScenesData_C.bytes':
        return raw
    raise UnityTextAssetError('Unreviewed TextAsset/source/schema combination')
