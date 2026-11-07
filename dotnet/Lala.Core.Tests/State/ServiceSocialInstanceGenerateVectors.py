"""Real State.apply oracle for mixed party, instance, tent and prior receive projections.

Every Python observer runs, in its retained order. Only offline catalog projections and
observation time are supplied; no request, tick, send, transport or resource activation.
The projection deliberately excludes player/battle knowledge and equipment mutations.
"""
import copy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

os.environ['WLRE_DISABLE_AUTO_CATALOG'] = '1'
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import wlre.core.state as state_module
from wlre.core.state import State
from wlre.core import inventory_updates
from wlre.services.items import crafting, reservations
from wlre.services.items.live_combat_catalog import _pinned
from wlre.network.protocol import decode
from wlre.network.wire import Packet, ProtocolError
from wlre.services.battle.party import own_team
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TestSupport'))
from gzip_json_fixture import csharp_gzip_json

ORDER = ('apply_daily_tasks', 'apply_cube', 'apply_recovery', 'apply_guild', 'apply_activity',
         'apply_crafting', 'apply_storage', 'apply_live', 'apply_points_event', 'apply_party',
         'apply_expedition', 'apply_instances', 'dispatch_local', 'apply_tent',
         'observe_shop_evidence', 'observe_efficiency', 'apply_actions', 'apply_ark')
ACTIVITIES = {'釣魚': 0, '採集': 1, '跳舞': 2, '馬桶製作': 3, '鍛鍊': 4, '夥伴鍛鍊': 5}
RULES = {'42': True, '43': False, '65535': True}
NPCS = {'1': [1001, 0, 1002, 1001, 0], '2': [0, 1002, 65535]}
CATALOG = dict(items={}, skills={}, keys={}, characters=[], element_weights={},
               npcs={key: {'skills': values} for key, values in NPCS.items()})
RECIPES = [{'recipe_id': 1, 'item_id': 500}, {'recipe_id': 42, 'item_id': 65535}, {'recipe_id': 65535, 'item_id': 500}]


def p(fmt, *values): return struct.pack('<' + fmt, *values)


def text(value):
    raw = value.encode('utf-16le')
    return bytes([len(raw)]) + raw


def world(role=17, scene=101):
    return (p('IBHHHBBBIIBBB', role, 0, scene, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0)
            + text('Synthetic 角色') + bytes(8) + text('') + p('H', 0))


def roster(role=17):
    profile = text('Synthetic 成員') + bytes(15) + b'\0' + bytes(8) + text('') + bytes(8)
    return (text('Synthetic 組織') + text('') + b'\1' + p('I', role) + profile + bytes(13)
            + text('') + bytes(2) + b'\1' + bytes(37) + p('I', 72))


def daily(progress=1, value=40):
    return bytes([value, value] + [progress]*20 + [0]*9 + [1, 0])


def team(index=1, minutes=3): return p('BH4H4HH', index, minutes, 1, 2, 0, 0, 42, 43, 0, 0, 7)


