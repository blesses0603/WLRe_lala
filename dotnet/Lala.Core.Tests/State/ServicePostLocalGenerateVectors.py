"""Real State.apply oracle for all four post-local receive observers.

Every retained observer runs in source order alongside the earlier service slices.
Only synthetic catalog/read observations and explicit timestamps are injected.
The actual Ark memory helper runs against a constructor that raises before storage.
No request, tick, send, filesystem persistence, candidate activation or solver runs.
"""
import copy
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import random
import itertools
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
from wlre.core import efficiency
from wlre.services import star_ark as ark
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


def project_efficiency(state):
    result = copy.deepcopy(state.snapshot()['efficiency'])
    for row in result['rows'].values():
        row['rates'] = efficiency.rates(row)
        row.setdefault('level_inferred', False)
        row.setdefault('degree_inferred', False)
        row.setdefault('sample_degree', None)
    return result


def project(state, now):
    return dict(shop=copy.deepcopy(state.shop_evidence), efficiency=project_efficiency(state),
                guild_actions=copy.deepcopy(state.guild_actions), ark=copy.deepcopy(state.star_ark),services=project_service(state), live=project_live(state), crafting=project_crafting(state, now),
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
    def __init__(self, name, *, boot=True, count=0, party=None, main=None, coop=None, tent=None, stats=None, allocation=None, guild_actions=None, ark_seed=None, gold=None):
        self.state = State(packet_count=count)
        bootstrap = world() if boot else None
        if bootstrap is not None:
            with patch('time.monotonic', return_value=100): self.state.apply(decode(Packet(3, 1, bootstrap)))
        for target, seed in ((self.state.party, party), (self.state.instances['main'], main),
                             (self.state.instances['coop'], coop), (self.state.tent, tent)):
            target.update(copy.deepcopy(seed or {}))
        self.state.knowledge['player']['stats'].update(stats or {})
        self.state.attribute_allocation.update(copy.deepcopy(allocation or {}))
        self.state.guild_actions.update(copy.deepcopy(guild_actions or {}))
        self.state.star_ark.update(copy.deepcopy(ark_seed or {}))
        if self.state.star_ark['pending']:
            self.state.star_ark['pending']['daily_generation'] = self.state.daily_tasks['generation']
        self.state.gold.update(copy.deepcopy(gold or {}))
        self.steps = []
        self.value = dict(name=name, count=str(count), bootstrap=bootstrap.hex() if bootstrap else None,
                          initial=project(self.state, 100), steps=self.steps)
        sequences.append(self.value)

    def packet(self, main, sub, payload=b'', *, at=None, stages=None, declared=(), catalogs=True, knowledge_catalog=0, ark_runtime=None, ark_second=None):
        now = 100 + len(self.steps)*.25 if at is None else at
        step = dict(main=main, sub=sub, hex=payload.hex(), at=now, stages=stages, declared=declared, catalogs=catalogs, knowledge_catalog=knowledge_catalog, ark_runtime=ark_runtime or runtime_read(), ark_second=ark_second)
        runtime = None if stages is None else SimpleNamespace(stages=dict.fromkeys(stages), combat_catalog=None, recipe_catalog=None)
        trace = []
        intents = []
        runtime_reads = [step['ark_runtime'], step['ark_second'] or step['ark_runtime']]
        read_index = 0
        def read_runtime():
            nonlocal read_index
            value = runtime_reads[min(read_index, 1)]; read_index += 1
            return ({'texts': value['texts']} if value['available'] else None), value['token'], 'synthetic runtime'
        remember = ark._remember_question
        def trace_memory(state, pending, question, correct=None):
            selected = question.get('selected')
            answer = None if selected is None else question['options'][selected - 1]
            rejected = correct is False and (question.get('selected_candidate', False) or
                (question.get('answer_kind') in ('computed', 'reviewed_candidate') and answer == question.get('known_answer')))
            intents.append(copy.deepcopy(dict(operation='Observe' if correct is None else 'Confirm' if correct else 'Reject',
                token=pending['token'], role=pending['role'], daily_generation=pending['daily_generation'],
                ark_generation=state.star_ark['generation'], event=pending.get('event'), question=question,
                selected_answer=answer, rejected_candidate=rejected)))
            remember(state, pending, question, correct)

        original = self.state.snapshot()
        def wrap(name, function):
            def observed(state, event, **kwargs):
                row = dict(name=name, before=evidence(state), bag_before=copy.deepcopy(state.inventory),
                           stats=copy.deepcopy(state.knowledge['player']['stats']), attributes=copy.deepcopy(state.attributes),
                           gold=copy.deepcopy(state.gold), daily_generation=state.daily_tasks['generation'])
                trace.append(row)
                result = function(state, event, **kwargs)
                row['after'] = evidence(state)
                row['bag_after'] = copy.deepcopy(state.inventory)
                return result
            return observed
        with ExitStack() as stack:
            stack.enter_context(patch('time.monotonic', return_value=now))
            stack.enter_context(patch.object(ark, 'runtime_catalog', read_runtime))
            stack.enter_context(patch.object(ark, 'QuestionStore', unavailable_store))
            stack.enter_context(patch.object(ark, '_remember_question', trace_memory))
            stack.enter_context(patch('wlre.services.world.dynamic_bundle_runtime.current_runtime', return_value=runtime))
            stack.enter_context(patch('wlre.services.instance_entry.entries_for',
                return_value=[dict(kind=1, map_id=value) for value in declared]))
            stack.enter_context(patch.object(inventory_updates, 'STACKABLE', RULES if catalogs else {}))
            token = _pinned.set({**CATALOGS[knowledge_catalog], 'npcs': CATALOGS[knowledge_catalog]['npcs'] if catalogs else {}})
            try:
                try:
                    event = decode(Packet(main, sub, payload), self.state.player.get('role_id'))
                except ProtocolError as exc:
                    step['error'] = True
                    step['error_message'] = str(exc)
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
        step['intents'] = intents
        step['runtime_reads'] = read_index
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

TOKEN = (True, 'a' * 64)
TEXTS = {101: '請問1+1=?', 201: '1', 202: '2', 203: '3', 204: '4'}
def runtime_read(available=True, token=TOKEN, texts=None):
    return dict(available=available, token=token, texts=TEXTS if texts is None else texts)
def unavailable_store(*args, **kwargs):
    raise OSError('synthetic unavailable store boundary, no filesystem access')
def eventrow(): return dict(index=1, id=123, kind=3, planet=1, main=False)
def ark_pending(kind='question', **updates):
    result = dict(kind=kind, role=17, token=TOKEN, daily_generation=0, due=100.5, task_before=2)
    if kind == 'dispatch':
        result.update(quote=dict(planet=1, agent=1, duration=60, price=20, hours=1), balance=100, paid=False, ship_ack=False)
    else: result.update(event=eventrow(), complete=False, result=False, bag_needed=False)
    result.update(updates); return result

def ark_seed(**updates):
    result = dict(role=17, pending=ark_pending(), generation=4, answers={'historical-key': 204},
        events={1:eventrow()}, reserved=20, confirmed=10, catalog_token=TOKEN)
    result.update(updates); return result

def question(**updates):
    result = dict(type='ark_question', question=101, award=dict(kind=6,id=8,value=5), options=[201,202,203,204],
        selected=2, text=TEXTS[101], labels=[TEXTS[i] for i in (201,202,203,204)], known_answer=202,
        answer_kind='reviewed_candidate', answer_source='synthetic source', selected_candidate=True)
    result.update(updates); return result

def qpacket(): return pack('IBII4I',101,6,8,5,201,202,203,204)
def ark_snapshot():
    return pack('BHB',2,100,2)+bytes([1,5,1,2,0,2,6,3,4,0])+pack('HhH',0,0,0)+bytes(60)
def ark_events(): return b''.join(pack('HBB',123 if i==1 else 0,3 if i==1 else 0,1 if i==1 else 0) for i in range(1,13))+b'\0'
def guild_pending(kind='donate', **updates):
    result = dict(kind=kind, role=17, guild=72, token=TOKEN, epoch=0, due=100.5)
    if kind=='sign': result.update(sign_ack=False)
    else: result.update(quote=dict(price=150,price_kind=4,sell_id=8,save_index=7,count=2,item_index=None),
                       before_remaining=5,gold_before=1000,gold_ack=False,sell_ack=False,remaining_ack=False)
    result.update(updates); return result
GOLD = dict(ready=True, reliable=True, amount=1000, revision=2**70, source='synthetic imported balance')

# Source order across all four observers, reliable/unreliable current bag and current gold,
# full updated knowledge, post-local identity, and ignored packets refreshing efficiency.
s = Scenario('all_postlocal_observers_mixed', count=2**90)
s.packet(39,2,roster()).packet(39,85,b'\1').packet(39,87,b'\5\1')
s.packet(26,4,pack('I',1000)).packet(23,5,b'\10'+bag_row())
s.packet(5,3,player(),knowledge_catalog=1).packet(15,8,companion(exp=10000))
s.packet(8,1,attr(35,15)).packet(8,1,attr(39,0)).packet(8,1,attr(36,20000))
for index in range(4):
    units(s,unit(17),unit(1,17,1,2),start=True)
    s.packet(8,1,attr(36,20100+index*100)).packet(8,2,attribute(kind=36,value=10100+index*30))
    s.packet(26,2,pack('IB',150,0)).packet(23,4,bag_row(2,count=1))
    s.packet(27,1,b'\0').packet(11,12,b'\1').packet(20,8)
s.packet(191,1,ark_snapshot()).packet(191,2,ark_events())
s.packet(75,24,pack('IIBB',100,0,0,1)).packet(191,17,pack('BH',2,100))
s.packet(124,1,daily()).packet(65,1,camp()).packet(8,4).packet(1,23,at=-100)
s.packet(5,47,pack('BBq',1,0,20000)+bytes(30))
s.packet(3,1,world(18)).packet(3,1,world(0)).packet(3,1,world(17))
s.packet(63,1).packet(63,7,b'\0\0')

# Imported pending acknowledgements are never completed by State.apply's tick-free path.
for order in itertools.permutations(('gold','sell','remaining')):
    s = Scenario('guild_ack_'+ '_'.join(order), guild_actions=dict(role=17,guild=72,pending=guild_pending(),reserved=150,confirmed=300), gold=GOLD)
    s.packet(39,2,roster())
    for event in order:
        if event=='gold':s.packet(26,2,pack('IB',150,0))
        elif event=='sell':s.packet(10,5,b'\1\7\3')
        else:s.packet(39,87,b'\4\1')
    s.packet(1,23,at=1e12).packet(39,85,b'\2').packet(39,85,b'\1')
    s.packet(10,5,b'\3').packet(10,5,b'\3').packet(39,2,roster(18))
    s.packet(3,1,world(18)).packet(63,1)
for kind in ('sign','donate'):
    s = Scenario('guild_pending_identity_'+kind, guild_actions=dict(role=17,guild=72,pending=guild_pending(kind)), gold=GOLD)
    s.packet(39,85,b'\1').packet(39,2,roster()).packet(39,86,b'\0')
    s.packet(26,2,pack('IB',150,0)).packet(26,2,pack('IB',150,0)).packet(39,2,roster(18))

# Real memory-failure oracle, including exact question text and identity-bound intent traces.
s=Scenario('ark_observe_intent_then_duplicate',ark_seed=ark_seed())
s.packet(124,1,daily()).packet(191,11,qpacket()).packet(1,23,at=1e12).packet(191,11,qpacket())
for correct in (False,True):
    s=Scenario('ark_answer_intent_'+str(correct),ark_seed=ark_seed(question=question()))
    s.packet(191,12,bytes([correct,2])).packet(191,10,pack('BH',1,123)).packet(1,23,at=1e12)
    s.packet(191,12,bytes([correct,2]))
for label,current,second in [
    ('unavailable',runtime_read(False),None),('changed_first',runtime_read(token=(True,'b'*64)),None),
    ('changed_second',runtime_read(),runtime_read(token=(True,'b'*64))),
    ('missing_text',runtime_read(texts={101:TEXTS[101]}),None)]:
    s=Scenario('ark_runtime_'+label,ark_seed=ark_seed())
    s.packet(191,11,qpacket(),ark_runtime=current,ark_second=second)
    s.packet(191,12,b'\1\2').packet(75,24,pack('IIBB',100,0,1,0))
s=Scenario('ark_daily_generation_and_role_reset',ark_seed=ark_seed())
s.packet(124,1,daily()).packet(124,1,daily(progress=0)).packet(191,11,qpacket())
s.packet(3,1,world(18)).packet(191,11,qpacket()).packet(63,1).packet(191,1,ark_snapshot())
s=Scenario('ark_dispatch_ack_not_settled',ark_seed=ark_seed(pending=ark_pending('dispatch'),ready=True,
    agents={1:dict(index=1,id=5,skills=[1,2],planet=0)},starcoin=dict(ready=True,reliable=True,amount=100,revision=7)))
s.packet(75,24,pack('IIBB',80,20,0,0)).packet(191,3,pack('BBBBH',1,1,1,0,60)).packet(1,23,at=1e12)
s.packet(75,24,pack('IIBB',80,20,0,0)).packet(191,1,ark_snapshot())

# Window eviction, null/zero/new identities, missing knowledge and source-reset distinctions.
s=Scenario('shop_bounded_window_current_state',count=2**90)
s.packet(23,5,b'\10'+bag_row()).packet(26,4,pack('I',1000))
for i in range(108):
    s.packet(26,1,pack('IB',1,0)).packet(27,1,bytes([i%3]))
s.packet(23,9,b'\1\xff\0').packet(26,3).packet(27,6,pack('IBB',9,1,1)).packet(27,8,b'\1')
s.packet(3,1,world(18)).packet(63,1)
s=Scenario('efficiency_zero_slot_and_wide_labels',boot=False)
s.packet(8,1,attr(36,20000)).packet(15,8,companion(index=0,exp=10000)).packet(3,1,world())
s.packet(8,1,attr(35,0xffffffff)).packet(8,1,attr(39,-0xffffffff))
for i in range(3):
    units(s,unit(17),unit(1,17,0,2),start=True)
    s.packet(8,2,attribute(index=0,kind=36,value=10100+i*100)).packet(20,8)
s.packet(15,8,companion(index=0,npc=2,exp=20000)).packet(15,2,pack('IBB',17,0,1)).packet(1,23)
s.packet(3,1,world(0)).packet(8,1,attr(36,99)).packet(3,1,world(18)).packet(63,1)

# Every truncated prefix and trailing data of mixed dependent packets goes through decode
# before mutation. Valid prefixes permitted by the retained decoder remain observations.
s=Scenario('malformed_prefixes_after_imported_pending',ark_seed=ark_seed(),guild_actions=dict(role=17,guild=72,pending=guild_pending()),gold=GOLD)
for main,sub,data in [(191,11,qpacket()),(191,1,ark_snapshot()),(75,24,pack('IIBB',100,0,0,1)),
    (39,87,b'\4\1'),(26,2,pack('IB',150,0)),(8,2,attribute(kind=36,value=10000)),
    (15,8,companion(index=0)),(23,5,b'\10'+bag_row())]:
    for length in range(len(data)):s.packet(main,sub,data[:length])
    s.packet(main,sub,data+b'\xff')

# Seeded interleavings exercise refresh and repeated/late observations across domain boundaries.
rng=random.Random(794419)
for trial in range(5):
    s=Scenario('seeded_postlocal_'+str(trial))
    s.packet(39,2,roster()).packet(26,4,pack('I',1000)).packet(23,5,b'\10'+bag_row())
    for i in range(45):
        choice=rng.randrange(15)
        if choice==0:s.packet(3,1,world(rng.choice((0,17,18))))
        elif choice==1:s.packet(15,8,companion(index=rng.choice((0,1,2)),npc=rng.choice((1,2)),exp=10000+i*100))
        elif choice==2:s.packet(8,1,attr(36,20000+i*100))
        elif choice==3:s.packet(8,2,attribute(index=rng.choice((0,1,2)),kind=36,value=10000+i*30))
        elif choice==4:units(s,unit(17),unit(1,17,1,2),start=True)
        elif choice==5:s.packet(20,8)
        elif choice==6:s.packet(39,2,roster(rng.choice((17,18))))
        elif choice==7:s.packet(39,87,bytes([rng.randrange(6),1]))
        elif choice==8:s.packet(26,2,pack('IB',150,0))
        elif choice==9:s.packet(23,4,bag_row(index=2,count=1))
        elif choice==10:s.packet(191,1,ark_snapshot())
        elif choice==11:s.packet(191,2,ark_events())
        elif choice==12:s.packet(75,24,pack('IIBB',i,0,0,1))
        elif choice==13:s.packet(10,5,b'\3')
        else:s.packet(1,23,at=-100 if i%2 else 1e12)
for sequence in sequences:
    if 'malformed' not in sequence['name']:
        assert not any(step['error'] for step in sequence['steps']), (sequence['name'], [(x['main'],x['sub'],x.get('error_message')) for x in sequence['steps'] if x['error']])
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
sources += ['wlre/storage/ark_questions.py', 'wlre/services/ark_candidates.py', 'wlre/services/ark_first_answer.py', 'wlre/services/ark_candidate_data.py']
sources += ['wlre/services/instance_' + name + '.py' for name in ('creation', 'room_flow', 'standby', 'start', 'entry', 'rewards')]
hashes = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
metadata = dict(sources=hashes, order=ORDER, scenarios=len(sequences), checkpoints=sum(len(s['steps']) for s in sequences), covered=sorted(covered))
header = '// Generated by ServicePostLocalGenerateVectors.py from real State.apply; synthetic offline evidence.\nnamespace Lala.Core.Tests.State;\n'
lines = [header, 'public static partial class ServicePostLocalPythonVectors', '{',
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
output = Path(__file__).with_name('ServicePostLocalPythonVectors.cs')
output.write_text('\n'.join(lines)+'\n')
# Generated-only files may be replaced when the deterministic partition count changes.
for old in output.parent.glob(output.stem + '.Part*.cs'): old.unlink()
prefix = header + 'public static partial class ServicePostLocalPythonVectors\n{\n'
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
