"""1262 game bundle extraction: static dungeon names and rewards."""
import unittest

from wlre.services.instance_browser import official_catalog, entries_for
from unittest.mock import patch

# Historical bundled 1262 fixture stays testable; actual runtime defaults to 1275.
_legacy_patch = None

def setUpModule():
    global _legacy_patch
    _legacy_patch = patch('wlre.services.world.runtime_1275.baseline_revision',
                          return_value='1262')
    _legacy_patch.start()
    official_catalog.cache_clear()

def tearDownModule():
    official_catalog.cache_clear()
    _legacy_patch.stop()


class OfficialInstanceCatalog(unittest.TestCase):
    def test_all_verified_records_loaded(self):
        value = official_catalog()
        self.assertEqual(value["version"], 1262)
        self.assertEqual(value["counts"]["scenes"], 1336)
        self.assertEqual(value["counts"]["traditional_chinese_texts"], 39901)
        self.assertEqual(len(entries_for("main")), 27)
        self.assertEqual(len(entries_for("coop")), 3)
        self.assertEqual(len({x["id"] for x in value["records"]}), 24)

    def test_difficulty_variants_do_not_overwrite_each_other(self):
        rows = [x for x in entries_for("main") if x["id"] == 16]
        self.assertEqual(sorted(x["variant"] for x in rows), [1, 2])
        self.assertEqual({x["name"] for x in rows}, {"本能寺之變"})
        self.assertEqual({x["map_id"] for x in rows}, {30010, 30042})

    def test_coop_title_uses_activity_text_not_shared_scene(self):
        titles = {x["name"] for x in entries_for("coop")}
        self.assertEqual(titles, {"協力對戰", "黑薔薇之影", "萬聖鬼武來襲"})
        for row in entries_for("coop"):
            self.assertNotEqual(row["name"], "麥哲倫艦隊")
            self.assertTrue(row["is_open"])  # static stage flag, not live room availability

    def test_rewards_are_official_slot_tuples(self):
        row = next(x for x in entries_for("main") if x["id"] == 1)
        self.assertEqual(row["awards"], [[1, 10, 63002, 5], [2, 10, 57270, 1]])
        row = next(x for x in entries_for("main") if x["id"] == 20 and x["variant"] == 1)
        self.assertEqual(len(row["awards"]), 15)
        self.assertEqual(row["awards"][0], [1, 10, 63002, 65])