def project_service(state):
    s = state.snapshot()
    session = {k: s[k] for k in ('phase', 'packet_count', 'roles', 'gold', 'event_flow', 'npc_dialogue',
                                'initial_data_complete', 'unimplemented_count', 'attributes')}
    session['npc_dialogue'].setdefault('history', [])
    session['npc_dialogue'].setdefault('choice_continuation_pending', False)
    world = {k: s[k] for k in ('phase', 'packet_count', 'player', 'positions', 'navigation', 'location',
                              'local_movement', 'movement_check')}
    world['player'] = world['player'] or None
    world['positions'] = [dict(role_id=int(k), x=v[0], y=v[1]) for k, v in world['positions'].items()]
    if world['navigation'].get('house_context') is not None:
        world['navigation']['house_context'].setdefault('sizes', {})
    battle = {k: s[k] for k in ('battle', 'battle_units', 'battle_count')}
    battle['unit_order'] = list(s['battle_units'])
    battle['command_order'] = list(s['battle'].get('commands', {}))
    d = s['daily_tasks']
    d['marks'] = dict(daily_value=d['daily_value'] or 0, weekly_value=d['weekly_value'] or 0,
        daily_done=d.pop('daily_done_mark'), daily_reward=d.pop('daily_reward_mark'),
        daily_event_a=d.pop('daily_event_reward_a'), daily_event_b=d.pop('daily_event_reward_b'),
        weekly_done=sum(v << (8*i) for i, v in enumerate(d.pop('weekly_done_mark'))),
        weekly_reward=d.pop('weekly_reward_mark'), weekly_event_a=d.pop('weekly_event_reward_a'),
        weekly_event_b=d.pop('weekly_event_reward_b'))
    return dict(local=dict(session=session, world=world, battle=battle), daily_tasks=d,
                time_cube=s['time_cube'], recovery=s['potion_storage'], guild=s['guild'],
                activities=sorted(ACTIVITIES[k] for k in s['activities']), storage=s['room_storage'],
                server_stackable=s['inventory'].get('server_stackable'), expedition=s['expedition'])


def evidence(state):
    s = state.snapshot()
    return dict(phase=s['phase'], player=s['player'] or None, packet_count=s['packet_count'])


def pack(fmt, *args): return struct.pack('<' + fmt, *args)


def item(item_id=42, count=2, serial=9, version=2, equip=False):
    data = pack('H', item_id) + (b'' if equip else pack('B', count)) + pack('BBI', 254, version, serial)
    if not equip: data += pack('II', 0x80000000, 0xffffffff)
    data += pack('HddBBH', 65535, -123.5, 1e-100, 255, 254, 65535)
    if not equip: data += pack('H', 65534)
    data += pack('BHI', 253, 65533, 0xffffffff)
    data += b''.join(pack('BH', i, 65535-i) for i in range(4)) + pack('BBB', 3, 255, 254)
    return data + (b'' if equip else b'\xfd')


def bag_row(index=1, item_id=42, count=2, serial=9, version=2):
    return pack('B', index) + item(item_id, count, serial, version)


def pet(simple=False, exp=-2147483648):
    if simple: data = pack('BHHHHHBI', 255, 101, 202, 303, 404, 505, 254, exp & 0xffffffff)
    else:
        name = '星河😀'.encode('utf-16le')
        data = pack('iBiHHHHHHBBBH', exp, 254, -2147483648, 65535, 303, 101, 202, 505, 404, 0, 255, 254, 65535) + pack('B', len(name)) + name
    data += b''.join(pack('BI', level, value) for level, value in [(3, 4), (0, 0xffffffff), (255, 1), (2, 5), (1, 6)])
    if simple: data += b'\xfe'
    data += b''.join(item(i, equip=True) for i in range(1, 10))
    if not simple: data += b'\xff'
    data += pack('BBBH', 253, 2, 255, 65535)
    if not simple: data += b'\xff'
    return data + pack('H', 65535)


def companion(index=1, npc=1, exp=-2147483648): return pack('BH', index, npc) + pet(exp=exp)


def add_pet(owner=7, npc=1): return pack('II', owner, npc) + pet(True) + b'\xff'


def attribute(index=1, kind=25, value=999, parameter=0, human=4):
    return pack('BHBBII', human, index, kind, 2 if value < 0 else 1, abs(value), parameter)


def project_live(state):
    inv = copy.deepcopy(state.inventory)
    for key in ['capacity', 'sync_error', 'last_use_result', 'field_supply', 'alchemy_slots', 'expedition_slots', 'maintenance_slots', 'server_stackable']:
        inv.setdefault(key, None)
    inv.setdefault('holds', {})
    return copy.deepcopy(dict(inventory=inv, item_order=list(inv['items']), hold_order=list(inv['holds']),
        available={str(i): reservations.available(state.inventory, i) for i in [0, 1, 2, 3, 4, 255, 65535]},
        companions=state.knowledge['companions'], companions_ready=state.knowledge['companions_ready'],
        active_npc_id=state.knowledge['active_npc_id'], companion_order=list(state.knowledge['companions']),
        attributes={k: v for k, v in state.attributes.items() if k.startswith("follow:")}))


