"""Real State.apply oracle for the bounded service, bag, companion and crafting composition.

Every Python observer runs, in its retained order. Only offline catalog projections and
observation time are supplied; no request, tick, send, transport or resource activation.
The projection deliberately excludes player/battle knowledge and equipment mutations.
"""
import base64
import copy
from contextlib import ExitStack
import gzip
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
    return dict(services=project_service(state), live=project_live(state), crafting=project_crafting(state, now))


sequences = []
covered = set()
class Scenario:
    def __init__(self, name, seeded=False, count=0):
        self.state = State(packet_count=count)
        if seeded:
            rows = decode(Packet(23, 5, b'\x08' + bag_row(1, count=8) + bag_row(2, count=5)))['items']
            self.state.inventory.update(ready=True, reliable=True, capacity=8, items={str(row['index']): row for row in rows},
                revision=2**90, holds={'crafting': [dict(index='1', identity=[42, 9, 2], count=3, remaining=3, before=8,
                exclusive=False, uncertain=False)], 'battle': [dict(index='1', identity=[42, 9, 2], count=2, remaining=2,
                before=8, exclusive=False, uncertain=False)]}, reserved={'1': 5}, server_stackable={'43': True},
                field_supply={'pending': True, 'status': 'synthetic'}, alchemy_slots=['2'])
            self.state.crafting.update(pending='complete', auto_continue=True, completion_requested=True,
                completed=2**100, revision=2**110)
            self.state.time_cube.update(pending=dict(count=2, bag_revision=1, count_updated=False, due=15))
        self.steps = []
        self.value = dict(name=name, count=str(count), initial=project(self.state, 100), steps=self.steps)
        sequences.append(self.value)
    def packet(self, main, sub, payload=b'', at=None, known=False, schedules='legacy', catalogs=True):
        now = 100 + len(self.steps)*.25 if at is None else at
        step = dict(main=main, sub=sub, hex=payload.hex(), at=now, known=known, schedules=schedules, catalogs=catalogs)
        runtime = SimpleNamespace(stages={101: {}}, combat_catalog=None,
            recipe_catalog=RECIPES if schedules == 'recipes' else None)
        trace = []
        original = self.state.snapshot()
        def wrap(name, function):
            def observed(state, event, **kwargs):
                entry = dict(name=name, before=evidence(state), bag_before=copy.deepcopy(state.inventory))
                trace.append(entry)
                result = function(state, event, **kwargs)
                entry['after'] = evidence(state)
                entry['bag_after'] = copy.deepcopy(state.inventory)
                return result
            return observed
        with ExitStack() as stack:
            stack.enter_context(patch('time.monotonic', return_value=now))
            stack.enter_context(patch('wlre.services.world.dynamic_bundle_runtime.current_runtime',
                return_value=runtime if known or schedules == 'recipes' else None))
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
    def bag(self, *rows, capacity=8): return self.packet(23, 5, pack('B', capacity) + b''.join(rows))
    def add(self, index=1, item_id=42, count=2, catalogs=True):
        return self.packet(23, 6, bag_row(index, item_id, count) + b'\xff\xff', catalogs=catalogs)
    def delete(self, index=1, count=1): return self.packet(23, 9, pack('BBB', index, count, 255))


s = Scenario('storage_stackability_imports_and_bag_replacements', count=2**90)
s.bag().add(1, 999, 2, catalogs=False).packet(62, 57, pack('BBHHH', 1, 2, 1, 999, 5))
s.add(1, 999, 2, catalogs=False).bag(bag_row(1, 999, 3)).add(1, 999, 2, catalogs=False)
s.packet(62, 57, pack('BBHH', 1, 1, 0, 0)).packet(62, 57, pack('BBHHH', 1, 2, 0, 43, 1))
s.add(2, 43, 2).packet(3, 1, world(17)).packet(63, 1).add(2, 43, 1)
s.packet(62, 57, pack('BBHHH', 1, 2, 1, 42, 3)).packet(3, 1, world(18))
s.bag(bag_row(2, 43, 3)).packet(124, 1, daily()).packet(122, 1, pack('BBHH', 1, 1, 3, 0))

