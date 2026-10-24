"""Pure 1275 SkillData_C schema and legacy-source isolation tests."""
import struct
import unittest
from types import SimpleNamespace

from wlre.network.wire import ProtocolError
from wlre.services.items.catalog import CAT
from wlre.services.items.skills_1275 import (
    FIELDS, activate_1275_skills, parse_skills_1275)


def sample_skill(**updates):
    row = {"Name": 123456, "ID": 15001, "Key": 901, "LvLimit": 5,
           "Kind": 1, "TargetKind": 0, "WeaponKind1": 1}
    row.update(updates)
    formats = {"u8": "B", "u16": "H", "u32": "I"}
    return b"".join(struct.pack("<" + formats[size], row.get(name, 0))
                    for name, size in FIELDS)


class Skill1275Tests(unittest.TestCase):
    def test_official_lua_layout_decodes_every_record_and_name(self):
        records = parse_skills_1275(struct.pack("<i", 1) + sample_skill(),
                                    {123456: "新版測試技能"})
        self.assertEqual(records["source_revision"], 1275)
        self.assertEqual(records["skills"]["15001"]["name"], "新版測試技能")
        self.assertEqual(records["skills"]["15001"]["WeaponKind1"], 1)
        self.assertEqual(records["keys"]["901"], 15001)

    def test_truncated_or_duplicate_records_rejected(self):
        sample = sample_skill()
        with self.assertRaises((ProtocolError, IndexError, ValueError)):
            parse_skills_1275(struct.pack("<i", 1) + sample[:-1], {})
        with self.assertRaises(ProtocolError):
            parse_skills_1275(struct.pack("<i", 2) + sample + sample, {})
        with self.assertRaises(ProtocolError):
            parse_skills_1275(struct.pack("<i", 1) + sample + b"x", {})

    def test_shared_catalog_swap_stays_in_place(self):
        records = parse_skills_1275(struct.pack("<i", 1) + sample_skill(), {})
        previous_skills, previous_keys = dict(CAT["skills"]), dict(CAT["keys"])
        ref, key_ref = CAT["skills"], CAT["keys"]
        try:
            self.assertEqual(activate_1275_skills(SimpleNamespace(
                revision=1275, skill_catalog=records)), 1)
            self.assertIs(CAT["skills"], ref)
            self.assertIs(CAT["keys"], key_ref)
            self.assertEqual(CAT["skills"]["15001"]["ID"], 15001)
        finally:
            ref.clear(); ref.update(previous_skills)
            key_ref.clear(); key_ref.update(previous_keys)

    def test_bad_source_cannot_overwrite_current_catalog(self):
        snapshot = dict(CAT["skills"])
        with self.assertRaises(ValueError):
            activate_1275_skills(SimpleNamespace(
                revision=1262, skill_catalog={}))
        self.assertEqual(CAT["skills"], snapshot)


if __name__ == "__main__":
    unittest.main()