def craft_row(index=1, identity=42, elapsed=1250, count=2, base=20):
    return pack('BHIBI', index, identity, elapsed, count, base)


def furniture(index=7, item=39053, status=0):
    return (pack('HHHHHBH', index, item, 0, 32768, 65535, 255, 65534)
            + pack('11H', *range(11)) + pack('BB', 255, status) + b'PRIVATE')


def project_crafting(state, now):
    result = copy.deepcopy({'crafting': state.crafting, 'furniture': state.furniture})
    for domain, keys in [('crafting', ('revision', 'completed')), ('furniture', ('revision',))]:
        for key in keys: result[domain][key] = str(result[domain][key])
    result['queue_order'] = [int(index) for index in state.crafting['queue']]
    result['furniture_order'] = [int(index) for index in state.furniture['items']]
    result['elapsed'] = {str(index): [crafting.elapsed(state.crafting, r, at) for at in (now-100, now, now+100000)]
                         for index, r in state.crafting['queue'].items()}
    return result


def project(state, now):
    return dict(services=project_service(state), live=project_live(state), crafting=project_crafting(state, now),
                party=copy.deepcopy(state.party), team_order=list(state.party['teams']), own_team=copy.deepcopy(own_team(state)),
                instances=normalize(copy.deepcopy(state.instances)), tent=copy.deepcopy(state.tent))

def normalize(value):
    if isinstance(value, tuple): return {'$tuple': [normalize(v) for v in value]}
    if isinstance(value, dict): return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list): return [normalize(v) for v in value]
    return value


def nearby(role, scene=101):
    return (pack('IBBBHHH', role, 2, 3, 4, scene, 5, 6) + bytes(13) + b'\0' + b'\7\10'
            + text('Synthetic 鄰居') + bytes(8) + text('') + bytes(2))


def camp(owner=17, identity=42): return pack('IH IIBB', owner, identity, 123, 456, 7, 8)
def phase(kind=1, room=500, host=17):
    return (85, 5, pack('BBHBI', 1, 0, room, 2, host) if kind == 1 else bytes([kind]))
def members(room=500, roles=(17, 18)):
    return (85, 4, pack('HB', room, len(roles)) + b''.join(pack('I', r) for r in roles))
def coop(room=9, roles=(17, 18), standby=True):
    return (186, 3, pack('BBHBBBB', 1, 1, room, standby, 2, 1, len(roles)) +
            b''.join(pack('IBIIII', r, i, 100+i, 200+i, 30+i, 40+i) for i, r in enumerate(roles)))
def match(): return (186, 2, bytes([18, 1]) + pack('II', 17, 18))
def pending(action='enter'): return dict(action=action, due=123.25)
def entry(): return dict(action='enter', source_scene=101, furniture_received=False)