s = Scenario('shared_companion_attributes_replay_clear_role_changes')
s.packet(8, 2, attribute(kind=206, value=100, human=9)).packet(8, 2, attribute(kind=47, value=200))
s.packet(8, 2, attribute(kind=110, parameter=1001, value=0)).packet(15, 8, companion())
s.packet(8, 2, attribute(kind=206, value=300)).packet(15, 8, companion(exp=123))
s.packet(15, 8, companion(npc=2)).packet(8, 1, pack('BBII', 25, 1, 123, 0))
s.packet(3, 1, world(17)).packet(8, 2, attribute()).packet(15, 2, pack('IBB', 18, 1, 0))
s.packet(15, 2, pack('IBB', 17, 1, 0)).packet(15, 1, add_pet(17, 2))
s.packet(8, 2, attribute(kind=110, parameter=1002, value=7)).packet(63, 1)
s.packet(3, 1, world(18)).packet(15, 2, pack('IBB', 17, 1, 0)).packet(15, 1, add_pet(18, 1))
s.packet(19, 1, pack('I', 2)).packet(19, 2).packet(8, 2, attribute(index=65535, value=-0xffffffff))
s.packet(15, 8, companion(1, 1) + companion(1, 2)).packet(15, 8)

s = Scenario('crafting_furniture_local_geometry_and_explicit_layout_context')
s.packet(62, 1, b'\1' + furniture()).packet(1, 11).packet(3, 1, world(17, 63501))
s.packet(62, 4, pack('I', 17) + furniture(1)).packet(62, 1, b'\2' + furniture(7))
s.packet(1, 11).packet(1, 11).packet(62, 5, pack('BHHH', 1, 7, 42, 65535))
s.packet(64, 1, craft_row(3, 1) + craft_row(1, 42) + b'\3', schedules='recipes', at=200)
s.packet(64, 3, b'\3', at=150).packet(64, 2, b'\3', at=210)
s.packet(64, 4, pack('BH', 3, 100), at=300).packet(64, 4, pack('BH', 3, 100))
s.packet(64, 16, craft_row(7, 999), schedules='recipes')
s.packet(64, 16, craft_row(7, 999), schedules='legacy').packet(64, 16, craft_row(2, 42), schedules='recipes')
s.packet(3, 1, world(18)).packet(62, 4, pack('I', 17) + furniture(3))
s.packet(62, 1, b'\1' + furniture(4)).packet(62, 1, b'\2' + furniture(4)).packet(1, 11)
s.packet(62, 76, pack('H', 4)).packet(62, 2, pack('H', 4)).packet(62, 5, pack('BHHH', 2, 7, 42, 0))
s.packet(64, 25, b'\1\1\2').packet(64, 5, b'\1').packet(64, 10, pack('BI', 2, 2))
s.packet(64, 6, pack('BH', 1, 65535)).packet(64, 1, b'\0', schedules='legacy').packet(1, 11)

s = Scenario('seeded_reservations_craft_pending_and_cube_receipts', seeded=True)
s.packet(3, 1, world(17)).packet(122, 1, pack('BBHH', 1, 1, 0, 0))
s.packet(64, 1, craft_row() + b'\1').delete(1, 2).packet(64, 4, pack('BH', 1, 1))
s.add(1, 42, 1).packet(1, 23, at=1e12).bag(bag_row(1, count=5), bag_row(2, count=5))
s.packet(62, 57, pack('BBHHH', 1, 2, 1, 999, 5)).add(3, 999, 2, catalogs=False)
s.delete(1, 255).bag(bag_row(1, count=8, serial=10), bag_row(2, count=5))
s.packet(1, 11).packet(64, 1, b'\0').packet(1, 23).packet(63, 1)

