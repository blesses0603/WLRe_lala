"""Small synthetic catalogs for protocol/UI tests; no official game data bundled."""
from unittest.mock import patch
import unittest


def catalog():
    rows = []
    for ident, variant, kind, scene, npc in ((1, 0, 1, 30012, 0),
            (16, 1, 1, 30010, 0), (16, 2, 1, 30042, 0),
            (7, 1, 1, 30019, 0), (26, 1, 3, 30040, 0), (21, 1, 2, 20001, 0),
            (27, 2, 2, 20000, 1), (28, 2, 2, 20000, 2)):
        rows.append(dict(id=ident, variant=variant, kind=kind, map_id=scene,
            npc_id=npc, name='測試副本 %s/%s' % (ident, variant),
            min_members=6 if ident in (7,16) else 2, max_members=4 if kind==2 else (12 if ident==7 else 6),
            min_level=10, time_minutes=15, room_count=10, is_open=None,
            awards=[[1,10,100,5]], creation_supported=kind in (1,2), catalog_key='test-catalog'))
    return dict(catalog_key='test-catalog', records=rows, source='synthetic_test',
                counts={'dungeon_records':len(rows)})


def install():
    mocked=patch('wlre.services.instance_browser.official_catalog', side_effect=catalog)
    mocked.start()
    unittest.addModuleCleanup(mocked.stop)


def fields(ident=1, variant=0):
    return dict(catalog_key='test-catalog', catalog_id=ident, catalog_variant=variant)