sequences = []
covered = set()
class Scenario:
    def __init__(self, name, *, boot=True, count=0, party=None, main=None, coop=None, tent=None):
        self.state = State(packet_count=count)
        bootstrap = world() if boot else None
        if bootstrap is not None:
            with patch('time.monotonic', return_value=100): self.state.apply(decode(Packet(3, 1, bootstrap)))
        for target, seed in ((self.state.party, party), (self.state.instances['main'], main),
                             (self.state.instances['coop'], coop), (self.state.tent, tent)):
            target.update(copy.deepcopy(seed or {}))
        self.steps = []
        self.value = dict(name=name, count=str(count), bootstrap=bootstrap.hex() if bootstrap else None,
                          initial=project(self.state, 100), steps=self.steps)
        sequences.append(self.value)

    def packet(self, main, sub, payload=b'', *, at=None, stages=None, declared=(), catalogs=True):
        now = 100 + len(self.steps)*.25 if at is None else at
        step = dict(main=main, sub=sub, hex=payload.hex(), at=now, stages=stages, declared=declared, catalogs=catalogs)
        runtime = None if stages is None else SimpleNamespace(stages=dict.fromkeys(stages), combat_catalog=None, recipe_catalog=None)
        trace = []
        original = self.state.snapshot()
        def wrap(name, function):
            def observed(state, event, **kwargs):
                row = dict(name=name, before=evidence(state), bag_before=copy.deepcopy(state.inventory))
                trace.append(row)
                result = function(state, event, **kwargs)
                row['after'] = evidence(state)
                row['bag_after'] = copy.deepcopy(state.inventory)
                return result
            return observed
        with ExitStack() as stack:
            stack.enter_context(patch('time.monotonic', return_value=now))
            stack.enter_context(patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime))
            stack.enter_context(patch('wlre.services.instance_entry.entries_for',
                return_value=[dict(kind=1, map_id=value) for value in declared]))
            stack.enter_context(patch.object(inventory_updates, 'STACKABLE', RULES if catalogs else {}))
            token = _pinned.set(CATALOG if catalogs else {**CATALOG, 'npcs': {}})
            try:
                try:
                    event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
                except ProtocolError:
                    step['error'] = True
                    assert self.state.snapshot() == original
                else:
                    covered.add(event['type'])
                    for name in ORDER:
                        stack.enter_context(patch.object(state_module, name, wrap(name, getattr(state_module, name))))
                    self.state.apply(event)
                    assert [row['name'] for row in trace] == list(ORDER)
                    dispatch = trace[ORDER.index('dispatch_local')]
                    assert all(row['before'] == dispatch['before'] for row in trace[:ORDER.index('dispatch_local')])
                    assert all(row['before'] == dispatch['after'] for row in trace[ORDER.index('dispatch_local')+1:])
                    assert trace[0]['bag_before'] == trace[1]['bag_before'] == original['inventory']
                    live = trace[ORDER.index('apply_live')]
                    assert live['bag_before'] == trace[ORDER.index('apply_storage')]['bag_after']
                    assert live['bag_after'] == self.state.inventory
                    step.update(error=False, kind=event['type'], before=dispatch['before'], after=dispatch['after'],
                        before_live_inventory=project_live(SimpleNamespace(inventory=live['bag_before'],
                        knowledge={'companions': {}, 'companions_ready': False, 'active_npc_id': None}, attributes={}))['inventory'])
            finally:
                _pinned.reset(token)
        step['expected'] = project(self.state, now)
        self.steps.append(step)
        return self

    def position(self, scene, role=17, **kwargs): return self.packet(12, 1, pack('IHHH', role, scene, 1, 2), **kwargs)
    def start(self): return self.packet(11, 250, b'\1\2\0')
    def room(self, owner=17): return self.packet(62, 4, pack('I', owner) + furniture())


s = Scenario('first_world_requires_pre_local_identity_then_same_world_confirms', boot=False, count=2**90,
             main={'enter_pending': {'room_id': 500, 'started': 0}})
s.packet(*phase()).packet(*phase(3)).packet(13, 9, pack('I', 18)).packet(65, 1, camp())
s.packet(3, 1, world(17, 500), declared=(500,)).packet(3, 1, world(17, 500), declared=(500,))
s.packet(65, 1, camp()).start().packet(11, 12, b'\1').packet(85, 15).packet(63, 1)

s = Scenario('main_room_role_changes_declared_ids_and_battle_late_evidence',
             main={'create_pending': {'map_id': 500, 'ack': False}, 'enter_pending': {'room_id': 500, 'started': 0}})
