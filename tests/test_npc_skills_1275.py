"""1275 NPC battle skill slots and anti-legacy source regression."""
import struct
import unittest
from types import SimpleNamespace

from wlre.network.wire import ProtocolError
from wlre.services.items.catalog import CAT
from wlre.services.expedition.data import parse_npcs, activate_1275_npcs


def npc_fixture(npc_id=14230):
    fields = bytearray(203)
    struct.pack_into('<H', fields, 1, npc_id)
    fields[74] = 1
    struct.pack_into('<5H', fields, 75, 25033, 11172, 0, 0, 0)
    fields[106] = 0
    raw = struct.pack('<i', 1)
    for name in ('測試艾琳', 'NPC'):
        encoded = name.encode('utf-16-le')
        raw += struct.pack('<H', len(encoded)) + encoded
    raw += fields
    return raw


class NpcSkills1275Tests(unittest.TestCase):
    def test_exact_five_official_skill_slots_are_read(self):
        npcs = parse_npcs(npc_fixture(), struct.pack('<i', 0))
        self.assertEqual(npcs['14230']['name'], '測試艾琳')
        self.assertEqual(npcs['14230']['element'], 1)
        self.assertEqual(npcs['14230']['skills'], [25033, 11172, 0, 0, 0])

    def test_duplicate_or_truncated_npc_rejected(self):
        raw = npc_fixture()
        with self.assertRaises((ProtocolError, IndexError, ValueError)):
            parse_npcs(raw[:-2], struct.pack('<i', 0))
        # Each record is repeated with its own two names.
        with self.assertRaises((ProtocolError, IndexError, ValueError)):
            parse_npcs(struct.pack('<i', 2) + raw[4:] + raw[4:],
                       struct.pack('<i', 0))

    def test_shared_npc_catalog_switch_stays_in_place(self):
        original = dict(CAT['npcs'])
        ref = CAT['npcs']
        source = {'source_revision': 1275, 'npcs': parse_npcs(
            npc_fixture(), struct.pack('<i', 0))}
        try:
            self.assertEqual(activate_1275_npcs(SimpleNamespace(
                revision=1275, expedition_catalog=source)), 1)
            self.assertIs(CAT['npcs'], ref)
            self.assertEqual(ref['14230']['skills'][1], 11172)
        finally:
            ref.clear(); ref.update(original)

    def test_incomplete_source_cannot_mutate(self):
        original = dict(CAT['npcs'])
        for source in (
            SimpleNamespace(revision=1262, expedition_catalog={}),
            SimpleNamespace(revision=1275, expedition_catalog={
                'source_revision': 1275, 'npcs': {'1': {'skills': []}}}),
        ):
            with self.assertRaises(ValueError):
                activate_1275_npcs(source)
        self.assertEqual(CAT['npcs'], original)


if __name__ == '__main__':
    unittest.main()
