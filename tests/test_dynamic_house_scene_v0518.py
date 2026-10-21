"""動態住宅 63501～65500 進入確認／地圖訊息回歸測試。"""
import struct
import unittest

from wlre.core.state import State
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.world.map_names import map_label
from wlre.services.world.tent import (
    HOUSE_SCENE_MIN, HOUSE_SCENE_MAX, activity_text, command,
    is_dynamic_house_scene, is_house_scene,
)
from wlre.ui.overview_ui import summarize


def camp(owner=91):
    return struct.pack('<IHIIBB', owner, 3, 150, 220, 1, 0)


def world(scene=12170):
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 91, 'name': '測試角色',
                    'scene': scene, 'x': 1000, 'y': 2600}
    return state


def receive(state, packet):
    event = decode(packet, state.player.get('role_id'))
    state.apply(event)
    return event


def change_scene(state, scene):
    receive(state, Packet(12, 1, struct.pack('<IHHH', 91, scene, 1000, 2600)))


def own_furniture(state, owner=91):
    receive(state, Packet(62, 4, struct.pack('<I', owner)))


class DynamicHouseSceneTests(unittest.TestCase):
    def test_exact_official_dynamic_range(self):
        self.assertEqual((HOUSE_SCENE_MIN, HOUSE_SCENE_MAX), (63501, 65500))
        for scene in (63501, 64000, 65500):
            self.assertTrue(is_dynamic_house_scene(scene))
            self.assertTrue(is_house_scene(scene))
            self.assertIn('住宅動態場景', map_label(scene))
        for scene in (63500, 65501, 12170, None):
            self.assertFalse(is_dynamic_house_scene(scene))
        self.assertTrue(is_house_scene(10299))  # 官方住宅基礎模型，不是玩家實例 ID

    def test_enter_house_with_scene_before_furniture(self):
        state = world()
        receive(state, Packet(65, 1, camp()))
        self.assertEqual([(p.main, p.sub) for p in command(state, {'action': 'enter'}, now=1)], [(65, 1)])
        change_scene(state, 63501)
        self.assertFalse(state.tent['inside'])
        self.assertEqual(state.tent['pending']['action'], 'enter')
        own_furniture(state)
        self.assertTrue(state.tent['inside'])
        self.assertFalse(state.tent['uncertain'])
        self.assertIsNone(state.tent['pending'])
        self.assertIn('已進入自家帳篷', summarize(state.snapshot(), True, {})['activity'])

    def test_enter_house_with_furniture_before_scene(self):
        state = world()
        receive(state, Packet(65, 1, camp()))
        command(state, {'action': 'enter'}, now=1)
        own_furniture(state)
        self.assertFalse(state.tent['inside'])
        change_scene(state, 63501)
        self.assertTrue(state.tent['inside'])

    def test_world_login_inside_house_requires_own_furniture(self):
        state = State()
        state.apply({'type': 'world_player', 'player': {
            'role_id': 91, 'scene': 63501, 'x': 1000, 'y': 2600,
            'name': '測試角色',
        }})
        self.assertFalse(state.tent['inside'])
        self.assertIn('等待自家家具', state.tent['status'])
        own_furniture(state, owner=77)
        self.assertFalse(state.tent['inside'])
        own_furniture(state, owner=91)
        self.assertTrue(state.tent['inside'])
        self.assertIsNone(state.tent['pending'])

    def test_house_rejects_tent_deploy_and_pack(self):
        state = world(63501)
        for action in ('open', 'close'):
            with self.subTest(action=action):
                if action == 'close':
                    state.tent['deployed_scene'] = 12170
                with self.assertRaisesRegex(ProtocolError, '小屋內'):
                    command(state, {'action': action}, now=1)

    def test_without_furniture_does_not_claim_enter(self):
        state = world()
        receive(state, Packet(65, 1, camp()))
        command(state, {'action': 'enter'}, now=1)
        change_scene(state, 63501)
        self.assertFalse(state.tent['inside'])
        self.assertIn('等待自家家具', activity_text(state.tent))

    def test_leaving_house_does_not_invent_outdoor_tent(self):
        state = world(63501)
        own_furniture(state)
        self.assertTrue(state.tent['inside'])
        change_scene(state, 12170)
        self.assertFalse(state.tent['inside'])
        self.assertFalse(state.tent['visible'])
        self.assertIn('等待', activity_text(state.tent))

    def test_other_owner_snapshot_does_not_confirm_enter(self):
        state = world()
        receive(state, Packet(65, 1, camp()))
        command(state, {'action': 'enter'}, now=1)
        change_scene(state, 63501)
        own_furniture(state, owner=77)
        self.assertFalse(state.tent['inside'])
        self.assertIsNotNone(state.tent['pending'])


if __name__ == '__main__':
    unittest.main()