s.packet(85, 2, b'\0').packet(*phase()).packet(*members()).packet(*phase(3))
s.packet(4, 1, nearby(18)).packet(4, 1, nearby(19, 500)).position(500, role=18, declared=(500,))
s.position(500, stages=(101, 500)).position(500, declared=(501,)).position(500, declared=(500,))
s.start().packet(11, 0, pack('IH', 18, 0)).packet(11, 12, b'\2').packet(63, 1)
s.packet(3, 1, world(18, 500), declared=(500,)).packet(*phase(1, room=501, host=18)).packet(*phase(3))
s.packet(3, 1, world(17, 501), declared=(501,)).position(501, role=18, declared=(501,)).position(501, declared=(501,))
s.start().packet(11, 0, pack('IH', 17, 0)).packet(85, 15).packet(*phase(2)).packet(*members())
s.packet(85, 3, b'\0').packet(1, 23, at=1e12)

s = Scenario('party_identity_role_retention_nearby_order_and_expired_requests',
    party={'outbound': {'invite:18': dict(role_id=18, expires=10)}, 'enabled_requested': True})
s.packet(4, 1, nearby(18)).packet(4, 1, nearby(19, 500)).packet(13, 9, pack('I', 18), at=-100)
s.packet(13, 1, pack('I', 19)).packet(1, 23, at=1e12).packet(13, 5, pack('II', 18, 17))
s.packet(13, 6, pack('IBIIBI', 19, 1, 17, 18, 1, 17)).packet(63, 1)
s.packet(13, 9, pack('I', 19)).packet(3, 1, world(18, 500)).position(500, role=18)
s.packet(13, 15, pack('BI', 1, 19)).packet(13, 15, pack('BII', 3, 17, 18))
s.packet(13, 4, pack('I', 17)).packet(13, 5, pack('II', 17, 18)).packet(13, 10, b'\1'+pack('I', 17))
s.packet(33, 2, b'\0\0\1\0').packet(33, 1, b'\26').packet(1, 1, pack('I', 18))

s = Scenario('coop_matches_rewards_and_room_switches_interleave_prior_domains',
    coop={'create_uncertain': True, 'create_attempt': {'kind': 2, 'npc_id': 1},
          'standby_pending': {'room_id': 9, 'target': True}, 'claim_pending': {'started': 0, 'fingerprint': (3, 3, 1, 1, 1)}})
s.packet(*coop()).packet(*match()).start().packet(186, 15, b'\3').packet(11, 0, pack('IH', 18, 0))
s.packet(11, 12, b'\1').packet(186, 11, bytes([3, 3, 1, 1, 1])).packet(186, 10, pack('BII', 1, 42, 3))
s.packet(23, 5, b'\10'+bag_row()).packet(62, 57, pack('BBHHH', 1, 2, 1, 42, 3))
s.packet(15, 8, companion()).packet(8, 2, attribute()).packet(124, 1, daily())
s.packet(122, 1, pack('BBHH', 1, 1, 3, 0)).packet(39, 2, roster()).packet(31, 18, team())
s.packet(*coop(10)).packet(186, 13).packet(186, 10, pack('BII', 1, 43, 9))
s.packet(3, 1, world(18)).packet(*coop(11, roles=(18, 17))).packet(*match()).start().packet(11, 0, pack('IH', 18, 0))

for stages in (None, (101,), (101, 63501)):
    for order in ('furniture_first', 'position_first'):
        s = Scenario(f'tent_entry_{stages}_{order}_post_local_scene_and_catalog',
                     tent={'scene': 101, 'pending': pending(), 'entry_context': entry(), 'uncertain': True})
        s.packet(65, 3, camp(18)+camp()+camp(identity=43)).room(18)
        if order == 'furniture_first': s.room().position(63501, stages=stages)
        else: s.position(63501, stages=stages).packet(62, 4, pack('I', 17)+furniture(), stages=stages)
        s.position(10299).room().packet(65, 16, b'\2').packet(1, 23, at=1e12)
        s.position(101).packet(65, 3).packet(65, 4, pack('I', 17)).packet(65, 4, pack('I', 17))
        s.packet(3, 1, world(18, 500)).packet(65, 1, camp(18)).packet(65, 7, b'\1\0')
        s.packet(65, 18, b'\2\3').packet(63, 1)

