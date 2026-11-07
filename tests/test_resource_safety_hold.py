"""Session holds stop new work, never undo server-confirmed or in-flight work."""
from copy import deepcopy
from contextlib import ExitStack
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from wlre.core.state import State
from wlre.network.client import SessionLogic, run_client
from wlre.network.resource_safety import command_allowed
from wlre.network.service_scheduler import advance_services
from wlre.network.wire import Packet, ProtocolError, encode


class ResourceSafetyHoldTests(unittest.TestCase):
    def setUp(self):
        self.hold = threading.Event()
        self.logic = SessionLogic(resource_safety_hold=self.hold)
        self.logic.world_acknowledged = True
        self.state = State(phase='world_ready', initial_data_complete=True)
        self.state.player.update(role_id=1, scene=12500)
        self.state.inventory.update(ready=True, reliable=True, capacity=10, revision=1)

    def advance(self):
        sent = []
        advance_services(self.logic, self.state, sent.append, sent.append, lambda e: None, None)
        return sent

    def test_hold_latches_and_cannot_clear_or_enable_the_old_session(self):
        self.hold.set()
        self.assertTrue(self.logic.check_resource_safety(self.state))
        self.hold.clear()
        with patch('wlre.network.client.dispatch') as dispatch:
            for command in ({'type': 'start_auto_battle'},
                            {'type': 'automatic_flows', 'enabled': True},
                            {'type': 'daily_assistant', 'action': 'configure'},
                            {'type': 'select_role', 'index': 1},
                            {'type': 'unknown_future_feature'}):
                with self.subTest(command=command), self.assertRaises(ProtocolError):
                    self.logic.command(command, self.state)
            dispatch.assert_not_called()
        self.assertTrue(self.state.automation['resource_safety_hold'])
        fresh = SessionLogic(resource_safety_hold=threading.Event())
        self.assertFalse(fresh.check_resource_safety(State()))

    def test_stop_allowlist_is_strict_and_preserves_local_controls(self):
        self.hold.set()
        for command in ({'type': 'stop_auto_battle'}, {'type': 'stop_expedition'},
                        {'type': 'stop_alchemy'}, {'type': 'automatic_flows', 'enabled': False},
                        {'type': 'craft', 'action': 'plan_pause'},
                        {'type': 'daily_assistant', 'action': 'stop'}):
            with self.subTest(command=command):
                self.assertEqual(self.logic.command(command, self.state), [])
        self.assertTrue(command_allowed({'type': 'chat'}))
        for command in ({'type': 'time_cube', 'action': 'auto', 'enabled': 0},
                        {'type': 'instance_auto_reward', 'enabled': None},
                        {'type': 'craft', 'action': 'pause'},
                        {'type': 'npc_next'}):
            self.assertFalse(command_allowed(command))

    def test_hold_preserves_pending_reservations_and_budget_evidence(self):
        for name in ('star_ark', 'guild_actions', 'daily_tasks', 'time_cube'):
            getattr(self.state, name).update(pending={'fixture': name}, reserved=17,
                                             confirmed=9, uncertain=True)
        self.logic.crafting.pending = {'action': 'add', 'due': 1234}
        self.state.crafting.update(pending='add', auto_continue=True,
                                    local_plan={'enabled': True, 'rows': []})
        self.logic.expedition.pending = {'due': 1234}
        self.state.expedition.update(enabled=True, pending={'fixture': 'expedition'})
        self.logic.alchemy.pending = {'deadline': 1234}
        self.state.alchemy.update(enabled=True, pending=True)
        self.logic.maintenance.pending = {'due': 1234}
        self.state.maintenance['pending'] = {'fixture': 'repair'}
        self.state.inventory['holds'] = {'fixture': {'1': 2}}
        before = self.state.snapshot()
        pending = [self.logic.crafting.pending, self.logic.expedition.pending,
                   self.logic.alchemy.pending, self.logic.maintenance.pending]
        self.hold.set()
        self.logic.check_resource_safety(self.state)
        for name in ('star_ark', 'guild_actions', 'daily_tasks', 'time_cube'):
            for key in ('pending', 'reserved', 'confirmed', 'uncertain'):
                self.assertEqual(getattr(self.state, name)[key], before[name][key])
        for original, actual in zip(pending, [self.logic.crafting.pending,
                self.logic.expedition.pending, self.logic.alchemy.pending,
                self.logic.maintenance.pending]):
            self.assertIs(actual, original)
        self.assertEqual(self.state.inventory['holds'], before['inventory']['holds'])
        self.assertFalse(self.state.expedition['enabled'])
        self.assertFalse(self.state.alchemy['enabled'])
        self.assertFalse(self.state.crafting['auto_continue'])
        self.assertFalse(self.state.crafting['local_plan']['enabled'])

    def test_hold_stops_every_existing_automatic_intent_without_runtime_invalidation(self):
        self.logic.auto_battle.enabled = True
        self.logic.roaming.enabled = True
        self.logic.movement.active = True
        self.state.expedition['enabled'] = True
        self.state.alchemy['enabled'] = True
        self.state.crafting['auto_continue'] = True
        self.state.instances['coop']['auto_claim_enabled'] = True
        self.hold.set()
        with (patch('wlre.services.world.dynamic_bundle_runtime.invalidate_runtime') as invalidate,
              patch('wlre.services.world.dynamic_bundle_runtime.activate_for_official') as activate):
            self.assertEqual(self.advance(), [])
        invalidate.assert_not_called()
        activate.assert_not_called()
        self.assertFalse(self.logic.auto_battle.enabled)
        self.assertFalse(self.logic.roaming.enabled)
        self.assertFalse(self.logic.movement.active)
        for name in ('time_cube', 'daily_tasks', 'star_ark'):
            self.assertFalse(getattr(self.state, name)['enabled'])
        self.assertFalse(self.state.guild_actions['donate_enabled'])
        self.assertFalse(self.state.instances['coop']['auto_claim_enabled'])

    def test_hold_between_service_ticks_finishes_only_the_started_batch(self):
        first, second, forbidden = Packet(99, 1), Packet(99, 2), Packet(99, 3)
        self.state.expedition['enabled'] = True
        sent = []
        def send(packet):
            sent.append(packet)
            self.hold.set()  # Another thread can signal during this in-flight batch.
        with (patch.object(self.logic.maintenance, 'tick', return_value=[first, second]),
              patch.object(self.logic.expedition, 'tick', return_value=[forbidden]) as later_tick):
            advance_services(self.logic, self.state, send, send, lambda e: None, None)
        self.assertEqual(sent, [first, second])
        later_tick.assert_not_called()
        self.assertTrue(self.logic.resource_safety_held)
        self.assertFalse(self.state.expedition['enabled'])

    def test_latched_hold_gates_every_producer_even_if_flags_are_reenabled(self):
        self.hold.set()
        self.logic.check_resource_safety(self.state)
        self.hold.clear()
        # Incoming role data resets several per-role defaults. Even incorrect
        # later local flags must not make a held session dispatch new work.
        self.state.apply({'type': 'world_player', 'player': {
            'role_id': 2, 'scene': 12500, 'x': 0, 'y': 0}})
        self.state.phase = 'world_ready'
        self.state.automation['enabled'] = True
        for name in ('expedition', 'alchemy', 'time_cube', 'daily_tasks', 'star_ark'):
            getattr(self.state, name)['enabled'] = True
        self.state.guild_actions.update(sign_enabled=True, donate_enabled=True)
        self.state.crafting.update(auto_continue=True,
                                   local_plan={'enabled': True, 'rows': []})
        self.state.instances['coop']['auto_claim_enabled'] = True
        for name in ('auto_battle', 'roaming'):
            getattr(self.logic, name).enabled = True
        self.logic.movement.active = True
        mocks = []
        with ExitStack() as stack:
            for name in ('maintenance', 'expedition', 'crafting', 'auto_battle',
                         'alchemy', 'roaming', 'movement', 'portal_travel', 'flows'):
                mocks.append(stack.enter_context(patch.object(
                    getattr(self.logic, name), 'tick', return_value=[Packet(99, 1)])))
            for target in ('wlre.network.service_scheduler.tick_instance_rewards',
                           'wlre.services.time_cube.tick', 'wlre.services.daily_tasks.tick',
                           'wlre.services.social.guild_actions.tick', 'wlre.services.star_ark.tick'):
                mocks.append(stack.enter_context(patch(target, return_value=[Packet(99, 1)])))
            self.assertEqual(self.advance(), [])
        for mocked in mocks:
            mocked.assert_not_called()

    def test_crafting_pending_timeout_keeps_uncertain_material_hold_without_retry(self):
        from wlre.services.items import reservations
        self.state.inventory['items']['1'] = {'item_id': 10, 'serial': 1, 'count': 2}
        reservations.acquire(self.state.inventory, 'crafting', [{'index': 1, 'count': 1}])
        self.logic.crafting._set_pending(self.state, 'add', -100)
        self.hold.set()
        self.logic.check_resource_safety(self.state)
        self.state.crafting.update(auto_continue=True,
                                   local_plan={'enabled': True, 'rows': [{'item_id': 10, 'count': 1}]})
        with patch.object(self.logic.crafting, 'tick') as plan_tick:
            self.assertEqual(self.advance(), [])
            self.assertEqual(self.advance(), [])
        plan_tick.assert_not_called()
        self.assertIsNone(self.logic.crafting.pending)
        self.assertTrue(self.state.crafting['uncertain'])
        self.assertTrue(self.state.inventory['holds']['crafting'][0]['uncertain'])

    def test_crafting_inbound_confirmation_is_processed_but_never_starts_next_plan(self):
        self.logic.crafting._set_pending(self.state, 'start', 10**12)
        self.hold.set()
        event = {'type': 'craft_started', 'index': 1}
        self.state.apply(event)
        self.logic.receive(event, self.state)
        self.assertIsNone(self.logic.crafting.pending)
        self.state.crafting['auto_continue'] = True
        self.logic.crafting.plan(self.state)['enabled'] = True
        with patch.object(self.logic.crafting, 'tick') as plan_tick:
            self.assertEqual(self.advance(), [])
        plan_tick.assert_not_called()

    def test_pending_repair_accepts_both_acks_then_stops_before_cleanup(self):
        from test_post_battle_maintenance import MaintenanceFlow
        fixture = MaintenanceFlow()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.logic, self.state = fixture.logic, fixture.state
        self.logic.resource_safety_hold = self.hold
        synthetic = {'items': {'22001': {'special': 0, 'fit_type': 1},
                               '34104': {'kind': 25, 'special': 130},
                               '32001': {'restrict': 0}}}
        for module in ('maintenance', 'post_battle_maintenance'):
            self.enterContext(patch('wlre.services.items.' + module + '.CAT', synthetic))
        self.assertEqual(len(fixture.begin()), 1)
        self.logic.maintenance.pending['due'] = 10**12
        self.hold.set()
        self.assertEqual(self.advance(), [])
        self.assertIsNotNone(self.logic.maintenance.pending)
        fixture.event(fixture.damage(2, 1, 0))
        fixture.event(fixture.damage(1, 1, 25))
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.logic.maintenance.pending)
        self.assertEqual(self.state.maintenance['completed'], 1)
        self.assertNotIn('maintenance', self.state.inventory['holds'])
        self.logic.auto_battle.enabled = True
        self.assertEqual(self.advance(), [])
        self.assertIn('2', self.state.inventory['items'])  # No follow-on sale.

    def test_pending_ark_known_answer_is_not_sent_even_after_flags_reenabled(self):
        from test_star_ark import StarArkTests
        fixture = StarArkTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.confirm_question()
        fixture.open_question(event_id=3, now=4)
        self.logic, self.state = fixture.logic, fixture.state
        self.logic.resource_safety_hold = self.hold
        pending = self.state.star_ark['pending']
        pending['due'] = 10**12
        self.assertEqual(self.state.star_ark['question']['known_answer'], 22)
        self.hold.set()
        self.logic.check_resource_safety(self.state)
        self.state.star_ark.update(enabled=True, questions_enabled=True)
        self.state.automation['enabled'] = True
        self.hold.clear()
        with patch('wlre.services.star_ark.command') as answer:
            self.assertEqual(self.advance(), [])
        answer.assert_not_called()
        self.assertIs(self.state.star_ark['pending'], pending)
        self.assertIsNone(self.state.star_ark['question']['selected'])
        pending['due'] = 0
        self.assertEqual(self.advance(), [])
        self.assertTrue(self.state.star_ark['uncertain'])

    def test_expedition_and_alchemy_timeouts_stay_uncertain_without_resend(self):
        self.logic.expedition.pending = {'due': 0, 'kind': 'dispatch'}
        self.state.expedition['pending'] = {'kind': 'dispatch'}
        self.logic.alchemy.pending = {'deadline': 0, 'consumption': [],
                                     'deleted': {}, 'result': None}
        self.state.alchemy['pending'] = True
        self.hold.set()
        for _ in range(2):
            self.assertEqual(self.advance(), [])
        self.assertTrue(self.state.expedition['uncertain'])
        self.assertIsNotNone(self.logic.expedition.pending)
        self.assertIsNone(self.logic.alchemy.pending)
        self.assertIn('逾時', self.state.alchemy['status'])
        self.assertFalse(self.state.inventory['reliable'])

    def test_pending_guild_payment_remains_accounted_after_hold(self):
        from test_guild_actions import GuildActionsTests
        from wlre.services.social import guild_actions
        fixture = GuildActionsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.logic, self.state = fixture.logic, fixture.state
        self.logic.resource_safety_hold = self.hold
        self.assertEqual(guild_actions.begin(self.state, 'donate', True),
                         [Packet(10, 5, b'\x08\x00')])
        self.hold.set()
        self.assertEqual(self.advance(), [])
        self.assertEqual(self.state.guild_actions['reserved'], 150)
        self.assertIsNotNone(self.state.guild_actions['pending'])
        fixture.pay(4)
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.state.guild_actions['pending'])
        self.assertEqual(self.state.guild_actions['confirmed'], 150)
        self.assertEqual(self.state.gold['amount'], 850)
        self.state.guild_actions['donate_enabled'] = True
        self.state.automation['enabled'] = True
        self.assertEqual(self.advance(), [])

    def test_pending_daily_claim_settles_without_claiming_the_next_reward(self):
        from test_daily_task_runtime import DailyRuntimeTests, marks, notice
        from wlre.services import daily_tasks
        fixture = DailyRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.logic, self.state = fixture.logic, fixture.state
        self.logic.resource_safety_hold = self.hold
        self.assertEqual(daily_tasks.tick(self.state, True), [Packet(124, 1, b'\xc8\x00')])
        self.hold.set()
        fixture.feed(marks(day=1))
        self.assertEqual(self.advance(), [])
        self.assertIsNotNone(self.state.daily_tasks['pending'])
        fixture.feed(notice())
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.state.daily_tasks['pending'])
        self.assertFalse(self.state.daily_tasks['uncertain'])
        self.state.daily_tasks['enabled'] = True
        self.state.automation['enabled'] = True
        self.assertEqual(self.advance(), [])

    def test_pending_cube_receives_both_confirmations_while_held_without_new_claim(self):
        self.state.time_cube.update(ready=True, count=1, role_id=1)
        self.assertEqual(self.logic.command({'type': 'time_cube', 'action': 'open'}, self.state),
                         [Packet(122, 2)])
        pending = deepcopy(self.state.time_cube['pending'])
        self.hold.set()
        self.assertEqual(self.advance(), [])
        self.assertEqual(self.state.time_cube['pending'], pending)
        for event in ({'type': 'cube_info', 'kind': 1, 'count': 0,
                       'check_minutes': 0, 'keep_minutes': 0},
                      {'type': 'bag_snapshot', 'capacity': 10,
                       'items': [{'index': 1, 'item_id': 100, 'count': 1}]}):
            self.state.apply(event)
            self.logic.receive(event, self.state)
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.state.time_cube['pending'])
        self.assertFalse(self.state.time_cube['uncertain'])
        self.state.time_cube['count'] = 1
        self.hold.clear()
        self.assertEqual(self.advance(), [])

    def test_pending_timeout_remains_uncertain_without_retry(self):
        self.state.time_cube.update(ready=True, count=1, role_id=1)
        self.logic.command({'type': 'time_cube', 'action': 'open'}, self.state)
        self.state.time_cube['pending']['due'] = 0
        self.hold.set()
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.state.time_cube['pending'])
        self.assertTrue(self.state.time_cube['uncertain'])
        self.assertEqual(self.advance(), [])

    def test_held_inbound_keeps_protocol_sync_but_not_role_or_script_actions(self):
        self.hold.set()
        self.logic.role_index = 1
        self.assertEqual(self.logic.receive({'type': 'heartbeat_request'}, self.state),
                         [Packet(63, 5)])
        with patch.object(self.logic, 'command') as command:
            self.logic.receive({'type': 'role_list_available'}, self.state)
            command.assert_not_called()
        self.logic.world_acknowledged = False
        self.assertEqual(self.logic.receive({'type': 'fixture'}, self.state),
                         [Packet(12, 1), Packet(3, 2)])
        self.state.expedition.update(ready=True, outpost_ready=True)
        self.assertEqual(self.logic.receive({'type': 'fixture'}, self.state), [Packet(31, 28)])
        self.assertEqual(self.logic.receive({'type': 'fixture'}, self.state), [])
        self.logic.receive({'type': 'event_continue_permission'}, self.state)
        self.assertTrue(self.logic.pending_event)
        with patch('wlre.network.client.flush_npc_choice') as choice:
            self.assertEqual(self.logic.flush_events(self.state), [])
            choice.assert_not_called()
        self.logic.receive({'type': 'event_end'}, self.state)
        self.assertFalse(self.logic.pending_event)

    def test_sent_portal_wait_is_not_canceled_by_hold(self):
        self.logic.portal_travel.pending = {'id': 9, 'role_id': 1, 'scene': 12500,
                                           'destination': 12600}
        self.logic.portal_travel.deadline = 10**12
        self.state.portal_travel.update(status='awaiting_map')
        self.state.event_flow.update(blocked=True, awaiting_response=True)
        self.logic.portal_travel.request_flow = self.state.event_flow
        original = self.logic.portal_travel.pending
        self.hold.set()
        self.assertEqual(self.advance(), [])
        self.assertIs(self.logic.portal_travel.pending, original)
        self.assertTrue(self.state.event_flow['awaiting_response'])
        self.logic.portal_travel.deadline = 0
        self.assertEqual(self.advance(), [])
        self.assertIsNone(self.logic.portal_travel.pending)
        self.assertEqual(self.state.portal_travel['status'], 'timeout')
        self.assertEqual(self.advance(), [])

    def test_hold_notification_is_once_and_no_worker_mutates_ui(self):
        signaller = threading.Thread(target=self.hold.set)
        signaller.start(); signaller.join()
        events = []
        for _ in range(3):
            self.logic.publish_resource_safety(self.state, events.append, None)
        self.assertEqual([e['type'] for e in events], ['resource_safety_hold'])
        self.assertEqual(self.state.phase, 'world_ready')


