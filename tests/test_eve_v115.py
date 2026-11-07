"""Synthetic v115 samples following EventData.lua layout (no real game bytes)."""
import json
import struct
import unittest
from unittest.mock import patch
from wlre.services.world import eve_v115
from wlre.services.world.eve_v115 import derive_eve_index, derive_eve_indexes, EveDecodeError


def u16(n):return struct.pack('<H',n)
def u32(n):return struct.pack('<I',n)


def fixture(*, npc_count=1, interact_count=1):
    npc = (u16(3) + bytes(20) + b'\x05' + u32(20) + u32(42) + b'\x01\x07'
           + b'\x00' + b'\x01' + u32(9001) + bytes(3) + b'\x00' + bytes(13)
           + b'\x00' + bytes(2+2+4+1+4+2+2+1+20))
    interact = (u16(8) + bytes(20) + b'\x03' + u16(1) + b'\x01'
                + b'\x01' + u16(3874) + b'\x02' + b'\x03')
    sections = [u16(npc_count) + b''.join(
        u16(3 + index) + npc[2:] for index in range(npc_count))]
    sections += [u16(0)] * 6  # door mine goods event group convey
    sections += [u16(interact_count) + b''.join(
        u16(8 + index) + interact[2:] for index in range(interact_count)),
        u16(0), u16(0), u16(0)]
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
    def test_combined_indexes_match_both_single_results_with_one_scene_pass(self):
        raw = fixture()
        with patch.object(eve_v115, '_scene', wraps=eve_v115._scene) as scene:
            expected = {source: derive_eve_index(raw, source) for source in (
                'EventData.NewNpc', 'EventData.NewInteract')}
            self.assertEqual(scene.call_count, 2)
            scene.reset_mock()
            self.assertEqual(derive_eve_indexes(raw), expected)
            self.assertEqual(scene.call_count, 1)

    def test_combined_record_limits_remain_independent(self):
        with patch.object(eve_v115, 'MAX_RECORDS', 1):
            # A limit of one permits one NPC AND one interaction, not one total.
            self.assertEqual(len(derive_eve_indexes(fixture())), 2)
            for raw, selected, other in (
                (fixture(npc_count=2), 'EventData.NewNpc', 'EventData.NewInteract'),
                (fixture(interact_count=2), 'EventData.NewInteract', 'EventData.NewNpc'),
            ):
                with self.subTest(source=selected):
                    self.assertEqual(json.loads(derive_eve_index(raw, other))['record_count'], 1)
                    with self.assertRaisesRegex(EveDecodeError, 'exceeds record limit'):
                        derive_eve_index(raw, selected)
                    with self.assertRaisesRegex(EveDecodeError, 'exceeds record limit'):
                        derive_eve_indexes(raw)

    def test_combined_indexes_validate_all_scenes_and_preserve_order(self):
        body = fixture()[24:]
        # Header order differs from both the byte order and numeric scene order.
        raw = (bytes(8) + u32(2)
               + struct.pack('<HHII', 900, 123, 36 + len(body), len(body))
               + struct.pack('<HHII', 100, 123, 36, len(body)) + body + body)
        expected = {source: derive_eve_index(raw, source) for source in (
            'EventData.NewNpc', 'EventData.NewInteract')}
        with patch.object(eve_v115, '_scene', wraps=eve_v115._scene) as scene:
            combined = derive_eve_indexes(raw)
        self.assertEqual(combined, expected)
        self.assertEqual(scene.call_count, 2)
        for payload in combined.values():
            document = json.loads(payload)
            self.assertEqual(document['record_count'], 2)
            self.assertEqual(list(document['scenes']), ['100', '900'])
        # Overlap is still rejected even though both indexes share one walk.
        damaged = bytearray(raw)
        damaged[16:20] = u32(36)
        with self.assertRaisesRegex(EveDecodeError, 'segments overlap'):
            derive_eve_indexes(bytes(damaged))

    def test_combined_keeps_malformed_source_errors_and_full_scene_validation(self):
        base = fixture()
        malformed = [b'', bytes(12), base[:-1]]
        raw = bytearray(base)
        raw[26:28] = u16(116)
        malformed.append(bytes(raw))
        raw = bytearray(base)
        raw[20:24] = u32(999999)
        malformed.append(bytes(raw))
        raw = bytearray(base + b'\x00')
        raw[20:24] = u32(len(raw) - 24)
        malformed.append(bytes(raw))
        raw = bytearray(base)
        raw[-44:-40] = u32(5)
        malformed.append(bytes(raw))
        raw = bytearray(base[:-44])
        raw[20:24] = u32(len(raw) - 24)
        malformed.append(bytes(raw))
        # Both APIs must still validate the interaction section for NPC output.
        offsets = struct.unpack_from('<11I', base, len(base) - 44)
        raw = bytearray(base)
        raw[24 + offsets[7] + 2 + 2 + 20] = 4
        malformed.append(bytes(raw))
        # Duplicate indexes remain invalid for both decoded section types.
        for raw, section in ((fixture(npc_count=2), 0),
                             (fixture(interact_count=2), 7)):
            raw = bytearray(raw)
            offsets = struct.unpack_from('<11I', raw, len(raw) - 44)
            start = 24 + offsets[section] + 2
            width = (offsets[section + 1] - offsets[section] - 2) // 2
            raw[start + width:start + width + 2] = raw[start:start + 2]
            malformed.append(bytes(raw))
        for index, raw in enumerate(malformed):
            with self.subTest(case=index):
                with self.assertRaises(EveDecodeError) as single:
                    derive_eve_index(raw, 'EventData.NewNpc')
                with self.assertRaises(EveDecodeError) as combined:
                    derive_eve_indexes(raw)
                self.assertEqual(str(combined.exception), str(single.exception))

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
