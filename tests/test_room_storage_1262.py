"""1262 Lua regression tests for read-only room storage.

Derived from:
  Logic/Protocols/Protocols_062.lua
  Logic/RoomStorage.lua
  Data/ItemData.lua (ItemSaveData:New with byte-sized item count)
"""
import unittest

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.items.room_storage import defaults


def u16(value):
    return int(value).to_bytes(2, 'little')


def garage_item(index=3, item_id=34144, count=5):
    # ItemSaveData:New(index, packet, false) reads exactly 64 bytes.
    raw = bytearray(64)
    raw[0:2] = u16(item_id)
    raw[2] = count
    return bytes([index]) + bytes(raw)


def dispatch(state, sub, payload):
    event = decode(Packet(62, sub, payload))
    state.apply(event)
    return event


class RoomStorage1262Tests(unittest.TestCase):
    def setUp(self):
        self.state = State()

    def test_default_independent_containers(self):
        storage = defaults()
        self.assertFalse(storage['garage']['ready'])
        self.assertFalse(storage['materials']['ready'])
        self.assertIsNot(storage['garage']['items'], storage['materials']['items'])

    def test_s62_7_initial_full_item_record(self):
        event = dispatch(self.state, 7, b'\x01' + garage_item())
        self.assertEqual(event['type'], 'storage_garage_initial')
        self.assertTrue(self.state.room_storage['garage']['ready'])
        self.assertEqual(self.state.room_storage['garage']['items']['3']['item_id'], 34144)
        self.assertEqual(self.state.room_storage['garage']['items']['3']['count'], 5)
        self.assertEqual(self.state.inventory['items'], {})

    def test_s62_7_empty_and_batched_snapshots(self):
        dispatch(self.state, 7, b'\x00')
        self.assertTrue(self.state.room_storage['garage']['ready'])
        dispatch(self.state, 7, b'\x01' + garage_item(index=8, count=4))
        self.assertEqual(self.state.room_storage['garage']['items']['8']['count'], 4)

    def test_garage_delta_add_and_subtract(self):
        dispatch(self.state, 7, b'\x01' + garage_item(index=8, count=4))
        dispatch(self.state, 11, garage_item(index=8, count=3))
        self.assertEqual(self.state.room_storage['garage']['items']['8']['count'], 7)
        dispatch(self.state, 13, bytes([8, 2]))
        self.assertEqual(self.state.room_storage['garage']['items']['8']['count'], 5)
        dispatch(self.state, 13, bytes([8, 5]))
        self.assertEqual(self.state.room_storage['garage']['items'], {})

    def test_bad_delete_marks_container_unreliable(self):
        dispatch(self.state, 7, b'\x01' + garage_item(index=8, count=2))
        dispatch(self.state, 13, bytes([8, 3]))
        self.assertFalse(self.state.room_storage['garage']['reliable'])
        self.assertEqual(self.state.room_storage['garage']['items']['8']['count'], 2)

    def test_materials_compact_initial_and_delta(self):
        initial = bytes([1, 1]) + u16(2) + u16(10) + u16(34144) + u16(110) + u16(11) + u16(34026) + u16(20)
        event = dispatch(self.state, 57, initial)
        self.assertEqual(event['type'], 'storage_materials_initial')
        self.assertTrue(self.state.room_storage['materials']['ready'])
        self.assertEqual(self.state.room_storage['materials']['items']['10']['count'], 110)
        self.assertFalse(self.state.room_storage['garage']['ready'])
        dispatch(self.state, 57, bytes([1, 2]) + u16(10) + u16(34144) + u16(3))
        self.assertEqual(self.state.room_storage['materials']['items']['10']['count'], 113)
        dispatch(self.state, 57, bytes([2]) + u16(10) + u16(13))
        self.assertEqual(self.state.room_storage['materials']['items']['10']['count'], 100)

    def test_storage_parameters_and_move_result(self):
        dispatch(self.state, 72, bytes([90]) + u16(220) + u16(999))
        self.assertEqual(self.state.room_storage['garage']['capacity'], 90)
        self.assertEqual(self.state.room_storage['materials']['capacity'], 220)
        self.assertEqual(self.state.room_storage['material_stack_limit'], 999)
        dispatch(self.state, 73, bytes([91]))
        dispatch(self.state, 74, u16(221))
        dispatch(self.state, 75, u16(1000))
        self.assertEqual(self.state.room_storage['garage']['capacity'], 91)
        self.assertEqual(self.state.room_storage['materials']['capacity'], 221)
        self.assertEqual(self.state.room_storage['material_stack_limit'], 1000)
        dispatch(self.state, 71, bytes([1]))
        self.assertEqual(self.state.room_storage['last_result'], 1)

    def test_storage_error_code(self):
        dispatch(self.state, 25, bytes([1, 11]))
        self.assertEqual(self.state.room_storage['last_error'], 11)

    def test_truncated_full_item_rejected(self):
        with self.assertRaises(ProtocolError):
            decode(Packet(62, 7, b'\x01\x03\x11\x22'))

    def test_truncated_materials_count_rejected(self):
        with self.assertRaises(ProtocolError):
            decode(Packet(62, 57, bytes([1, 1]) + u16(2) + u16(10) + u16(34144) + u16(1)))

    def test_duplicated_initial_slots_rejected(self):
        with self.assertRaises(ProtocolError):
            decode(Packet(62, 7, b'\x02' + garage_item(index=3) + garage_item(index=3)))


if __name__ == '__main__':
    unittest.main()
