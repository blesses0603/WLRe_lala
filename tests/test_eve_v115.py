"""Synthetic v115 samples following EventData.lua layout (no real game bytes)."""
import json
import struct
import unittest
from wlre.services.world.eve_v115 import derive_eve_index, EveDecodeError


def u16(n):return struct.pack('<H',n)
def u32(n):return struct.pack('<I',n)


def fixture():
    npc = (u16(3) + bytes(20) + b'\x05' + u32(20) + u32(42) + b'\x01\x07'
           + b'\x00' + b'\x01' + u32(9001) + bytes(3) + b'\x00' + bytes(13)
           + b'\x00' + bytes(2+2+4+1+4+2+2+1+20))
    interact = (u16(8) + bytes(20) + b'\x03' + u16(1) + b'\x01'
                + b'\x01' + u16(3874) + b'\x02' + b'\x03')
    sections = [u16(1) + npc]
    sections += [u16(0)] * 6  # door mine goods event group convey
    sections += [u16(1) + interact, u16(0), u16(0), u16(0)]
    # Real 1275 Eve v115 scenes end with 11 LE UInt32 offsets pointing at
    # section count headers, measured from the beginning of the scene.
    offsets = []
    length = 4
    for section in sections:
        offsets.append(length)
        length += len(section)
    assert len(offsets) == 11
    scene = (u16(123) + u16(115) + b''.join(sections) +
             b''.join(u32(value) for value in offsets))
    header = bytes(8) + u32(1) + struct.pack('<HHII', 500, 123, 24, len(scene))
    return header + scene


class EveTests(unittest.TestCase):
    def test_derive_npc_and_shop_index(self):
        blob = fixture()
        npc = json.loads(derive_eve_index(blob, 'EventData.NewNpc'))
        shops = json.loads(derive_eve_index(blob, 'EventData.NewInteract'))
        self.assertEqual(npc['record_count'], 1)
        self.assertEqual(npc['scenes']['500'][0]['npc_id'], 9001)
        self.assertEqual(npc['scenes']['500'][0]['event_ids'], [7])
        self.assertEqual(shops['record_count'], 1)
        self.assertEqual(shops['scenes']['500'][0]['items'][0]['text_id'], 3874)
        self.assertEqual(derive_eve_index(blob,'EventData.NewNpc'),
                         derive_eve_index(blob,'EventData.NewNpc'))

    def test_reject_unknown_revision(self):
        raw=bytearray(fixture());raw[26:28]=u16(116)
        with self.assertRaisesRegex(EveDecodeError, 'Unsupported Eve') as raised:
            derive_eve_index(bytes(raw),'EventData.NewNpc')
        self.assertIn('場景 500', str(raised.exception))
        self.assertIn('偏移 24', str(raised.exception))

    def test_reject_size_and_overlap(self):
        raw=bytearray(fixture());raw[20:24]=u32(999999)
        with self.assertRaises(EveDecodeError):
            derive_eve_index(bytes(raw),'EventData.NewInteract')
        with self.assertRaises(EveDecodeError):
            derive_eve_index(bytes(fixture())[:-1],'EventData.NewNpc')

    def test_trailing_bytes_report_exact_count_and_zero_state(self):
        """Unknown scene suffixes must be diagnosed, never silently skipped."""
        base = fixture()
        scene_size = struct.unpack_from('<I', base, 20)[0]
        for trailer, expected in ((bytes((0, 0)), 'True'),
                                  (bytes((0, 1)), 'False')):
            with self.subTest(trailer=trailer):
                raw = bytearray(base + trailer)
                struct.pack_into('<I', raw, 20, scene_size + len(trailer))
                with self.assertRaises(EveDecodeError) as raised:
                    derive_eve_index(bytes(raw), 'EventData.NewNpc')
                message = str(raised.exception)
                self.assertIn('場景 500', message)
                self.assertIn('剩餘 46 bytes', message)
                self.assertIn('預期 44 bytes', message)
                self.assertIn('npc:1', message)
                self.assertIn('interact:1', message)

    def test_offset_table_rejects_corrupted_section_position(self):
        original = fixture()
        raw = bytearray(original)
        # The first 4-byte slot is NPC section offset; valid value is 4.
        first_slot = len(raw) - 44
        self.assertEqual(raw[first_slot:first_slot+4], u32(4))
        raw[first_slot:first_slot+4] = u32(5)
        with self.assertRaisesRegex(EveDecodeError, 'offset table differs at npc') as raised:
            derive_eve_index(bytes(raw), 'EventData.NewNpc')
        self.assertIn('expected 4, got 5', str(raised.exception))

    def test_table_is_required_not_silently_ignored(self):
        original = fixture()
        raw = bytearray(original[:-44])
        struct.pack_into('<I', raw, 20, len(raw) - 24)
        with self.assertRaisesRegex(EveDecodeError, 'offset table length mismatch'):
            derive_eve_index(bytes(raw), 'EventData.NewNpc')

    def test_record_truncation_identifies_section_and_record(self):
        raw = bytearray(fixture())
        # First NPC event_count field, after scene header and common fields.
        raw[24 + 4 + 2 + 2 + 20 + 1 + 4 + 4] = 255
        with self.assertRaises(EveDecodeError) as raised:
            derive_eve_index(bytes(raw), 'EventData.NewNpc')
        self.assertIn('場景 500', str(raised.exception))
        self.assertIn('npc 第 1/1 筆', str(raised.exception))
        self.assertIn('場景內偏移', str(raised.exception))

    def test_reject_bad_source(self):
        with self.assertRaises(EveDecodeError):
            derive_eve_index(fixture(), 'Other')


if __name__=='__main__':
    unittest.main()