for action, response in [('open', (65, 2, b'')), ('enter', (65, 8, b'')), ('enter', (65, 16, b'\2')),
                         ('leave', (20, 74, b'\2'))]:
    s = Scenario('tent_pending_error_and_late_return_' + action + str(response[1]),
        tent={'scene': 101, 'pending': pending(action), 'entry_context': entry(), 'uncertain': True})
    s.packet(1, 23, at=1e12).packet(*response).packet(*response).room().position(10299).position(101)
    s.packet(65, 3).packet(65, 5).packet(63, 1).packet(3, 1, world())

s = Scenario('instance_lists_and_requests_use_each_observation_time_without_expiring')
listing = b'\1' + pack('H', 500)+text('Synthetic')+b'\2'+text('Guild')+b'\1'+pack('H', 65535)
s.packet(85, 1, listing, at=1000).packet(13, 9, pack('I', 18), at=1000)
s.packet(85, 1, listing, at=-50).packet(186, 17, b'\0\0', at=-100).packet(*phase()).packet(*phase(3))
s.packet(1, 23, at=1e12).packet(13, 16, b'\1').packet(85, 1, b'\0')

s = Scenario('malformed_social_instance_tent_packets_preserve_every_projection',
    party={'requests': {'team_invite:18': dict(key='team_invite:18', type='team_invite', role_id=18, expires=1, status='pending')}},
    main={'join_pending': {'room_id': 500}}, tent={'pending': pending(), 'entry_context': entry()})
