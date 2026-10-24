"""Co-op named event creation and full-room host standby regression."""
import unittest
from wlre.core.state import State
from wlre.network.client import SessionLogic
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError, Writer
from wlre.services.instance_creation import expire


def setup():
    state = State(phase='world_ready', initial_data_complete=True)
    state.player = {'role_id': 678}
    logic = SessionLogic()
    logic.world_acknowledged = True
    return state, logic


def create(logic, state, activity=28):
    return logic.command({'type': 'instance_create', 'mode': 'coop',
        'dungeon_id': activity, 'player_count': 2, 'public': True,
        'password': '', 'confirm_cost': True}, state)


def roster(kind=2, npc=2, host=678, other=889, created=False):
    w = Writer().u8(int(created)).u8(0).u16(91).u8(0).u8(kind).u8(npc).u8(2)
    for role in (host, other):
        w.u32(role).u8(1 if role else 0)
        for value in (100, 100, 40, 40):
            w.u32(value if role else 0)
    return decode(Packet(186, 3, w.build()))


def ready(logic, state):
    return logic.command({'type': 'instance_coop_standby',
                          'mode': 'coop', 'standby': True}, state)


class CooperativeRoomRecovery(unittest.TestCase):
    def test_three_official_activities_allow_host_to_start(self):
        for activity, kind, npc in ((21, 1, 0), (27, 2, 1), (28, 2, 2)):
            with self.subTest(activity=activity):
                state, logic = setup()
                create(logic, state, activity)
                data = state.instances['coop']
                self.assertEqual(data['create_pending']['npc_id'], npc)
                state.apply(decode(Packet(186, 2, b'\x09')))
                self.assertIsNotNone(data['create_pending'])
                state.apply(roster(kind, npc, created=True))
                self.assertIsNone(data['create_pending'])
                self.assertFalse(data['create_uncertain'])
                self.assertEqual(data['room']['host_id'], 678)
                self.assertEqual(ready(logic, state),
                                 [Packet(186, 7, Writer().u16(91).u8(1).build())])

    def test_late_roster_reconciles_only_matching_host(self):
        state, logic = setup()
        self.assertEqual(len(create(logic, state)), 1)
        data = state.instances['coop']
        self.assertTrue(expire(state, data['create_pending']['started'] + 20))
        self.assertTrue(data['create_uncertain'])
        self.assertRaises(ProtocolError, create, logic, state)
        state.apply(decode(Packet(186, 2, b'\x09')))
        state.apply(roster(npc=1))
        state.apply(roster(host=889, other=678))
        self.assertTrue(data['create_uncertain'])
        # A later S186-3 member-refresh can supply the missing strong proof.
        state.apply(roster(created=False))
        self.assertFalse(data['create_uncertain'])
        self.assertIsNone(data['create_attempt'])
        self.assertEqual(len(ready(logic, state)), 1)

    def test_wrong_activity_or_nonhost_never_unlocks(self):
        for event in (roster(npc=0), roster(host=889, other=678),
                      roster(host=0, other=678)):
            state, logic = setup()
            create(logic, state)
            state.apply(event)
            self.assertIsNotNone(state.instances['coop']['create_pending'])
            self.assertRaises(ProtocolError, ready, logic, state)

    def test_guest_cannot_start_full_room(self):
        state, logic = setup()
        state.apply(roster(host=889, other=678))
        with self.assertRaisesRegex(ProtocolError, '房主'):
            ready(logic, state)


if __name__ == '__main__':
    unittest.main()


# 1262 historical packet/layout fixtures. Never enable these fixture indices in
# production 1275; tests explicitly select their original source baseline.
from unittest.mock import patch as _legacy_baseline_patch
_legacy_baseline_context = None

def setUpModule():
    global _legacy_baseline_context
    _legacy_baseline_context = _legacy_baseline_patch(
        'wlre.services.world.runtime_1275.baseline_revision', return_value='1262')
    _legacy_baseline_context.start()
    from wlre.services.instance_browser import official_catalog
    official_catalog.cache_clear()

def tearDownModule():
    from wlre.services.instance_browser import official_catalog
    official_catalog.cache_clear()
    _legacy_baseline_context.stop()
