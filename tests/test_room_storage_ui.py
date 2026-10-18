"""Hyperspace UI never misstates unlock or incomplete S62 storage as confirmed."""
import unittest

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet
from wlre.ui.room_storage_status import (
    unlock_message, storage_sync_message, confirmed_view,
)


def u16(n):
    return n.to_bytes(2, 'little')


class RoomStorageStatusTests(unittest.TestCase):
    def test_unlock_item_is_not_unlock_proof(self):
        self.assertIn('尚未同步', unlock_message({'ready': False, 'items': {}}))
        inv = {'ready': True, 'items': {'0': {'item_id': 34977, 'count': 2}}}
        self.assertIn('×2', unlock_message(inv))
        self.assertIn('仍須', unlock_message(inv))
        self.assertIn('不代表尚未啟用', unlock_message({'ready': True, 'items': {}}))

    def test_independent_waiting_and_capacity(self):
        storage = {
            'garage': {'ready': True, 'reliable': True, 'capacity': 90,
                       'items': {'7': {'item_id': 34144, 'count': 2}}},
            'materials': {'ready': False, 'reliable': True, 'items': {}},
        }
        msg = storage_sync_message(storage)
        self.assertIn('已同步 1 / 90 格（唯讀）', msg)
        self.assertIn('雜物櫃：等待初始 S62 同步', msg)
        storage['garage']['reliable'] = False
        self.assertIn('同步異常', storage_sync_message(storage))
        self.assertIn('重新登入', storage_sync_message(storage))

    def test_storage_add_before_initial_remains_hidden(self):
        pending = {'ready': False, 'reliable': True,
                   'items': {'4': {'item_id': 34026, 'count': 3}}}
        shown = confirmed_view(pending)
        self.assertEqual(shown['items'], {})
        self.assertFalse(shown['ready'])
        self.assertIn('4', pending['items'])

    def test_real_s62_room_snapshot_is_independent_of_bag(self):
        state = State()
        record = bytearray(64)
        record[0:2] = u16(34144)
        record[2] = 3
        state.apply(decode(Packet(62, 7, b'\x01\x05' + bytes(record))))
        snap = state.snapshot()
        self.assertTrue(snap['room_storage']['garage']['ready'])
        self.assertEqual(confirmed_view(snap['room_storage']['garage'])['items']['5']['count'], 3)
        self.assertEqual(snap['inventory']['items'], {})
        self.assertIn('已同步 1', storage_sync_message(snap['room_storage']))


if __name__ == '__main__':
    unittest.main()