for main, sub, payload in [(13, 6, pack('IBII', 17, 2, 17, 18)), (65, 3, camp()), phase(), members(), coop(),
                          (62, 4, pack('I', 17)+furniture()), (11, 250, b'\1\2\0')]:
    for cut in (0, 1, len(payload)//2, len(payload)-1): s.packet(main, sub, payload[:cut]).packet(1, 23)
    s.packet(main, sub, payload+b'\xff')

rng = random.Random(2026110901)
for sequence in range(6):
    s = Scenario('deterministic_mixed_receive_' + str(sequence), count=sequence*100)
    for step in range(64):
        role = rng.choice((17, 18)); scene = rng.choice((101, 500, 63501, 10299)); choice = rng.randrange(31)
        context = dict(stages=rng.choice((None, (101,), (101, 500))), declared=rng.choice(((), (500,))))
        if choice == 0: s.packet(3, 1, world(role, scene), **context)
        elif choice == 1: s.packet(63, 1)
        elif choice == 2: s.position(scene, role, **context)
        elif choice == 3: s.packet(4, 1, nearby(role, scene))
        elif choice == 4: s.packet(13, 9, pack('I', role))
        elif choice == 5: s.packet(13, 5, pack('II', 17, role))
        elif choice == 6: s.packet(13, 4, pack('I', role))
        elif choice == 7: s.packet(65, 3, camp(role))
        elif choice == 8: s.packet(65, 4, pack('I', role))
        elif choice == 9: s.packet(65, 16, bytes([rng.randrange(4)]))
        elif choice == 10: s.packet(62, 4, pack('I', role)+furniture(), **context)
        elif choice == 11: s.packet(*phase(rng.choice((1, 2, 3, 4)), host=role))
        elif choice == 12: s.packet(*members())
        elif choice == 13: s.packet(*coop(rng.choice((9, 10)), standby=bool(step%2)))
        elif choice == 14: s.packet(*match())
        elif choice == 15: s.start()
        elif choice == 16: s.packet(11, 12, b'\1')
        elif choice == 17: s.packet(11, 0, pack('IH', role, 0))
        elif choice == 18: s.packet(186, 11, bytes([3, 3, 1, 1, 1]))
        elif choice == 19: s.packet(186, 13)
        elif choice == 20: s.packet(85, 15)
        elif choice == 21: s.packet(23, 5, b'\10'+bag_row())
        elif choice == 22: s.packet(62, 57, pack('BBHHH', 1, 2, 1, 42, 3))
        elif choice == 23: s.packet(15, 8, companion(), catalogs=bool(step%2))
        elif choice == 24: s.packet(8, 2, attribute(value=step))
        elif choice == 25: s.packet(64, 1, craft_row()+b'\1')
        elif choice == 26: s.packet(124, 1, daily(step%4))
        elif choice == 27: s.packet(122, 1, pack('BBHH', 1, 1, 3, 0))
        elif choice == 28: s.packet(31, 18, team())
        elif choice == 29: s.packet(23, 208, pack('BBi', 3, 1, step))
        else: s.packet(1, 23, at=1e12)

# Intended valid sequences must not accidentally degrade into decoder-error coverage.
for sequence in sequences:
    if 'malformed' not in sequence['name']:
        assert not any(step['error'] for step in sequence['steps']), sequence['name']

sources = ['wlre/core/state.py', 'wlre/core/state_events.py', 'wlre/core/state_session_events.py',
    'wlre/core/state_world_events.py', 'wlre/core/state_battle_events.py', 'wlre/core/activity.py',
    'wlre/services/daily_tasks.py', 'wlre/services/time_cube.py', 'wlre/services/items/recovery.py',
    'wlre/services/items/room_storage.py', 'wlre/services/social/guild.py', 'wlre/services/expedition/manager.py',
    'wlre/services/items/crafting.py', 'wlre/services/items/combat_resources.py', 'wlre/services/items/inventory.py',
    'wlre/core/inventory_updates.py', 'wlre/services/items/reservations.py', 'wlre/services/items/live_combat_catalog.py',
    'wlre/services/battle/attribute_points.py', 'wlre/services/battle/party.py', 'wlre/services/instances.py',
    'wlre/services/world/tent.py', 'wlre/services/world/npc_shop_evidence.py', 'wlre/core/efficiency.py',
    'wlre/services/social/guild_actions.py', 'wlre/services/star_ark.py', 'wlre/network/protocol.py',
    'wlre/network/live_data.py', 'wlre/network/wire.py', 'wlre/network/instances.py', 'wlre/network/social_protocol.py', 'wlre/network/layouts.py', 'wlre/services/world/house_navigation.py']
sources += ['wlre/services/instance_' + name + '.py' for name in ('creation', 'room_flow', 'standby', 'start', 'entry', 'rewards')]
hashes = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
metadata = dict(sources=hashes, order=ORDER, scenarios=len(sequences), checkpoints=sum(len(s['steps']) for s in sequences), covered=sorted(covered))
header = '// Generated by ServiceSocialInstanceGenerateVectors.py from real State.apply; synthetic offline evidence.\nnamespace Lala.Core.Tests.State;\n'
lines = [header, 'public static partial class ServiceSocialInstancePythonVectors', '{',
         '    public static string Metadata() => ' + csharp_gzip_json(json.dumps(metadata, ensure_ascii=False)) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
parts = []
for index, vector in enumerate(sequences):
    raw = json.dumps(vector, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    lines.append('        yield return new object[] { ' + json.dumps(vector['name']) + f', Sequence{index}()' + ' };')
    parts.append('    private static string Sequence' + str(index) + '() => ' + csharp_gzip_json(raw) + ';')
lines += ['    }', '}']
output = Path(__file__).with_name('ServiceSocialInstancePythonVectors.cs')
output.write_text('\n'.join(lines)+'\n')
for start in range(0, len(parts), 4):
    target = output.with_name(output.stem + f'.Part{start//4:02}' + output.suffix)
    target.write_text(header + 'public static partial class ServiceSocialInstancePythonVectors\n{\n' + '\n'.join(parts[start:start+4]) + '\n}\n')
    assert target.stat().st_size < 500000
print(f'Generated {len(sequences)} real State.apply scenarios / {metadata["checkpoints"]} checkpoints / {len(covered)} event kinds.')
