"""Real State.apply oracle for mixed combat knowledge, allocation and prior receive projections.

Every Python observer runs, in its retained order. Only offline catalog projections and
observation time are supplied; no request, tick, send, transport or resource activation.
The projection retains current player/companion/battle equipment and allocation context.
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
CATALOGS = [
    dict(keys={}, items={}),
    dict(keys={'1': 1001, '2': 1002, '3': 1001, '4': 0}, items={'42': {'fit_type': 3}, '43': {'fit_type': 11}, '44': {'fit_type': 0}, '45': {'fit_type': 9}}),
    dict(keys={'1': 2001, '2': 1002, '3': 1001}, items={'42': {'fit_type': 3}, '43': {'fit_type': 11}, '44': {'fit_type': 0}, '45': {'fit_type': 9}, '99': {'fit_type': 3}, '100': {'fit_type': 2}}),
    dict(keys={}, items={'99': {'fit_type': 3}, '100': {'fit_type': 2}}),
]
for catalog in CATALOGS:
    catalog.update(skills={}, characters=[], element_weights={}, npcs={key: {'skills': values} for key, values in NPCS.items()})
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
                instances=normalize(copy.deepcopy(state.instances)), tent=copy.deepcopy(state.tent),
                knowledge=copy.deepcopy(dict(player=state.knowledge['player'], player_skill_order=list(state.knowledge['player']['skills']),
                    companions=state.knowledge['companions'], companion_order=list(state.knowledge['companions']),
                    units=state.battle_units, unit_order=list(state.battle_units), attributes=state.attributes)),
                allocation=copy.deepcopy(state.attribute_allocation))

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
    def __init__(self, name, *, boot=True, count=0, party=None, main=None, coop=None, tent=None, stats=None, allocation=None):
        self.state = State(packet_count=count)
        bootstrap = world() if boot else None
        if bootstrap is not None:
            with patch('time.monotonic', return_value=100): self.state.apply(decode(Packet(3, 1, bootstrap)))
        for target, seed in ((self.state.party, party), (self.state.instances['main'], main),
                             (self.state.instances['coop'], coop), (self.state.tent, tent)):
            target.update(copy.deepcopy(seed or {}))
        self.state.knowledge['player']['stats'].update(stats or {})
        self.state.attribute_allocation.update(copy.deepcopy(allocation or {}))
        self.steps = []
        self.value = dict(name=name, count=str(count), bootstrap=bootstrap.hex() if bootstrap else None,
                          initial=project(self.state, 100), steps=self.steps)
        sequences.append(self.value)

    def packet(self, main, sub, payload=b'', *, at=None, stages=None, declared=(), catalogs=True, knowledge_catalog=0):
        now = 100 + len(self.steps)*.25 if at is None else at
        step = dict(main=main, sub=sub, hex=payload.hex(), at=now, stages=stages, declared=declared, catalogs=catalogs, knowledge_catalog=knowledge_catalog)
        runtime = None if stages is None else SimpleNamespace(stages=dict.fromkeys(stages), combat_catalog=None, recipe_catalog=None)
        trace = []
        original = self.state.snapshot()
        def wrap(name, function):
            def observed(state, event, **kwargs):
                row = dict(name=name, before=evidence(state), bag_before=copy.deepcopy(state.inventory),
                           stats=copy.deepcopy(state.knowledge['player']['stats']), attributes=copy.deepcopy(state.attributes))
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
            token = _pinned.set({**CATALOGS[knowledge_catalog], 'npcs': CATALOGS[knowledge_catalog]['npcs'] if catalogs else {}})
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
                    points = trace[ORDER.index('apply_points_event')]
                    assert points['attributes'] == dispatch['attributes']
                    if event['type'] == 'attribute_set':
                        assert points['attributes'] == original['attributes']
                    step.update(allocation_stats=points['stats'], attributes_at_allocation=points['attributes'],
                        error=False, kind=event['type'], before=dispatch['before'], after=dispatch['after'],
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


def player(records=((1,3,9),(2,0,0),(3,7,8),(4,1,0),(999,9,9))):
    return (pack('BIHHHHHHBIHHIH', 255, 0xffffffff, 65535, 101, 202, 303, 404, 505, 254, 0xffffffff, 65535, 65534, 0xffffffff, 65535) +
        pack('IIIIII', *range(0xfffffff9, 0xffffffff)) + bytes(range(12)) + pack('H', len(records)) +
        b''.join(pack('HBI', *row) for row in records) + pack('HHBBB', 65535, 65534, 1, 255, 254))

def unit(pid=7, master=0, npc=0, col=1, row=1, hp=300):
    return (pack('BBIHIBBIHIHBBBBHHBBII', 9, 4, pid, npc, master, col, row, 0xffffffff, 65535, hp, 9, 21, 2, 1, 0, 0, 0, 1, 2, 0, 0) +
        b'\x00' + b''.join(pack('HI', i+42, i+100) for i in range(9)))

def attr(kind=25, value=999, parameter=0): return pack('BBII', kind, 2 if value < 0 else 1, abs(value), parameter)



def pending(expected, acknowledged=False, uncertain=False):
    return dict(pending=True, acknowledged=acknowledged, uncertain=uncertain, expected=expected, sent_at=1.25, status='imported pending')

def equips(s, *ids, **kwargs): return s.packet(23, 11, b''.join(item(i, equip=True) for i in ids), **kwargs)
def equip(s, owner=17, npc=0, index=3, item_id=99, design=123, **kwargs):
    return s.packet(11, 252, pack('IBBHI', owner, npc, index, item_id, design), **kwargs)
def damage(s, index=3, value=17, npc=0, **kwargs): return s.packet(23, 140, pack('BBBIB', 1, 2, index, value, npc), **kwargs)
def units(s, *values, start=False, **kwargs):
    return s.packet(11, 250 if start else 5, (b'\1\2' if start else b'')+pack('B', len(values))+b''.join(values), **kwargs)

for ack_first in (False, True):
    s = Scenario('ack_first' if ack_first else 'stats_first', count=2**90,
                 stats={'str': 20, 'attribute_potential': 20}, allocation=pending({'str': 22, 'attribute_potential': 18}))
    s.packet(8, 1, attr(28, 20)).packet(13, 9, pack('I', 18)).packet(65, 1, camp())
    if ack_first: s.packet(8, 4).packet(8, 4)
    s.packet(8, 1, attr(28, 22)).packet(8, 2, attribute(kind=28, value=123))
    s.packet(8, 1, attr(38, 18))
    if not ack_first: s.packet(8, 4)
    s.packet(8, 4).packet(8, 1, attr(28, 20)).packet(1, 23, at=1e12)

for ack_first in (False, True):
    s = Scenario('combat_snapshot_ack_' + str(ack_first), allocation=pending({'str': 101, 'con': 202, 'int': 303, 'attribute_potential': 65534}))
    if ack_first: s.packet(8, 4)
    s.packet(5, 3, player(), knowledge_catalog=1)
    if not ack_first: s.packet(8, 4)
    s.packet(8, 1, attr(110, 0, 1001)).packet(5, 3, player(()), knowledge_catalog=2)

s = Scenario('battle_updates_profiles_before_allocation_and_s11_persists', allocation=pending({'hp': 123}, True))
s.packet(15, 8, companion()).packet(8, 2, attribute(value=765))
units(s, unit(17), unit(1, 17, 1, 2), unit(1, 18, 1, 3), unit(2, 17, 1, 4), start=True)
s.packet(51, 1, pack('BBBI', 1, 1, 25, 123)+pack('BBBI', 2, 1, 47, 999))
# Battle changes knowledge but is not a qualifying allocation receipt. Any later S8 is.
s.packet(8, 3, pack('I', 17)+attr(255, 0))
equips(s, 42, knowledge_catalog=1)
equip(s); equip(s, design=999); equip(s, npc=1); damage(s, npc=1, value=0xffffffff)
s.packet(23, 35, pack('BH', 1, 42), knowledge_catalog=1)
s.packet(11, 1, b'\1\1').packet(51, 1, pack('BBBI', 1, 1, 26, 88))
s.packet(13, 5, pack('II', 17, 18)).packet(*phase()).packet(*members()).position(500, declared=(500,))
equip(s, owner=18, npc=1, item_id=45)
units(s, unit(17, col=1, hp=400)); units(s, unit(1, 17, 1, 2, hp=500))
s.packet(15, 8, companion(npc=2)).packet(8, 2, attribute(value=21)).packet(15, 2, pack('IBB', 17, 1, 0))
s.packet(15, 8, companion()).packet(11, 12, b'\1').packet(63, 1).packet(3, 1, world(18))

s = Scenario('resolver_runs_before_inventory_return_and_no_catalog_retention')
equips(s, 42, 99, 43, 100, 44, knowledge_catalog=1)
damage(s); equip(s, item_id=42, design=888); equip(s, item_id=45)
s.packet(23, 5, b'\10'+bag_row(), knowledge_catalog=3)
s.packet(62, 57, pack('BBHHH', 1, 2, 1, 42, 3), knowledge_catalog=2)
s.packet(1, 23)
equips(s, 99)  # omitted mappings must not reuse the previous per-observation catalog
damage(s); s.packet(23, 5, b'\10'+bag_row(count=4), knowledge_catalog=2)
s.packet(64, 1, craft_row()+b'\1').packet(124, 1, daily()).packet(31, 18, team())

s = Scenario('s8_buffer_replay_identity_reuse_and_equipment_reset')
s.packet(8, 2, attribute(value=345)).packet(15, 8, companion())
equip(s, npc=1); damage(s, npc=1); s.packet(15, 8, companion())
s.packet(15, 8, companion(npc=2)).packet(8, 2, attribute(kind=110, value=9, parameter=1002))
s.packet(15, 2, pack('IBB', 17, 1, 0)).packet(15, 8, companion())
s.packet(15, 8, companion(index=2)).packet(15, 1, add_pet(17)).packet(63, 1)
s.packet(3, 1, world(18)).packet(15, 1, add_pet(17)).packet(15, 1, add_pet(18))

for expected, stats, kind, value in [({'exp': -2**63}, {}, 255, 0), ({'unknown': 0}, {}, 255, 0),
    ({'STR': 22}, {'str': 22}, 28, 22), ({'str': 2**90}, {'str': 22}, 28, 22),
    ({'str': -0xffffffff}, {}, 28, -0xffffffff), (None, {}, 255, 0), ({}, {}, 255, 0)]:
    s = Scenario('numeric_presence_' + str(len(sequences)), stats=stats, allocation=pending(expected, True, True))
    s.packet(5, 47, pack('BBq', 255, 254, -2**63)+bytes(30)).packet(8, 1, attr(kind, value))
    s.packet(8, 4).packet(1, 23, at=1e12)

s = Scenario('unknown_first_and_changed_role_identity', boot=False, allocation=pending({'hp': 300}, True))
s.packet(15, 8, companion()); units(s, unit(17), unit(1, 17, 1, 2), start=True)
s.packet(3, 1, world(17)); units(s, unit(17), unit(1, 17, 1, 2), start=True)
s.packet(8, 1, attr(255, 0)).packet(3, 1, world(18))
equip(s, owner=17); units(s, unit(17, hp=123)); s.packet(3, 1, world(0)); units(s, unit(0, hp=999))

s = Scenario('malformed_packets_do_not_resolve_or_count', allocation=pending({'str': 22}, True))
equips(s, 99); damage(s)
for main, sub, payload in [(5, 3, player()), (23, 11, item(equip=True)), (8, 1, attr(28, 22)),
    (11, 252, pack('IBBHI', 17, 0, 3, 99, 1)), (11, 250, b'\1\2\1'+unit(17)), (8, 4, b'')]:
    for cut in sorted({0, 1, len(payload)//2, max(0, len(payload)-1)}):
        if cut < len(payload): s.packet(main, sub, payload[:cut], knowledge_catalog=2)
    s.packet(main, sub, payload+b'\xff', knowledge_catalog=2)
s.packet(51, 1, b'\1', knowledge_catalog=2).packet(1, 23)

for overflow in ('damage', 'appearance'):
    s = Scenario('deferred_queue_boundary_' + overflow)
    equips(s, 42, 99, knowledge_catalog=1)
    for i in range(257):
        if overflow == 'damage': damage(s, value=i)
        else: equip(s, item_id=45 if i%2 else 42, design=i)
    s.packet(23, 5, b'\10'+bag_row(), knowledge_catalog=2)
    equips(s, 42, 99, knowledge_catalog=2); damage(s)

rng = random.Random(202611080901)
for sequence in range(8):
    s = Scenario('mixed_all_projections_' + str(sequence), allocation=pending({'str': 22, 'hp': 300}, bool(sequence%2)))
    for step in range(40):
        role = rng.choice((17, 18)); choice = rng.randrange(22); cat = rng.randrange(4)
        if choice == 0: s.packet(3, 1, world(role))
        elif choice == 1: s.packet(5, 3, player(), knowledge_catalog=cat)
        elif choice == 2: s.packet(8, 1, attr(28, rng.choice((20, 22, -1))))
        elif choice == 3: s.packet(8, 4)
        elif choice == 4: equips(s, 42, 99, knowledge_catalog=cat)
        elif choice == 5: equip(s, owner=role, npc=rng.choice((0, 1)), design=step)
        elif choice == 6: damage(s, npc=rng.choice((0, 1)), value=step, knowledge_catalog=cat)
        elif choice == 7: units(s, unit(role), unit(1, role, 1, 2), start=True)
        elif choice == 8: s.packet(51, 1, pack('BBBI', 1, 1, 25, step))
        elif choice == 9: s.packet(15, 8, companion(npc=rng.choice((1, 2))))
        elif choice == 10: s.packet(8, 2, attribute(value=step))
        elif choice == 11: s.packet(23, 5, b'\10'+bag_row(count=step%20), knowledge_catalog=cat)
        elif choice == 12: s.packet(62, 57, pack('BBHHH', 1, 2, 1, 42, 3))
        elif choice == 13: s.packet(13, 9, pack('I', role))
        elif choice == 14: s.packet(*phase()).packet(*members())
        elif choice == 15: s.position(500, role, declared=(500,))
        elif choice == 16: s.packet(65, 1, camp(role)).room(role)
        elif choice == 17: s.packet(64, 1, craft_row()+b'\1')
        elif choice == 18: s.packet(124, 1, daily(step%4)).packet(31, 18, team())
        elif choice == 19: s.packet(122, 1, pack('BBHH', 1, 1, 3, 0)).packet(39, 2, roster())
        elif choice == 20: s.packet(11, 12, b'\1').packet(63, 1)
        else: s.packet(1, 23, at=-100 if step%2 else 1e12, knowledge_catalog=cat)

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
header = '// Generated by ServiceKnowledgeAllocationGenerateVectors.py from real State.apply; synthetic offline evidence.\nnamespace Lala.Core.Tests.State;\n'
lines = [header, 'public static partial class ServiceKnowledgeAllocationPythonVectors', '{',
         '    public static string Metadata() => ' + csharp_gzip_json(json.dumps(metadata, ensure_ascii=False)) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
parts = []
for index, vector in enumerate(sequences):
    raw = json.dumps(vector, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    lines.append('        yield return new object[] { ' + json.dumps(vector['name']) + f', Sequence{index}()' + ' };')
    expression = csharp_gzip_json(raw)
    # Keep exactly the shared helper's gzip bytes; split large byte arrays, not CLR strings.
    rows = expression.splitlines()[1:-1]
    chunks = [rows[offset:offset+1500] for offset in range(0, len(rows), 1500)]
    calls = ', '.join(f'.. Sequence{index}Bytes{part}()' for part in range(len(chunks)))
    parts.append(f'    private static string Sequence{index}() => Lala.Core.Tests.TestSupport.GzipJson.Decode([{calls}]);')
    for part, chunk in enumerate(chunks):
        parts.append(f'    private static byte[] Sequence{index}Bytes{part}() => [\n' + '\n'.join(chunk) + '\n    ];')
lines += ['    }', '}']
output = Path(__file__).with_name('ServiceKnowledgeAllocationPythonVectors.cs')
output.write_text('\n'.join(lines)+'\n')
# Generated-only files may be replaced when the deterministic partition count changes.
for old in output.parent.glob(output.stem + '.Part*.cs'): old.unlink()
prefix = header + 'public static partial class ServiceKnowledgeAllocationPythonVectors\n{\n'
part_index, body = 0, prefix
for part in parts:
    if len((body + part + '\n}\n').encode('utf-8')) > 450000:
        target = output.with_name(output.stem + f'.Part{part_index:02}' + output.suffix)
        target.write_text(body + '}\n'); assert target.stat().st_size < 500000
        part_index += 1; body = prefix
    body += part + '\n'
target = output.with_name(output.stem + f'.Part{part_index:02}' + output.suffix)
target.write_text(body + '}\n'); assert target.stat().st_size < 500000
print(f'Generated {len(sequences)} real State.apply scenarios / {metadata["checkpoints"]} checkpoints / {len(covered)} event kinds.')