class ResourceHoldRunLoopTests(unittest.TestCase):
    profile = {'rx_xor': 0, 'tx_xor': 0, 'platform': 3, 'language': 0,
               'verification_endpoint': {'host': 'fixture.invalid', 'port': 1}}

    def connection(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.recv.return_value = b''
        return connection

    def test_hold_before_connect_or_after_account_verify_sends_no_new_login(self):
        for during_verify in (False, True):
            hold = threading.Event()
            if not during_verify:
                hold.set()
            with (patch('wlre.network.client.socket.create_connection') as socket,
                  patch('wlre.network.client.verify_account', side_effect=lambda *a: hold.set()) as verify):
                run_client('fixture.invalid', 1, self.profile, lambda e: None,
                           account='fixture', password='fixture', verify_first=True,
                           resource_safety_hold=hold)
            socket.assert_not_called()
            self.assertEqual(verify.call_count, int(during_verify))

    def test_queued_command_after_hold_is_rejected_not_sent_or_falsely_pending(self):
        hold = threading.Event()
        commands = queue.Queue()
        commands.put({'type': 'first'})
        commands.put({'type': 'later'})
        connection = self.connection()
        calls, events = [], []
        first_batch = [Packet(99, 1), Packet(99, 2)]
        def dispatch(logic, command, state):
            calls.append(command['type'])
            return first_batch if command['type'] == 'first' else [Packet(99, 3)]
        def emit(event):
            events.append(event)
            if event['type'] == 'sent':
                hold.set()
        with (patch('wlre.network.client.socket.create_connection', return_value=connection),
              patch('wlre.network.client.dispatch', side_effect=dispatch)):
            run_client('fixture.invalid', 1, self.profile, emit, commands=commands,
                       resource_safety_hold=hold)
        self.assertEqual(calls, ['first'])
        self.assertEqual([c.args[0] for c in connection.sendall.call_args_list],
                         [encode(p, 0) for p in first_batch])
        self.assertEqual([e['command_type'] for e in events if e['type'] == 'command_rejected'], ['later'])

    def test_held_connection_still_receives_and_replies_heartbeat_until_explicit_close(self):
        hold, stop = threading.Event(), threading.Event()
        connection = self.connection()
        receives = [encode(Packet(1, 23), 0), b'']
        events = []
        def recv(_):
            hold.set()
            return receives.pop(0)
        connection.recv.side_effect = recv
        def emit(event):
            events.append(event)
            if event.get('type') == 'sent' and (event.get('main'), event.get('sub')) == (63, 5):
                stop.set()
        with patch('wlre.network.client.socket.create_connection', return_value=connection):
            result = run_client('fixture.invalid', 1, self.profile, emit,
                                account='fixture', password='fixture', duration=None,
                                stop_event=stop, resource_safety_hold=hold)
        self.assertIn(encode(Packet(63, 5), 0), [c.args[0] for c in connection.sendall.call_args_list])
        self.assertEqual(result.phase, 'disconnected')
        self.assertEqual([e['reason'] for e in events if e['type'] == 'connection_closed'], ['stopped'])
        self.assertEqual(sum(e['type'] == 'resource_safety_hold' for e in events), 1)