s = Scenario('malformed_packets_never_mutate_composed_domains', seeded=True)
for main, sub, payload in [(23, 5, b'\x08' + bag_row()), (15, 8, companion()),
        (64, 1, craft_row() + b'\1'), (62, 4, pack('I', 17) + furniture()),
        (62, 57, pack('BBHHH', 1, 2, 1, 42, 3)), (8, 2, attribute())]:
    for cut in (0, 1, len(payload)//2, len(payload)-1):
        s.packet(main, sub, payload[:cut]).packet(1, 23)
    s.packet(main, sub, payload+b'\xff')

rng = random.Random(2026110815)
for index in range(8):
    s = Scenario('seeded_mixed_full_apply_' + str(index), seeded=index%2 == 0, count=index*100)
    for step in range(48):
        role = rng.choice((17, 18))
        choice = rng.randrange(24)
        if choice == 0: s.packet(3, 1, world(role, rng.choice((101, 63501))))
        elif choice == 1: s.packet(63, 1)
        elif choice == 2: s.bag(bag_row(rng.randrange(1, 4), count=rng.randrange(1, 9)))
        elif choice == 3: s.add(rng.randrange(4), rng.choice((42, 43, 999)), rng.randrange(1, 4), catalogs=bool(step%2))
        elif choice == 4: s.delete(rng.randrange(1, 4), rng.randrange(4))
        elif choice == 5: s.packet(62, 57, pack('BBHHH', 1, 2, rng.randrange(1, 4), rng.choice((42, 999)), 3))
        elif choice == 6: s.packet(15, 8, companion(rng.randrange(1, 4), rng.choice((1, 2))), catalogs=bool(step%2))
        elif choice == 7: s.packet(15, 1, add_pet(role, rng.choice((1, 2))))
        elif choice == 8: s.packet(15, 2, pack('IBB', role, rng.randrange(1, 4), 0))
        elif choice == 9: s.packet(8, 2, attribute(rng.randrange(1, 4), rng.choice((25, 110, 206)), rng.randrange(4), 1001, rng.choice((4, 9))))
        elif choice == 10: s.packet(64, 1, craft_row(rng.randrange(1, 4)) + bytes([rng.randrange(4)]), schedules=rng.choice(('legacy', 'recipes')))
        elif choice == 11: s.packet(64, rng.choice((2, 3, 5)), bytes([rng.randrange(1, 4)]))
        elif choice == 12: s.packet(64, 4, pack('BH', rng.randrange(1, 4), 1))
        elif choice == 13: s.packet(62, 4, pack('I', role) + furniture(rng.randrange(1, 4)))
        elif choice == 14: s.packet(62, 1, bytes([rng.choice((1, 2))]) + furniture(rng.randrange(1, 4)))
        elif choice == 15: s.packet(1, 11)
        elif choice == 16: s.packet(124, 1, daily(rng.randrange(4)))
        elif choice == 17: s.packet(122, 1, pack('BBHH', 1, rng.randrange(4), 0, 0))
        elif choice == 18: s.packet(39, 2, roster(role))
        elif choice == 19: s.packet(23, 208, pack('BBi', 3, 1, rng.randrange(100)))
        elif choice == 20: s.packet(31, 18, team(rng.randrange(1, 4), rng.randrange(5)))
        elif choice == 21: s.packet(23, 123, pack('IB', role, 0))
        elif choice == 22: s.packet(62, 64, known=bool(step%2))
        else: s.packet(255, 254)

sources = ['wlre/core/state.py', 'wlre/core/state_events.py', 'wlre/core/state_session_events.py',
    'wlre/core/state_world_events.py', 'wlre/core/state_battle_events.py', 'wlre/core/activity.py',
    'wlre/services/daily_tasks.py', 'wlre/services/time_cube.py', 'wlre/services/items/recovery.py',
    'wlre/services/items/room_storage.py', 'wlre/services/social/guild.py', 'wlre/services/expedition/manager.py',
    'wlre/services/items/crafting.py', 'wlre/services/items/combat_resources.py', 'wlre/services/items/inventory.py',
    'wlre/core/inventory_updates.py', 'wlre/services/items/reservations.py', 'wlre/services/items/live_combat_catalog.py',
    'wlre/services/battle/attribute_points.py', 'wlre/services/battle/party.py', 'wlre/services/instances.py',
    'wlre/services/world/tent.py', 'wlre/services/world/npc_shop_evidence.py', 'wlre/core/efficiency.py',
    'wlre/services/social/guild_actions.py', 'wlre/services/star_ark.py', 'wlre/network/protocol.py',
    'wlre/network/live_data.py', 'wlre/network/wire.py']
hashes = {path: hashlib.sha256((ROOT/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for path in sources}
lines = ['// Generated by ServiceInventoryGenerateVectors.py from real State.apply. Synthetic offline evidence.',
         'namespace Lala.Core.Tests.State;', 'public static class ServiceInventoryPythonVectors', '{',
         '    public const string SourceSha256 = ' + json.dumps(json.dumps(hashes)) + ';',
         '    public static IEnumerable<object[]> Sequences()', '    {']
for vector in sequences:
    raw = json.dumps(vector, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    lines.append('        yield return new object[] { ' + json.dumps(vector['name']) + ', Decode(' + json.dumps(encoded) + ') };')
lines += ['    }', '    private static string Decode(string encoded)', '    {',
    '        using var input = new System.IO.MemoryStream(System.Convert.FromBase64String(encoded));',
    '        using var gzip = new System.IO.Compression.GZipStream(input, System.IO.Compression.CompressionMode.Decompress);',
    '        using var reader = new System.IO.StreamReader(gzip, System.Text.Encoding.UTF8);',
    '        return reader.ReadToEnd();', '    }', '}']
output = Path(__file__).with_name('ServiceInventoryPythonVectors.cs')
output.write_text('\n'.join(lines)+'\n')
assert output.stat().st_size < 500000
print(f'Generated {len(sequences)} real State.apply scenarios / {sum(len(s["steps"]) for s in sequences)} checkpoints; {len(covered)} event kinds; {output.stat().st_size} bytes.')
